"""Приложение «Сделки в amoCRM»: создание сделок из xlsx-отчёта.

Запуск: «Сделки amoCRM.exe» (или `python app.py` из исходников).
Интерфейс — страница http://127.0.0.1:8765 в отдельном окне браузера.
Браузер с amoCRM управляется из фонового потока (Playwright).
"""

from __future__ import annotations

import os
import queue
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

import paths

# В exe без консоли sys.stdout/stderr = None: print и логи Flask упали бы — пишем их в файл
if sys.stdout is None or sys.stderr is None:
    paths.LOG_DIR.mkdir(exist_ok=True)
    _console = open(paths.LOG_DIR / "console.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _console
    sys.stderr = sys.stderr or _console

from flask import Flask, jsonify, request, send_from_directory  # noqa: E402

import history  # noqa: E402
from excel_reader import Contact, Deal, fix_name_case, read_deals  # noqa: E402
from kids_lists import class_key, count_kids  # noqa: E402

CONFIG = paths.load_config()
if os.environ.get("AMO_URL"):  # для проверок на макете amoCRM
    CONFIG["amo_url"] = os.environ["AMO_URL"]
PROGRESS = paths.PROGRESS_FILE
UPLOADS = paths.UPLOADS_DIR
LOG_DIR = paths.LOG_DIR
IDLE_EXIT_SEC = 180  # запасной вариант, если процесс окна не найден: окно молчит так долго — выходим
WINDOW_PROFILE = paths.DATA_DIR / "app-window"  # отдельный профиль браузера для окна программы

app = Flask(__name__, static_folder=str(paths.STATIC_DIR))
_last_seen = time.time()  # когда окно приложения последний раз обращалось к серверу


# ---------------- общее состояние ----------------
class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.log: list[str] = []
        self.rows: dict[str, dict] = {}   # id строки -> {status, url, error}
        self.running = False
        self.logged_in = False
        self.browser_open = False
        self.phase: str | None = None      # "login" — открываем amoCRM / ждём входа, "run" — создаём сделки
        self.relogin = False               # пользователь ещё раз нажал «войти» — прервать текущий вход
        self.waiting: str | None = None    # текст паузы в пошаговом режиме
        self.stop_flag = False
        self.continue_evt = threading.Event()
        self.total = self.done_n = self.failed_n = self.notes_n = 0
        self.pipelines: list[str] = list(CONFIG.get("pipelines", []))

    def add_log(self, msg: str):
        line = f"{time.strftime('%H:%M:%S')}  {msg}"
        with self.lock:
            self.log.append(line)
            self.log = self.log[-500:]
        try:  # журнал на диске — чтобы разобраться после закрытия окна
            LOG_DIR.mkdir(exist_ok=True)
            with open(LOG_DIR / "app.log", "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d ") + line + "\n")
        except OSError:
            pass

    def set_row(self, rid: str, **kw):
        with self.lock:
            self.rows.setdefault(rid, {}).update(kw)


S = State()
jobs: "queue.Queue[tuple[str, dict]]" = queue.Queue()


def load_progress() -> dict:
    data = paths.read_json(PROGRESS, {})
    return data if isinstance(data, dict) else {}


def save_progress(p: dict):
    paths.write_json(PROGRESS, p)


