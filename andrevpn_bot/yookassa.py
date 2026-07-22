from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from .config import Config, Plan
from .db import Database, PaymentFinalization, PaymentOrder, User
from .referrals import ReferralGrant


PROVIDER = "yookassa_sbp"


class YookassaError(RuntimeError):
    pass


class YookassaVerificationError(YookassaError):
    pass


@dataclass(frozen=True)
class YookassaPaymentCheck:
    order: PaymentOrder
    provider_payment: dict[str, Any] | None
    finalization: PaymentFinalization | None
    status: str


class YookassaClient:
    def __init__(
        self,
        *,
        shop_id: str,
        secret_key: str,
        api_base_url: str,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.shop_id = shop_id
        self.secret_key = secret_key
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client = client

    async def create_sbp_payment(self, order: PaymentOrder, return_url: str, description: str) -> dict[str, Any]:
        payload = {
            "amount": {"value": _kopecks_to_api_amount(order.amount_kopecks), "currency": order.currency},
            "payment_method_data": {"type": "sbp"},
            "confirmation": {"type": "redirect", "return_url": return_url},
            "capture": True,
            "description": description,
            "metadata": {
                "local_order_id": str(order.id),
                "telegram_id": str(order.telegram_id),
                "plan_code": order.plan_code,
            },
        }
        return await self._request(
            "POST",
            "/payments",
            headers={"Idempotence-Key": order.idempotency_key},
            json=payload,
        )

    async def get_payment(self, payment_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/payments/{payment_id}")

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        async def send(client: httpx.AsyncClient) -> httpx.Response:
            return await client.request(
                method,
                f"{self.api_base_url}{path}",
                auth=(self.shop_id, self.secret_key),
                timeout=self.timeout_seconds,
                **kwargs,
            )

        try:
            if self._client is not None:
                response = await send(self._client)
            else:
                async with httpx.AsyncClient() as client:
                    response = await send(client)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise YookassaError(f"YooKassa API request failed: {type(exc).__name__}") from exc

        if not isinstance(data, dict):
            raise YookassaError("YooKassa API returned invalid JSON")
        return data


class YookassaPaymentService:
    def __init__(self, config: Config, db: Database, client: YookassaClient | None = None) -> None:
        self.config = config
        self.db = db
        self.client = client or YookassaClient(
            shop_id=config.yookassa_shop_id,
            secret_key=config.yookassa_secret_key,
            api_base_url=config.yookassa_api_base_url,
            timeout_seconds=config.yookassa_timeout_seconds,
        )

    async def create_sbp_payment(self, user: User, plan: Plan) -> PaymentOrder:
        order = self.db.create_or_reuse_payment_order(
            telegram_id=user.telegram_id,
            plan_code=plan.code,
            plan_days=plan.days,
            amount_kopecks=plan.price * 100,
            currency="RUB",
            provider=PROVIDER,
        )
        if order.external_payment_id and order.confirmation_url:
            return order

        try:
            provider_payment = await self.client.create_sbp_payment(
                order,
                self.config.yookassa_return_url,
                f"ANDREVPN - {plan.title}",
            )
        except YookassaError as exc:
            self.db.update_payment_order_status(order.id, "created", last_error=str(exc))
            raise

        external_payment_id = _required_str(provider_payment, "id")
        confirmation = provider_payment.get("confirmation")
        if not isinstance(confirmation, dict):
            raise YookassaError("YooKassa response does not contain confirmation")
        confirmation_url = _required_str(confirmation, "confirmation_url")
        status = str(provider_payment.get("status") or "pending")
        return self.db.attach_payment_order_provider_data(
            order_id=order.id,
            external_payment_id=external_payment_id,
            confirmation_url=confirmation_url,
            status=status if status in {"pending", "succeeded", "canceled"} else "pending",
            raw_response=_safe_json(provider_payment),
            expires_at=_parse_iso(provider_payment.get("expires_at")),
        )

    async def check_order(self, order_id: int) -> YookassaPaymentCheck:
        order = self.db.get_payment_order(order_id)
        if not order.external_payment_id:
            return YookassaPaymentCheck(order=order, provider_payment=None, finalization=None, status=order.status)

        provider_payment = await self.client.get_payment(order.external_payment_id)
        return self._process_provider_payment(order, provider_payment)

    async def process_webhook(self, payload: dict[str, Any]) -> YookassaPaymentCheck:
        if payload.get("type") != "notification":
            raise YookassaVerificationError("Unsupported YooKassa webhook type")
        event = payload.get("event")
        if event not in {"payment.succeeded", "payment.canceled"}:
            raise YookassaVerificationError("Unsupported YooKassa webhook event")
        obj = payload.get("object")
        if not isinstance(obj, dict) or not obj.get("id"):
            raise YookassaVerificationError("YooKassa webhook has no payment id")

        payment_id = str(obj["id"])
        provider_payment = await self.client.get_payment(payment_id)
        if provider_payment.get("id") != payment_id:
            raise YookassaVerificationError("YooKassa payment id mismatch")

        order = self.db.get_payment_order_by_external_id(payment_id)
        if order is None:
            metadata = provider_payment.get("metadata")
            if not isinstance(metadata, dict) or not str(metadata.get("local_order_id", "")).isdigit():
                raise YookassaVerificationError("YooKassa payment does not match a local order")
            order = self.db.get_payment_order(int(metadata["local_order_id"]))
        return self._process_provider_payment(order, provider_payment)

    def _process_provider_payment(self, order: PaymentOrder, provider_payment: dict[str, Any]) -> YookassaPaymentCheck:
        status = str(provider_payment.get("status") or "")
        if status == "pending":
            updated_order = self.db.update_payment_order_status(order.id, "pending", raw_response=_safe_json(provider_payment))
            return YookassaPaymentCheck(order=updated_order, provider_payment=provider_payment, finalization=None, status="pending")
        if status == "canceled":
            updated_order = self.db.update_payment_order_status(order.id, "canceled", raw_response=_safe_json(provider_payment))
            return YookassaPaymentCheck(order=updated_order, provider_payment=provider_payment, finalization=None, status="canceled")
        if status != "succeeded":
            updated_order = self.db.update_payment_order_status(order.id, "failed", raw_response=_safe_json(provider_payment))
            return YookassaPaymentCheck(order=updated_order, provider_payment=provider_payment, finalization=None, status="failed")

        self._verify_succeeded_payment(order, provider_payment)
        finalization = self.db.finalize_payment_order_success(
            order_id=order.id,
            external_payment_id=str(provider_payment["id"]),
            raw_payload=_safe_json(provider_payment),
        )
        return YookassaPaymentCheck(
            order=finalization.order,
            provider_payment=provider_payment,
            finalization=finalization,
            status="succeeded",
        )

    def referral_grant(self, finalization: PaymentFinalization) -> ReferralGrant | None:
        if finalization.referral_reward is None or finalization.referrer is None:
            return None
        return ReferralGrant(reward=finalization.referral_reward, referrer=finalization.referrer)

    def _verify_succeeded_payment(self, order: PaymentOrder, payment: dict[str, Any]) -> None:
        if payment.get("id") != order.external_payment_id:
            raise YookassaVerificationError("Payment id does not match local order")
        if payment.get("status") != "succeeded" or payment.get("paid") is not True:
            raise YookassaVerificationError("Payment is not succeeded and paid")

        amount = payment.get("amount")
        if not isinstance(amount, dict):
            raise YookassaVerificationError("Payment amount is missing")
        if amount.get("currency") != order.currency:
            raise YookassaVerificationError("Payment currency mismatch")
        if _api_amount_to_kopecks(str(amount.get("value", ""))) != order.amount_kopecks:
            raise YookassaVerificationError("Payment amount mismatch")

        payment_method = payment.get("payment_method")
        if not isinstance(payment_method, dict) or payment_method.get("type") != "sbp":
            raise YookassaVerificationError("Payment method mismatch")

        metadata = payment.get("metadata")
        if not isinstance(metadata, dict):
            raise YookassaVerificationError("Payment metadata is missing")
        if str(metadata.get("local_order_id")) != str(order.id):
            raise YookassaVerificationError("Payment local order id mismatch")
        if str(metadata.get("telegram_id")) != str(order.telegram_id):
            raise YookassaVerificationError("Payment telegram id mismatch")
        if metadata.get("plan_code") != order.plan_code:
            raise YookassaVerificationError("Payment plan code mismatch")

        plan = _find_plan(self.config.sbp_plans, order.plan_code)
        if plan.days != order.plan_days or plan.price * 100 != order.amount_kopecks:
            raise YookassaVerificationError("Local SBP tariff mismatch")


def _find_plan(plans: list[Plan], code: str) -> Plan:
    for plan in plans:
        if plan.code == code:
            return plan
    raise YookassaVerificationError("Unknown local SBP tariff")


def _kopecks_to_api_amount(amount_kopecks: int) -> str:
    rubles = Decimal(amount_kopecks) / Decimal(100)
    return f"{rubles:.2f}"


def _api_amount_to_kopecks(value: str) -> int:
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise YookassaVerificationError("Invalid payment amount") from exc
    return int(amount * 100)


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise YookassaError(f"YooKassa response field {key} is missing")
    return value


def _parse_iso(value: object):
    if not isinstance(value, str) or not value:
        return None
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _safe_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
