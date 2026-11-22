"""Списки детей из чата MAX: поиск сообщений с классом и сопоставление с классом сделки.

Сообщения в беседе пишут по-разному, правило — «лучше вставить лишнее, чем ничего»:

    6Б                        3А                           4в Сизинцева София
    1.Грузинов Владислав      Идут на фотосессию :
    2.Леонтьев Артём          1. Соломин Толя
                              2. Герасимова Вика (убрать невидимку)

* Полный список — строка-заголовок с классом («6Б», «6 Б», «6-б», «6 «Б»», «6Б класс», латинская «B»)
  и все строки после неё до следующего заголовка: пометки в скобках, фамилии без имён, пояснения.
* Короткая запись — класс в начале строки и сразу текст («4в Сизинцева София»): в примечание
  идёт всё сообщение.

Последний полный список класса заменяет прежние; короткие записи после него дописываются
к нему. Полного списка нет — берутся все короткие записи класса.
Для детского сада: «гр.11», «группа 11», «11 группа» → ключ «11».
"""

from __future__ import annotations

import re

# латинские буквы, похожие на русские (часто печатают «5B» вместо «5В»)
_LATIN = str.maketrans("abcehkmoptxy", "авсенкмортху")
_WORDS_RE = re.compile(r"\b(класс\w*|кл|группа|гр|group|список\w*)\b\.?", re.I)
_KEY_RE = re.compile(r"^\d{1,2}[а-я]{0,2}$")
_TIME_RE = re.compile(r"^\s*(ред\.?\s*)?\d{1,2}:\d{2}(\s*(изменено|ред\.?))?\s*$", re.I)
_ITEM_NO_RE = re.compile(r"^\s*\d{1,3}\s*[.)\-–:]\s*\S")  # «10.Ли», «3) Иванов» — ребёнок, не класс
# «4в Сизинцева София», «3 «В»: Антонов» — класс в начале строки и текст после него
_INLINE_RE = re.compile(
    r"^\s*(\d{1,2})\s*[-–]?\s*[«\"']?([А-Яа-яЁёA-Za-z])[»\"']?"
    r"(?:\s*(?:класс\w*|кл\.?))?(?=[\s,:;.\-–])[\s,:;.\-–]+(\S.*)$", re.I)


_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u2060\ufeff]")


def class_key(text: str) -> str:
    """«6 «Б» класс» → «6б», «гр.11» → «11». Пусто, если это не похоже на класс/группу."""
    s = _INVISIBLE_RE.sub("", str(text or "")).strip().lower().replace("ё", "е")
    s = _WORDS_RE.sub(" ", s)
    s = re.sub(r"[\s\-–—_.,:;\"'«»“”„()№]+", "", s)
    s = s.translate(_LATIN)
    return s if _KEY_RE.match(s) else ""


def _header_key(line: str) -> str:
    """Ключ класса, если строка целиком — заголовок («6Б», «Список 3А:»)."""
    line = line.strip()
    if not line or len(line) > 25:
        return ""
    return class_key(line)


def _inline_key(line: str) -> str:
    m = _INLINE_RE.match(_INVISIBLE_RE.sub("", line))
    return class_key(m.group(1) + m.group(2)) if m else ""


def parse_message(text: str) -> list[tuple[str, str, bool]]:
    """Списки в одном сообщении: [(ключ класса, текст, полный ли список), ...]."""
    lines = [ln.rstrip() for ln in text.replace("\r", "").split("\n")]
    lines = [ln for ln in lines if ln.strip() and not _TIME_RE.match(ln)]
    out: list[tuple[str, str, bool]] = []
    key, head, body = "", "", []

    def flush():
        if key and body:
            out.append((key, "\n".join([head, *body]), True))

    for ln in lines:
        s = ln.strip()
        k = "" if (key and _ITEM_NO_RE.match(s)) else _header_key(s)
        if k:
            flush()
            key, head, body = k, s, []
        elif key:
            body.append(s)
    flush()
    if out:
        return out
    # короткая запись: класс в начале одной из первых строк (первой может быть имя отправителя)
    for s in [ln.strip() for ln in lines[:2]]:
        k = _inline_key(s)
        if k:
            return [(k, "\n".join(ln.strip() for ln in lines), False)]
    return []


def collect_lists(messages: list[str]) -> dict[str, str]:
    """Списки по классам из сообщений чата (от старых к новым)."""
    parts: dict[str, list[str]] = {}
    for msg in messages:
        for key, body, full in parse_message(msg):
            if full:
                parts[key] = [body]
            elif body not in parts.setdefault(key, []):
                parts[key].append(body)
    return {k: "\n".join(v) for k, v in parts.items()}


def full_list_keys(messages: list[str]) -> set[str]:
    """Классы, у которых в этих сообщениях есть полный список (дальше в прошлое искать не нужно)."""
    return {key for msg in messages for key, _, full in parse_message(msg) if full}


def find_lists(text: str) -> list[tuple[str, str]]:
    """[(ключ, текст)] из одного сообщения — для журнала и проверок."""
    return [(k, b) for k, b, _ in parse_message(text)]


def merge_history(history: list[str], older: list[str]) -> list[str]:
    """Склеивает уже прочитанную историю (от старых к новым) с более старым «снимком» экрана.

    Снимки перекрываются: ищем самое длинное совпадение конца `older` с началом `history`.
    """
    if not history:
        return list(older)
    for k in range(min(len(older), len(history)), 0, -1):
        if older[-k:] == history[:k]:
            return older[:-k] + history
    return older + history


_LIST_PREFIX_RE = re.compile(r"^(?:\d{1,3}(?:\s*[.)\-–:]\s*|\s+)|[•*\-–]\s*)")
_COUNT_COMMENT_RE = re.compile(r"^(?:идут\b|снимаются\b|список\b|всего\b|итого\b|количество\b|на\s+фотосессию\b)", re.I)
_PERSON_RE = re.compile(r"[А-ЯЁA-Zа-яёa-z]+(?:[-'][А-ЯЁA-Zа-яёa-z]+)*(?:\s+[А-ЯЁA-Zа-яёa-z]+(?:[-'][А-ЯЁA-Zа-яёa-z]+)*){0,2}")


def count_kids(body: str) -> int:
    """Оценивает число детей в тексте списка, сохраняя сам текст для примечания."""
    lines = [s.strip() for s in _INVISIBLE_RE.sub("", body).splitlines() if s.strip()]
    if len(lines) >= 2 and not (_header_key(lines[0]) or _inline_key(lines[0])) and _inline_key(lines[1]):
        lines = lines[1:]  # имя отправителя перед короткой записью
    count = 0
    for i, line in enumerate(lines):
        if _TIME_RE.fullmatch(line) or _COUNT_COMMENT_RE.match(line):
            continue
        inline = _INLINE_RE.match(line)
        if inline:
            line = inline.group(3)
        elif _header_key(line) and (i == 0 or not _ITEM_NO_RE.match(line)):
            continue
        else:
            line = _LIST_PREFIX_RE.sub("", line)
        line = re.sub(r"\([^)]*\)", "", line).strip()
        for name in re.split(r"\s+и\s+|\s*[;,]\s*", line, flags=re.I):
            name = re.sub(r"\s+\d{1,2}\s*[А-Яа-яЁёA-Za-z]$", "", name).strip(" .")
            if _PERSON_RE.fullmatch(name):
                count += 1
    return count
