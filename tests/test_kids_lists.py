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

    def test_two_classes_in_one_message(self):
        self.assertEqual([k for k, _ in find_lists("1б\n1.Ли\n2.Ким\n2а\n1.Петров")], ["1б", "2а"])

    def test_class_header_with_count(self):
        msg = "2к, 3 чел:\nПервый Ребёнок\nВторой Ребёнок (невидимки)\nТретий Ребёнок"
        self.assertEqual(parse_message(msg), [("2к", msg, True)])
        self.assertEqual(count_kids(msg), 3)
        self.assertEqual(collect_lists([msg, "Третий Ребёнок добавился"]), {"2к": msg})

    def test_counted_roster_with_comment(self):
        roster = (
            "1д (7чел) должно было быть 9, 2 заболели\nВремя 9:10\n"
            + "\n".join(f"{i}. Иванов Ребёнок" for i in range(1, 8))
        )
        self.assertEqual(parse_message(roster), [("1д", roster, True)])
        self.assertEqual(count_kids(collect_lists(["1д Старый Ребёнок", roster])["1д"]), 7)

    def test_time_and_header_only(self):
        self.assertEqual(find_lists("6Б\n12:40"), [])
        self.assertEqual(count_kids(find_lists("6Б\nИванов\nред. 10:17")[0][1]), 1)


class Collect(unittest.TestCase):
    def test_latest_full_wins_and_inline_appended(self):
        msgs = ["5б\n1.Старый Список", "привет", "5 Б класс\n1) Новый Иван\n2) Новая Мария",
                "5б Петров Пётр", "4в Сизинцева София", "3в Антонов и Антонова 6а", MSG_1V]
        lists = collect_lists(msgs)
        self.assertEqual(lists["5б"], "5 Б класс\n1) Новый Иван\n2) Новая Мария\n5б Петров Пётр")
        self.assertEqual(lists["4в"], "4в Сизинцева София")
        self.assertEqual(lists["1в"], MSG_1V)
        self.assertEqual(full_list_keys(msgs), {"5б", "1в"})

    def test_full_after_inline_replaces(self):
        self.assertEqual(collect_lists(["7а Иванов", "7а\nИванов\nПетров"])["7а"], "7а\nИванов\nПетров")

    def test_merge_history(self):
        h = merge_history([], ["c", "d", "e"])
        h = merge_history(h, ["a", "b", "c", "d"])  # прокрутка вверх, перекрытие «c d»
        self.assertEqual(h, ["a", "b", "c", "d", "e"])
        self.assertEqual(merge_history(h, ["a", "b"]), h)  # тот же экран — ничего нового
        self.assertEqual(merge_history(["x"], ["w"]), ["w", "x"])  # без перекрытия
        self.assertEqual(merge_history(h, ["b", "c"]), h)


class MaxChatReading(unittest.TestCase):
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
        self.assertIn("последний полный список", chat.warnings[0])

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
