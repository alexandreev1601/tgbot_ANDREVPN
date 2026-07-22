from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from andrevpn_bot.config import Plan
from andrevpn_bot.db import Database
from andrevpn_bot.keyboards import (
    BTN_ADMIN,
    BTN_CONNECT,
    BTN_INSTRUCTIONS,
    BTN_PAY,
    BTN_PROFILE,
    BTN_REFERRALS,
    BTN_SUPPORT,
    COPY_TEXT_LIMIT,
    connection_menu,
    home_actions_menu,
    main_reply_keyboard,
    referrals_menu,
    sbp_plans_menu,
)
from andrevpn_bot.texts import home_card, profile_card


class TelegramUxTest(unittest.TestCase):
    def test_main_reply_keyboard_regular_user_has_expected_buttons(self) -> None:
        keyboard = main_reply_keyboard(is_admin=False)
        rows = [[button.text for button in row] for row in keyboard.keyboard]

        self.assertEqual(
            rows,
            [
                [BTN_PROFILE, BTN_PAY],
                [BTN_CONNECT, BTN_INSTRUCTIONS],
                [BTN_REFERRALS, BTN_SUPPORT],
            ],
        )
        self.assertNotIn(BTN_ADMIN, [button for row in rows for button in row])
        self.assertTrue(keyboard.resize_keyboard)
        self.assertTrue(keyboard.is_persistent)

    def test_main_reply_keyboard_admin_has_admin_button(self) -> None:
        keyboard = main_reply_keyboard(is_admin=True)
        rows = [[button.text for button in row] for row in keyboard.keyboard]

        self.assertEqual(rows[-1], [BTN_ADMIN])

    def test_home_actions_show_trial_only_when_available(self) -> None:
        inactive = _button_texts(home_actions_menu(is_active=False, trial_available=True))
        used_trial = _button_texts(home_actions_menu(is_active=False, trial_available=False))
        active = _button_texts(home_actions_menu(is_active=True, trial_available=False))

        self.assertIn("🎁 Попробовать 3 дня", inactive)
        self.assertNotIn("🎁 Попробовать 3 дня", used_trial)
        self.assertIn("🔗 Подключить VPN", active)
        self.assertIn("💳 Продлить", active)

    def test_profile_cards_for_active_inactive_and_expired_users(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "bot.sqlite3")
            db.init()
            inactive = db.upsert_user(1, None, None)
            active = db.extend_subscription(1, 2)
            expired = db.upsert_user(2, None, None)
            with db.connect() as conn:
                conn.execute(
                    "UPDATE users SET subscription_until = ? WHERE telegram_id = ?",
                    ((datetime.now(UTC) - timedelta(days=1)).isoformat(), expired.telegram_id),
                )
            expired = db.get_user(2)

        self.assertIn("🔴 Не активна", profile_card(inactive))
        self.assertIn("🟢 Активна", profile_card(active))
        self.assertIn("Осталось:", home_card(active, SimpleNamespace(brand_name="ANDREVPN")))
        self.assertIn("🔴 Закончилась", profile_card(expired))

    def test_sbp_plan_labels_are_derived_from_config_with_savings(self) -> None:
        plans = [
            Plan("m", "1 месяц", 150, 30),
            Plan("two", "2 месяца", 250, 60),
            Plan("q", "3 месяца", 350, 90),
        ]
        texts = _button_texts(sbp_plans_menu(plans))

        self.assertIn("1 месяц — 150 ₽", texts)
        self.assertIn("2 месяца — 250 ₽ · выгода 50 ₽", texts)
        self.assertIn("3 месяца — 350 ₽ · выгода 100 ₽", texts)

    def test_copy_button_uses_exact_link_and_long_link_falls_back(self) -> None:
        link = "https://panel-l.andreev-it.ru:2097/sub/abc"
        keyboard = connection_menu(link)
        copy_button = keyboard.inline_keyboard[0][0]

        self.assertEqual(copy_button.copy_text.text, link)

        long_link = "https://example.test/" + ("a" * COPY_TEXT_LIMIT)
        long_keyboard = connection_menu(long_link)
        self.assertTrue(all(button.copy_text is None for row in long_keyboard.inline_keyboard for button in row))

    def test_referral_share_url_is_encoded(self) -> None:
        referral_link = "https://t.me/test_bot?start=ref_a b"
        keyboard = referrals_menu(referral_link)
        share_button = next(button for row in keyboard.inline_keyboard for button in row if button.url and "share/url" in button.url)
        parsed = urlparse(share_button.url)
        query = parse_qs(parsed.query)

        self.assertEqual(query["url"], [referral_link])
        self.assertIn("ANDREVPN", query["text"][0])


def _button_texts(markup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


if __name__ == "__main__":
    unittest.main()
