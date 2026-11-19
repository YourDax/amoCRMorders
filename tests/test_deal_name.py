"""Название сделки: класс без пробела и со строчной буквой («6 Ж» → «6ж»)."""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from excel_reader import KINDERGARTEN, SCHOOL, deal_name, norm_class  # noqa: E402


class DealName(unittest.TestCase):
    def test_norm_class(self):
        for raw, want in [("6 ж", "6ж"), ("6 Ж", "6ж"), ("3Б", "3б"), ("2а", "2а"), (" 11  А ", "11а"),
                          ("10 ИТ", "10ит"), ("11 мат", "11 мат"), ("Солнышко", "Солнышко"), ("5", "5")]:
            self.assertEqual(norm_class(raw), want, raw)

    def test_deal_name(self):
        self.assertEqual(deal_name("6 Ж", "Под_18-сп1", SCHOOL), "6ж Под_18-сп1")
        self.assertEqual(deal_name("гр. 4 А", "1368-до4", KINDERGARTEN), "гр.4а 1368-до4")
        self.assertEqual(deal_name("6 Ж", "Под_18-сп1", SCHOOL, normalize=False), "6 Ж Под_18-сп1")


class LegacyProgress(unittest.TestCase):
    """Сделка, созданная со старым названием «6 Ж …», узнаётся и не создаётся второй раз."""

    def test_parse_finds_old_name(self):
        import openpyxl

        import app
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        app.PROGRESS = Path(tmp.name) / "progress.json"
        app.UPLOADS = Path(tmp.name) / "uploads"
        import history
        history.FILE = Path(tmp.name) / "history.json"
        app.save_progress({"6 Ж Под_18-сп1": {"url": "u", "status": "ok"}})
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Школа: Под_18-сп1"])
        ws.append(["Класс", "ФИО КР", "Телефон КР", "ФИО РК", "Телефон РК"])
        ws.append(["6 Ж", "Иванова Анна", "+79990000001", "", ""])
        ws.append(["3Б", "Петрова Ольга", "+79990000002", "", ""])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        res = app.app.test_client().post("/api/parse", data={"file": (buf, "a.xlsx")})
        deals = json.loads(res.data)["deals"]
        self.assertEqual([d["name"] for d in deals], ["6ж Под_18-сп1", "3б Под_18-сп1"])
        self.assertEqual((deals[0]["done"], deals[0]["sel"]), ("u", False))
        self.assertTrue(deals[1]["sel"])
        self.assertEqual(app.load_progress()["6ж Под_18-сп1"]["url"], "u")


if __name__ == "__main__":
    unittest.main()