# ---------------- фоновый поток с браузером ----------------
def worker():
    """Все вызовы Playwright — только в этом потоке."""
    from amo_bot import AmoBot, BrowserClosed, is_closed_error

    bot: AmoBot | None = None

    def pause(msg: str):
        S.continue_evt.clear()
        S.waiting = msg
        S.add_log("⏸ " + msg)
        try:
            while not S.continue_evt.is_set():
                if S.stop_flag:
                    raise RuntimeError("Остановлено пользователем")
                bot.wait(300)  # ждём через Playwright — так сразу видно, если окно amoCRM закрыли
        finally:
            S.waiting = None

    def close_bot():
        nonlocal bot
        if bot is not None:
            bot.stop()
            bot = None
        S.logged_in = S.browser_open = False

    def ensure_bot():
        nonlocal bot
        if bot is not None:
            try:
                if bot.closed:
                    raise BrowserClosed()
                bot.page.title()
                return bot
            except Exception:  # noqa: BLE001 — окно закрыли, откроем заново
                close_bot()
        S.add_log("Открываю браузер amoCRM...")
        bot = AmoBot(CONFIG["amo_url"], slow_mo=CONFIG.get("slow_mo_ms", 150))
        bot.log_cb = S.add_log
        bot.ui_pause = pause
        bot.should_stop = lambda: S.stop_flag
        bot.start()
        S.browser_open = True
        bot.ensure_logged_in(wait_minutes=10, cancelled=lambda: S.relogin)
        S.logged_in = True
        try:
            found = bot.list_pipelines()
            if found:
                S.pipelines = found
                S.add_log("Воронки в amoCRM: " + ", ".join(found))
        except Exception:  # noqa: BLE001
            pass
        return bot

    while True:
        kind, payload = jobs.get()
        S.running, S.phase = True, kind
        try:
            if kind == "login":
                S.relogin = False
                if bot is not None:  # новое окно amoCRM — старое закрываем
                    S.add_log("Закрываю прежнее окно amoCRM.")
                    close_bot()
                ensure_bot()
            elif kind == "run":
                try:
                    b = ensure_bot()  # не вошли в amoCRM — в историю нечего писать
                    try:
                        run_deals(b, payload["deals"], payload.get("step", False), payload.get("pipeline", ""),
                                  payload.get("max_chat", ""), payload.get("notes_only", False))
                    finally:
                        log_history(payload)
                finally:
                    clear_queued(payload["deals"])
        except Exception as e:  # noqa: BLE001
            if is_closed_error(e) or (bot is not None and bot.closed):
                S.add_log("Окно amoCRM закрыто. Нажмите «amoCRM: войти», чтобы открыть его снова.")
                close_bot()
            elif S.relogin:
                S.add_log(str(e).splitlines()[0])
            elif "Остановлено пользователем" in str(e):
                S.add_log("Остановлено.")
            else:
                S.add_log(f"❌ {str(e).splitlines()[0][:300]}")
                S.logged_in = False
        finally:
            S.phase = None
            S.running = not jobs.empty()


MAX_ERRORS_IN_ROW = 3  # столько ошибок подряд = что-то сломалось целиком, останавливаемся


def read_kids_lists(bot, chat: str, items: list[dict]) -> dict[str, str] | None:
    """Списки детей из беседы MAX по классам сделок; None — прочитать не удалось."""
    from amo_bot import is_closed_error
    from max_chat import MaxChat
    need = {class_key(it.get("klass", "")) for it in items} - {""}
    if not need:
        S.add_log("Списки детей: у сделок не указан класс — MAX пропускаю.")
        return None
    S.add_log(f"Списки детей: читаю чат MAX «{chat}» (классов: {len(need)})…")
    mx = MaxChat(bot.ctx, log=S.add_log, should_stop=lambda: S.stop_flag)
    try:
        lists = mx.read_lists(chat, need)
    except Exception as e:  # noqa: BLE001
        if is_closed_error(e) or "Остановлено пользователем" in str(e):
            raise
        S.add_log(f"   ⚠ MAX: {str(e).splitlines()[0][:300]}")
        return None
    finally:
        try:
            bot.page.bring_to_front()
        except Exception:  # noqa: BLE001
            pass
    missing = sorted(need - set(lists))
    S.add_log(f"   Найдены списки: {len(need) - len(missing)} из {len(need)}"
              + (f"; нет в чате: {', '.join(missing)}" if missing else ""))
    return lists


