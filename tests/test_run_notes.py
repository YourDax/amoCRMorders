"""Логика run_deals со списками детей на подставном боте (без браузера)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: E402


class FakePage:
    url = "about:blank"


class FakeBot:
    closed = False
    ctx = None

    def __init__(self):
        self.page = FakePage()
        self.notes: list[tuple[str, str]] = []
        self.current = ""
        self.created = 0

    def open_new_deal(self, pipeline):
        self.page.url = "https://x/leads/add/"

    def fill_deal_name(self, name):
        self.current = name

    def fill_contact(self, c, company=""):
        pass

    def _pause(self, msg):
        pass

    def save(self):
        if "/leads/add" in self.page.url:
            self.created += 1
            self.page.url = f"https://x/leads/detail/{self.created}"

    def deal_url(self):
        return self.page.url

    def open_deal(self, url):
        self.page.url = url
        self.current = url

    def add_note(self, text):
        self.notes.append((self.current, text))

    def screenshot(self, name):
        return Path(name)


def item(i, klass):
    return {"id": f"r{i}", "name": f"{klass} Щ_10", "klass": klass,
            "contacts": [{"role": "КР", "name": "Иванова Анна", "phone": "+79990000000"}]}


LISTS = {"5б": "5Б\n1.Иванов Иван", "6б": "6Б\n1.Петров Пётр\n2.Сидоров Сидор"}


class RunNotes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app.PROGRESS = Path(self.tmp.name) / "progress.json"
        app.LOG_DIR = Path(self.tmp.name) / "logs"  # не писать в журнал программы
        self.calls = []
        app.read_kids_lists = lambda bot, chat, items: self.calls.append([i["klass"] for i in items]) or LISTS
        app.S.rows = {}

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_adds_notes(self):
        bot = FakeBot()
        app.run_deals(bot, [item(1, "5 Б"), item(2, "6б"), item(3, "7а")], False, "P", "Щ_10 - Зима 2026")
        self.assertEqual([t for _, t in bot.notes], [LISTS["5б"], LISTS["6б"]])
        self.assertEqual(app.S.rows["r1"]["note"], "ok")
        self.assertEqual(app.S.rows["r3"]["note"], "none")
        p = app.load_progress()
        self.assertTrue(p[app.progress_key(p,"5 Б Щ_10","P")]["note"])
        self.assertNotIn("note", p[app.progress_key(p,"7а Щ_10","P")])

        # повторный запуск: сделки не создаются, MAX читается только для 7а (у других список уже есть)
        bot2 = FakeBot()
        app.run_deals(bot2, [item(1, "5 Б"), item(2, "6б"), item(3, "7а")], False, "P", "Щ_10 - Зима 2026")
        self.assertEqual(bot2.created, 0)
        self.assertEqual(self.calls[-1], ["7а"])
        self.assertEqual(bot2.notes, [])  # для 7а в чате списка по-прежнему нет

    def test_without_chat_no_notes(self):
        bot = FakeBot()
        app.run_deals(bot, [item(1, "5б")], False, "P", "")
        self.assertEqual(bot.notes, [])
        self.assertEqual(self.calls, [])

    def test_notes_only_for_existing(self):
        bot = FakeBot()
        app.run_deals(bot, [item(1, "5б")], False, "P", "")  # создана без списка
        bot2 = FakeBot()
        app.run_deals(bot2, [item(1, "5б"), item(2, "6б")], False, "P", "Щ_10 - Зима 2026", notes_only=True)
        self.assertEqual(bot2.created, 0)
        self.assertEqual(bot2.notes, [("https://x/leads/detail/1", LISTS["5б"])])
        self.assertEqual(app.S.rows["r2"]["status"], "error")  # 6б ещё не создана


if __name__ == "__main__":
    unittest.main()
