"""Проверка разбора списков детей: python -m unittest discover tests"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kids_lists import class_key, count_kids, find_lists, merge_snapshots  # noqa: E402

CHAT = """Мария Ивановна
6Б

1.Грузинов Владислав
2.Леонтьев Артём
3.Бойко Богдан
12:40
Ольга Петровна
5 Б
1) Иванов Иван
2) Петров Пётр
12:41
Спасибо, получили!
12:45
Ольга Петровна
5-б класс
1. Иванов Иван
2. Петров Пётр
3. Сидорова Анна
13:02
"""


class ClassKey(unittest.TestCase):
    def test_variants(self):
        for s in ("5б", "5 Б", "5-Б", "5 «Б»", '5"Б"', "5Б класс", "5 б кл."):
            self.assertEqual(class_key(s), "5б", s)
        self.assertEqual(class_key("10А"), "10а")
        self.assertEqual(class_key("5B"), "5в")  # латинская B = русская В
        self.assertEqual(class_key("гр.11"), "11")
        self.assertEqual(class_key("11 группа"), "11")

    def test_not_class(self):
        for s in ("Спасибо", "12:40", "Иванов Иван", "", "2024"):
            self.assertEqual(class_key(s), "", s)


class FindLists(unittest.TestCase):
    def test_lists(self):
        found = find_lists(CHAT)
        self.assertEqual([k for k, _ in found], ["6б", "5б", "5б"])
        self.assertEqual(found[0][1].split("\n")[0], "6Б")
        self.assertEqual(count_kids(found[0][1]), 3)
        self.assertNotIn("12:40", found[0][1])
        self.assertNotIn("Ольга", found[0][1])

    def test_latest_wins(self):
        lists = merge_snapshots([CHAT])
        self.assertEqual(count_kids(lists["5б"]), 3)
        self.assertIn("Сидорова Анна", lists["5б"])

    def test_newer_snapshot_wins(self):
        newer = "5б\n1. Новый Список\n"
        older = "5б\n1. Старый Список\n2. Ещё Один\n"
        self.assertIn("Новый", merge_snapshots([newer, older])["5б"])

    def test_unnumbered(self):
        lists = merge_snapshots(["7а\nИванов Иван\nПетрова Мария\n10:00\nПривет всем, как дела?"])
        self.assertEqual(lists["7а"], "7а\nИванов Иван\nПетрова Мария")

    def test_short_surname_not_class(self):
        # «10.Ли» и «1.Ю» похожи на заголовки классов «10Л» / «1Ю», но это дети по порядку
        kids = ["Костин", "Мусаев", "Бахтина", "Долганин", "Хохлов", "Саранчин", "Гетманский",
                "Чичева", "Брндаренко", "Ли", "Брагин", "Лузгин", "Асатрян", "Самойленко"]
        text = "1б\n" + "\n".join(f"{n}.{k}" for n, k in enumerate(kids, 1)) + "\n12:58"
        found = find_lists(text)
        self.assertEqual(len(found), 1)
        self.assertEqual(count_kids(found[0][1]), 14)
        self.assertEqual(count_kids(find_lists("2а\n1.Ю\n2.Ким")[0][1]), 2)
        # а настоящий следующий класс после списка по-прежнему начинает новый список
        self.assertEqual([k for k, _ in find_lists("1б\n1.Ли\n2.Ким\n2а\n1.Петров")], ["1б", "2а"])

    def test_header_without_list_ignored(self):
        self.assertEqual(find_lists("Завтра снимаем 6Б\n6Б\nВо сколько?"), [])


if __name__ == "__main__":
    unittest.main()
