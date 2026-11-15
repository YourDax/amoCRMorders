"""Создание сделок в amoCRM через браузер (Playwright), кликами как человек.

Все селекторы собраны в SEL — если amoCRM поменяет вёрстку, править только здесь.
Поля ищутся по видимому тексту (плейсхолдеры, подписи «Раб. тел.», «Должность»),
а не по внутренним id, поэтому должны переживать мелкие изменения интерфейса.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from playwright.sync_api import BrowserContext, Locator, Page, TimeoutError as PWTimeout, sync_playwright

from excel_reader import Contact, Deal
from paths import LOG_DIR, PROFILE_DIR

SEL = {
    # левое меню и кнопка на странице сделок
    "nav_deals": ['#nav_menu a[href*="/leads"]', 'a.nav__menu__item__link[href*="/leads"]'],
    "nav_deals_text": "Сделки",
    "new_deal_text": "Новая сделка",
    # название сделки в шапке карточки
    "deal_name_placeholder": re.compile(r"Сделка\s*#"),
    "deal_name_css": ['[name="lead[NAME]"]', "#person_n"],
    # контакт
    "contact_name_placeholder": "Добавить контакт",
    "label_phone": "Раб. тел.",
    "label_position": "Должность",
    "label_company": "Компания",
    "company_placeholder": "Название компании",
    "add_contact_text": "Добавить контакт",
    "save_text": "Сохранить",
}



class AmoBot:
    def __init__(self, base_url: str, step: bool = False, slow_mo: int = 150, timeout: int = 15000):
        self.base_url = base_url.rstrip("/")
        self.step = step
        self.slow_mo = slow_mo
        self.timeout = timeout
        self.pause_cb = None      # функция(msg) — для пошагового режима из интерфейса
        self.log_cb = print       # функция(msg) — куда писать ход работы
        self._pipeline_urls: dict[str, str] = {}  # название воронки -> ссылка
        self._pw = None
        self.ctx: BrowserContext | None = None
        self.page: Page | None = None

    # ---------- запуск / вход ----------
    def start(self):
        self._pw = sync_playwright().start()
        # AMO_HEADLESS=1 — без окна браузера, только для автоматических проверок
        kwargs = dict(headless=os.environ.get("AMO_HEADLESS") == "1", slow_mo=self.slow_mo,
                      no_viewport=True,  # страница подстраивается под реальный размер окна
                      args=["--start-maximized"])
        # Edge есть на любом Windows 10/11 — тогда ничего не нужно скачивать.
        # Затем Chrome, затем Chromium от Playwright (если установлен).
        # У каждого браузера свой профиль: профили разных браузеров несовместимы.
        errors = []
        for channel in ("msedge", "chrome", None):
            profile = PROFILE_DIR / (channel or "chromium")
            try:
                self.ctx = self._pw.chromium.launch_persistent_context(
                    user_data_dir=str(profile), **({"channel": channel} if channel else {}), **kwargs)
                break
            except Exception as e:  # noqa: BLE001
                errors.append(f"{channel or 'chromium'}: {str(e).splitlines()[0]}")
        else:
            raise RuntimeError("Не удалось открыть браузер (нужен Microsoft Edge или Google Chrome). "
                               + " | ".join(errors))
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.page.set_default_timeout(self.timeout)

    def stop(self):
        try:
            if self.ctx:
                self.ctx.close()
        finally:
            if self._pw:
                self._pw.stop()

    def ensure_logged_in(self, wait_minutes: int = 5):
        p = self.page
        p.goto(self.base_url + "/dashboard/", wait_until="domcontentloaded")
        if self._nav_deals_visible(5000):
            return
        self.log_cb(f"Войдите в amoCRM в открывшемся окне браузера (жду до {wait_minutes} мин)...")
        deadline = time.time() + wait_minutes * 60
        while time.time() < deadline:
            if self._nav_deals_visible(2000):
                self.log_cb("Вход выполнен.")
                return
        raise RuntimeError("Не дождался входа в amoCRM")

    def _nav_deals_visible(self, timeout: int) -> bool:
        try:
            self._nav_deals().wait_for(state="visible", timeout=timeout)
            return True
        except PWTimeout:
            return False

    # ---------- поиск элементов ----------
    def _nav_deals(self) -> Locator:
        p = self.page
        loc = p.locator(", ".join(SEL["nav_deals"]))
        return loc.or_(p.get_by_text(SEL["nav_deals_text"], exact=True)).first

    def _deal_name_input(self) -> Locator:
        p = self.page
        return p.get_by_placeholder(SEL["deal_name_placeholder"]).or_(
            p.locator(", ".join(SEL["deal_name_css"]))).first

    def _empty_contact_name_inputs(self) -> Locator:
        return self.page.get_by_placeholder(SEL["contact_name_placeholder"], exact=True)

    @staticmethod
    def _contact_form(name_input: Locator) -> Locator:
        """Ближайший общий блок поля ФИО и подписи «Должность» = форма этого контакта."""
        lbl = SEL["label_position"]
        return name_input.locator(
            f'xpath=ancestor::*[.//*[normalize-space(text())="{lbl}"]][1]')

    @staticmethod
    def _field_by_label(scope: Locator, label: str) -> Locator:
        """Первое видимое текстовое поле в строке с подписью label."""
        return scope.locator(
            f'xpath=.//*[normalize-space(text())="{label}"]'
            f'/ancestor::*[.//input[not(@type="hidden") and not(@type="checkbox")]][1]'
            f'//input[not(@type="hidden") and not(@type="checkbox")]'
        ).first

    def _click_save(self):
        p = self.page
        btn = p.get_by_role("button", name=SEL["save_text"], exact=True).or_(
            p.locator(f'button:has-text("{SEL["save_text"]}")')).first
        btn.click()

    def _pause(self, msg: str):
        if self.pause_cb:
            self.pause_cb(msg)
        elif self.step:
            input(f"   [пошагово] {msg} — Enter, чтобы продолжить...")

    def screenshot(self, name: str) -> Path:
        LOG_DIR.mkdir(exist_ok=True)
        safe = re.sub(r"[^\w.-]+", "_", name)
        path = LOG_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{safe}.png"
        try:
            self.page.screenshot(path=str(path), full_page=True)
        except Exception:
            pass
        return path

    # ---------- сценарий ----------
    def _pipeline_href(self, pipeline: str) -> str:
        """Ссылка на воронку из меню «Сделки» (ищем и среди скрытых пунктов)."""
        return self.page.evaluate("""name => {
            const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            const a = [...document.querySelectorAll('a[href*="/leads/pipeline/"]')]
                .find(a => norm(a.textContent) === norm(name));
            return a ? a.href : '';
        }""", pipeline)

    def open_pipeline(self, pipeline: str):
        """Открывает воронку по её ссылке из меню «Сделки».

        Раньше бот наводил курсор и кликал в подменю, но amoCRM после этого оставлял
        затемнение страницы. Теперь ссылка берётся из меню один раз и открывается напрямую —
        страница загружается заново, без затемнения.
        """
        p = self.page
        href = self._pipeline_urls.get(pipeline) or self._pipeline_href(pipeline)
        if not href:
            # пункты меню ещё не отрисованы — наводим на «Сделки», чтобы меню появилось
            for _ in range(3):
                self._nav_deals().hover()
                p.wait_for_timeout(1200)
                href = self._pipeline_href(pipeline)
                if href:
                    break
                self._mouse_away()
            self._mouse_away()
            p.keyboard.press("Escape")
        if not href:
            raise RuntimeError(f"Не нашёл воронку «{pipeline}» в меню «Сделки»")
        self._pipeline_urls[pipeline] = href
        p.goto(href, wait_until="domcontentloaded")
        self._mouse_away()

    def list_pipelines(self) -> list[str]:
        """Названия воронок из меню «Сделки» (без наведения — пункты есть в разметке)."""
        names = self.page.evaluate("""() => [...document.querySelectorAll('a[href*="/leads/pipeline/"]')]
            .map(a => [(a.textContent || '').replace(/\\s+/g, ' ').trim(), a.href])
            .filter(([t]) => t && t.length < 60)""")
        out = []
        for name, href in names:
            if name not in out:
                out.append(name)
                self._pipeline_urls.setdefault(name, href)
        return out

    def open_deal(self, url: str):
        """Открывает уже созданную сделку (для дозаполнения контактов)."""
        self.page.goto(url, wait_until="domcontentloaded")
        self._mouse_away()

    def deal_url(self) -> str:
        """Ссылка на текущую сделку без служебных параметров (?after_add=yes...)."""
        m = re.search(r"^(.*?/leads/detail/\d+)", self.page.url)
        return m.group(1) if m else self.page.url

    def _mouse_away(self):
        """Уводит курсор в правую часть окна, чтобы закрылось всплывающее меню «Сделки»."""
        p = self.page
        w, h = p.evaluate("[window.innerWidth, window.innerHeight]")
        p.mouse.move(w * 0.75, h * 0.6, steps=5)
        p.wait_for_timeout(600)

    def _is_clickable(self, loc: Locator) -> bool:
        """Не перекрыт ли элемент затемнением/всплывашкой: что лежит сверху в его центре."""
        try:
            # проверяем центр каждой части элемента (ссылка может переноситься на несколько строк)
            return loc.evaluate("""el => [...el.getClientRects()].some(r => {
                const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
                return !!top && (el === top || el.contains(top) || top.contains(el)); })""")
        except Exception:
            return False

    def _click_when_free(self, loc: Locator, what: str, timeout_s: float = 15):
        """Кликает, когда элемент не перекрыт. Если перекрыт — уводит курсор и жмёт Escape."""
        p = self.page
        loc.wait_for(state="visible", timeout=int(timeout_s * 1000))
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:  # кнопка может быть за краем маленького окна
                loc.scroll_into_view_if_needed(timeout=2000)
            except PWTimeout:
                pass
            if self._is_clickable(loc):
                loc.click()
                return
            self._mouse_away()
            if not self._is_clickable(loc):
                p.keyboard.press("Escape")
                p.wait_for_timeout(500)
        raise RuntimeError(f"Кнопка «{what}» перекрыта (страница затемнена) и не нажимается")

    def open_new_deal(self, pipeline: str = ""):
        p = self.page
        if pipeline:
            self.open_pipeline(pipeline)
        else:
            self._nav_deals().click()
            p.wait_for_load_state("domcontentloaded")
            self._mouse_away()
        btn = p.locator('a[href*="/leads/add"]').locator("visible=true").or_(
            p.get_by_text(SEL["new_deal_text"], exact=False).locator("visible=true")).first
        try:
            self._click_when_free(btn, SEL["new_deal_text"])
        except PWTimeout:
            if pipeline:
                raise RuntimeError("Не нашёл кнопку «Новая сделка» на странице воронки")
            # запасной путь — прямая ссылка на форму новой сделки
            p.goto(self.base_url + "/leads/add/", wait_until="domcontentloaded")
        self._deal_name_input().wait_for(state="visible")

    def fill_deal_name(self, name: str):
        inp = self._deal_name_input()
        inp.click()
        inp.fill(name)

    def _find_empty_contact_input(self) -> Locator | None:
        loc = self._empty_contact_name_inputs()
        for i in reversed(range(loc.count())):
            el = loc.nth(i)
            try:
                if el.is_visible() and el.input_value() == "":
                    return el
            except Exception:
                continue
        return None

    def fill_contact(self, c: Contact, company: str = ""):
        """Заполняет форму контакта. company — в поле «Название компании» (класс + школа)."""
        p = self.page
        name_inp = self._find_empty_contact_input()
        if name_inp is None:
            # пустой формы контакта нет — нажимаем «+ Добавить контакт»
            p.get_by_text(SEL["add_contact_text"], exact=True).last.click()
            p.wait_for_timeout(700)
            name_inp = self._find_empty_contact_input()
        if name_inp is None:
            raise RuntimeError("Не нашёл пустое поле «Добавить контакт»")
        form = self._contact_form(name_inp)

        name_inp.click()
        name_inp.fill(c.name)
        # amoCRM показывает подсказки существующих контактов — не выбираем их,
        # просто уходим в следующее поле, чтобы создался новый контакт.
        phone_inp = self._field_by_label(form, SEL["label_phone"])
        phone_inp.click()
        phone_inp.fill(c.phone_field)

        pos_inp = self._field_by_label(form, SEL["label_position"])
        pos_inp.click()
        pos_inp.fill(c.role)

        if company:
            # заполняем последним: подсказки существующих компаний не перекроют другие поля
            comp_inp = form.get_by_placeholder(SEL["company_placeholder"]).first
            if comp_inp.count() == 0 or not comp_inp.is_visible():
                comp_inp = self._field_by_label(form, SEL["label_company"])
            comp_inp.click()
            comp_inp.fill(company)
            self._mouse_away()

    def save(self):
        p = self.page
        new_deal = "/leads/add" in p.url
        self._click_save()
        # Не ждём «networkidle»: amoCRM постоянно держит соединения, и такое ожидание
        # никогда не заканчивается. Ждём конкретных признаков сохранения.
        if new_deal:
            # сделка создана — адрес меняется на /leads/detail/<id>
            p.wait_for_url(re.compile(r"/leads/detail/\d+"), timeout=30000)
        # кнопка «Сохранить» исчезает, когда изменения записаны
        save_btn = p.get_by_role("button", name=SEL["save_text"], exact=True)
        try:
            save_btn.locator("visible=true").first.wait_for(state="hidden", timeout=20000)
        except PWTimeout:
            raise RuntimeError("После «Сохранить» кнопка не исчезла — amoCRM не сохранил изменения")
        p.wait_for_timeout(1500)

    def create_deal(self, deal: Deal, pipeline: str = "") -> str:
        """Создаёт сделку, возвращает её URL."""
        self.open_new_deal(pipeline)
        self.fill_deal_name(deal.name)
        for i, c in enumerate(deal.contacts):
            self.fill_contact(c, company=deal.name)
            self._pause(f"{deal.name}: заполнен {c.role} ({c.name}), дальше «Сохранить»")
            self.save()
            if "/leads/add" in self.page.url and i == 0:
                raise RuntimeError("После «Сохранить» сделка не создалась (адрес не сменился)")
        if not deal.contacts:
            self._pause(f"{deal.name}: контактов нет, дальше «Сохранить»")
            self.save()
        return self.page.url

    # ---------- диагностика ----------
    def probe(self) -> Path:
        """Открывает форму новой сделки и выгружает описание полей в logs/probe.txt (ничего не сохраняет)."""
        self.open_new_deal()
        info = self.page.evaluate("""() => [...document.querySelectorAll('input, textarea, button, [contenteditable]')]
            .filter(e => e.offsetParent !== null)
            .map(e => ({tag: e.tagName, type: e.type || '', name: e.name || '', id: e.id || '',
                        ph: e.placeholder || '', cls: (e.className || '').toString().slice(0, 80),
                        text: (e.innerText || e.value || '').slice(0, 40),
                        label: (e.closest('div') && e.closest('div').parentElement
                                ? e.closest('div').parentElement.innerText.slice(0, 60) : '').replace(/\\s+/g, ' ')}))""")
        LOG_DIR.mkdir(exist_ok=True)
        out = LOG_DIR / "probe.txt"
        out.write_text("\n".join(str(x) for x in info), encoding="utf-8")
        self.screenshot("probe")
        return out
