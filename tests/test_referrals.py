from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from andrevpn_bot.config import Plan
from andrevpn_bot.db import Database
from andrevpn_bot.payments import PaidSubscriptionService
from andrevpn_bot.referrals import ReferralService


PLANS = [
    Plan(code="month", title="1 месяц", price=80, days=30),
    Plan(code="two_months", title="2 месяца", price=150, days=60),
    Plan(code="quarter", title="3 месяца", price=200, days=90),
]


class ReferralProgramTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.sqlite3")
        self.db.init()
        self.referrals = ReferralService(self.db)
        self.payments = PaidSubscriptionService(self.db, self.referrals)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def user(self, telegram_id: int):
        user = self.db.upsert_user(telegram_id, f"user{telegram_id}", f"User {telegram_id}")
        return self.referrals.ensure_referral_code(user)

    def bind_referred_user(self):
        referrer = self.user(1001)
        referred = self.user(2002)
        bound = self.referrals.bind_from_start_argument(
            referred,
            f"ref_{referrer.referral_code}",
            is_new_user=True,
        )
        return referrer, self.db.get_user(referred.telegram_id), bound

    def pay(self, user, plan: Plan, external_payment_id: str):
        return self.payments.confirm_payment_and_extend_subscription(
            user=user,
            plan=plan,
            amount=plan.price,
            currency="XTR",
            provider="telegram_stars",
            external_payment_id=external_payment_id,
            raw_payload="{}",
        )

    def test_referral_code_is_created_and_stable(self) -> None:
        user = self.user(1001)
        same_user = self.referrals.ensure_referral_code(self.db.get_user(1001))

        self.assertTrue(user.referral_code)
        self.assertEqual(user.referral_code, same_user.referral_code)

    def test_start_ref_binds_new_user_to_referrer(self) -> None:
        referrer, referred, bound = self.bind_referred_user()

        self.assertTrue(bound)
        self.assertEqual(referred.referred_by, referrer.telegram_id)
        self.assertIsNotNone(referred.referred_at)

    def test_self_referral_is_rejected(self) -> None:
        user = self.user(1001)
        bound = self.referrals.bind_from_start_argument(user, f"ref_{user.referral_code}", is_new_user=True)

        self.assertFalse(bound)
        self.assertIsNone(self.db.get_user(user.telegram_id).referred_by)

    def test_referrer_cannot_be_overwritten(self) -> None:
        first_referrer, referred, _ = self.bind_referred_user()
        second_referrer = self.user(3003)

        rebound = self.referrals.bind_from_start_argument(
            referred,
            f"ref_{second_referrer.referral_code}",
            is_new_user=True,
        )

        self.assertFalse(rebound)
        self.assertEqual(self.db.get_user(referred.telegram_id).referred_by, first_referrer.telegram_id)

    def test_existing_user_does_not_get_referrer_from_new_start_link(self) -> None:
        referrer = self.user(1001)
        existing_user = self.user(2002)

        bound = self.referrals.bind_from_start_argument(
            existing_user,
            f"ref_{referrer.referral_code}",
            is_new_user=False,
        )

        self.assertFalse(bound)
        self.assertIsNone(self.db.get_user(existing_user.telegram_id).referred_by)

    def test_trial_reward_adds_three_days_once(self) -> None:
        referrer, referred, _ = self.bind_referred_user()
        before = self.db.get_user(referrer.telegram_id).subscription_until

        first = self.referrals.grant_trial_reward(referred)
        second = self.referrals.grant_trial_reward(referred)
        after = self.db.get_user(referrer.telegram_id).subscription_until

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertIsNone(before)
        self.assertIsNotNone(after)
        self.assertGreaterEqual((after - first.reward.created_at).days, 2)
        self.assertEqual(self.db.referral_stats(referrer.telegram_id)["reward_days"], 3)

    def test_payment_one_month_adds_seven_days(self) -> None:
        referrer, referred, _ = self.bind_referred_user()

        result = self.pay(referred, PLANS[0], "stars-1")

        self.assertIsNotNone(result.referral_grant)
        self.assertEqual(result.referral_grant.reward.reward_days, 7)
        self.assertEqual(self.db.referral_stats(referrer.telegram_id)["reward_days"], 7)

    def test_payment_two_months_adds_fourteen_days(self) -> None:
        referrer, referred, _ = self.bind_referred_user()

        result = self.pay(referred, PLANS[1], "stars-2")

        self.assertIsNotNone(result.referral_grant)
        self.assertEqual(result.referral_grant.reward.reward_days, 14)
        self.assertEqual(self.db.referral_stats(referrer.telegram_id)["reward_days"], 14)

    def test_payment_three_months_adds_twenty_one_days(self) -> None:
        referrer, referred, _ = self.bind_referred_user()

        result = self.pay(referred, PLANS[2], "stars-3")

        self.assertIsNotNone(result.referral_grant)
        self.assertEqual(result.referral_grant.reward.reward_days, 21)
        self.assertEqual(self.db.referral_stats(referrer.telegram_id)["reward_days"], 21)

    def test_repeated_payment_event_is_idempotent(self) -> None:
        referrer, referred, _ = self.bind_referred_user()

        first = self.pay(referred, PLANS[0], "same-payment")
        second = self.pay(referred, PLANS[0], "same-payment")

        self.assertFalse(first.already_processed)
        self.assertTrue(second.already_processed)
        self.assertIsNone(second.referral_grant)
        self.assertEqual(self.db.referral_stats(referrer.telegram_id)["reward_days"], 7)

    def test_new_payment_from_same_referred_user_gets_new_bonus(self) -> None:
        referrer, referred, _ = self.bind_referred_user()

        self.pay(referred, PLANS[0], "payment-a")
        self.pay(self.db.get_user(referred.telegram_id), PLANS[0], "payment-b")

        self.assertEqual(self.db.referral_stats(referrer.telegram_id)["payment_rewards"], 2)
        self.assertEqual(self.db.referral_stats(referrer.telegram_id)["reward_days"], 14)

    def test_active_referrer_gets_days_added_to_current_expiration(self) -> None:
        referrer, referred, _ = self.bind_referred_user()
        active_referrer = self.db.extend_subscription(referrer.telegram_id, 30)

        self.referrals.grant_trial_reward(referred)
        updated_referrer = self.db.get_user(referrer.telegram_id)

        self.assertEqual((updated_referrer.subscription_until - active_referrer.subscription_until).days, 3)

    def test_expired_referrer_gets_days_from_now(self) -> None:
        referrer, referred, _ = self.bind_referred_user()

        self.referrals.grant_trial_reward(referred)
        updated_referrer = self.db.get_user(referrer.telegram_id)

        self.assertTrue(updated_referrer.is_active)
        self.assertEqual(self.db.referral_stats(referrer.telegram_id)["reward_days"], 3)


if __name__ == "__main__":
    unittest.main()
