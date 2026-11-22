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
    r"^\s*(\d{1,2})\s*[-–]?\s*[«\"']?([А-Яа-яЁёA-Za-z]{1,2})[»\"']?"
    r"(?:\s*(?:класс\w*|кл\.?))?(?=[\s,:;.\-–])[\s,:;.\-–]+(\S.*)$", re.I)


def class_key(text: str) -> str:
    """«6 «Б» класс» → «6б», «гр.11» → «11». Пусто, если это не похоже на класс/группу."""
    s = str(text or "").strip().lower().replace("ё", "е")
    s = _WORDS_RE.sub(" ", s)
    s = re.sub(r"[\s\-–—_.,:;\"'«»“”„()№]+", "", s)
    s = s.translate(_LATIN)
    return s if _KEY_RE.match(s) else ""


def _header_key(line: str) -> str:
    """Ключ класса, если строка целиком — заголовок («6Б», «Список 3А:»)."""
    line = line.replace("\u200b", "").replace("\u00a0", " ")
    line = re.sub(r"^\s*(?:📋|список\s+(?:детей|учеников|участников)(?:\s+(?:для|на))?)\s*[:–—-]?\s*", "", line, flags=re.I)
    line = re.sub(r"[\s:,(–—-]*\d+\s*(?:чел(?:овек[аи]?)?\.?|дет(?:ей|и)|ученик(?:а|ов)?)\s*\)?[.:]?\s*$", "", line, flags=re.I)
    line = re.sub(r"\s*[:–—-]?\s*(?:список детей|на (?:фотосессию|съ[её]мку))\s*[:.]?$", "", line, flags=re.I)
    return class_key(line)


def people(line: str) -> int:
    """Число похожих на имена записей, без пояснений и отсутствующих."""
    line = re.sub(r"\([^)]*\)", "", line).strip()
    if re.search(r"\?|(?:^|\s)(?:нет|не будет|не будут|отсутству\w*|не прид[её]т)(?:\s|$|[.,:])", line, re.I):
        return 0
    if re.match(r"^(?:спасибо|здравствуйте|добрый|завтра|сегодня|готово|понятно|вопрос|итого|всего|сбор|список|привет|хорошо)\b", line, re.I):
        return 0
    marked = bool(re.match(r"^(?:\d+[.)\-:]|[•*–—-])", line))
    line = re.sub(r"^(?:\d+[.)\-:]|[•*–—-])\s*", "", line)
    parts = re.split(r"[,;]|\s+и\s+", line)
    return sum(bool(re.fullmatch(r"[А-ЯЁA-Z][\w’'-]*(?:\s+[А-ЯЁA-Z][\w.’'-]*){0,3}[.]?", part.strip(), flags=re.I if marked else 0)) for part in parts)


def _inline(line):
    match = _INLINE_RE.match(line)
    if match:
        return class_key(match[1] + match[2]), match[3]
    split = re.match(r"^(.+?)\s*[:—–]\s*(\S.*)$", line)
    if split and not _ITEM_NO_RE.match(line):
        key = _header_key(split[1])
        if key:
            return key, split[2]
    return None


def parse_message(text: str) -> list[tuple[str, str, bool]]:
    lines = [s.strip() for s in text.splitlines() if s.strip() and not _TIME_RE.match(s)]
    out = []
    key, body, evidence, full = "", [], 0, False
    for i, line in enumerate(lines):
        header = "" if re.match(r"^\d+\s*[.):]", line) else _header_key(line)
        inline = None if header else _inline(line)
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


def _joined_lists(messages):
    """Отдельно отправленный заголовок и непосредственно следующий нумерованный список."""
    i = 0
    while i < len(messages):
        msg = messages[i]
        i += 1
        if _header_key(msg.strip()) and i < len(messages):
            following = messages[i].strip()
            if _ITEM_NO_RE.match(following) or re.match(r"^[•*–—-]\s+", following):
                msg += "\n" + following
                i += 1
        yield msg


def collect_lists(messages: list[str]) -> dict[str, str]:
    """Списки по классам из сообщений чата (от старых к новым)."""
    parts: dict[str, list[str]] = {}
    for msg in _joined_lists(messages):
        for key, body, full in parse_message(msg):
            if full:
                parts[key] = [body]
            elif body not in parts.setdefault(key, []):
                parts[key].append(body)
    return {k: "\n".join(v) for k, v in parts.items()}


def full_list_keys(messages: list[str]) -> set[str]:
    """Классы, у которых в этих сообщениях есть полный список (дальше в прошлое искать не нужно)."""
    return {key for msg in _joined_lists(messages) for key, _, full in parse_message(msg) if full}


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


def count_kids(body: str) -> int:
    total = 0
    for _, block, full in parse_message(body):
        started = full
        for i, line in enumerate(block.splitlines()):
            inline = _inline(line)
            if not full and inline and not started:
                total += people(inline[1])
                started = True
            elif started and i:
                total += people(line)
    return total
