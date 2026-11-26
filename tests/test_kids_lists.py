"""Проверка разбора списков детей: python -m unittest discover tests"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kids_lists import (class_key, collect_lists, count_kids, find_lists, full_list_keys,  # noqa: E402
                        merge_history, parse_message)

# сообщения из настоящей беседы (скриншоты пользователя)
MSG_1V = """1в
Белова Василиса (убрать невидимки)
Деньгин Роман
Вдовина Мирослава
Краснова Елена
Ярцева Ванесса
Рябова Стефания"""
MSG_3G = """3г
Захарченко Есения (убрать невидимки)
Кучиных Кирилл
Беспалова Анна (убрать невидимки)"""
MSG_3A = """3А
Идут на фотосессию :
1. Соломин Толя
2. Герасимова Вика (убрать невидимку)
3. Фомичева Марьяна (убрать невидимки)
4. Измайлова Маша (убрать невидимки)
5. Фарафонов Ваня
6. Елесина Серафима
7. Сима Козлова
8. Каргин Ваня
9. Чуреева Алиса
10. Шилина Настя
11. Белобородова Варя
12. Яковлев Андрей
13. Шмакова Милослава
14. Козлова Серафима"""
MSG_3B = """3б
Шустрова (убрать невидимки)
  Аванесян (убрать невидимки)
  Елесин
  Липилов
  Плескачевская (убрать невидимки)
  Михеев
  Крючков
  Балдохина
  Олишевская"""
MSG_1B = "1б\n" + "\n".join(f"{n}.{k}" for n, k in enumerate(
    ["Костин", "Мусаев", "Бахтина", "Долганин", "Хохлов", "Саранчин", "Гетманский", "Чичева",
     "Брндаренко", "Ли", "Брагин", "Лузгин", "Асатрян", "Самойленко"], 1))


class ClassKey(unittest.TestCase):
    def test_variants(self):
        for s in ("5б", "5 Б", "5-Б", "5 «Б»", '5"Б"', "5Б класс", "5 б кл.", "Список 5Б:"):
            self.assertEqual(class_key(s), "5б", s)
        self.assertEqual(class_key("10А"), "10а")
        self.assertEqual(class_key("5B"), "5в")  # латинская B = русская В
        self.assertEqual(class_key("гр.11"), "11")
        self.assertEqual(class_key("11 группа"), "11")

    def test_numbered_classes(self):
        expected = {r"1м\1": "1м1", "1М/1": "1м1", "1 М1": "1м1",
                    "2м2": "2м2", "2м1": "2м1"}
        for raw, key in expected.items():
            self.assertEqual(class_key(raw), key, raw)
        self.assertEqual(class_key("1/2"), "")

    def test_not_class(self):
        for s in ("Спасибо", "12:40", "Иванов Иван", "", "2024"):
            self.assertEqual(class_key(s), "", s)


class Messages(unittest.TestCase):
    def test_real_full_lists(self):
        for msg, key, kids in ((MSG_1V, "1в", 6), (MSG_3G, "3г", 3), (MSG_3B, "3б", 9), (MSG_1B, "1б", 14)):
            found = parse_message(msg)
            self.assertEqual([(k, full) for k, _, full in found], [(key, True)], msg)
            self.assertEqual(count_kids(found[0][1]), kids, msg)
        body = parse_message(MSG_3A)[0][1]
        self.assertIn("Идут на фотосессию", body)  # лишнее не страшно
        self.assertIn("14. Козлова Серафима", body)
        self.assertEqual(count_kids(body), 14)
        self.assertIn("Шустрова (убрать невидимки)", parse_message(MSG_3B)[0][1])

    def test_inline(self):
        self.assertEqual(count_kids("София\n4в Сизинцева София"), 1)
        self.assertEqual(count_kids("3в Антонов и Антонова 6а"), 2)
        self.assertEqual(parse_message("3в Антонов и Антонова 6а"), [("3в", "3в Антонов и Антонова 6а", False)])
        self.assertEqual(parse_message("София\n4в Сизинцева София"),
                         [("4в", "София\n4в Сизинцева София", False)])
        self.assertEqual(parse_message("Завтра в 10:00, не опаздывайте"), [])
        self.assertEqual(parse_message("12 детей придут"), [])

    def test_numbered_classes_in_full_and_short_messages(self):
        first = r"1М/1" + "\n1. Орлова Анна"
        second = "Фотосессия 2 М2:\n1. Петрова Вера"
        third = "2м1 Иванова Мария"
        fourth = r"1м\1" + "\n1. Смирнова Ирина"
        need = {"1м1", "2м2", "2м1"}

        lists = collect_lists([first, second, third, fourth], need)
        self.assertEqual(lists["2м2"], second)
        self.assertEqual(lists["2м1"], third)
        self.assertIn("Орлова Анна", lists["1м1"])
        self.assertIn("Смирнова Ирина", lists["1м1"])
        self.assertEqual({key: count_kids(body) for key, body in lists.items()},
                         {"1м1": 2, "2м2": 1, "2м1": 1})
        self.assertEqual(full_list_keys([first, second, third], need), {"1м1", "2м2"})

    def test_two_classes_in_one_message(self):
        self.assertEqual([k for k, _ in find_lists("1б\n1.Ли\n2.Ким\n2а\n1.Петров")], ["1б", "2а"])

    def test_separate_class_messages_with_lowercase_given_names(self):
        first = "1г:\nИванова анна\nПетров иван\nСидорова мария"
        second = "1н:\nОрлова елена \nКим мирослав\nВолкова настя"
        comments = "1а:\nНа фотосессию\nВремя уточним\nСнимаются завтра"
        need = {"1г", "1н", "1а"}

        messages = [first, second, comments, "1г Пришлите фото"]
        self.assertEqual(full_list_keys(messages, need), {"1г", "1н"})
        self.assertEqual(collect_lists(messages, need),
                         {"1г": first, "1н": second.replace("елена ", "елена")})
        self.assertEqual(count_kids(first, need), 3)
        self.assertEqual(count_kids(second, need), 3)
        self.assertEqual(count_kids(comments, need), 0)

    def test_class_header_with_count(self):
        msg = "2к, 3 чел:\nПервый Ребёнок\nВторой Ребёнок (невидимки)\nТретий Ребёнок"
        self.assertEqual(parse_message(msg), [("2к", msg, True)])
        self.assertEqual(count_kids(msg), 3)
        self.assertEqual(collect_lists([msg, "Третий Ребёнок добавился"]), {"2к": msg})

    def test_number_in_parentheses_is_count_not_class_suffix(self):
        message = "1 а (4)\n\nИванова Анна \nПетров Иван\nСидорова Мария\nОрлов Александр"
        roster = "1 а (4)\nИванова Анна\nПетров Иван\nСидорова Мария\nОрлов Александр"
        with_suffix = "1а4\nКузнецова Елена"
        need = {"1а", "1а4"}

        self.assertEqual(parse_message(message), [("1а", roster, True)])
        self.assertEqual(full_list_keys([message], need), {"1а"})
        self.assertEqual(collect_lists([message, with_suffix], need), {"1а": roster, "1а4": with_suffix})
        self.assertEqual(count_kids(roster, need), 4)

    def test_list_heading_and_surname_only_rows_in_one_or_several_messages(self):
        surnames = ["Иванова", "Петрова", "Орлов", "Сидоров", "Волкова", "Ким", "Попов", "Ли", "Смирнова", "Кузнецова"]
        rows = [f"{i}.{' ' if i % 2 == 0 else ''}{name}" for i, name in enumerate(surnames, 1)]
        for heading in ("Список 3А", "Список: 3 А", "📋 Список класса 3‑А:", "Список детей для 3А (10)"):
            full = "\n".join([heading, *rows])
            for messages in ([heading + "\n\n" + "\n".join(rows)], [heading, *rows],
                             ["\n".join([heading, *rows[:3]]), "\n".join(rows[3:7]), *rows[7:]]):
                with self.subTest(heading=heading, messages=len(messages)):
                    self.assertEqual(collect_lists(messages + ["1. Другая"], {"3а"}), {"3а": full})
                    self.assertEqual(full_list_keys(messages, {"3а"}), {"3а"})
                    self.assertEqual(count_kids(full), 10)

    def test_explicit_standalone_heading_and_unnumbered_surnames(self):
        rows = "Иванова\nПетрова\nОрлов"
        self.assertEqual(collect_lists(["Список 3А", rows, "Добрый день"], {"3а"}), {"3а": "Список 3А\n" + rows})
        self.assertEqual(collect_lists(["Список 3А", "Добрый день"], {"3а"}), {})

    def test_dash_numbering_does_not_turn_short_surname_into_a_new_class(self):
        roster = "1а\n1—Иванова Анна\n2—Ли Пётр\n3—Орлова Маша"
        self.assertEqual(collect_lists([roster], {"1а"}), {"1а": roster})
        self.assertEqual(count_kids(roster), 3)

    def test_attention_mark_and_unnamed_siblings(self):
        roster = "! 1-МА класс\n1. Иванова Анна +брат\n2. Петров Иван + брат (Возьму 2 комплекта)"
        self.assertEqual(collect_lists([roster], {"1ма"}), {"1ма": roster})
        self.assertEqual(full_list_keys([roster.replace("! 1-", "‼️ 1‑")], {"1ма"}), {"1ма"})
        self.assertEqual(count_kids(roster), 4)
        self.assertEqual(count_kids("1МА\n1. Иванова Анна + 2 комплекта"), 1)
        merged = collect_lists(["1МА\n1. Иванова Анна", roster], {"1ма"})["1ма"]
        self.assertEqual(count_kids(merged), 4)

    def test_counted_roster_with_comment(self):
        roster = (
            "1д (7чел) должно было быть 9, 2 заболели\nВремя 9:10\n"
            + "\n".join(f"{i}. Иванов Ребёнок" for i in range(1, 8))
        )
        self.assertEqual(parse_message(roster), [("1д", roster, True)])
        self.assertEqual(count_kids(collect_lists(["1д Старый Ребёнок", roster])["1д"]), 7)

    def test_middle_dot_heading_and_numbers_without_punctuation(self):
        heading = "· 1Д"
        rows = "\n".join(
            ["1 Ли Пётр"]
            + [f"{i} Иванов Ребёнок" for i in range(2, 9)]
            + ["9 Петров Георгий, Петров Давид (2Ж)"]
        )
        roster = f"{heading}\n{rows}"
        self.assertEqual(parse_message(roster), [("1д", roster, True)])
        self.assertEqual(collect_lists([heading, rows]), {"1д": roster})
        self.assertEqual(count_kids(roster), 10)

    def test_photo_project_and_session_headings(self):
        numbered = "Участники новогоднего фотопроекта от 2Д:\n" + "\n".join(
            f"{i}. Иванов Алексей" for i in range(1, 11)
        )
        unnumbered = "Зимняя фотосессия 5 И:\n" + "\n".join(
            ["Смирнова Анна"] * 11
        )
        messages = [numbered, "Доброе утро\n" + unnumbered]
        keys = {"2д", "5и"}

        self.assertEqual(collect_lists(messages, keys), {"2д": numbered, "5и": unnumbered})
        self.assertEqual(full_list_keys(messages, keys), keys)
        self.assertEqual(count_kids(numbered), 10)
        self.assertEqual(count_kids(unnumbered), 11)
        self.assertEqual(parse_message("Напоминаю про фотосессию 5 И:\nЗавтра утром"), [])

    def test_rosters_with_siblings(self):
        only_row = "8Б\n1. Иванов Михаил с братом Иванов Максим 5В"
        several_rows = (
            "3Г\n1. Петрова Арина\n2. Сидоров Валерий с сестрой Сидорова Вера 5В"
            "\n3. Смирнова Надежда\n4. Орлов Максим"
        )
        self.assertEqual(collect_lists([only_row, several_rows]), {"8б": only_row, "3г": several_rows})
        self.assertEqual(count_kids(only_row), 2)
        self.assertEqual(count_kids(several_rows), 5)

    def test_time_and_header_only(self):
        self.assertEqual(find_lists("6Б\n12:40"), [])
        self.assertEqual(count_kids(find_lists("6Б\nИванов\nред. 10:17")[0][1]), 1)


class Collect(unittest.TestCase):
    def test_class_lists_are_combined_and_inline_appended(self):
        msgs = ["5б\n1.Старый Список", "привет", "5 Б класс\n1) Новый Иван\n2) Новая Мария",
                "5б Петров Пётр", "4в Сизинцева София", "3в Антонов и Антонова 6а", MSG_1V]
        lists = collect_lists(msgs)
        self.assertEqual(lists["5б"], "5 Б класс\n1. Старый Список\n2. Новый Иван\n3. Новая Мария\n5б Петров Пётр")
        self.assertEqual(lists["4в"], "4в Сизинцева София")
        self.assertEqual(lists["1в"], MSG_1V)
        self.assertEqual(full_list_keys(msgs), {"5б", "1в"})

    def test_two_days_merge_without_duplicate_participants(self):
        first = "5Г\n1. Иванова\n2. Петров\nВасилий Сидоров отказался"
        second = "5 Г\n1. Орлов Артём\n2) петров"
        combined = collect_lists([first, second], {"5г"})["5г"]

        self.assertEqual(combined, "5 Г\n1. Иванова\n2. петров\n3. Орлов Артём\nВасилий Сидоров отказался")
        self.assertEqual(count_kids(combined), 3)
        self.assertEqual(count_kids(first), 2)

    def test_full_after_inline_replaces(self):
        self.assertEqual(collect_lists(["7а Иванов", "7а\nИванов\nПетров"])["7а"], "7а\nИванов\nПетров")

    def test_merge_history(self):
        h = merge_history([], ["c", "d", "e"])
        h = merge_history(h, ["a", "b", "c", "d"])  # прокрутка вверх, перекрытие «c d»
        self.assertEqual(h, ["a", "b", "c", "d", "e"])
        self.assertEqual(merge_history(h, ["a", "b"]), h)  # тот же экран — ничего нового
        self.assertEqual(merge_history(["x"], ["w"]), ["w", "x"])  # без перекрытия
        self.assertEqual(merge_history(h, ["b", "c"]), h)


class KindergartenLists(unittest.TestCase):
    def test_latest_full_list_replaces_older_group_list(self):
        older = "Мечтатели\n1. Орлова Анна"
        latest = "Мечтатели\n1. Иванова Мария"
        self.assertEqual(collect_lists([older, latest], {"мечтатели"}), {"мечтатели": latest})

    def test_bare_group_header_and_two_children_on_one_line(self):
        from kids_lists import group_key

        key = group_key("Мечтатели")
        rows = [f"{i}. Примерова Анна" for i in range(1, 12)]
        rows[8] = "9. Примерова Анна и Алиса"
        roster = "\n".join(["Мечтатели ", *rows])
        self.assertEqual(collect_lists([roster], {key}), {key: roster.replace("Мечтатели ", "Мечтатели")})
        self.assertEqual(full_list_keys([roster], {key}), {key})
        self.assertEqual(count_kids(roster, {key}), 12)
        self.assertEqual(collect_lists([roster]), {})

    def test_group_headings_split_combined_message_and_support_separate_lists(self):
        from kids_lists import group_key

        keys = {group_key("Мечтатели"), group_key("Искорки")}
        messages = ["· группа «Мечтатели» (1 чел.)\n1. Первая Анна\nГруппа «Солнышко»\n1. Чужая Вера",
                    "Искорки группа", "1. Вторая Яна"]
        lists = collect_lists(messages, keys)
        self.assertEqual(full_list_keys(messages, keys) & keys, keys)
        self.assertIn("Первая Анна", lists["мечтатели"])
        self.assertNotIn("Чужая Вера", lists["мечтатели"])
        self.assertEqual(lists["искорки"], "Искорки группа\n1. Вторая Яна")


class MaxChatSearch(unittest.TestCase):
    name = "1101-сп2 - Зима 2026"
    prefix = "1101-сп2"

    def setUp(self):
        from unittest.mock import Mock
        from max_chat import MaxChat

        self.chat = MaxChat(None, log=Mock())
        self.chat.page = Mock()
        self.chat.page.locator.return_value.locator.return_value.count.return_value = 0
        self.chat._open_tab_all = Mock()
        self.chat._search_chats = Mock()
        self.chat._sleep = Mock()
        self.chat._header_title = Mock(side_effect=["", self.name, self.name])
        self.results = self.chat.page.locator(".searchResultsList > *")
        self.chat.page.locator.reset_mock()

    def test_retries_by_prefix_but_opens_only_full_title(self):
        from unittest.mock import call

        self.chat._search_chats.side_effect = [[], [(0, "Архив " + self.name), (3, self.name)]]
        self.chat.open_chat(self.name)
        self.assertEqual(self.chat._search_chats.call_args_list, [call(self.name, self.name), call(self.prefix, self.name)])
        self.results.nth.assert_called_once_with(3)
        self.results.nth.return_value.click.assert_called_once()

    def test_rejects_similar_or_duplicate_titles_after_retry(self):
        for titles, error in (
            ([(0, "Архив " + self.name)], "не найден"),
            ([(0, self.name), (1, self.name)], "несколько чатов"),
        ):
            with self.subTest(titles=titles):
                self.chat._header_title.return_value = ""
                self.chat._header_title.side_effect = None
                self.chat._search_chats.side_effect = [[], titles]
                with self.assertRaisesRegex(RuntimeError, error):
                    self.chat.open_chat(self.name)
        self.results.nth.assert_not_called()

    def test_does_not_retry_when_full_search_succeeds(self):
        self.chat._search_chats.return_value = [(2, self.name)]
        self.chat.open_chat(self.name)
        self.chat._search_chats.assert_called_once_with(self.name, self.name)
        self.results.nth.assert_called_once_with(2)


class MaxChatReading(unittest.TestCase):
    def test_retries_incomplete_history_after_opening_chat(self):
        from unittest.mock import Mock
        from max_chat import MaxChat, _BUBBLES_JS, _SCROLLER_JS, _SCROLL_BOTTOM_JS, _SCROLL_UP_JS

        chat = MaxChat(None, log=Mock())
        chat.open = Mock()
        chat.open_chat = Mock(return_value=True)
        chat._sleep = Mock()
        chat.page = Mock()
        first = "1А\n1. Орлова Анна"
        delayed = "1Б\n1. Примеров Пётр\n2. Иванова Анна + Иванова Вера\nДругова Мария нет"
        snapshots = iter([[first]] * 6 + [[delayed, first]])
        scrollers = iter([False, True])
        scrolls = iter([{"before": 100, "after": 25, "height": 300}, None])

        def evaluate(script):
            if script == _BUBBLES_JS:
                return {"messages": next(snapshots), "hasReplies": False}
            if script == _SCROLLER_JS:
                return next(scrollers)
            if script == _SCROLL_BOTTOM_JS:
                return None
            if script == _SCROLL_UP_JS:
                return next(scrolls)
            self.fail(f"Unexpected script: {script}")

        chat.page.evaluate.side_effect = evaluate

        self.assertEqual(chat.read_lists("Чат", {"1а", "1б"}), {"1а": first, "1б": delayed})
        chat.open_chat.assert_called_once_with("Чат")

    def test_reads_second_list_on_older_screen_after_finding_class(self):
        from unittest.mock import Mock
        from max_chat import MaxChat, _BUBBLES_JS, _SCROLLER_JS, _SCROLL_BOTTOM_JS, _SCROLL_UP_JS

        chat = MaxChat(None, log=Mock())
        chat.open = Mock()
        chat.open_chat = Mock(return_value=False)
        chat._sleep = Mock()
        chat.page = Mock()
        older = "5Г\n1. Иванова\n2. Петров\nВасилий Сидоров отказался"
        newer = "5Г\n1. Орлов Артём"
        snapshots = iter([[newer]] * 5 + [[older, newer]])
        scrolls = iter([{"before": 100, "after": 25, "height": 300}, None])

        def evaluate(script):
            if script == _BUBBLES_JS:
                return {"messages": next(snapshots), "hasReplies": False}
            if script == _SCROLLER_JS:
                return True
            if script == _SCROLL_BOTTOM_JS:
                return None
            if script == _SCROLL_UP_JS:
                return next(scrolls)
            self.fail(f"Unexpected script: {script}")

        chat.page.evaluate.side_effect = evaluate
        body = chat.read_lists("Чат", {"5г"})["5г"]
        self.assertEqual(body, "5Г\n1. Иванова\n2. Петров\n3. Орлов Артём\nВасилий Сидоров отказался")
        self.assertEqual(count_kids(body), 3)

    def test_collects_delayed_tail_before_scrolling_to_older_messages(self):
        from unittest.mock import Mock
        from max_chat import MaxChat, _BUBBLES_JS, _SCROLLER_JS, _SCROLL_BOTTOM_JS, _SCROLL_UP_JS

        chat = MaxChat(None)
        chat.open = Mock()
        chat.open_chat = Mock(return_value=False)
        chat._sleep = Mock()
        chat.page = Mock()
        earlier = "4Г\n1. Орлова Анна"
        tail = [
            "6Б\n1.Иванова Анна\n2.Петрова София",
            "5а\n1.Кузнецова\n2.Смирнова\n3.Лебедев\n4.Орлова\n5.Попова",
            "5в\n1.Михайлова\n2.Алексеева\n3.Козлов",
        ]
        scrolls_to_bottom = 0
        scrolling_up = False

        def evaluate(script):
            nonlocal scrolls_to_bottom, scrolling_up
            if script == _BUBBLES_JS:
                messages = tail if scrolls_to_bottom >= 3 and not scrolling_up else [earlier]
                return {"messages": messages, "hasReplies": False}
            if script == _SCROLLER_JS:
                return True
            if script == _SCROLL_BOTTOM_JS:
                scrolls_to_bottom += 1
                return None
            if script == _SCROLL_UP_JS:
                scrolling_up = True
                return None
            self.fail(f"Unexpected script: {script}")

        chat.page.evaluate.side_effect = evaluate
        found = chat.read_lists("Чат", {"4г", "5а", "5в", "6б"})
        self.assertEqual({key: count_kids(body) for key, body in found.items()},
                         {"4г": 1, "5а": 5, "5в": 3, "6б": 2})

    def test_retries_even_if_chat_was_already_open(self):
        from unittest.mock import Mock
        from max_chat import MaxChat

        chat = MaxChat(None, log=Mock())
        chat.open = Mock()
        chat.open_chat = Mock(return_value=False)
        chat._sleep = Mock()
        chat._visible_messages = Mock(return_value=["6Б\n1. Орлова Анна"])
        chat._scan_history = Mock(side_effect=[([], False), (["6Б\n1. Орлова Анна"], False)])
        self.assertEqual(chat.read_lists("Чат", {"6б"}), {"6б": "6Б\n1. Орлова Анна"})
        self.assertEqual(chat._scan_history.call_count, 2)

    def test_journal_counts_unique_lists(self):
        from max_chat import MaxChat

        chat = MaxChat(None)
        chat.warnings = []
        roster = "1д (7чел) будет меньше\n1. Первый Ребёнок"
        addon = "1д Другой Ребёнок"
        self.assertEqual(chat._finish_lists([roster, roster, addon, addon], {"1д"}),
                         {"1д": f"{roster}\n{addon}"})
        self.assertEqual(len(chat.warnings), 1)
        self.assertIn("найдено несколько сообщений (2)", chat.warnings[0])
        self.assertIn("Объединили списки и дополнения", chat.warnings[0])

    def test_short_chat_without_scroller(self):
        from unittest.mock import Mock
        from max_chat import MaxChat, _BUBBLES_JS, _SCROLLER_JS

        chat = MaxChat(None)
        chat.open = Mock()
        chat.open_chat = Mock()
        chat.page = Mock()
        chat.page.evaluate.side_effect = {
            _BUBBLES_JS: {"messages": ["6 Ж\u200b\n1. Пример Ребёнок", "6ж Другой Ребёнок"], "hasReplies": True},
            _SCROLLER_JS: False,
        }.__getitem__
        self.assertEqual(chat.read_lists("Чат", {"6ж"})["6ж"], "6 Ж\u200b\n1. Пример Ребёнок\n6ж Другой Ребёнок")
        self.assertTrue(any("ответы на сообщения" in warning for warning in chat.warnings))
        self.assertTrue(any("6ж: найдено несколько сообщений (2)" in warning for warning in chat.warnings))



if __name__ == "__main__":
    unittest.main()