def add_kids_note(bot, it: dict, lists: dict[str, str] | None, progress: dict, name: str) -> None:
    """Примечание со списком детей в открытую сделку; результат — в строку таблицы и progress."""
    from amo_bot import is_closed_error
    if lists is None:
        return
    body = lists.get(class_key(it.get("klass", "")))
    if not body:
        S.set_row(it["id"], note="none")
        S.add_log("   Списка детей для этого класса в чате нет")
        return
    try:
        bot.add_note(body)
    except Exception as e:  # noqa: BLE001
        if "Остановлено пользователем" in str(e) or is_closed_error(e) or bot.closed:
            raise
        shot = bot.screenshot(f"note-{name}")
        S.set_row(it["id"], note="error")
        S.add_log(f"   ⚠ примечание не добавлено: {str(e).splitlines()[0][:200]} (скриншот: {shot.name})")
        return
    progress.setdefault(name, {})["note"] = True
    save_progress(progress)
    S.set_row(it["id"], note="ok")
    with S.lock:
        S.notes_n += 1
    S.add_log(f"   📝 примечание: список детей ({count_kids(body)})")


def run_deals(bot, items: list[dict], step: bool, pipeline: str, max_chat: str = "", notes_only: bool = False):
    from amo_bot import BrowserClosed, is_closed_error
    progress = load_progress()
    S.stop_flag = False
    S.running = True
    with S.lock:
        S.total, S.done_n, S.failed_n, S.notes_n = len(items), 0, 0, 0
    lists = None
    if max_chat:
        todo = [it for it in items if not progress.get(it["name"].strip(), {}).get("note")]
        if notes_only:
            todo = [it for it in todo if progress.get(it["name"].strip(), {}).get("status") == "ok"]
        if todo:
            lists = read_kids_lists(bot, max_chat, todo)
    errors_in_row = 0
    for n, it in enumerate(items, 1):
        if S.stop_flag:
            S.add_log("Остановлено.")
            break
        rid = it["id"]
        name = it["name"].strip()
        contacts = [Contact(role=c["role"], name=fix_name_case(c["name"].strip()), phone=c["phone"].strip())
                    for c in it["contacts"] if c["name"].strip() or c["phone"].strip()]
        prev = progress.get(name, {})
        if notes_only and prev.get("status") != "ok":
            S.set_row(rid, status="error", error="Сделка ещё не создана — сначала «Создать»")
            with S.lock:
                S.failed_n += 1
            continue
        if prev.get("status") == "ok":
            S.set_row(rid, status="skip", url=prev.get("url"), note="ok" if prev.get("note") else None)
            if lists is not None and not prev.get("note") and prev.get("url"):
                S.add_log(f"[{n}/{len(items)}] «{name}» — уже создана, добавляю список детей")
                try:
                    bot.open_deal(prev["url"])
                    add_kids_note(bot, it, lists, progress, name)
                except Exception as e:  # noqa: BLE001
                    if is_closed_error(e) or bot.closed:
                        S.logged_in = False
                        S.add_log("❌ Окно amoCRM закрыто — останавливаюсь.")
                        break
                    if "Остановлено пользователем" not in str(e):
                        S.set_row(rid, note="error")
                        S.add_log(f"   ⚠ {str(e).splitlines()[0][:300]}")
            else:
                S.add_log(f"Пропуск «{name}» — уже создана" + (" (список детей уже добавлен)" if prev.get("note") else ""))
            with S.lock:
                S.done_n += 1
            continue
        S.set_row(rid, status="work", error=None)
        S.add_log(f"[{n}/{len(items)}] «{name}» → воронка «{pipeline}»")
        bot.step = False
        bot.pause_cb = bot.ui_pause if step else None

        # ход создания: ссылка на сделку и сколько контактов уже сохранено (для дозаполнения)
        state = {"url": prev.get("url") if prev.get("status") == "partial" else None,
                 "contacts_done": prev.get("contacts_done", 0) if prev.get("status") == "partial" else 0}
        if state["url"]:
            S.add_log(f"   Сделка уже есть ({state['contacts_done']} контакт.), дозаполняю")
        last_err = None
        created = False
        for attempt in (1, 2):
            if S.stop_flag:
                break
            try:
                create_or_resume(bot, name, contacts, pipeline, state)
                last_err, created = None, True
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                if "Остановлено пользователем" in str(e):
                    if state["url"]:  # сделка уже сохранена частично — запомнить для дозаполнения
                        progress[name] = {"url": state["url"], "status": "partial",
                                          "contacts_done": state["contacts_done"], "at": time.strftime("%Y-%m-%d %H:%M")}
                        save_progress(progress)
                    break
                if is_closed_error(e) or bot.closed:  # окно amoCRM закрыли — повторять бессмысленно
                    last_err = BrowserClosed()
                    if state["url"]:
                        progress[name] = {"url": state["url"], "status": "partial",
                                          "contacts_done": state["contacts_done"], "at": time.strftime("%Y-%m-%d %H:%M")}
                        save_progress(progress)
                    break
                shot = bot.screenshot(f"error-{name}")
                msg = str(e).splitlines()[0][:300]
                S.add_log(f"   ⚠ попытка {attempt}: {msg} (скриншот: {shot.name})")
                if state["url"]:
                    progress[name] = {"url": state["url"], "status": "partial",
                                      "contacts_done": state["contacts_done"], "at": time.strftime("%Y-%m-%d %H:%M")}
                    save_progress(progress)
        if created:  # сделка дозаполнена до конца — засчитываем, даже если в этот момент нажали «Стоп»
            progress[name] = {"url": state["url"], "status": "ok", "at": time.strftime("%Y-%m-%d %H:%M")}
            save_progress(progress)
            S.set_row(rid, status="ok", url=state["url"])
            S.add_log(f"   ✅ создана")
            errors_in_row = 0
            with S.lock:
                S.done_n += 1
            if not S.stop_flag:
                try:  # сделка уже создана: без примечания её можно дополнить позже кнопкой «Списки детей»
                    add_kids_note(bot, it, lists, progress, name)
                except Exception as e:  # noqa: BLE001
                    if is_closed_error(e) or bot.closed:
                        S.logged_in = False
                        S.add_log("❌ Окно amoCRM закрыто — останавливаюсь.")
                        break
            continue
        err = "Остановлено" if S.stop_flag else str(last_err).splitlines()[0][:300]
        S.set_row(rid, status="partial" if state["url"] else "error", error=err, url=state["url"])
        if state["url"]:
            S.add_log("   Сделка сохранена не полностью — можно нажать «Повторить ошибочные», бот дозаполнит её.")
        with S.lock:
            S.failed_n += 1
        if isinstance(last_err, BrowserClosed):
            S.logged_in = False
            S.add_log("❌ Окно amoCRM закрыто — останавливаюсь.")
            break
        errors_in_row += 1
        if errors_in_row >= MAX_ERRORS_IN_ROW:
            S.add_log(f"❌ {MAX_ERRORS_IN_ROW} ошибки подряд — останавливаюсь. Посмотрите скриншоты в папке logs.")
            break
    clear_queued(items)
    S.add_log(f"Готово: {'обработано' if notes_only else 'создано'} {S.done_n}, с ошибками {S.failed_n}.")


