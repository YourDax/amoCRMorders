"""Чтение отчёта по мероприятию (xlsx) и превращение строк в сделки.

Ожидаемый формат листа (как в «Отчет по мероприятию»):
  * в первых строках есть ячейка «Школа: <название>»;
  * строка заголовков с колонками «Класс», «ФИО КР», «Телефон КР», «ФИО РК», «Телефон РК»;
  * ниже — по строке на класс. Строки без класса пропускаются.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import openpyxl

from excel_colors import cell_is_red, theme_palette

HEADER_ALIASES = {
    "class": ["класс"],
    "kr_name": ["фио кр"],
    "kr_phone": ["телефон кр"],
    "rk_name": ["фио рк"],
    "rk_phone": ["телефон рк"],
}
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
    school: str
    klass: str
    contacts: list[Contact] = field(default_factory=list)
    info: str = ""      # «Доп.Информация / Причина отказа» из отчёта
    red: bool = False   # строка помечена в файле красным — по умолчанию не создаём

    @property
    def refused(self) -> bool:
        """Похоже ли на отказ класса — такие строки по умолчанию не отмечены."""
        return bool(REFUSAL_RE.search(self.info))

    @property
    def name(self) -> str:
        return f"{self.klass} {self.school}".strip()

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
    for m in re.finditer(r"\+?\d[\d\s\-()]{8,}\d", text):
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
    phone, phone_note = normalize_phone(phone_raw)
    if not name and not phone:
        return None
    note = "; ".join(p for p in (name_note, phone_note) if p)
    return Contact(role=role, name=name, phone=phone, note=note)


def _find_school(ws) -> str:
    for row in ws.iter_rows(min_row=1, max_row=5):
        for c in row:
            t = _cell_text(c.value)
            if t.lower().startswith("школа"):
                return t.split(":", 1)[1].strip() if ":" in t else ""
    return ""


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
            return row[0].row, cols
    return None


def read_deals(path: str, sheets: list[str] | None = None, school_override: str = "") -> tuple[list[Deal], list[str]]:
    """Читает книгу. Возвращает (сделки, предупреждения)."""
    wb = openpyxl.load_workbook(path, data_only=True)
    palette = theme_palette(wb)
    deals: list[Deal] = []
    warnings: list[str] = []

    for ws in wb.worksheets:
        if sheets and ws.title not in sheets:
            continue
        header = _find_header(ws)
        if not header:
            warnings.append(f"Лист «{ws.title}»: не найдена строка заголовков, пропущен")
            continue
        header_row, cols = header
        school = school_override or _find_school(ws)

        def get(r, key):
            col = cols.get(key)
            return ws.cell(row=r, column=col).value if col else None

        for r in range(header_row + 1, ws.max_row + 1):
            klass = _cell_text(get(r, "class"))
            if not klass:
                continue
            if not school:
                warnings.append(f"Лист «{ws.title}»: не заполнена школа (ячейка «Школа: ...»), строки пропущены")
                break
            red = any(cell_is_red(ws.cell(row=r, column=col), palette) for col in cols.values())
            deal = Deal(sheet=ws.title, row=r, school=school, klass=klass,
                        info=_cell_text(get(r, "info")), red=red)
            kr = _make_contact("КР", get(r, "kr_name"), get(r, "kr_phone"))
            rk = _make_contact("РК", get(r, "rk_name"), get(r, "rk_phone"))
            if kr:
                deal.contacts.append(kr)   # КР всегда первым
            else:
                warnings.append(f"«{ws.title}» стр.{r} ({deal.name}): нет КР")
            if rk:
                deal.contacts.append(rk)
            for c in deal.contacts:
                if not c.phone:
                    warnings.append(f"«{ws.title}» стр.{r} ({deal.name}): у {c.role} нет телефона")
            deals.append(deal)

    seen: dict[str, Deal] = {}
    for d in deals:
        if d.name in seen:
            warnings.append(f"«{d.name}» встречается дважды (листы «{seen[d.name].sheet}» и «{d.sheet}»)")
        seen.setdefault(d.name, d)
    return deals, warnings
