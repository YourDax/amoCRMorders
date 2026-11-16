"""Где лежат файлы программы и где хранить данные пользователя.

* Запуск из исходников: всё в папке проекта (как раньше).
* Запуск собранного .exe: ресурсы (страница, config.json по умолчанию) — внутри exe,
  а данные (вход в amoCRM, созданные сделки, журнал) — в %LOCALAPPDATA%\\amoCRMorders,
  чтобы их не терять при обновлении exe и не требовать прав на запись рядом с ним.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "amoCRMorders"
VERSION = "1.0.2"

FROZEN = bool(getattr(sys, "frozen", False))
RES_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

if FROZEN:
    DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME
else:
    DATA_DIR = Path(__file__).resolve().parent
DATA_DIR.mkdir(parents=True, exist_ok=True)

STATIC_DIR = RES_DIR / "static"
LOG_DIR = DATA_DIR / "logs"
PROFILE_DIR = DATA_DIR / "browser-profile"
PROGRESS_FILE = DATA_DIR / "progress.json"
UPLOADS_DIR = DATA_DIR / "uploads"


def load_config() -> dict:
    """config.json из программы + (для exe) личные настройки из папки данных поверх."""
    cfg: dict = {}
    for path in (RES_DIR / "config.json", DATA_DIR / "config.json"):
        try:
            cfg.update(json.loads(path.read_text(encoding="utf-8")))
        except (FileNotFoundError, ValueError):
            pass
    return cfg