def clear_queued(items: list[dict]):
    """Строки, до которых не дошли (стоп, ошибка MAX, закрыли окно), больше не «в очереди»."""
    with S.lock:
        for it in items:
            if S.rows.get(it["id"], {}).get("status") == "queued":
                S.rows[it["id"]]["status"] = None


def log_history(payload: dict):
    """Итог запуска — в журнал действий таблицы в истории."""
    hid = payload.get("history_id")
    if not hid:
        return
    with S.lock:
        done, failed, notes, total = S.done_n, S.failed_n, S.notes_n, S.total
    if payload.get("notes_only"):
        text = f"Списки детей в созданные: добавлено {notes} из {total}"
    else:
        text = f"Создание сделок ({payload.get('pipeline', '')}): готово {done} из {total}"
        if payload.get("max_chat"):
            text += f", списков детей {notes}"
    if failed:
        text += f", ошибок {failed}"
    if S.stop_flag:
        text += " — остановлено"
    try:
        history.add_action(hid, text)
    except OSError:
        pass


def create_or_resume(bot, name: str, contacts: list[Contact], pipeline: str, state: dict):
    """Создаёт сделку или дозаполняет уже сохранённую (state['url'], state['contacts_done'])."""
    if state["url"]:
        bot.open_deal(state["url"])
    else:
        bot.open_new_deal(pipeline)
        bot.fill_deal_name(name)
    todo = contacts[state["contacts_done"]:]
    for i, c in enumerate(todo):
        if i and state.get("just_created"):
            # Сразу после первого «Сохранить» карточка перестраивается, и форма следующего
            # контакта не находилась (ошибка через 15 с и повтор). Открываем сделку заново — 2–3 с.
            bot.open_deal(state["url"])
            state["just_created"] = False
        bot.fill_contact(c, company=name)  # «Название компании» = класс + школа
        bot._pause(f"«{name}»: заполнен {c.role} ({c.name}). Проверьте форму и нажмите «Продолжить» — будет «Сохранить»")
        bot.save()
        if not state["url"]:
            if "/leads/detail/" not in bot.page.url:
                raise RuntimeError("После «Сохранить» сделка не создалась")
            state["url"] = bot.deal_url()
            state["just_created"] = True
        state["contacts_done"] += 1
    if not state["url"]:  # сделка без контактов
        bot._pause(f"«{name}»: контактов нет. «Продолжить» — сохранить")
        bot.save()
        state["url"] = bot.deal_url()


