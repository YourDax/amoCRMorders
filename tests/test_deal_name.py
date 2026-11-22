"""Название сделки: класс без пробела и со строчной буквой («6 Ж» → «6ж»)."""

import io
import sys
import tempfile
import unittest
from unittest.mock import patch
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


class ImportProgress(unittest.TestCase):
    def test_new_import_starts_fresh_and_history_resumes(self):
        import openpyxl

        import app
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        import history
        self.enterContext(patch.object(app, "PROGRESS", Path(tmp.name) / "progress.json"))
        self.enterContext(patch.object(app, "UPLOADS", Path(tmp.name) / "uploads"))
        self.enterContext(patch.object(app, "S", app.State()))
        self.enterContext(patch.object(history, "FILE", Path(tmp.name) / "history.json"))
        app.save_progress({"6 Ж Под_18-сп1": {"url": "u", "status": "ok"}})
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Школа: Под_18-сп1"])
        ws.append(["Класс", "ФИО КР", "Телефон КР", "ФИО РК", "Телефон РК", "Количество человек", "Кол-во снимавшихся"])
        ws.append(["6 Ж", "Иванова Анна", "+79990000001", "", "", 30, 12])
        ws.append(["3Б", "Петрова Ольга", "+79990000002", "", "", 25, "0 чел."])
        buf = io.BytesIO()
        wb.save(buf)
        client = app.app.test_client()

        def upload():
            res = client.post("/api/parse", data={"file": (io.BytesIO(buf.getvalue()), "a.xlsx")})
            self.assertEqual(res.status_code, 200)
            return res.get_json()

        first = upload()
        deals = first["deals"]
        self.assertEqual([d["name"] for d in deals], ["6ж Под_18-сп1", "3б Под_18-сп1"])
        self.assertTrue(all(d["sel"] and not d["done"] for d in deals))
        self.assertEqual([d["expectedKids"] for d in deals], [12, 0])
        key = history.progress_key(deals[0])
        app.save_progress({key: {"url": "created", "status": "ok", "note": True}})
        app.S.set_row(deals[0]["id"], status="ok", url="created")
        second = upload()
        self.assertNotEqual(deals[0]["id"], second["deals"][0]["id"])
        self.assertTrue(all(d["sel"] and not d["done"] for d in second["deals"]))
        self.assertEqual(client.get("/api/status").get_json()["rows"], {})
        restored = client.get("/api/history/" + first["historyId"]).get_json()["entry"]["deals"]
        self.assertEqual((restored[0]["done"], restored[0]["sel"], restored[0]["note"]), ("created", False, True))
        self.assertTrue(restored[1]["sel"])
        self.assertEqual(restored[0]["expectedKids"], 12)


if __name__ == "__main__":
    unittest.main()
