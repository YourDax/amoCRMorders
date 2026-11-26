"""Логика run_deals со списками детей на подставном боте (без браузера)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: E402

read_kids_lists = app.read_kids_lists


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

    def test_kindergarten_opens_max_and_adds_notes_to_existing_deals(self):
        from unittest.mock import patch
        from kids_lists import collect_lists

        roster = "Мечтатели\n1. Примерова Анна и Алиса"
        other = "Искорки\n1. Другая Вера"
        rows = [{**item(1, "Мечтатели"), "kind": "kindergarten", "expectedKids": 2},
                {**item(2, "Искорки"), "kind": "kindergarten", "expectedKids": 1}]
        app.run_deals(FakeBot(), rows, False, "P")
        bot = FakeBot()
        with patch.object(app, "read_kids_lists", read_kids_lists), patch("max_chat.MaxChat") as max_chat:
            max_chat.return_value.warnings = []
            max_chat.return_value.read_lists.side_effect = lambda chat, need: collect_lists([roster, other], need)
            app.run_deals(bot, rows, False, "P", "Детский сад", notes_only=True)
            max_chat.return_value.read_lists.assert_called_once_with("Детский сад", {"мечтатели", "искорки"})
        self.assertEqual(bot.created, 0)
        self.assertEqual([text for _, text in bot.notes], [roster, other])
        self.assertIsNone(app.S.rows["r1"].get("countWarning"))
        self.assertIsNone(app.S.rows["r2"].get("countWarning"))

    def test_prefix_tag_is_added_before_first_save_only(self):
        from unittest.mock import Mock

        bot = FakeBot()
        calls = Mock()
        calls.save.side_effect = bot.save
        bot.save = calls.save
        bot.fill_deal_tag = calls.tag

        different_name = {**item(1, "5б"), "name": "Название изменили вручную"}
        app.run_deals(bot, [different_name], False, "P", tag="Новый год")
        app.run_deals(bot, [different_name], False, "P", tag="Новый год")
        app.run_deals(bot, [item(2, "6б")], False, "P")
        self.assertEqual([call[0] for call in calls.mock_calls], ["tag", "save", "save"])
        calls.tag.assert_called_once_with("Новый год")

    def test_same_name_in_two_imports_and_resume_first(self):
        first = {**item(1, "5б"), "id": "import-first-1"}
        second = {**first, "id": "import-second-1"}
        bot = FakeBot()
        app.run_deals(bot, [first], False, "P")
        app.run_deals(bot, [second], False, "P")
        app.run_deals(bot, [first], False, "P")
        self.assertEqual(bot.created, 2)
        self.assertEqual(app.S.rows[first["id"]]["url"], "https://x/leads/detail/1")
        self.assertEqual(app.S.rows[second["id"]]["url"], "https://x/leads/detail/2")

    def test_count_warning_does_not_stop_notes(self):
        bot = FakeBot()
        rows = [{**item(1, "5б"), "expectedKids": 2},
                {**item(2, "6б"), "expectedKids": 2},
                {**item(3, "7а"), "expectedKids": 3}]
        app.run_deals(bot, rows, False, "P", "Чат")
        self.assertEqual(bot.created, 3)
        self.assertEqual(len(bot.notes), 2)
        self.assertEqual(app.S.rows["r1"]["countWarning"], "В таблице 2, в MAX 1")
        self.assertIsNone(app.S.rows["r2"].get("countWarning"))
        self.assertEqual(app.S.rows["r3"]["countWarning"], "В таблице 3, в MAX 0")

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

    def test_stop_while_reading_max_unqueues_rows(self):
        def stopped(*_):
            raise RuntimeError("Остановлено пользователем")
        app.read_kids_lists = stopped
        items = [item(1, "5б"), item(2, "6б")]
        for it in items:
            app.S.set_row(it["id"], status="queued")
        with self.assertRaises(RuntimeError):
            app.run_deals(FakeBot(), items, False, "P", "Щ_10 - Зима 2026")
        app.clear_queued(items)  # так делает worker в finally
        self.assertIsNone(app.S.rows["r1"]["status"])

    def test_history_action_logged(self):
        import history
        history.FILE = Path(self.tmp.name) / "history.json"
        hid = history.create({"file": "a.xlsx", "deals": []}, "Загружен файл")
        app.run_deals(FakeBot(), [item(1, "5б"), item(2, "6б")], False, "P", "Щ_10 - Зима 2026")
        app.log_history({"history_id": hid, "pipeline": "P", "max_chat": "Щ_10"})
        self.assertEqual(history.get(hid)["actions"][-1]["text"],
                         "Создание сделок (P): готово 2 из 2, списков детей 2")


if __name__ == "__main__":
    unittest.main()