# ---------------- API ----------------
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/parse")
def api_parse():
    f = request.files.get("file")
    if not f:
        return jsonify(error="Файл не получен"), 400
    UPLOADS.mkdir(exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(suffix=".xlsx", dir=UPLOADS)
    os.close(fd)  # на Windows открытый дескриптор не даёт потом удалить файл
    tmp = Path(tmp_name)
    f.save(tmp)
    try:
        deals, warnings = read_deals(str(tmp), None, request.form.get("school", ""))
        kind = deals[0].kind if deals else None
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"Не удалось прочитать файл: {e}"), 400
    finally:
        tmp.unlink(missing_ok=True)
    progress = load_progress()
    migrated = False
    out = []
    for i, d in enumerate(deals):
        kr = next((c for c in d.contacts if c.role in ("КР", "ВС")), None)
        rk = next((c for c in d.contacts if c.role == "РК"), None)
        done = progress.get(d.name)
        if done is None and d.legacy_name in progress:
            # создана до v1.0.15 со старым названием («6 Ж Школа») — запоминаем и под новым («6ж Школа»),
            # чтобы не создать дубль и чтобы «Списки детей в созданные» её нашли
            done = progress[d.name] = dict(progress[d.legacy_name])
            migrated = True
        out.append({
            "id": f"r{i}", "sheet": d.sheet, "row": d.row, "name": d.name, "klass": d.klass,
            "kr": {"name": kr.name if kr else "", "phone": kr.phone_field if kr else ""},
            "rk": {"name": rk.name if rk else "", "phone": rk.phone_field if rk else ""},
            "info": d.info, "refused": d.refused, "red": d.red,
            "done": done.get("url") if done else None,
            "note": bool(done.get("note")) if done else False,
            "doneStatus": done.get("status") if done else None,
        })
    if migrated:
        save_progress(progress)
    with S.lock:
        S.rows = {}
        if not S.running:
            S.total = S.done_n = S.failed_n = 0
    school = deals[0].school if deals else ""
    kind = kind or "school"
    for d in out:
        d["sel"] = not (d["done"] and d["doneStatus"] != "partial") and not d["refused"] and not d["red"]
    hid = None
    try:
        hid = history.create({"file": f.filename, "kind": kind, "fileKind": kind, "school": school,
                              "fileSchool": school, "prefix": "", "deals": out, "original": out,
                              "warnings": warnings}, f"Загружен файл, строк: {len(out)}")
    except OSError:
        pass
    return jsonify(deals=out, warnings=warnings, school=school, file=f.filename, kind=kind, historyId=hid)


