"""История таблиц: сохранение, журнал действий, «закончена ли работа»."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import history  # noqa: E402
import paths  # noqa: E402


def deal(name, sel=True):
    return {"id": name, "name": name, "sel": sel}


class History(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        history.FILE = Path(self.tmp.name) / "history.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_update_actions(self):
        hid = history.create({"file": "a.xlsx", "deals": [deal("1а")], "original": [deal("1а")]}, "Загружен файл")
        self.assertTrue(history.update(hid, {"prefix": "НГ", "deals": [deal("НГ 1а")]}))
        history.add_action(hid, "Создание сделок: готово 1 из 1")
        e = history.get(hid)
        self.assertEqual(e["prefix"], "НГ")
        self.assertEqual(e["deals"][0]["name"], "НГ 1а")
        self.assertEqual([a["text"] for a in e["actions"]], ["Загружен файл", "Создание сделок: готово 1 из 1"])
        self.assertFalse(history.update("нет", {}))

    def test_summary_states(self):
        deals = [deal("1а"), deal("1б"), deal("1в", sel=False)]  # 1в снята намеренно
        hid = history.create({"file": "a.xlsx", "deals": deals}, "x")
        state = lambda p: {h["id"]: h for h in history.listing(p)}[hid]  # noqa: E731
        self.assertEqual(state({})["state"], "new")
        s = state({"1а": {"status": "ok"}})
        self.assertEqual((s["state"], s["created"], s["pending"]), ("work", 1, 1))
        self.assertEqual(state({"1а": {"status": "ok"}, "1б": {"status": "partial"}})["state"], "work")
        self.assertEqual(state({"1а": {"status": "ok"}, "1б": {"status": "ok"}})["state"], "done")

    def test_refresh_deals(self):
        ds = history.refresh_deals([deal("1а"), deal("1б")], {"1а": {"status": "ok", "url": "u", "note": True}})
        self.assertEqual((ds[0]["done"], ds[0]["note"], ds[0]["sel"]), ("u", True, False))
        self.assertEqual((ds[1]["done"], ds[1]["sel"]), (None, True))

    def test_broken_file_kept_aside(self):
        history.FILE.write_text("{обрыв", encoding="utf-8")
        self.assertEqual(history.listing({}), [])
        self.assertTrue(Path(str(history.FILE) + ".bad").exists())
        history.create({"file": "b.xlsx", "deals": []}, "x")
        self.assertEqual(len(paths.read_json(history.FILE, [])), 1)

    def test_limit(self):
        for i in range(history.MAX_ENTRIES + 5):
            history.create({"file": f"{i}.xlsx", "deals": []}, "x")
        self.assertEqual(len(history.listing({})), history.MAX_ENTRIES)


if __name__ == "__main__":
    unittest.main()
