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
from paths import LOG_DIR, PROFILE_DIR, RES_DIR

SEL = {
    # левое меню и кнопка на странице сделок
    "nav_deals": ['#nav_menu a[href*="/leads"]', 'a.nav__menu__item__link[href*="/leads"]'],
    "nav_deals_text": "Сделки",
    "new_deal_text": "Новая сделка",
    # название сделки в шапке карточки
    "deal_name_placeholder": re.compile(r"Сделка\s*#"),
    "deal_name_css": ['[name="lead[NAME]"]', "#person_n"],
    # теги в шапке карточки
    "tag_button": re.compile(r"^#\s*т[еэ]гировать$", re.IGNORECASE),
    "tag_editor": '[class*="tags"] input:not([type="hidden"]), input[class*="tags"], [class*="tags"] [contenteditable="true"]',
    "tag_options": '[role="option"], .tags-lib__item, .tags-lib__tag',
    # контакт
    "contact_name_placeholder": "Добавить контакт",
    "label_phone": "Раб. тел.",
    "label_position": "Должность",
    "label_company": "Компания",
    "company_placeholder": "Название компании",
    "add_contact_text": "Добавить контакт",
    "save_text": "Сохранить",
    # примечание внизу ленты сделки: «Примечание: введите текст» → «Добавить»
    "note_composer": [".feed-compose", ".notes-wrapper .feed-compose__inner", '[class*="feed-compose"]'],
    "note_switcher": '.feed-compose-switcher, [class*="switcher"]',
    "note_text": "Примечание",
    "note_add_text": "Добавить",
}



class BrowserClosed(RuntimeError):
    """Пользователь закрыл окно браузера amoCRM."""
    def __init__(self):
        super().__init__("Окно amoCRM закрыто")


def is_closed_error(e: BaseException) -> bool:
    """Ошибка Playwright из-за закрытого окна/браузера (а не из-за самой amoCRM)."""
    if isinstance(e, BrowserClosed):
        return True
    m = str(e)
    return any(s in m for s in ("has been closed", "Target closed", "Browser closed", "Connection closed"))


STOPPED_MSG = "Остановлено пользователем"