@app.post("/api/login")
def api_login():
    """Открыть окно amoCRM. Если оно уже открыто или идёт вход — старое закрывается, открывается новое."""
    if S.running and S.phase != "login":
        return jsonify(error="Идёт создание сделок — дождитесь окончания или нажмите «Стоп»"), 409
    if S.phase == "login":
        S.relogin = True  # прервать текущее ожидание входа
    S.stop_flag = False  # прежний «Стоп» не должен прервать новый вход
    S.running = True
    jobs.put(("login", {}))
    return jsonify(ok=True)


@app.post("/api/run")
def api_run():
    if S.running:
        return jsonify(error="Уже идёт работа"), 409
    data = request.get_json(force=True)
    items = data.get("deals", [])
    if not items:
        return jsonify(error="Не выбрано ни одной сделки"), 400
    pipeline = (data.get("pipeline") or "").strip()
    if not pipeline:
        return jsonify(error="Выберите воронку"), 400
    max_chat = (data.get("maxChat") or "").strip()
    notes_only = bool(data.get("notesOnly"))
    if notes_only and not max_chat:
        return jsonify(error="Впишите название чата MAX со списками детей"), 400
    with S.lock:  # два быстрых нажатия не должны запустить работу дважды
        if S.running:
            return jsonify(error="Уже идёт работа"), 409
        S.running = True
    for it in items:
        S.set_row(it["id"], status="queued", error=None, note=None)
    S.stop_flag = False
    jobs.put(("run", {"deals": items, "step": bool(data.get("step")), "pipeline": pipeline,
                      "max_chat": max_chat, "notes_only": notes_only,
                      "history_id": data.get("historyId") or ""}))
    return jsonify(ok=True)


@app.post("/api/continue")
def api_continue():
    S.continue_evt.set()
    return jsonify(ok=True)


@app.post("/api/stop")
def api_stop():
    """Останавливает работу бота, браузер amoCRM остаётся открытым. Бот проверяет «Стоп»
    между всеми действиями и в ожиданиях (AmoBot.check_stop) — прерывается сразу; только уже
    нажатое «Сохранить» доводит до конца (несколько секунд), чтобы не потерять созданную сделку."""
    S.stop_flag = True
    S.continue_evt.set()
    S.add_log("Остановлено." if S.waiting else "Остановка — прерываю текущее действие.")
    return jsonify(ok=True)


@app.get("/api/history")
def api_history():
    return jsonify(items=history.listing(load_progress()))


@app.get("/api/history/<hid>")
def api_history_open(hid):
    """Таблица из истории — продолжить работу. Отметки «создана» берутся свежие из progress.json."""
    if S.running:
        return jsonify(error="Дождитесь окончания или нажмите «Стоп»"), 409
    e = history.get(hid)
    if e is None:
        return jsonify(error="Запись истории не найдена"), 404
    progress = load_progress()
    history.refresh_deals(e.get("deals"), progress)
    history.refresh_deals(e.get("original"), progress)
    with S.lock:
        S.rows = {}
        S.total = S.done_n = S.failed_n = S.notes_n = 0
    return jsonify(entry=e)


@app.post("/api/history/<hid>")
def api_history_save(hid):
    if not history.update(hid, request.get_json(force=True) or {}):
        return jsonify(error="Запись истории не найдена"), 404
    return jsonify(ok=True)


@app.post("/api/forget")
def api_forget():
    name = request.get_json(force=True).get("name", "")
    p = load_progress()
    if p.pop(name, None) is not None:
        save_progress(p)
    return jsonify(ok=True)


@app.get("/api/status")
def api_status():
    global _last_seen
    _last_seen = time.time()
    with S.lock:
        return jsonify(log=S.log[-200:], rows=S.rows, running=S.running, waiting=S.waiting,
                       loggedIn=S.logged_in, phase=S.phase, amoUrl=CONFIG["amo_url"], version=paths.VERSION,
                       pipelines=S.pipelines, total=S.total, doneN=S.done_n, failedN=S.failed_n,
                       notesN=S.notes_n)


