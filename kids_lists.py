"""Списки детей из чата MAX: сопоставление сообщений с классом или группой сделки.

Сообщения в беседе пишут по-разному, правило — «лучше вставить лишнее, чем ничего»:

    6Б                        3А                           4в Сизинцева София
    1.Грузинов Владислав      Идут на фотосессию :
    2.Леонтьев Артём          1. Соломин Толя
                              2. Герасимова Вика (убрать невидимку)

* Полный список — строка-заголовок с классом («6Б», «6 Б», «6-б», «6 «Б»», «6Б класс», латинская «B»)
  и все строки после неё до следующего заголовка: пометки в скобках, фамилии без имён, пояснения.
* Короткая запись — класс в начале строки и сразу текст («4в Сизинцева София»): в примечание
  идёт всё сообщение.

Полные списки одного школьного класса объединяются: съёмка может идти в несколько дней.
Короткие записи после первого полного списка добавляются к нему. Для групп берётся последний полный список.
Для детского сада: «гр.11» → «11», «Группа „Мечтатели“» → «мечтатели».
"""

from __future__ import annotations

import re
from collections.abc import Set

# латинские буквы, похожие на русские (часто печатают «5B» вместо «5В»)
_LATIN = str.maketrans("abcehkmoptxy", "авсенкмортху")
_WORDS_RE = re.compile(r"\b(класс\w*|кл|группа|гр|group|список\w*)\b\.?", re.I)
_SCHOOL_KEY_RE = re.compile(r"\d{1,2}[а-я]{1,2}\d{0,2}")
_KEY_RE = re.compile(rf"(?:\d{{1,2}}|{_SCHOOL_KEY_RE.pattern})")
_CLASS_LABEL = r"""\d{1,2}\s*[-‐‑–—]?\s*[«"']?[а-яёa-z]{1,2}[»"']?(?:\d{1,2}|\s*[/\\]\s*\d{1,2})?"""
_TIME_RE = re.compile(r"^\s*(ред\.?\s*)?\d{1,2}:\d{2}(\s*(изменено|ред\.?))?\s*$", re.I)
_ITEM_NO_RE = re.compile(r"^\s*(\d{1,3})\s*[.)\-–—:]\s*(?=\S)")
_BARE_ITEM_RE = re.compile(r"^\s*(\d{1,3})\s+(?=[А-ЯЁA-Z][а-яёa-z])")
_BULLET_ITEM_RE = re.compile(r"^\s*[•●▪*\-–—]\s*(?=\S)")
_HEADER_MARKS = " ·•📋!‼❗❕"
_LIST_HEADER_RE = re.compile(
    r"^список(?:\s+(?:детей|учеников|участников))?"
    r"(?:\s+(?:для|на|класса))?\b[\s:–—-]*", re.I,
)
_ANONYMOUS_SIBLING_RE = re.compile(r"\s*\+\s*(?:брат|сестра)\s*(?=$|[+,;])", re.I)
# «4в Сизинцева София», «3 «В»: Антонов» — класс в начале строки и текст после него
_INLINE_RE = re.compile(
    rf"^\s*({_CLASS_LABEL})"
    r"(?:\s*(?:класс\w*|кл\.?))?(?=[\s,:;.\-–])[\s,:;.\-–]+(\S.*)$", re.I)


_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u2060\ufe0e\ufe0f\ufeff]")


def class_key(text: str) -> str:
    """«6 «Б» класс» → «6б», «гр.11» → «11». Пусто, если это не похоже на класс/группу."""
    s = _INVISIBLE_RE.sub("", str(text or "")).strip().lower().replace("ё", "е")
    s = _WORDS_RE.sub(" ", s)
    s = re.sub(r"[\s\-‐‑–—_.,:;\"'«»“”„()№]+", "", s)
    s = s.translate(_LATIN)
    s = re.sub(r"(?<=[а-я])[/\\](?=\d{1,2}$)", "", s)
    return s if _KEY_RE.fullmatch(s) else ""


