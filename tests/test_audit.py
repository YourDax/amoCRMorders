import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook
from excel_reader import Deal, normalize_phone, progress_key, read_deals
from kids_lists import collect_lists, count_kids
from test_run_notes import FakeBot, item
import app
from unittest.mock import patch


class Regression(unittest.TestCase):
    def test_compound_class(self):
        names = "Лопанов Домбровская Выхристенко Родионов Савицкий Крашенинников Шматова Шульгина Илларионова Лоренц Агеева".split()
        msg = "2мК - 11 человек\n" + "\n".join(f"{i}. {n}" for i,n in enumerate(names, 1)) + "\n\nНоздрин, Андреева, Варгасова нет"
        body = collect_lists([msg, "2мК\nВо сколько сбор?"])["2мк"]
        self.assertIn("Варгасова нет", body)
        self.assertEqual(count_kids(body), 11)

    def test_header_variants(self):
        for header in ["2-МК", "2 «МК» (2 чел.)", "Список детей: 2мК", "2мк — 2 ученика", "2мК на съёмку:"]:
            with self.subTest(header=header):
                body = collect_lists([header + "\n• иванов\n• петров"])["2мк"]
                self.assertEqual(count_kids(body), 2)

    def test_inline(self):
        lists = collect_lists(["3А Анна\n4Б Олег"])
        self.assertEqual(set(lists), {"3а", "4б"})
        self.assertEqual(count_kids(lists["3а"]), 1)
        self.assertNotIn("Олег", lists["3а"])

    def test_group_inline(self):
        body = collect_lists(["Группа 11: Иванов, Петров"])["11"]
        self.assertEqual(count_kids(body), 2)

    def test_separate_header(self):
        self.assertEqual(count_kids(collect_lists(["2мК", "1. Анна\n2. Оля"])["2мк"]), 2)

    def test_input(self):
        self.assertEqual(normalize_phone("89000000001 89000000002"), ("+79000000001", "доп. +79000000002"))
        self.assertFalse(Deal("", 1, "", "", info="отказов нет").refused)

    def test_second_day_and_mixed_book(self):
        wb = Workbook()
        for idx, (title, place, klass, tutor) in enumerate([
                ("День 1", "Школа: А", "2мК", "КР"),
                ("Досъем", "Школа: А", "2 МК", "КР"),
                ("ДС", "ДС: Б", "11", "воспитателя")]):
            ws = wb.active if idx == 0 else wb.create_sheet()
            ws.title = title
            ws.append([place])
            ws.append(["Класс" if idx < 2 else "Группа", "ФИО " + tutor])
            ws.append([klass, "Анна"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "book.xlsx"
            wb.save(path)
            deals, warnings = read_deals(path)
        self.assertEqual(len(deals), 2)
        self.assertEqual(deals[1].contacts[0].role, "ВС")
        self.assertTrue(any("Повтор" in w for w in warnings))

    def test_pipeline_and_uncertain_save(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "PROGRESS", Path(tmp)/"p.json"), patch.object(app.S,"add_log"):
            bot = FakeBot()
            original = bot.save
            def ambiguous():
                original()
                raise RuntimeError("timeout")
            bot.save = ambiguous
            for klass in ["2мК", "2 МК"]:
                app.run_deals(bot, [item(1, klass)], False, "A")
            self.assertEqual(bot.created, 1)
            bot.save = original
            app.run_deals(bot, [item(1, "2 МК")], False, "B")
            self.assertEqual(bot.created, 2)
