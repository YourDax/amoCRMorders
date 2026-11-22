"""Чтение беседы MAX (web.max.ru) во второй вкладке браузера amoCRM.

Приёмы и селекторы — из агента MAX проекта Fotomania CRM (crm/agent/max_agent/max_browser):
поле «Найти» над списком чатов, `.searchResultsList` (свои чаты до раздела «Глобальный поиск»),
шапка открытого чата `span.title span.name span.text`, сообщения `.bubble` с текстом в `.text`.

В MAX ничего не пишется и не отправляется: только поиск чата и чтение сообщений.
"""

from __future__ import annotations

import os
import re
import time

from playwright.sync_api import BrowserContext, Page

from kids_lists import collect_lists, full_list_keys, merge_history

MAX_URL = os.environ.get("AMO_MAX_URL", "https://web.max.ru/")  # другой адрес — только для проверок на макете
_MAX_HOST = MAX_URL.split("://", 1)[-1].split("/", 1)[0]
LOGIN_WAIT_MIN = 10
SCROLL_MAX_STEPS = 400  # ~ несколько тысяч сообщений; дальше история слишком длинная

_SEARCH_INPUTS = [
    "input.field[placeholder='Найти']",
    "input[placeholder*='Найти' i]",
    "input[type='search']",
    "input[placeholder*='Поиск' i]",
]
_HEADER_TITLE = [
    "div[class*='content--subtitle'] span.title span.name span.text",
    "span.title span.name span.text",
    "[class*='header'] h2[class*='title']",
]
_RESULTS_JS = """
() => {
  const list = document.querySelector('.searchResultsList');
  if (!list) return null;
  const rows = [];
  [...list.children].forEach((node, index) => {
    if (node.classList.contains('separator')) {
      rows.push({index, separator: (node.innerText || '').trim()});
      return;
    }
    const name = node.querySelector('.name') || node.querySelector('.title');
    const title = name ? (name.innerText || '').trim() : '';
    if (title) rows.push({index, title});
  });
  return rows;
}
"""
# Тексты сообщений на экране по порядку (сверху вниз = от старых к новым), без времени.
_BUBBLES_JS = """
() => [...document.querySelectorAll('[data-kids-scroller] .bubble')].filter(b => b.getClientRects().length).map((b) => {
  const texts = [...b.querySelectorAll('.text')].filter((t) => !t.closest('.meta'));
  return (texts.length ? texts.map((t) => t.innerText).join('\\n') : (b.innerText || '')).trim();
}).filter(Boolean)
"""
# Прокручиваемый контейнер истории — ближайший предок сообщения с прокруткой.
_SCROLLER_JS = """
() => {
  const b = document.querySelector('.bubble');
  let el = b && b.parentElement;
  while (el && el !== document.body) {
    const st = getComputedStyle(el);
    if (/(auto|scroll)/.test(st.overflowY)) {
      el.setAttribute('data-kids-scroller', '1');
      return true;
    }
    el = el.parentElement;
  }
  if (b) document.body.setAttribute('data-kids-scroller', '1');
  return !!b;
}
"""
_SCROLL_UP_JS = """
() => {
  const el = document.querySelector('[data-kids-scroller]');
  if (!el) return null;
  const before = el.scrollTop;
  el.scrollBy(0, -Math.max(200, el.clientHeight * 0.5));
  return {before, after: el.scrollTop, height: el.scrollHeight};
}
"""
_SCROLL_BOTTOM_JS = """
() => { const el = document.querySelector('[data-kids-scroller]');
        if (el) el.scrollTop = el.scrollHeight; }
"""
_SPACES = re.compile(r"[\s ​-‍⁠﻿]+")
_DASHES = re.compile(r"[‐-―−]")


def norm_title(s: str) -> str:
    return _SPACES.sub(" ", _DASHES.sub("-", s or "")).strip().casefold().replace("ё", "е")


def pick_chat(titles: list[str], query: str) -> int:
    """Индекс чата: точное совпадение названия, иначе единственный, где есть все слова запроса."""
    q = norm_title(query)
    exact = [i for i, t in enumerate(titles) if norm_title(t) == q]
    if len(exact) == 1:
        return exact[0]
    words = set(q.split())
    partial = [i for i, t in enumerate(titles) if words <= set(norm_title(t).split())]
    if len(partial) == 1:
        return partial[0]
    if not partial and not exact:
        raise RuntimeError(f"Чат «{query}» не найден в MAX. Проверьте название.")
    names = ", ".join(f"«{titles[i]}»" for i in (exact or partial)[:5])
    raise RuntimeError(f"По названию «{query}» в MAX несколько чатов: {names}. Впишите название точнее.")