_GROUP_PREFIX = re.compile(r"^(?:гр\.\s*|(?:гр|групп[аыуе]|group)\b[\s:№.]+)", re.I)
_GROUP_SUFFIX = re.compile(r"\s+(?:гр\.?|групп[аыуе]|group)$", re.I)
_GROUP_NAME = re.compile(r"[\w]+(?:[\s.‑–—'-]+[\w]+)*", re.UNICODE)


def is_school_class(key: str) -> bool:
    return bool(_SCHOOL_KEY_RE.fullmatch(key))


def group_key(text: str) -> str:
    """Ключ группы из таблицы или заголовка MAX."""
    name = _INVISIBLE_RE.sub("", str(text or "")).casefold().replace("ё", "е")
    name = name.strip(' \t\u00a0:«»„“”"')
    name = _GROUP_SUFFIX.sub("", _GROUP_PREFIX.sub("", name))
    name = " ".join(name.strip(' \t\u00a0:«»„“”"№').split())
    return class_key(name) or (name if _GROUP_NAME.fullmatch(name) else "")


_PAREN_COUNT_RE = re.compile(
    r"^(.+?)\s*\(\s*\d{1,3}\s*(?:чел(?:овек[аи]?)?\.?|детей|ученик(?:а|ов))\s*\)",
    re.I,
)
_BARE_COUNT_RE = re.compile(r"^(.+?)\s*\(\s*\d{1,3}\s*\)\s*[:.]?\s*$")


def _counted_header_key(line: str, need: Set[str]) -> str:
    match = _PAREN_COUNT_RE.match(line)
    return _header_key(match[1], need) if match else ""


_PHOTO_HEADER_RE = re.compile(
    r"^(?:участники\s+(?:[а-яё-]+\s+)*фотопроекта\s+от\s+|(?:[а-яё-]+\s+)*фотосессия\s+)"
    rf"({_CLASS_LABEL}(?:\s+класс)?)\s*[:.]?$",
    re.I,
)


def _header_key(line: str, need: Set[str]) -> str:
    """Ключ класса, если строка целиком — заголовок («6Б», «Список 3А:»)."""
    line = _INVISIBLE_RE.sub("", line).replace("\u00a0", " ").lstrip(_HEADER_MARKS)
    if re.match(r"^\d+\s*[.):]", line):
        return ""
    line = _LIST_HEADER_RE.sub("", line)
    line = re.sub(r"[\s:,(–—-]*\d+\s*(?:чел(?:овек[аи]?)?\.?|дет(?:ей|и)|ученик(?:а|ов)?)\s*\)?[.:]?\s*$", "", line, flags=re.I)
    line = re.sub(r"\s*[:–—-]?\s*(?:список детей|на (?:фотосессию|съ[её]мку))\s*[:.]?$", "", line, flags=re.I)
    count = _BARE_COUNT_RE.fullmatch(line)
    if count:
        key = class_key(count[1])
        if is_school_class(key):
            return key
    photo_header = _PHOTO_HEADER_RE.fullmatch(line)
    key = class_key(photo_header[1] if photo_header else line)
    if key or not need:
        return key
    name = group_key(line)
    if name in need:
        return name
    # Явный заголовок другой группы тоже завершает текущий список.
    if (_GROUP_PREFIX.match(line) or _GROUP_SUFFIX.search(line)) and any(not _KEY_RE.fullmatch(k) for k in need):
        return name
    return ""


