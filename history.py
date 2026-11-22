"""История таблиц: загруженные отчёты с правками и что с ними делали.

Хранится в history.json в папке данных. Запись — таблица в том виде, в каком её оставили
(правки, галочки, префикс, тип учреждения), плюс журнал действий («Создано 5 из 6»).
Создана ли сделка, берётся из progress.json по идентификатору строки в отчёте. У ранее сохранённых таблиц ключом остаётся название.
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

import paths

FILE: Path = paths.HISTORY_FILE
MAX_ENTRIES = 30   # старые записи вытесняются
MAX_ACTIONS = 50
_lock = threading.Lock()
# что из таблицы хранится (присылает интерфейс)
TABLE_FIELDS = ("file", "kind", "fileKind", "school", "fileSchool", "prefix", "deals", "original", "warnings")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


def _load() -> list[dict]:
    data = paths.read_json(FILE, [])
    return data if isinstance(data, list) else []


def _save(entries: list[dict], touched: dict | None = None) -> None:
    """Сохраняет; изменённая запись поднимается наверх (список — от свежих к старым)."""
    if touched is not None:
        entries = [touched] + [e for e in entries if e is not touched]
    paths.write_json(FILE, entries[:MAX_ENTRIES])


def _find(entries: list[dict], hid: str) -> dict | None:
    return next((e for e in entries if e.get("id") == hid), None)


def create(table: dict, action: str) -> str:
    hid = uuid.uuid4().hex[:12]
    entry = {k: table.get(k) for k in TABLE_FIELDS}
    entry.update(id=hid, created=_now(), updated=_now(), actions=[{"at": _now(), "text": action}])
    with _lock:
        entries = _load()
        _save(entries, entry)
    return hid


def update(hid: str, table: dict) -> bool:
    """Сохраняет текущее состояние таблицы (правки, галочки)."""
    with _lock:
        entries = _load()
        e = _find(entries, hid)
        if e is None:
            return False
        for k in TABLE_FIELDS:
            if k in table:
                e[k] = table[k]
        e["updated"] = _now()
        _save(entries, e)
    return True


def add_action(hid: str, text: str) -> None:
    if not hid:
        return
    with _lock:
        entries = _load()
        e = _find(entries, hid)
        if e is None:
            return
        e.setdefault("actions", []).append({"at": _now(), "text": text})
        e["actions"] = e["actions"][-MAX_ACTIONS:]
        e["updated"] = _now()
        _save(entries, e)


def get(hid: str) -> dict | None:
    with _lock:
        return _find(_load(), hid)


def progress_key(row: dict) -> str:
    rid = str(row.get("id", ""))
    if rid.startswith("import-"):
        return rid
    return str(row.get("name", "")).strip()  # tables saved before isolated imports


def saved_record(row, progress):
    from excel_reader import progress_key as scoped_key
    return progress.get(scoped_key(progress, progress_key(row), ""))


def refresh_deals(deals: list[dict], progress: dict) -> list[dict]:
    """Отметки «уже создана» / «список детей» из progress.json (могли измениться после сохранения)."""
    for d in deals or []:
        done = saved_record(d, progress)
        d["done"] = done.get("url") if done else None
        d["doneStatus"] = done.get("status") if done else None
        d["note"] = bool(done.get("note")) if done else False
        if done and done.get("status") == "ok":
            d["sel"] = False
    return deals


def summary(entry: dict, progress: dict) -> dict:
    """Кратко о ходе работы: сколько создано, сколько осталось, закончена ли."""
    deals = entry.get("deals") or []
    created = partial = pending = 0
    for d in deals:
        st = (saved_record(d, progress) or {}).get("status")
        if st == "ok":
            created += 1
        elif st == "partial":
            partial += 1
        elif d.get("sel"):
            pending += 1  # отмечена, но ещё не создана (неотмеченные — пропущены намеренно)
    if not deals:
        state = "empty"
    elif created and not pending and not partial:
        state = "done"
    elif created or partial:
        state = "work"
    else:
        state = "new"
    return {"total": len(deals), "created": created, "partial": partial, "pending": pending, "state": state}


def listing(progress: dict) -> list[dict]:
    with _lock:
        entries = _load()
    return [{"id": e["id"], "file": e.get("file") or "без названия", "school": e.get("school") or "",
             "created": e.get("created", ""), "updated": e.get("updated", ""),
             "actions": (e.get("actions") or [])[-5:], **summary(e, progress)} for e in entries]
