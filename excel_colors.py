"""Распознавание красной заливки / красного текста в ячейках Excel.

В отчётах классы, которые не нужно заводить в amoCRM, иногда помечают красным.
Цвет в xlsx бывает задан тремя способами — всё сводим к RGB:
  * rgb      — напрямую, ARGB-строка вида "FFFF0000";
  * indexed  — номер в старой палитре Excel (openpyxl.styles.colors.COLOR_INDEX);
  * theme    — номер цвета темы книги + осветление/затемнение (tint).
«Красный» — оттенок около 0°, достаточно насыщенный: сюда попадают и яркий красный,
и бледно-красная заливка (как у стиля «Плохой»), но не оранжевый и не серый.
"""

from __future__ import annotations

import colorsys
import re

from openpyxl.styles.colors import COLOR_INDEX

# порядок цветов темы в Excel: 0 — светлый фон, 1 — тёмный текст, 2/3 — доп., 4..9 — акценты
_THEME_ORDER = ["lt1", "dk1", "lt2", "dk2", "accent1", "accent2", "accent3",
                "accent4", "accent5", "accent6", "hlink", "folHlink"]


def theme_palette(wb) -> list[str]:
    """RGB-цвета темы книги в порядке индексов Excel (пусто, если тема не найдена)."""
    xml = getattr(wb, "loaded_theme", None)
    if not xml:
        return []
    if isinstance(xml, bytes):
        xml = xml.decode("utf-8", "ignore")
    found = {}
    for tag in _THEME_ORDER:
        m = re.search(rf"<a:{tag}>(.*?)</a:{tag}>", xml, re.S)
        if not m:
            continue
        c = re.search(r'(?:srgbClr val|lastClr)="([0-9A-Fa-f]{6})"', m.group(1))
        if c:
            found[tag] = c.group(1).upper()
    return [found.get(t, "") for t in _THEME_ORDER]


def _apply_tint(rgb: str, tint: float) -> str:
    r, g, b = (int(rgb[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = l * (1 + tint) if tint < 0 else l * (1 - tint) + tint
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return "".join(f"{round(x * 255):02X}" for x in (r, g, b))


def color_rgb(color, palette: list[str]) -> str:
    """RGB ('RRGGBB') цвета openpyxl или '' если определить нельзя."""
    if color is None:
        return ""
    try:
        if color.type == "rgb" and isinstance(color.rgb, str) and len(color.rgb) >= 6:
            return color.rgb.upper()[-6:]  # альфа-канал Excel не учитывает
        if color.type == "indexed" and color.indexed is not None and color.indexed < len(COLOR_INDEX):
            return COLOR_INDEX[color.indexed][-6:].upper()
        if color.type == "theme" and color.theme is not None and color.theme < len(palette):
            base = palette[color.theme]
            if base:
                return _apply_tint(base, color.tint or 0.0)
    except (AttributeError, TypeError, ValueError):
        pass
    return ""


def is_red(rgb: str) -> bool:
    if not rgb or len(rgb) != 6:
        return False
    r, g, b = (int(rgb[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    hue = h * 360
    return (hue <= 15 or hue >= 340) and s >= 0.18 and v >= 0.45


def cell_is_red(cell, palette: list[str]) -> bool:
    """Красная заливка или красный текст в ячейке."""
    fill = cell.fill
    if fill is not None and fill.fill_type == "solid" and is_red(color_rgb(fill.fgColor, palette)):
        return True
    font = cell.font
    return font is not None and is_red(color_rgb(font.color, palette))