def people(line: str) -> int:
    """Число похожих на имена записей, без пояснений и отсутствующих."""
    line = re.sub(r"\([^)]*\)", "", line).strip()
    if re.search(r"\?|(?:^|\s)(?:нет|не будет|не будут|отсутству\w*|не прид[её]т|отказ(?:ался|алась|ались))(?:\s|$|[.,:])", line, re.I):
        return 0
    if re.match(r"^(?:спасибо|здравствуйте|добрый|завтра|сегодня|готово|понятно|вопрос|итого|всего|сбор|список|привет|хорошо)\b", line, re.I):
        return 0
    marker = _ITEM_NO_RE.match(line) or _BULLET_ITEM_RE.match(line)
    if marker:
        line = line[marker.end():]
    line = _BARE_ITEM_RE.sub("", line)
    line = re.sub(rf"\s+{_CLASS_LABEL}$", "", line, flags=re.I)
    line, siblings = _ANONYMOUS_SIBLING_RE.subn("", line)
    parts = re.split(r"[,;+]|\s+(?:и|с\s+(?:братом|сестрой))\s+", line, flags=re.I)
    named = sum(bool(re.fullmatch(r"[А-ЯЁA-Z][\w’'-]*(?:\s+[А-ЯЁA-Z][\w.’'-]*){0,3}[.]?", part.strip(), flags=re.I if marker else 0)) for part in parts)
    return named + siblings if named else 0


def _inline(line: str, need: Set[str]):
    match = _INLINE_RE.match(line)
    if match:
        return class_key(match[1]), match[2]
    split = re.match(r"^(.+?)\s*[:—–]\s*(\S.*)$", line)
    if split and not _ITEM_NO_RE.match(line):
        key = _header_key(split[1], need)
        if key:
            return key, split[2]
    return None


def parse_message(text: str, need: Set[str] = frozenset()) -> list[tuple[str, str, bool]]:
    lines = [s.strip() for s in text.splitlines() if s.strip() and not _TIME_RE.match(s)]
    out = []
    key, body, evidence, full = "", [], 0, False
    for i, line in enumerate(lines):
        if full and _BARE_ITEM_RE.match(line) and not _BARE_COUNT_RE.fullmatch(line):
            body.append(line)
            evidence += people(line)
            continue
        header = _header_key(line, need) or _counted_header_key(line, need)
        inline = None if header else _inline(line, need)
        inline_key = inline[0] if inline else ""
        if header or inline_key:
            if key and evidence:
                out.append((key, "\n".join(body), full))
            key, full = header or inline_key, bool(header)
            body = lines[:2] if inline_key and i == 1 and not out and not body else [line]
            evidence = people(inline[1]) if inline_key else 0
        elif key:
            body.append(line)
            evidence += people(line)
    if key and evidence:
        out.append((key, "\n".join(body), full))
    return out


def _row_span(text: str) -> tuple[int, int] | None:
    """Диапазон смежных номеров, если весь текст состоит из строк списка."""
    first = last = None
    for line in text.splitlines():
        if not line.strip():
            continue
        match = _ITEM_NO_RE.match(line) or _BARE_ITEM_RE.match(line)
        if not match or not people(line):
            return None
        number = int(match[1])
        if last is not None and number != last + 1:
            return None
        if first is None:
            first = number
        last = number
    return (first, last) if first is not None else None


def _joined_lists(messages, need: Set[str]):
    """Собирает отдельно отправленный заголовок и соседние части списка."""
    i = 0
    while i < len(messages):
        msg = messages[i]
        i += 1
        heading, _, body = msg.strip().partition("\n")
        key = _header_key(heading, need)
        if key and not body and i < len(messages):
            following = messages[i].strip()
            rows = [s.strip() for s in following.splitlines() if s.strip()]
            clean_heading = _INVISIBLE_RE.sub("", heading).lstrip(_HEADER_MARKS)
            explicit_list = _LIST_HEADER_RE.match(clean_heading) or _BARE_COUNT_RE.fullmatch(clean_heading)
            plain_list = len(rows) > 1 and all(
                _PERSON_RE.fullmatch(row) and people(row) == 1 and (explicit_list or " " in row)
                for row in rows
            )
            if (_ITEM_NO_RE.match(following) or _BARE_ITEM_RE.match(following)
                    or _BULLET_ITEM_RE.match(following) or plain_list):
                msg += "\n" + following
                i += 1
                body = following
        span = _row_span(body) if key else None
        while span and i < len(messages):
            continuation = messages[i].strip()
            if _header_key(continuation.split("\n", 1)[0], need):
                break
            more = _row_span(continuation)
            if not more or more[0] != span[1] + 1:
                break
            msg += "\n" + continuation
            span = more
            i += 1
        yield msg