class AmoBot:
    def __init__(self, base_url: str, step: bool = False, slow_mo: int = 150, timeout: int = 15000, browser: str = "auto"):
        self.base_url = base_url.rstrip("/")
        self.browser = browser
        self.step = step
        self.slow_mo = slow_mo
        self.timeout = timeout
        self.pause_cb = None      # функция(msg) — для пошагового режима из интерфейса
        self.log_cb = print       # функция(msg) — куда писать ход работы
        self._pipeline_urls: dict[str, str] = {}  # название воронки -> ссылка
        self._pw = None
        self.ctx: BrowserContext | None = None
        self.page: Page | None = None
        self._ctx_closed = False
        self.should_stop = lambda: False  # функция() -> True, если нажали «Стоп»

    # ---------- запуск / вход ----------
    def start(self):
        bundled = RES_DIR / "chromium-browsers"
        if bundled.is_dir():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled)
        self._pw = sync_playwright().start()
        # AMO_HEADLESS=1 — без окна браузера, только для автоматических проверок
        kwargs = dict(headless=os.environ.get("AMO_HEADLESS") == "1", slow_mo=self.slow_mo,
                      no_viewport=True,  # страница подстраивается под реальный размер окна
                      # если браузер закрылся аварийно — не предлагать «восстановить вкладки»
                      args=["--start-maximized", "--hide-crash-restore-bubble"])
        # Edge есть на любом Windows 10/11 — тогда ничего не нужно скачивать.
        # Затем Chrome, затем Chromium от Playwright (если установлен).
        # У каждого браузера свой профиль: профили разных браузеров несовместимы.
        errors = []
        choices = {"auto": ("msedge", "chrome", None), "msedge": ("msedge",), "chromium": (None,)}
        for channel in choices[self.browser]:
            profile = PROFILE_DIR / (channel or "chromium")
            try:
                self.ctx = self._pw.chromium.launch_persistent_context(
                    user_data_dir=str(profile), channel=channel or "chromium", **kwargs)
                break
            except Exception as e:  # noqa: BLE001
                errors.append(f"{channel or 'chromium'}: {str(e).splitlines()[0]}")
        else:
            self._pw.stop()
            self._pw = None
            hint = " Для запуска из исходников установите Chromium через python -m playwright install chromium." if self.browser == "chromium" else ""
            raise RuntimeError("Не удалось открыть браузер. " + " | ".join(errors) + hint)
        self.ctx.on("close", lambda *_: setattr(self, "_ctx_closed", True))
        self.page = next((p for p in self.ctx.pages if p.url.startswith(self.base_url + "/")), None)
        if self.page is None:
            self.page = next((p for p in self.ctx.pages if p.url == "about:blank"), None)
        if self.page is None:
            self.page = self.ctx.new_page()
        self.page.set_default_timeout(self.timeout)

    @property
    def closed(self) -> bool:
        return self._ctx_closed or self.page is None or self.page.is_closed()

    def stop(self):
        """Закрывает браузер amoCRM (если пользователь его ещё не закрыл)."""
        for fn in (lambda: self.ctx and self.ctx.close(), lambda: self._pw and self._pw.stop()):
            try:
                fn()
            except Exception:  # noqa: BLE001 — уже закрыт
                pass
        self.ctx = self._pw = self.page = None

    def wait(self, ms: int):
        """Пауза, во время которой Playwright замечает закрытие окна (тогда — BrowserClosed)."""
        try:
            self.page.wait_for_timeout(ms)
        except Exception as e:  # noqa: BLE001
            if is_closed_error(e) or self.closed:
                raise BrowserClosed() from None
            raise

    def check_stop(self):
        """Нажали «Стоп» — прерываемся здесь же (браузер не закрываем)."""
        if self.should_stop():
            raise RuntimeError(STOPPED_MSG)

    def _sleep(self, ms: int):
        """Пауза кусочками, чтобы «Стоп» срабатывал сразу."""
        end = time.time() + ms / 1000
        while True:
            self.check_stop()
            left = end - time.time()
            if left <= 0:
                return
            self.wait(int(min(left, 0.2) * 1000))

    def _wait_until(self, fn, timeout_ms: int, step_ms: int = 300) -> bool:
        """Ждёт, пока fn() не станет True (fn сама ждёт не дольше step_ms), проверяя «Стоп»."""
        end = time.time() + timeout_ms / 1000
        while time.time() < end:
            self.check_stop()
            try:
                if fn():
                    return True
            except PWTimeout:
                pass
        return False

    def ensure_logged_in(self, wait_minutes: int = 5, cancelled=lambda: False):
        p = self.page
        try:
            p.goto(self.base_url + "/dashboard/", wait_until="domcontentloaded")
            if self._nav_deals_visible(5000):
                return
            self.log_cb(f"Войдите в amoCRM в открывшемся окне браузера (жду до {wait_minutes} мин)...")
            deadline = time.time() + wait_minutes * 60
            while time.time() < deadline:
                if cancelled():
                    raise RuntimeError("Вход отменён — открываю окно amoCRM заново")
                self.check_stop()
                if self._nav_deals_visible(1000):
                    self.log_cb("Вход выполнен.")
                    return
        except Exception as e:  # noqa: BLE001
            if is_closed_error(e) or self.closed:
                raise BrowserClosed() from None
            raise
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
        self.check_stop()
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
    @staticmethod
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", s or "").strip().lower()

    def _pipelines_from_api(self) -> dict[str, str]:
        """Воронки через API amoCRM из уже открытой (залогиненной) страницы — без меню.
        {название: ссылка}; пусто, если API не ответил."""
        try:
            data = self.page.evaluate("""async () => {
                const r = await fetch('/api/v4/leads/pipelines', {credentials: 'include',
                    headers: {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'}});
                if (!r.ok) return [];
                const j = await r.json();
                return ((j._embedded || {}).pipelines || []).map(p => [p.name, p.id]);
            }""")
        except Exception as e:  # noqa: BLE001
            if is_closed_error(e):
                raise
            return {}
        return {name: f"{self.base_url}/leads/pipeline/{pid}/" for name, pid in data if name and pid}

    def stored_pipeline_names(self, urls):
        """Разрешает старые записи истории по фактической воронке карточки."""
        from urllib.parse import urlsplit
        ids = {}
        for url in urls:
            if url and urlsplit(url).netloc == urlsplit(self.base_url).netloc:
                match = re.fullmatch(r"/leads/detail/(\d+)/?", urlsplit(url).path)
                if match:
                    ids[match[1]] = url
        if not ids:
            return {}
        names = {url.rstrip("/").split("/")[-1]: name for name, url in self._pipelines_from_api().items()}
        result = {}
        for start in range(0, len(ids), 50):
            batch = list(ids)[start:start+50]
            leads = self.page.evaluate("""async ids => {
                const q = new URLSearchParams();
                ids.forEach(id => q.append('filter[id][]', id));
                const r = await fetch('/api/v4/leads?' + q);
                if (r.status !== 200) return [];
                return (await r.json())._embedded?.leads || [];
            }""", batch)
            for lead in leads:
                ident, pid = str(lead["id"]), str(lead["pipeline_id"])
                if ident in ids and pid in names:
                    result[ids[ident]] = names[pid]
        return result

    def _pipelines_from_menu(self) -> dict[str, str]:
        """Пункты воронок, которые сейчас есть в разметке меню «Сделки» (в том числе скрытые)."""
        pairs = self.page.evaluate("""() => [...document.querySelectorAll('a[href*="/leads/pipeline/"]')]
            .map(a => [(a.textContent || '').replace(/\\s+/g, ' ').trim(), a.href])
            .filter(([t]) => t && t.length < 80)""")
        return {name: href for name, href in pairs}

    def _match(self, found: dict[str, str], pipeline: str) -> str:
        """Ссылка на воронку: сначала точное совпадение названия, потом «начинается с»
        (в меню к названию может добавляться число сделок)."""
        want = self._norm(pipeline)
        for name, href in found.items():
            if self._norm(name) == want:
                return href
        for name, href in found.items():
            if self._norm(name).startswith(want):
                return href
        return ""

    def _pipeline_via_hover(self, pipeline: str) -> str:
        """Запасной путь: навести на «Сделки», увести курсор в столбец воронок и держать его там,
        пока не появится нужная воронка (раньше курсор уводился в сторону и меню сворачивалось)."""
        p = self.page
        for _ in range(3):
            self.check_stop()
            nav = self._nav_deals()
            nav.hover()
            box = nav.bounding_box()
            if box:  # вправо от иконки «Сделки» — туда, где выезжает столбец воронок
                p.mouse.move(box["x"] + box["width"] + 40, box["y"] + box["height"] / 2, steps=8)
            href = ""

            def found():
                nonlocal href
                href = self._match(self._pipelines_from_menu(), pipeline)
                if not href:
                    self.wait(250)
                return bool(href)

            if self._wait_until(found, 5000):
                return href
        return ""

    def open_pipeline(self, pipeline: str):
        """Открывает воронку по прямой ссылке (страница загружается заново, без затемнения).
        Ссылка: из запомненных → из API amoCRM → из разметки меню → наведением на «Сделки»."""
        p = self.page
        href = self._pipeline_urls.get(pipeline)
        if not href:
            for source in (self._pipelines_from_api, self._pipelines_from_menu):
                found = source()
                self._pipeline_urls.update({k: v for k, v in found.items() if k not in self._pipeline_urls})
                href = self._match(found, pipeline)
                if href:
                    break
        if not href:
            href = self._pipeline_via_hover(pipeline)
            self._mouse_away()
            p.keyboard.press("Escape")
        if not href:
            raise RuntimeError(f"Не нашёл воронку «{pipeline}» в меню «Сделки»")
        self._pipeline_urls[pipeline] = href
        self.check_stop()
        p.goto(href, wait_until="domcontentloaded")
        self._mouse_away()

    def list_pipelines(self) -> list[str]:
        """Названия воронок: через API amoCRM, если не вышло — из разметки меню «Сделки»."""
        found = self._pipelines_from_api() or self._pipelines_from_menu()
        for name, href in found.items():
            self._pipeline_urls.setdefault(name, href)
        return list(found)

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
        p.mouse.move(w * 0.75, h * 0.6, steps=3)
        self._sleep(250)

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
        if not self._wait_until(lambda: loc.wait_for(state="visible", timeout=300) or True, int(timeout_s * 1000)):
            raise PWTimeout(f"Не дождался кнопки «{what}»")
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            self.check_stop()
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
                self._sleep(500)
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
        if not self._wait_until(lambda: self._deal_name_input().wait_for(state="visible", timeout=300) or True,
                                self.timeout):
            raise RuntimeError("Не открылась форма новой сделки")

    def fill_deal_name(self, name: str):
        self.check_stop()
        inp = self._deal_name_input()
        inp.click()
        inp.fill(name)

    def fill_deal_tag(self, tag: str):
        self.check_stop()
        p = self.page
        exact_tag = re.compile(r"^#?\s*" + re.escape(re.sub(r"\s+", " ", tag)) + r"$")
        chips = p.get_by_text(exact_tag).locator("visible=true")
        initial_count = chips.count()

        button = p.get_by_text(SEL["tag_button"], exact=True).locator("visible=true").first
        button.click()
        focused = p.locator('input:not([type="hidden"]):not([name="lead[NAME]"]):not(#person_n):focus, [contenteditable="true"]:focus')
        editor = focused.or_(p.locator(SEL["tag_editor"])).locator("visible=true").first
        editor.fill(tag)

        option = p.locator(SEL["tag_options"]).filter(
            has_text=exact_tag).locator("visible=true").first
        if option.count():
            option.click()
        else:
            editor.press("Enter")

        try:
            option.wait_for(state="hidden", timeout=self.timeout)
            chips.nth(initial_count).wait_for(state="visible", timeout=self.timeout)
        except PWTimeout as exc:
            raise RuntimeError(f"amoCRM не подтвердил добавление тега «{tag}»") from exc

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
        self.check_stop()
        name_inp = self._find_empty_contact_input()
        if name_inp is None:
            # пустой формы контакта нет — нажимаем «+ Добавить контакт»
            p.get_by_text(SEL["add_contact_text"], exact=True).last.click()
            self._sleep(700)
            name_inp = self._find_empty_contact_input()
        if name_inp is None:
            raise RuntimeError("Не нашёл пустое поле «Добавить контакт»")
        form = self._contact_form(name_inp)

        self.check_stop()
        name_inp.click()
        name_inp.fill(c.name)
        # amoCRM показывает подсказки существующих контактов — не выбираем их,
        # просто уходим в следующее поле, чтобы создался новый контакт.
        self.check_stop()
        phone_inp = self._field_by_label(form, SEL["label_phone"])
        phone_inp.click()
        phone_inp.fill(c.phone_field)

        self.check_stop()
        pos_inp = self._field_by_label(form, SEL["label_position"])
        pos_inp.click()
        pos_inp.fill(c.role)

        if company:
            self.check_stop()
            # заполняем последним: подсказки существующих компаний не перекроют другие поля
            comp_inp = form.get_by_placeholder(SEL["company_placeholder"]).first
            if comp_inp.count() == 0 or not comp_inp.is_visible():
                comp_inp = self._field_by_label(form, SEL["label_company"])
            comp_inp.click()
            comp_inp.fill(company)
            self._mouse_away()

    def save(self):
        """После нажатия «Сохранить» «Стоп» уже не прерывает: иначе сделка может сохраниться,
        а программа об этом не узнает и при повторе создаст дубль. Ожидание — несколько секунд."""
        p = self.page
        self.check_stop()
        new_deal = "/leads/add" in p.url
        try:
            self._save_and_wait(new_deal)
        except Exception as exc:
            exc.uncertain_save = True
            raise

    def _save_and_wait(self, new_deal):
        p = self.page
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
        p.wait_for_timeout(500)

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

    # ---------- примечание ----------
    def _note_composer(self) -> Locator:
        """Поле ввода внизу ленты сделки («Примечание: введите текст»)."""
        p = self.page
        for sel in SEL["note_composer"]:
            loc = p.locator(sel).locator("visible=true")
            if loc.count():
                return loc.last
        raise RuntimeError("Не нашёл поле «Примечание» внизу карточки сделки")

    def _note_via_api(self, text: str) -> bool:
        """Примечание через API amoCRM из залогиненной страницы: мгновенно и без поля ввода.
        False — API не принял (тогда пишем через поле внизу карточки)."""
        m = re.search(r"/leads/detail/(\d+)", self.page.url)
        if not m:
            return False
        try:
            res = self.page.evaluate("""async ([id, text]) => {
                const csrf = (document.cookie.match(/(?:^|;\\s*)csrf_token=([^;]+)/) || [])[1];
                const headers = {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json',
                                 'Content-Type': 'application/json'};
                if (csrf) headers['X-CSRF-Token'] = decodeURIComponent(csrf);
                const r = await fetch(`/api/v4/leads/${id}/notes`, {method: 'POST', credentials: 'include',
                    headers, body: JSON.stringify([{note_type: 'common', params: {text}}])});
                let body; try { body = await r.json(); } catch (e) {}
                const notes = body?._embedded?.notes ?? (Array.isArray(body) ? body : [body]);
                return {status: r.status, saved: Array.isArray(notes) && notes.some(n => n?.id != null)};
            }""", [int(m.group(1)), text])
        except Exception as e:  # noqa: BLE001
            if is_closed_error(e):
                raise
            self.log_cb(f"   API примечаний недоступен ({str(e).splitlines()[0][:120]}), пишу через поле")
            return False
        if res["status"] in (200, 201) and res["saved"]:
            return True
        self.log_cb(f"   API примечаний ответил {res['status']}, пишу через поле")
        return False

    @staticmethod
    def _composer_mode(comp: Locator) -> str:
        """Режим поля ввода по началу текста: «примечание», «чат», «задача»."""
        try:
            head = comp.inner_text(timeout=1000)
        except Exception:  # noqa: BLE001
            return ""
        m = re.match(r"\s*([А-Яа-яЁё]+)", head)
        return m.group(1).lower() if m else ""

    # Пункт «Примечание» в раскрывшемся меню режимов — ближайший к переключателю видимый элемент
    # с ровно этим текстом (самый глубокий, чтобы клик пришёлся на сам пункт).
    _NOTE_OPTION_JS = """([word, x, y]) => {
        const items = [...document.querySelectorAll('body *')].filter(el => {
            if ((el.innerText || '').trim() !== word) return false;
            if ([...el.children].some(c => (c.innerText || '').trim() === word)) return false;
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
        }).map(el => { const r = el.getBoundingClientRect();
            return {x: r.x + r.width / 2, y: r.y + r.height / 2}; });
        items.sort((a, b) => Math.hypot(a.x - x, a.y - y) - Math.hypot(b.x - x, b.y - y));
        return items[0] || null;
    }"""

    def _switch_to_note(self, comp: Locator):
        """Переключает поле ввода в «Примечание». Не получилось — ошибка ДО ввода текста:
        в режиме «Чат» текст ушёл бы клиенту."""
        want = SEL["note_text"].lower()
        for _ in range(3):
            mode = self._composer_mode(comp)
            if mode == want:
                return
            self.check_stop()
            link = comp.get_by_text(re.compile(rf"^\s*{re.escape(mode)}\s*$", re.I)).first if mode else None
            if link is None or not link.count():
                link = comp.locator(SEL["note_switcher"]).locator("visible=true").first
            box = link.bounding_box() if link.count() else None
            if not box:
                break
            link.click()
            self._sleep(300)
            opt = self.page.evaluate(self._NOTE_OPTION_JS,
                                     [SEL["note_text"], box["x"] + box["width"] / 2, box["y"] + box["height"] / 2])
            if opt:
                self.page.mouse.click(opt["x"], opt["y"])
            self._sleep(300)
        if self._composer_mode(comp) != want:
            raise RuntimeError("Не удалось переключить поле внизу сделки на «Примечание» — текст не вписан")

    def add_note(self, text: str):
        """Добавляет примечание в открытую сделку: через API amoCRM, а если он не принял —
        через поле «Примечание» внизу карточки и кнопку «Добавить» (только в режиме «Примечание»)."""
        p = self.page
        lines = text.split("\n")
        self._pause(f"Будет добавлено примечание со списком детей ({len(lines) - 1}). «Продолжить» — добавить")
        self.check_stop()
        if self._note_via_api(text):
            return
        comp = self._note_composer()
        comp.scroll_into_view_if_needed(timeout=3000)
        self._switch_to_note(comp)
        area = comp.locator('[contenteditable="true"], textarea').locator("visible=true").first
        if not area.count():
            raise RuntimeError("Не нашёл редактируемое поле примечания")
        box = area
        box.click()
        p.keyboard.press("Control+A")  # поле могло остаться с прошлым текстом
        p.keyboard.press("Delete")
        for i, line in enumerate(lines):
            if i:
                p.keyboard.press("Shift+Enter")
            p.keyboard.insert_text(line)
        self.check_stop()
        if self._composer_mode(comp) != SEL["note_text"].lower():  # режим сменился во время ввода
            p.keyboard.press("Control+A")
            p.keyboard.press("Delete")
            raise RuntimeError("Поле внизу сделки не в режиме «Примечание» — текст стёрт, ничего не отправлено")
        btn = comp.get_by_role("button", name=SEL["note_add_text"], exact=True).or_(
            comp.locator(f'button:has-text("{SEL["note_add_text"]}")')).locator("visible=true").first
        if not btn.count():
            raise RuntimeError("Не нашёл кнопку «Добавить» у примечания")
        btn.click()
        end = time.monotonic() + 10
        while box.evaluate("(el) => (el.value ?? el.textContent ?? '').trim()", timeout=2000):
            if time.monotonic() > end:
                raise RuntimeError("Примечание не добавилось (текст остался в поле)")
            self._sleep(250)

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
