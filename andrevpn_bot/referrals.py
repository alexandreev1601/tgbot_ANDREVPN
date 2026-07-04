from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from sqlite3 import IntegrityError

from .config import Plan
from .db import Database, Payment, ReferralReward, User


TRIAL_REWARD_DAYS = 3
PAYMENT_REWARD_DAYS_BY_PLAN_DAYS = {
    30: 7,
    60: 14,
    90: 21,
}

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReferralGrant:
    reward: ReferralReward
    referrer: User


class ReferralService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def ensure_referral_code(self, user: User) -> User:
        if user.referral_code:
            return user

        for _ in range(20):
            code = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8]
            if not code:
                continue
            try:
                return self.db.save_referral_code(user.telegram_id, code)
            except IntegrityError:
                logger.info("Referral code collision while creating code for user %s", user.telegram_id)

        raise RuntimeError("Could not generate unique referral code")

    def referral_link(self, user: User, bot_username: str) -> str:
        user = self.ensure_referral_code(user)
        return f"https://t.me/{bot_username}?start=ref_{user.referral_code}"

    def bind_from_start_argument(self, user: User, start_argument: str | None, *, is_new_user: bool) -> bool:
        if not is_new_user or not start_argument or not start_argument.startswith("ref_"):
            return False

        referral_code = start_argument.removeprefix("ref_").strip()
        if not referral_code:
            return False

        referrer = self.db.get_user_by_referral_code(referral_code)
        if referrer is None or referrer.telegram_id == user.telegram_id:
            return False

        bound = self.db.set_referrer_once(user.telegram_id, referrer.telegram_id)
        if bound:
            logger.info("User %s was referred by %s", user.telegram_id, referrer.telegram_id)
        return bound

    def stats(self, user: User) -> dict[str, int]:
        return self.db.referral_stats(user.telegram_id)

    def grant_trial_reward(self, referred_user: User) -> ReferralGrant | None:
        if referred_user.referred_by is None:
            return None

        reward = self.db.create_referral_reward(
            referrer_id=referred_user.referred_by,
            referred_user_id=referred_user.telegram_id,
            event_type="trial_started",
            idempotency_key=f"trial:{referred_user.referred_by}:{referred_user.telegram_id}",
            reward_days=TRIAL_REWARD_DAYS,
        )
        if reward is None:
            return None

        referrer = self.db.extend_subscription(referred_user.referred_by, TRIAL_REWARD_DAYS)
        logger.info(
            "Granted referral trial reward: referrer=%s referred=%s days=%s",
            referrer.telegram_id,
            referred_user.telegram_id,
            TRIAL_REWARD_DAYS,
        )
        return ReferralGrant(reward=reward, referrer=referrer)

    def grant_payment_reward(self, referred_user: User, payment: Payment, plan: Plan) -> ReferralGrant | None:
        if referred_user.referred_by is None:
            return None

        reward_days = _payment_reward_days(plan)
        if reward_days <= 0:
            return None

        reward = self.db.create_referral_reward(
            referrer_id=referred_user.referred_by,
            referred_user_id=referred_user.telegram_id,
            event_type="payment_succeeded",
            idempotency_key=f"payment:{payment.id}",
            payment_id=payment.id,
            reward_days=reward_days,
        )
        if reward is None:
            return None

        referrer = self.db.extend_subscription(referred_user.referred_by, reward_days)
        logger.info(
            "Granted referral payment reward: referrer=%s referred=%s payment=%s days=%s",
            referrer.telegram_id,
            referred_user.telegram_id,
            payment.id,
            reward_days,
        )
        return ReferralGrant(reward=reward, referrer=referrer)


def _payment_reward_days(plan: Plan) -> int:
    if plan.days in PAYMENT_REWARD_DAYS_BY_PLAN_DAYS:
        return PAYMENT_REWARD_DAYS_BY_PLAN_DAYS[plan.days]
    if plan.days >= 90:
        return 21
    if plan.days >= 60:
        return 14
    if plan.days >= 30:
        return 7
    return 0