def message_lists(messages: list[str], need: Set[str] = frozenset()):
    """Разобранные списки по сообщениям, без повторов одного и того же текста."""
    parsed = [tuple(parse_message(message, need)) for message in _joined_lists(messages, need)]
    return reversed(dict.fromkeys(reversed(parsed)))


def _combine_full_lists(bodies: list[str]) -> str:
    if len(bodies) == 1:
        return bodies[0]

    names = {}
    comments = {}
    for body in bodies:
        for line in body.splitlines()[1:]:
            if people(line):
                marker = _ITEM_NO_RE.match(line) or _BARE_ITEM_RE.match(line) or _BULLET_ITEM_RE.match(line)
                name = line[marker.end():] if marker else line
                identity = _ANONYMOUS_SIBLING_RE.sub("", re.sub(r"\([^)]*\)", "", name)).strip(" .")
                identity = " ".join(identity.casefold().replace("ё", "е").split())
                names[identity] = name
            else:
                comments[line] = None

    header = bodies[-1].splitlines()[0]
    rows = [f"{number}. {name}" for number, name in enumerate(names.values(), 1)]
    return "\n".join([header, *rows, *comments])


def collect_lists(messages: list[str], need: Set[str] = frozenset()) -> dict[str, str]:
    """Списки по классам из сообщений чата (от старых к новым)."""
    full_lists: dict[str, list[str]] = {}
    additions: dict[str, list[str]] = {}
    for entries in message_lists(messages, need):
        for key, body, full in entries:
            if full:
                if key not in full_lists or not is_school_class(key):
                    full_lists[key] = []
                    additions[key] = []
                full_lists[key].append(body)
            elif body not in additions.setdefault(key, []):
                additions[key].append(body)

    result = {key: _combine_full_lists(bodies) for key, bodies in full_lists.items()}
    for key, bodies in additions.items():
        if bodies:
            result[key] = "\n".join([result[key], *bodies] if key in result else bodies)
    return result


def full_list_keys(messages: list[str], need: Set[str] = frozenset()) -> set[str]:
    """Классы или группы с полным списком в прочитанных сообщениях."""
    return {key for msg in _joined_lists(messages, need) for key, _, full in parse_message(msg, need) if full}


def find_lists(text: str) -> list[tuple[str, str]]:
    """[(ключ, текст)] из одного сообщения — для журнала и проверок."""
    return [(k, b) for k, b, _ in parse_message(text)]


def merge_history(history: list[str], older: list[str]) -> list[str]:
    """Склеивает уже прочитанную историю (от старых к новым) с более старым «снимком» экрана.

    Снимки перекрываются: ищем самое длинное совпадение конца `older` с началом `history`.
    """
    if not history:
        return list(older)
    if any(history[i:i + len(older)] == older for i in range(len(history) - len(older) + 1)):
        return history
    for k in range(min(len(older), len(history)), 0, -1):
        if older[-k:] == history[:k]:
            return older[:-k] + history
    return older + history


_COUNT_COMMENT_RE = re.compile(r"^(?:идут\b|снимаются\b|список\b|всего\b|итого\b|количество\b|на\s+фотосессию\b)", re.I)
_PERSON_RE = re.compile(r"[А-ЯЁA-Zа-яёa-z]+(?:[-'][А-ЯЁA-Zа-яёa-z]+)*(?:\s+[А-ЯЁA-Zа-яёa-z]+(?:[-'][А-ЯЁA-Zа-яёa-z]+)*){0,2}")


def count_kids(body: str, need: Set[str] = frozenset()) -> int:
    total = 0
    for _, block, full in parse_message(body, need):
        started = full
        for i, line in enumerate(block.splitlines()):
            inline = _inline(line, need)
            if not full and inline and not started:
                total += people(inline[1])
                started = True
            elif started and i:
                total += people(line)
    return total
