"""Чтение отчёта по мероприятию (xlsx) и превращение строк в сделки.

Ожидаемый формат листа (как в «Отчет по мероприятию»):
  * в первых строках есть ячейка «Школа: <название>» (детский сад — «ДС: <название>»);
  * строка заголовков с колонками «Класс», «ФИО КР», «Телефон КР», «ФИО РК», «Телефон РК»
    (детский сад — «Группа», «ФИО Воспитателя», «Телефон Воспитателя», «ФИО РК», «Телефон РК»);
  * ниже — по строке на класс/группу. Строки без класса пропускаются.

Школа: сделка «1а ВХТЛ-сп4», первый контакт — КР (классный руководитель).
Детский сад: сделка «гр.11 1368-до4», первый контакт — ВС (воспитатель).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import openpyxl

from kids_lists import class_key
from excel_colors import cell_is_red, theme_palette

HEADER_ALIASES = {
    "class": ["класс", "группа"],
    "kr_name": ["фио кр", "фио воспитателя", "фио вс"],
    "kr_phone": ["телефон кр", "телефон воспитателя", "телефон вс"],
    "rk_name": ["фио рк"],
    "rk_phone": ["телефон рк"],
}
# Явный заголовок имеет приоритет над общей колонкой «Количество человек».
_SHOT_HEADER_RE = re.compile(
    r"^(?:(?:количество|кол[.\s-]*во)\s+)?(?:чел(?:овек)?\.?[,]?\s+)?(?:которые\s+)?"
    r"(?:снимал(?:ось|ись)|снимавш\w*|снято|фотографировал(?:ось|ись)|фотографировавш\w*)"
    r"(?:\s+(?:\(?чел(?:овек)?\.?\)?|детей))?\s*[:.]?$"
)
_COUNT_HEADER_RE = re.compile(r"^(?:количество|кол[.\s-]*во)\s+(?:чел(?:овек)?\.?|детей)\s*:?$")
_COUNT_CELL_RE = re.compile(r"([0-9]+)(?:\s*(?:чел(?:овек)?\.?|детей))?", re.I)

SCHOOL, KINDERGARTEN = "school", "kindergarten"
LEAD_ROLE = {SCHOOL: "КР", KINDERGARTEN: "ВС"}  # первый контакт: классный руководитель / воспитатель
# подпись учреждения в шапке листа: «Школа: ...», «ДС: ...», «Детский сад: ...», «Д/с: ...»
PLACE_RE = re.compile(r"^\s*(школа|дс|д/с|детский\s+сад)\s*[:№]?\s*(.*)$", re.I)


# класс «6 Ж», «6Ж», «11 а» — цифры и буква (буквы), между ними может быть пробел
CLASS_RE = re.compile(r"^(\d{1,2})\s*([A-Za-zА-Яа-яЁё]{1,2})$")


def norm_class(klass: str) -> str:
    """«6 ж» → «6ж», «3Б» → «3б». Другие записи («11 мат», «Солнышко») не трогает."""
    klass = klass.strip()
    m = CLASS_RE.match(klass)
    return (m.group(1) + m.group(2).lower()) if m else klass


def deal_name(klass: str, place: str, kind: str, normalize: bool = True) -> str:
    """Название сделки: «1а ВХТЛ-сп4» для школы, «гр.11 1368-до4» для детского сада.
    normalize=False — как до v1.0.15 (класс как в файле): по нему ищутся созданные раньше сделки."""
    klass = klass.strip()
    if kind == KINDERGARTEN:
        klass = re.sub(r"^гр(уппа)?\.?\s*", "", klass, flags=re.I)
        klass = "гр." + (norm_class(klass) if normalize else klass)
    elif normalize:
        klass = norm_class(klass)
    return f"{klass} {place}".strip()


def deal_identity(name: str) -> str:
    words = name.casefold().replace("ё", "е").split()
    for i in range(len(words)):
        for end in range(min(i + 3, len(words)), i, -1):
            candidate = " ".join(words[i:end])
            key = class_key(candidate)
            if end > i + 1 and class_key(words[i]) and not words[i].isdigit():
                continue
            if key and not (end > i + 1 and words[end-1].isdigit() and not words[i].startswith("гр")):
                words[i:end] = [key]
                return " ".join(words)
    return " ".join(words)


def progress_key(progress, name, pipeline):
    import json
    identity = deal_identity(name)
    key = json.dumps([pipeline.strip().casefold(), identity], ensure_ascii=False)
    if key in progress:
        return key
    if not pipeline:
        # CLI без явной воронки сохраняет совместимость со старыми карточками.
        for saved in progress:
            if saved.startswith("["):
                try:
                    _, other = json.loads(saved)
                except (TypeError, ValueError):
                    continue
                if other == identity:
                    return saved
    # Старый формат не хранил воронку. Сохраняем защиту старых карточек.
    for old in progress:
        if not old.startswith("[") and deal_identity(old) == identity:
            return old
    return key if pipeline else name


def fix_name_case(name: str) -> str:
    """ФИО с заглавных букв: «диля халимовна» → «Диля Халимовна», «ИВАНОВА» → «Иванова»,
    двойные через дефис — «анна-мария» → «Анна-Мария». Инициалы («Е.») не трогает."""
    def word(w: str) -> str:
        return "-".join(p[:1].upper() + p[1:].lower() for p in w.split("-"))
    return " ".join(word(w) for w in name.split())
REFUSAL_RE = re.compile(r"отказ|друг\w* фотограф|не будут фот|не хотят", re.I)

# колонки, которые узнаём по началу заголовка
HEADER_PREFIXES = {
    "info": ["доп.информация", "доп. информация", "доп информация"],
}


@dataclass
class Contact:
    role: str          # "КР" или "РК"
    name: str
    phone: str         # нормализованный номер, например +79261234567
    note: str = ""     # примечание (текст из ячеек помимо номера/имени)

    @property
    def phone_field(self) -> str:
        """Что вводим в поле «Раб. тел.»: номер и примечание в скобках."""
        if self.note and self.phone:
            return f"{self.phone} ({self.note})"
        return self.phone or self.note


@dataclass
class Deal:
    sheet: str
    row: int
    school: str          # название учреждения (школа или детский сад)
    klass: str           # класс или группа, как в файле
    kind: str = SCHOOL
    contacts: list[Contact] = field(default_factory=list)
    info: str = ""      # «Доп.Информация / Причина отказа» из отчёта
    red: bool = False   # строка помечена в файле красным — по умолчанию не создаём
    expected_kids: int | None = None

    @property
    def refused(self) -> bool:
        """Похоже ли на отказ класса — такие строки по умолчанию не отмечены."""
        return bool(REFUSAL_RE.search(re.sub(r"\b(?:без\s+отказ\w*|отказ\w*\s+нет|не\s+отказ\w*)\b", "", self.info, flags=re.I)))

    @property
    def name(self) -> str:
        return deal_name(self.klass, self.school, self.kind)

    @property
    def legacy_name(self) -> str:
        """Название, как его строили до v1.0.15 («6 Ж Школа»), — для поиска уже созданных сделок."""
        return deal_name(self.klass, self.school, self.kind, normalize=False)

    @property
    def key(self) -> str:
        """Ключ для защиты от повторного создания — название сделки."""
        return self.name


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return re.sub(r"\s+", " ", str(value)).strip()


def _norm_header(value) -> str:
    return re.sub(r"\s+", " ", _cell_text(value).lower())


def normalize_phone(raw) -> tuple[str, str]:
    """Возвращает (номер, примечание).

    89261234567 / 8 (926) 123-45-67 / +7 926 ... -> +79261234567.
    Всё, что не номер (например «только WhatsApp»), уходит в примечание.
    Если номеров несколько, первый идёт в номер, остальные — в примечание.
    """
    text = _cell_text(raw)
    if not text:
        return "", ""

    numbers = []
    rest = text
    for m in re.finditer(r"(?<!\d)(?:\+?[78][\s()-]*)?(?:\d[\s()-]*){9}\d(?!\d)", text):
        digits = re.sub(r"\D", "", m.group())
        if len(digits) == 11 and digits[0] in "78":
            numbers.append("+7" + digits[1:])
        elif len(digits) == 10:
            numbers.append("+7" + digits)
        else:
            numbers.append(m.group().strip())
        rest = rest.replace(m.group(), " ")

    note_parts = []
    rest = re.sub(r"\s+", " ", rest).strip(" ,;/()-")
    if rest:
        note_parts.append(rest)
    if len(numbers) > 1:
        note_parts.append("доп. " + ", ".join(numbers[1:]))

    phone = numbers[0] if numbers else ""
    if not numbers:  # номера нет совсем — весь текст как примечание
        return "", text
    return phone, "; ".join(note_parts)


def split_name(raw) -> tuple[str, str]:
    """«Олеся (мама)» -> ("Олеся", "мама")."""
    text = _cell_text(raw)
    notes = re.findall(r"\(([^)]*)\)", text)
    name = re.sub(r"\([^)]*\)", " ", text)
    name = re.sub(r"\s+", " ", name).strip(" ,;")
    return name, "; ".join(n.strip() for n in notes if n.strip())


def _make_contact(role: str, name_raw, phone_raw) -> Contact | None:
    name, name_note = split_name(name_raw)
    name = fix_name_case(name)
    phone, phone_note = normalize_phone(phone_raw)
    if not name and not phone:
        return None
    note = "; ".join(p for p in (name_note, phone_note) if p)
    return Contact(role=role, name=name, phone=phone, note=note)


def _find_place(ws) -> tuple[str, str | None]:
    """(название учреждения, тип по подписи: school / kindergarten / None)."""
    for row in ws.iter_rows(min_row=1, max_row=5):
        for c in row:
            m = PLACE_RE.match(_cell_text(c.value))
            if m:
                return m.group(2).strip(), (SCHOOL if m.group(1).lower() == "школа" else KINDERGARTEN)
    return "", None


def _kind_by_headers(ws, header_row: int) -> str | None:
    heads = [_norm_header(c.value) for c in ws[header_row]]
    if any(h in ("группа", "фио воспитателя", "телефон воспитателя") for h in heads):
        return KINDERGARTEN
    if any(h in ("класс", "фио кр", "телефон кр") for h in heads):
        return SCHOOL
    return None


def _find_header(ws) -> tuple[int, dict[str, int]] | None:
    for row in ws.iter_rows(min_row=1, max_row=15):
        cols: dict[str, int] = {}
        for c in row:
            h = _norm_header(c.value)
            for key, aliases in HEADER_ALIASES.items():
                if key not in cols and h in aliases:
                    cols[key] = c.column
            for key, prefixes in HEADER_PREFIXES.items():
                if key not in cols and any(h.startswith(pr) for pr in prefixes):
                    cols[key] = c.column
        if "class" in cols and "kr_name" in cols:
            for pattern in (_SHOT_HEADER_RE, _COUNT_HEADER_RE):
                col = next((c.column for c in row if pattern.fullmatch(_norm_header(c.value))), None)
                if col is not None:
                    cols["expected_kids"] = col
                    break
            return row[0].row, cols
    return None


def detect_kind(path: str) -> str:
    """Школа или детский сад — по подписи «Школа:/ДС:» и заголовкам («Класс»/«Группа», «Воспитатель»)."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        votes = {SCHOOL: 0, KINDERGARTEN: 0}
        for ws in wb.worksheets:
            for row in ws.iter_rows(min_row=1, max_row=15, values_only=True):
                for v in row:
                    t = _cell_text(v)
                    m = PLACE_RE.match(t)
                    if m:
                        votes[SCHOOL if m.group(1).lower() == "школа" else KINDERGARTEN] += 2
                    h = t.lower()
                    if h in ("группа", "фио воспитателя", "телефон воспитателя"):
                        votes[KINDERGARTEN] += 1
                    elif h in ("класс", "фио кр", "телефон кр"):
                        votes[SCHOOL] += 1
        return KINDERGARTEN if votes[KINDERGARTEN] > votes[SCHOOL] else SCHOOL
    finally:
        wb.close()


