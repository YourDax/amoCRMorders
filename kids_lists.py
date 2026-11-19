"""Списки детей из чата MAX: поиск сообщения «класс + список» и сопоставление с классом сделки.

Сообщение в беседе выглядит так:

    6Б

    1.Грузинов Владислав
    2.Леонтьев Артём

Класс пишут по-разному: «6Б», «6 Б», «6-б», «6 «Б»», «6Б класс», латинской «B». Всё приводится
к одному ключу «6б». Для детского сада: «гр.11», «группа 11», «11 группа» → «11».
Если для класса несколько сообщений — берётся последнее (самое новое).
"""

from __future__ import annotations

import re

# латинские буквы, похожие на русские (часто печатают «5B» вместо «5В»)
_LATIN = str.maketrans("abcehkmoptxy", "авсенкмортху")
_WORDS_RE = re.compile(r"\b(класс\w*|кл|группа|гр|group)\b\.?", re.I)
_KEY_RE = re.compile(r"^\d{1,2}[а-я]{0,2}$")
_TIME_RE = re.compile(r"^\s*(\d{1,2}:\d{2})(\s*(изменено|ред\.?))?\s*$", re.I)
_NUMBERED_RE = re.compile(r"^\s*\d{1,3}\s*[.)\-–:]?\s*\S")
_NAME_RE = re.compile(r"^[А-ЯЁа-яёA-Za-z][А-ЯЁа-яёA-Za-z\-'’]*(\s+[А-ЯЁа-яёA-Za-z][А-ЯЁа-яёA-Za-z\-'’.]*){0,3}$")


def class_key(text: str) -> str:
    """«6 «Б» класс» → «6б», «гр.11» → «11». Пусто, если это не похоже на класс/группу."""
    s = str(text or "").strip().lower().replace("ё", "е")
    s = _WORDS_RE.sub(" ", s)
    s = re.sub(r"[\s\-–—_.,:;\"'«»“”„()№]+", "", s)
    s = s.translate(_LATIN)
    return s if _KEY_RE.match(s) else ""


def _is_class_line(line: str) -> str:
    """Ключ класса, если строка — заголовок списка (короткая, только класс)."""
    line = line.strip()
    if not line or len(line) > 25:
        return ""
    return class_key(line)


def _is_entry(line: str, numbered: bool | None) -> bool:
    s = line.strip()
    if not s or _TIME_RE.match(s):
        return False
    if numbered is None:
        return bool(_NUMBERED_RE.match(s) or _NAME_RE.match(s))
    return bool(_NUMBERED_RE.match(s)) if numbered else bool(_NAME_RE.match(s))


def find_lists(text: str) -> list[tuple[str, str]]:
    """Все списки в тексте по порядку: [(ключ класса, текст списка), ...].

    Текст списка — заголовок класса как в сообщении и строки детей (пустые строки убраны).
    """
    lines = text.replace("\r", "").split("\n")
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        key = _is_class_line(lines[i])
        if not key:
            i += 1
            continue
        head = lines[i].strip()
        entries: list[str] = []
        numbered: bool | None = None
        j = i + 1
        while j < len(lines):
            s = lines[j].strip()
            if not s:  # пустые строки внутри сообщения допустимы
                j += 1
                continue
            if _is_class_line(s) or not _is_entry(s, numbered):
                break
            if numbered is None:
                numbered = bool(_NUMBERED_RE.match(s))
            entries.append(s)
            j += 1
        if entries:
            out.append((key, "\n".join([head, *entries])))
            i = j
        else:
            i += 1
    return out


def merge_snapshots(snapshots: list[str]) -> dict[str, str]:
    """Списки по классам из нескольких «снимков» чата.

    snapshots — от самого нового (низ чата) к более старым (прокрутка вверх). Внутри снимка
    последний список класса новее; найденный в более новом снимке не заменяется более старым.
    """
    result: dict[str, str] = {}
    for snap in snapshots:
        latest: dict[str, str] = {}
        for key, body in find_lists(snap):
            latest[key] = body
        for key, body in latest.items():
            result.setdefault(key, body)
    return result


def count_kids(body: str) -> int:
    return max(0, len(body.split("\n")) - 1)
