"""Проверка тега после перехода в сохранённую карточку amoCRM."""

import unittest
from unittest.mock import Mock

from amo_bot import AmoBot


class ConfirmDealTagTests(unittest.TestCase):
    def setUp(self):
        self.bot = AmoBot("https://example.test")
        self.bot.page = Mock(url="https://example.test/leads/detail/42?after_add=yes")
        self.bot.open_deal = Mock()
        self.bot.fill_deal_tag = Mock()
        self.bot._save_and_wait = Mock()

    def test_api_confirmation_keeps_card_open(self):
        self.bot.page.evaluate.return_value = {"found": True}

        self.bot.confirm_deal_tag("НГ")

        self.bot.open_deal.assert_not_called()
        self.bot.fill_deal_tag.assert_not_called()

    def test_tag_visible_after_reopening_card_is_not_added_again(self):
        self.bot.page.evaluate.side_effect = [{"found": False}, {"found": True}]

        self.bot.confirm_deal_tag("НГ")

        self.bot.open_deal.assert_called_once_with("https://example.test/leads/detail/42")
        self.bot.fill_deal_tag.assert_not_called()
        self.bot._save_and_wait.assert_not_called()

    def test_missing_tag_can_still_be_added_to_saved_card(self):
        saved = False

        def save(*, new_deal):
            nonlocal saved
            self.assertFalse(new_deal)
            saved = True

        self.bot.page.evaluate.side_effect = lambda *_: {"found": saved}
        self.bot._save_and_wait.side_effect = save
        self.bot._wait_until = Mock(side_effect=lambda check, _: check())

        self.bot.confirm_deal_tag("НГ")

        self.bot.fill_deal_tag.assert_called_once_with("НГ")
        self.bot._save_and_wait.assert_called_once_with(new_deal=False)