class MaxChat:
    """Вкладка MAX в том же браузере, что и amoCRM (вход по QR запоминается в профиле)."""

    def __init__(self, ctx: BrowserContext, log=print, should_stop=lambda: False):
        self.ctx = ctx
        self.log = log
        self.should_stop = should_stop
        self.page: Page | None = None

    def _check_stop(self):
        if self.should_stop():
            raise RuntimeError("Остановлено пользователем")

    def _sleep(self, ms: int):
        end = time.time() + ms / 1000
        while time.time() < end:
            self._check_stop()
            self.page.wait_for_timeout(min(250, max(1, int((end - time.time()) * 1000))))

    def _visible(self, selectors: list[str]):
        for sel in selectors:
            loc = self.page.locator(sel)
            try:
                for i in range(min(loc.count(), 5)):
                    if loc.nth(i).is_visible():
                        return loc.nth(i)
            except Exception:  # noqa: BLE001 — страница перерисовалась
                continue
        return None

    def open(self):
        """Открывает (или находит) вкладку MAX и ждёт входа."""
        if self.page is None or self.page.is_closed():
            self.page = next((p for p in self.ctx.pages if _MAX_HOST in p.url), None)
        if self.page is None:
            self.page = self.ctx.new_page()
            self.page.goto(MAX_URL, wait_until="domcontentloaded")
        self.page.bring_to_front()
        if self._visible(_SEARCH_INPUTS):
            return
        self.log("MAX: войдите в аккаунт во вкладке MAX (QR-код из приложения MAX на телефоне). Жду до "
                 f"{LOGIN_WAIT_MIN} мин.")
        deadline = time.time() + LOGIN_WAIT_MIN * 60
        while time.time() < deadline:
            self._sleep(1000)
            if self._visible(_SEARCH_INPUTS):
                self.log("MAX: вход выполнен.")
                self._sleep(1500)
                return
        raise RuntimeError("Не дождался входа в MAX")

    def _header_title(self) -> str:
        loc = self._visible(_HEADER_TITLE)
        try:
            return _SPACES.sub(" ", loc.inner_text(timeout=500)).strip() if loc else ""
        except Exception:  # noqa: BLE001
            return ""

    def _open_tab_all(self):
        btn = self.page.get_by_role("button", name=re.compile(r"^Все")).locator("visible=true").first
        try:
            if btn.count() and "active" not in (btn.get_attribute("class") or ""):
                btn.click()
                self._sleep(500)
        except Exception:  # noqa: BLE001 — кнопки раздела нет, остаёмся где были
            pass

    def open_chat(self, name: str):
        """Находит чат по названию через поле «Найти» и открывает его."""
        if norm_title(self._header_title()) == norm_title(name):
            return
        # открыт другой чат или профиль — «назад» к списку
        back = self.page.locator("button[aria-label*='назад' i]").locator("visible=true")
        if back.count():
            try:
                back.first.click(timeout=2000)
                self._sleep(400)
            except Exception:  # noqa: BLE001
                pass
        self._open_tab_all()
        search = self._visible(_SEARCH_INPUTS)
        if search is None:
            raise RuntimeError("Не нашёл поле «Найти» в MAX")
        search.fill("")
        search.fill(name)
        found: list[tuple[int, str]] = []
        prev, same = None, 0
        deadline = time.time() + 8
        while time.time() < deadline:
            self._sleep(400)
            rows = self.page.evaluate(_RESULTS_JS) or []
            found = []
            for r in rows:
                if "separator" in r:
                    if re.search(r"глобальн|global", r["separator"], re.I):
                        break
                    continue
                t = _SPACES.sub(" ", r["title"]).strip()
                if t.casefold() != "ничего не нашли":
                    found.append((r["index"], t))
            titles = [t for _, t in found]
            if any(norm_title(t) == norm_title(name) for t in titles):
                break
            same = same + 1 if titles == prev else 0
            prev = titles
            if same >= (2 if titles else 5):
                break
        self.log(f"MAX: найдено чатов: {len(found)}" + (f" ({', '.join(t for _, t in found[:5])})" if found else ""))
        idx = pick_chat([t for _, t in found], name)
        self.page.locator(".searchResultsList > *").nth(found[idx][0]).click()
        for _ in range(20):
            self._sleep(250)
            if norm_title(self._header_title()) == norm_title(found[idx][1]):
                break
        else:
            raise RuntimeError("MAX не подтвердил открытие выбранного чата")
        self.log(f"MAX: открыт чат «{self._header_title() or found[idx][1]}»")

    def read_lists(self, chat: str, need: set[str]) -> dict[str, str]:
        """Списки детей по классам (ключ kids_lists.class_key → текст), самые новые.

        Листает историю снизу вверх, пока у всех нужных классов не найдётся полный список
        или не дойдёт до начала чата (короткие записи вида «4в Сизинцева София» тоже собираются).
        """
        self.open()
        self.open_chat(chat)
        for _ in range(40):  # сообщения подгружаются после открытия чата
            if self.page.evaluate(_SCROLLER_JS):
                break
            self._sleep(250)
        else:
            raise RuntimeError("В чате MAX не видно сообщений")
        self.page.evaluate(_SCROLL_BOTTOM_JS)
        self._sleep(800)
        history: list[str] = []  # тексты сообщений от старых к новым
        full: set[str] = set()     # классы, у которых уже найден полный список
        still = 0
        for step in range(SCROLL_MAX_STEPS):
            self._check_stop()
            before = len(history)
            history = merge_history(history, self.page.evaluate(_BUBBLES_JS))
            full |= full_list_keys(history[:len(history) - before + 1])
            # полный список найден — более старые сообщения его уже не изменят
            if need and need <= full:
                break
            pos = self.page.evaluate(_SCROLL_UP_JS)
            if pos is None:
                break
            moved = abs(pos["after"] - pos["before"]) > 1
            self._sleep(200 if moved else 1000)  # у начала MAX догружает старые сообщения
            if moved:
                still = 0
            else:
                h = self.page.evaluate("() => document.querySelector('[data-kids-scroller]').scrollHeight")
                still = 0 if h != pos["height"] else still + 1
                if still >= 3:  # начало чата: прокрутка стоит и ничего не догружается
                    break
            if step and step % 20 == 0:
                self.log(f"MAX: листаю историю… сообщений: {len(history)}, полных списков: {len(full & need)}")
        return collect_lists(history)
