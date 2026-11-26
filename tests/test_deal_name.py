"""Название сделки: класс без пробела и со строчной буквой («6 Ж» → «6ж»)."""

import io
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from excel_reader import KINDERGARTEN, SCHOOL, deal_name, norm_class, progress_key  # noqa: E402


class DealName(unittest.TestCase):
    def test_norm_class(self):
        for raw, want in [("6 ж", "6ж"), ("6 Ж", "6ж"), ("3Б", "3б"), ("2а", "2а"), (" 11  А ", "11а"),
                          ("10 ИТ", "10ит"), ("11 мат", "11 мат"), ("Солнышко", "Солнышко"), ("5", "5")]:
            self.assertEqual(norm_class(raw), want, raw)

    def test_deal_name(self):
        self.assertEqual(deal_name("6 Ж", "Под_18-сп1", SCHOOL), "6ж Под_18-сп1")
        self.assertEqual(deal_name("гр. 4 А", "1368-до4", KINDERGARTEN), "гр.4а 1368-до4")
        self.assertEqual(deal_name("6 Ж", "Под_18-сп1", SCHOOL, normalize=False), "6 Ж Под_18-сп1")


    def test_progress_reuses_saved_numbered_class_in_the_same_pipeline(self):
        old_key = json.dumps(["школа", r"1м\1 лицей"], ensure_ascii=False)
        progress = {old_key: {"status": "ok"}}
        self.assertEqual(progress_key(progress, "1М/1 Лицей", "Школа"), old_key)
        self.assertNotEqual(progress_key(progress, "1М/1 Лицей", "Другая"), old_key)
        self.assertNotEqual(progress_key(progress, "1м2 Лицей", "Школа"), old_key)


class ImportProgress(unittest.TestCase):
    def test_import_matches_numbered_classes_with_max_keys(self):
        import openpyxl

        import app
        import history

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(app, "PROGRESS", root / "progress.json"), \
                    patch.object(app, "UPLOADS", root / "uploads"), \
                    patch.object(app, "S", app.State()), \
                    patch.object(history, "FILE", root / "history.json"):
                workbook = openpyxl.Workbook()
                sheet = workbook.active
                sheet.append(["Школа: Лицей"])
                sheet.append(["Класс", "ФИО КР", "Телефон КР"])
                for klass in (r"1м\1", "2м2", "2м1"):
                    sheet.append([klass, "Иванова Анна", "+79990000001"])
                data = io.BytesIO()
                workbook.save(data)
                data.seek(0)
                response = app.app.test_client().post("/api/parse", data={"file": (data, "a.xlsx")})
                self.assertEqual(response.status_code, 200)
                deals = response.get_json()["deals"]
                self.assertEqual([d["klass"] for d in deals], [r"1м\1", "2м2", "2м1"])
                self.assertEqual([app.roster_key(d) for d in deals], ["1м1", "2м2", "2м1"])

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
        saved = client.post("/api/history/" + first["historyId"], json={"prefix": "НГ", "tagFromPrefix": True})
        self.assertEqual(saved.status_code, 200)
        second = upload()
        self.assertEqual(second["prefixes"], ["НГ"])
        self.assertNotEqual(deals[0]["id"], second["deals"][0]["id"])
        self.assertTrue(all(d["sel"] and not d["done"] for d in second["deals"]))
        self.assertEqual(client.get("/api/status").get_json()["rows"], {})
        entry = client.get("/api/history/" + first["historyId"]).get_json()["entry"]
        self.assertEqual((entry["prefix"], entry["tagFromPrefix"]), ("НГ", True))
        restored = entry["deals"]
        self.assertEqual((restored[0]["done"], restored[0]["sel"], restored[0]["note"]), ("created", False, True))
        self.assertTrue(restored[1]["sel"])
        self.assertEqual(restored[0]["expectedKids"], 12)


if __name__ == "__main__":
    unittest.main()
