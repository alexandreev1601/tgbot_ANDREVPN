from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .config import Plan
from .db import Database, Payment, User
from .referrals import ReferralGrant, ReferralService


@dataclass(frozen=True)
class PaidSubscriptionResult:
    user: User
    payment: Payment
    referral_grant: ReferralGrant | None
    already_processed: bool = False


class PaidSubscriptionService:
    def __init__(self, db: Database, referrals: ReferralService | None = None) -> None:
        self.db = db
        self.referrals = referrals or ReferralService(db)

    def confirm_payment_and_extend_subscription(
        self,
        *,
        user: User,
        plan: Plan,
        amount: int,
        currency: str,
        provider: str,
        raw_payload: str,
        provider_payment_charge_id: str | None = None,
        telegram_payment_charge_id: str | None = None,
        external_payment_id: str | None = None,
        confirmed_by: int | None = None,
        admin_comment: str | None = None,
    ) -> PaidSubscriptionResult:
        existing_payment = self._find_existing_payment(provider, telegram_payment_charge_id, external_payment_id)
        if existing_payment is not None:
            return PaidSubscriptionResult(
                user=self.db.get_user(user.telegram_id),
                payment=existing_payment,
                referral_grant=None,
                already_processed=True,
            )

        updated_user = self.db.extend_subscription(user.telegram_id, plan.days)
        payment = self.db.add_payment(
            telegram_id=user.telegram_id,
            plan_code=plan.code,
            amount=amount,
            currency=currency,
            provider_payment_charge_id=provider_payment_charge_id,
            telegram_payment_charge_id=telegram_payment_charge_id,
            raw_payload=raw_payload,
            provider=provider,
            status="succeeded",
            external_payment_id=external_payment_id,
            confirmed_by=confirmed_by,
            confirmed_at=datetime.now(UTC) if confirmed_by is not None else None,
            admin_comment=admin_comment,
        )
        referral_grant = self.referrals.grant_payment_reward(updated_user, payment, plan)
        return PaidSubscriptionResult(user=updated_user, payment=payment, referral_grant=referral_grant)

    def _find_existing_payment(
        self,
        provider: str,
        telegram_payment_charge_id: str | None,
        external_payment_id: str | None,
    ) -> Payment | None:
        payment = self.db.get_payment_by_telegram_charge_id(telegram_payment_charge_id)
        if payment is not None:
            return payment
        return self.db.get_payment_by_external_id(provider, external_payment_id)
