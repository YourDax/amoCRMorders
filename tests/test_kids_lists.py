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

    def test_header_without_list_ignored(self):
        self.assertEqual(find_lists("Завтра снимаем 6Б\n6Б\nВо сколько?"), [])


if __name__ == "__main__":
    unittest.main()