def read_deals(path: str, sheets: list[str] | None = None, school_override: str = "",
               kind: str | None = None) -> tuple[list[Deal], list[str]]:
    """Читает книгу. kind — school / kindergarten (None — определить по файлу).
    Возвращает (сделки, предупреждения)."""
    forced_kind = kind
    wb = openpyxl.load_workbook(path, data_only=True)
    palette = theme_palette(wb)
    deals: list[Deal] = []
    warnings: list[str] = []

    per_sheet: list[tuple[str, list[Deal], list[str]]] = []  # (лист, сделки, предупреждения по строкам)
    for ws in wb.worksheets:
        if sheets and ws.title not in sheets:
            continue
        sheet_deals: list[Deal] = []
        sheet_warns: list[str] = []
        per_sheet.append((ws.title, sheet_deals, sheet_warns))
        header = _find_header(ws)
        if not header:
            warnings.append(f"Лист «{ws.title}»: не найдена строка заголовков, пропущен")
            continue
        header_row, cols = header
        place, label_kind = _find_place(ws)
        school = school_override or place
        kind = forced_kind or label_kind or _kind_by_headers(ws, header_row) or SCHOOL
        lead = LEAD_ROLE[kind]
        place_word = "название учреждения"

        def get(r, key):
            col = cols.get(key)
            return ws.cell(row=r, column=col).value if col else None

        for r in range(header_row + 1, ws.max_row + 1):
            klass = _cell_text(get(r, "class"))
            if not klass:
                if any(_cell_text(get(r, key)) for key in ("kr_name", "kr_phone", "rk_name", "rk_phone")):
                    sheet_warns.append(f"«{ws.title}» стр.{r}: есть контакты, но не указан класс или группа. Строка пропущена.")
                continue
            if not school:
                warnings.append(f"Лист «{ws.title}»: не заполнен {place_word}, строки пропущены")
                break
            red = any(cell_is_red(ws.cell(row=r, column=col), palette)
                      for key, col in cols.items() if key != "expected_kids")
            number = _COUNT_CELL_RE.fullmatch(_cell_text(get(r, "expected_kids")))
            expected_kids = int(number.group(1)) if number else None
            deal = Deal(sheet=ws.title, row=r, school=school, klass=klass, kind=kind,
                        info=_cell_text(get(r, "info")), red=red, expected_kids=expected_kids)
            kr = _make_contact(lead, get(r, "kr_name"), get(r, "kr_phone"))
            rk = _make_contact("РК", get(r, "rk_name"), get(r, "rk_phone"))
            if kr:
                deal.contacts.append(kr)   # КР / воспитатель всегда первым
            else:
                sheet_warns.append(f"«{ws.title}» стр.{r} ({deal.name}): нет {lead}")
            if rk:
                deal.contacts.append(rk)
            for c in deal.contacts:
                if not c.phone:
                    sheet_warns.append(f"«{ws.title}» стр.{r} ({deal.name}): у {c.role} нет телефона")
            sheet_deals.append(deal)

    # Лист без единого контакта (например «Досъем» — только номера групп) — это не список сделок:
    # его строки дублировали бы сделки с основного листа. Пропускаем, если в файле есть листы с контактами.
    with_contacts = any(d.contacts for _, sd, _ in per_sheet for d in sd)
    for title, sheet_deals, sheet_warns in per_sheet:
        if with_contacts and sheet_deals and not any(d.contacts for d in sheet_deals):
            warnings.append(f"Лист «{title}»: нет ни одного контакта — пропущен")
            continue
        deals.extend(sheet_deals)
        warnings.extend(sheet_warns)

    seen = {}
    for d in deals:
        key = (d.kind, d.school.casefold(), class_key(d.klass) or d.klass.casefold())
        if key in seen:
            first = seen[key]
            warnings.append(f"Повтор «{d.name}» на листе «{d.sheet}», строка {d.row}. Объединён со строкой {first.row} листа «{first.sheet}».")
            for contact in d.contacts:
                prior = next((c for c in first.contacts if c.role == contact.role), None)
                if prior is None:
                    first.contacts.append(contact)
                elif prior.name and contact.name and prior.name != contact.name:
                    warnings.append(f"«{d.name}»: разные контакты {contact.role}; сохранён контакт из строки {first.row} листа «{first.sheet}».")
                else:
                    if prior.phone and contact.phone and prior.phone != contact.phone:
                        warnings.append(f"«{d.name}»: разные телефоны {contact.role}; сохранён первый.")
                    prior.name = prior.name or contact.name
                    prior.phone = prior.phone or contact.phone
                    prior.note = "; ".join(dict.fromkeys(filter(None, [prior.note, contact.note])))
            first.red |= d.red
            if d.info and d.info != first.info:
                first.info = "; ".join(filter(None, [first.info, d.info]))
        else:
            seen[key] = d
    wb.close()
    return list(seen.values()), warnings