def open_ui(url: str) -> bool:
    """Открывает интерфейс отдельным окном без адресной строки (как приложение).
    Окно запускается в своём профиле браузера, поэтому у него свой процесс: он живёт,
    пока открыто окно, и по нему программа понимает, что её закрыли (см. close_with_window).
    Если Edge/Chrome не найдены — обычной вкладкой браузера (возвращает False)."""
    import subprocess
    candidates = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for exe in candidates:
        if os.path.exists(exe):
            try:
                subprocess.Popen([exe, f"--app={url}", "--window-size=1400,900",
                                  f"--user-data-dir={WINDOW_PROFILE}",
                                  "--no-first-run", "--no-default-browser-check"])
                return True
            except OSError:
                continue
    webbrowser.open(url)
    return False


def find_browser_pids(profile) -> list[int]:
    """PID главных процессов Edge/Chrome, запущенных с профилем profile (без дочерних --type=...)."""
    import subprocess
    prof = str(profile).lower()
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' OR Name='chrome.exe'\" | "
          "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=20,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except Exception:  # noqa: BLE001
        return []
    pids = []
    for line in out.splitlines():
        pid, _, cmd = line.partition("\t")
        cmd = cmd.lower()
        if prof in cmd and "--type=" not in cmd and pid.strip().isdigit():
            pids.append(int(pid))
    return pids


def find_window_process() -> int | None:
    """PID главного процесса браузера с окном программы (ищется по профилю окна)."""
    pids = find_browser_pids(WINDOW_PROFILE)
    return pids[0] if pids else None




def close_with_window():
    """Программа живёт, пока открыто её окно: закрыли окно — процесс браузера окна
    завершился — выходим сразу (вместе с ботом, драйвером Playwright и браузером amoCRM).
    Процесс окна ищется один раз при запуске, дальше — ожидание средствами Windows, без опросов."""
    import ctypes
    pid = None
    for _ in range(20):  # окну нужно пару секунд, чтобы запуститься
        time.sleep(1)
        pid = find_window_process()
        if pid:
            break
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(0x00100000, False, pid) if pid else None  # SYNCHRONIZE
    if not handle:
        S.add_log("Не нашёл окно программы — закроюсь, когда окно перестанет обращаться к программе.")
        idle_watchdog()
        return
    k32.WaitForSingleObject(handle, 0xFFFFFFFF)  # ждём закрытия окна
    S.add_log("Окно программы закрыто — завершаю работу.")
    os._exit(0)


def port_busy(port: int) -> bool:
    import socket
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main():
    port = int(CONFIG.get("port", 8765))
    if "--port" in sys.argv:  # для проверок рядом с уже запущенной программой
        port = int(sys.argv[sys.argv.index("--port") + 1])
    url = f"http://127.0.0.1:{port}"
    if port_busy(port):
        # приложение уже запущено — просто показываем его окно
        print("Приложение уже запущено, открываю окно.")
        if "--no-open" not in sys.argv:
            open_ui(url)
        return
    threading.Thread(target=worker, daemon=True).start()
    # ярлыки на рабочем столе и в «Пуске» создаёт установщик (installer.iss)
    print(f"Приложение работает: {url}")
    if "--no-open" not in sys.argv:
        def start_window():
            time.sleep(1.0)
            if open_ui(url):
                close_with_window()
            elif paths.FROZEN:
                idle_watchdog()
        threading.Thread(target=start_window, daemon=True).start()
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


def idle_watchdog():
    """Запасной вариант, когда процесс окна неизвестен (нет Edge/Chrome): выходим, если окно
    давно не обращалось к программе, а бот не работает или стоит на паузе «Проверьте форму»."""
    while True:
        time.sleep(15)
        if time.time() - _last_seen > IDLE_EXIT_SEC and (not S.running or S.waiting):
            os._exit(0)  # фоновый браузер amoCRM закроется вместе с процессом


def message_box(text: str):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "Сделки amoCRM", 0x10)
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        message_box(f"Не удалось запустить программу:\n{e}\n\nПодробности: {paths.LOG_DIR / 'console.log'}")
        raise
