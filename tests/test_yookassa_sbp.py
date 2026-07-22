from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import httpx

from andrevpn_bot.config import Plan
from andrevpn_bot.db import Database
from andrevpn_bot.handlers import _after_successful_external_payment
from andrevpn_bot.referrals import ReferralService
from andrevpn_bot.xui import XuiError
from andrevpn_bot.yookassa import YookassaClient, YookassaError, YookassaPaymentService, YookassaVerificationError


SBP_PLANS = [
    Plan(code="month", title="1 месяц", price=150, days=30),
    Plan(code="two_months", title="2 месяца", price=250, days=60),
    Plan(code="quarter", title="3 месяца", price=350, days=90),
]


def config():
    return SimpleNamespace(
        admin_ids={1738661194},
        yookassa_shop_id="shop",
        yookassa_secret_key="secret",
        yookassa_api_base_url="https://api.yookassa.ru/v3",
        yookassa_timeout_seconds=15,
        yookassa_return_url="https://panel-l.andreev-it.ru:8443/payments/yookassa/return",
        sbp_plans=SBP_PLANS,
        xui_total_gb=0,
        vpn_profiles=[],
    )


class FakeYookassaClient:
    def __init__(self) -> None:
        self.created_orders = []
        self.payments = {}
        self.fail_create = False

    async def create_sbp_payment(self, order, return_url: str, description: str):
        self.created_orders.append((order, return_url, description))
        if self.fail_create:
            raise YookassaError("HTTPStatusError")
        payment = provider_payment(order)
        self.payments[payment["id"]] = payment
        return payment

    async def get_payment(self, payment_id: str):
        return self.payments[payment_id]


def provider_payment(order, *, status="pending", paid=False, value=None, currency="RUB", method="sbp", metadata=None):
    return {
        "id": order.external_payment_id or f"yk-{order.id}",
        "status": status,
        "paid": paid,
        "amount": {"value": value or f"{order.amount_kopecks // 100}.00", "currency": currency},
        "payment_method": {"type": method},
        "confirmation": {"confirmation_url": f"https://yookassa.test/pay/{order.id}"},
        "metadata": metadata or {
            "local_order_id": str(order.id),
            "telegram_id": str(order.telegram_id),
            "plan_code": order.plan_code,
        },
    }


class YookassaSbpTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "test.sqlite3")
        self.db.init()
        self.config = config()
        self.client = FakeYookassaClient()
        self.service = YookassaPaymentService(self.config, self.db, self.client)
        self.referrals = ReferralService(self.db)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def user(self, telegram_id: int):
        user = self.db.upsert_user(telegram_id, f"user{telegram_id}", f"User {telegram_id}")
        return self.referrals.ensure_referral_code(user)

    async def create_order(self, telegram_id=1001, plan=SBP_PLANS[0]):
        user = self.user(telegram_id)
        return await self.service.create_sbp_payment(user, plan)

    async def test_create_sbp_payment_uses_exact_amount_sbp_redirect_and_metadata(self) -> None:
        order = await self.create_order()
        created_order, return_url, description = self.client.created_orders[0]
        raw = json.loads(self.db.get_payment_order(order.id).raw_response)

        self.assertEqual(created_order.amount_kopecks, 15000)
        self.assertEqual(return_url, self.config.yookassa_return_url)
        self.assertEqual(description, "ANDREVPN - 1 месяц")
        self.assertEqual(raw["amount"], {"value": "150.00", "currency": "RUB"})
        self.assertEqual(raw["payment_method"], {"type": "sbp"})
        self.assertEqual(raw["metadata"]["local_order_id"], str(order.id))
        self.assertEqual(raw["metadata"]["telegram_id"], str(order.telegram_id))
        self.assertEqual(raw["metadata"]["plan_code"], "month")

    async def test_yookassa_client_builds_expected_create_payment_request(self) -> None:
        captured = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["json"] = json.loads(request.content.decode())
            return httpx.Response(
                200,
                json={
                    "id": "yk-1",
                    "status": "pending",
                    "confirmation": {"confirmation_url": "https://yookassa.test/pay/1"},
                    "metadata": captured["json"]["metadata"],
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            yookassa_client = YookassaClient(
                shop_id="shop",
                secret_key="secret",
                api_base_url="https://api.yookassa.ru/v3",
                timeout_seconds=15,
                client=client,
            )
            order = self.db.create_or_reuse_payment_order(
                telegram_id=1001,
                plan_code="month",
                plan_days=30,
                amount_kopecks=15000,
                provider="yookassa_sbp",
            )
            await yookassa_client.create_sbp_payment(
                order,
                "https://panel-l.andreev-it.ru:8443/payments/yookassa/return",
                "ANDREVPN - 1 месяц",
            )

        body = captured["json"]
        self.assertEqual(captured["url"], "https://api.yookassa.ru/v3/payments")
        self.assertEqual(captured["headers"]["idempotence-key"], order.idempotency_key)
        self.assertEqual(body["amount"], {"value": "150.00", "currency": "RUB"})
        self.assertEqual(body["payment_method_data"], {"type": "sbp"})
        self.assertEqual(body["confirmation"]["type"], "redirect")
        self.assertTrue(body["capture"])
        self.assertEqual(body["description"], "ANDREVPN - 1 месяц")
        self.assertEqual(body["metadata"]["local_order_id"], str(order.id))

    async def test_idempotency_key_is_reused_for_same_pending_order(self) -> None:
        first = await self.create_order()
        second = await self.create_order()

        self.assertEqual(first.id, second.id)
        self.assertEqual(first.idempotency_key, second.idempotency_key)
        self.assertEqual(len(self.client.created_orders), 1)

    async def test_network_error_reuses_local_order_and_does_not_extend_subscription(self) -> None:
        user = self.user(1001)
        self.client.fail_create = True
        with self.assertRaises(YookassaError):
            await self.service.create_sbp_payment(user, SBP_PLANS[0])
        failed_order = self.db.create_or_reuse_payment_order(
            telegram_id=user.telegram_id,
            plan_code="month",
            plan_days=30,
            amount_kopecks=15000,
            provider="yookassa_sbp",
        )

        self.client.fail_create = False
        order = await self.service.create_sbp_payment(user, SBP_PLANS[0])

        self.assertEqual(order.id, failed_order.id)
        self.assertIsNone(self.db.get_user(user.telegram_id).subscription_until)

    async def test_pending_and_canceled_do_not_extend_subscription(self) -> None:
        order = await self.create_order()
        self.client.payments[order.external_payment_id] = provider_payment(order, status="pending", paid=False)
        pending = await self.service.check_order(order.id)
        self.assertEqual(pending.status, "pending")
        self.assertIsNone(self.db.get_user(order.telegram_id).subscription_until)

        self.client.payments[order.external_payment_id] = provider_payment(order, status="canceled", paid=False)
        canceled = await self.service.check_order(order.id)
        self.assertEqual(canceled.status, "canceled")
        self.assertIsNone(self.db.get_user(order.telegram_id).subscription_until)

    async def test_succeeded_payment_extends_subscription_once_and_records_payment(self) -> None:
        order = await self.create_order()
        self.client.payments[order.external_payment_id] = provider_payment(order, status="succeeded", paid=True)

        first = await self.service.check_order(order.id)
        second = await self.service.check_order(order.id)

        self.assertEqual(first.status, "succeeded")
        self.assertFalse(first.finalization.already_processed)
        self.assertTrue(second.finalization.already_processed)
        self.assertTrue(self.db.get_user(order.telegram_id).is_active)
        self.assertEqual(self.db.stats()["payments_count"], 1)

    async def test_referral_reward_is_granted_once_for_repeated_webhook(self) -> None:
        referrer = self.user(1001)
        referred = self.user(2002)
        self.referrals.bind_from_start_argument(referred, f"ref_{referrer.referral_code}", is_new_user=True)
        order = await self.create_order(telegram_id=referred.telegram_id, plan=SBP_PLANS[2])
        self.client.payments[order.external_payment_id] = provider_payment(order, status="succeeded", paid=True)
        webhook = {"type": "notification", "event": "payment.succeeded", "object": {"id": order.external_payment_id}}

        await self.service.process_webhook(webhook)
        await self.service.process_webhook(webhook)

        stats = self.db.referral_stats(referrer.telegram_id)
        self.assertEqual(stats["payment_rewards"], 1)
        self.assertEqual(stats["reward_days"], 21)

    async def test_mismatches_block_subscription_delivery(self) -> None:
        checks = [
            {"value": "149.00"},
            {"currency": "USD"},
            {"method": "bank_card"},
            {"metadata_override": {"local_order_id": "999"}},
            {"metadata_override": {"telegram_id": "9999"}},
            {"metadata_override": {"plan_code": "quarter"}},
        ]
        for index, params in enumerate(checks):
            with self.subTest(params=params):
                db = Database(Path(self.tmpdir.name) / f"mismatch-{index}.sqlite3")
                db.init()
                service = YookassaPaymentService(self.config, db, FakeYookassaClient())
                user = db.upsert_user(1001, "user1001", "User 1001")
                order = await service.create_sbp_payment(user, SBP_PLANS[0])
                metadata = {
                    "local_order_id": str(order.id),
                    "telegram_id": str(order.telegram_id),
                    "plan_code": order.plan_code,
                }
                metadata.update(params.get("metadata_override", {}))
                service.client.payments[order.external_payment_id] = provider_payment(
                    order,
                    status="succeeded",
                    paid=True,
                    value=params.get("value"),
                    currency=params.get("currency", "RUB"),
                    method=params.get("method", "sbp"),
                    metadata=metadata,
                )
                with self.assertRaises(YookassaVerificationError):
                    await service.check_order(order.id)
                self.assertIsNone(db.get_user(order.telegram_id).subscription_until)

    async def test_webhook_without_successful_server_get_does_not_extend(self) -> None:
        order = await self.create_order()
        self.client.payments[order.external_payment_id] = provider_payment(order, status="pending", paid=False)
        webhook = {"type": "notification", "event": "payment.succeeded", "object": {"id": order.external_payment_id}}

        result = await self.service.process_webhook(webhook)

        self.assertEqual(result.status, "pending")
        self.assertIsNone(self.db.get_user(order.telegram_id).subscription_until)

    async def test_xui_error_after_successful_payment_does_not_rollback_subscription(self) -> None:
        class Bot:
            async def send_message(self, *args, **kwargs):
                return None

        class Xui:
            async def provision_user(self, *args, **kwargs):
                raise XuiError("xui down")

        order = await self.create_order()
        self.client.payments[order.external_payment_id] = provider_payment(order, status="succeeded", paid=True)
        result = await self.service.check_order(order.id)

        await _after_successful_external_payment(Bot(), self.config, self.db, Xui(), self.service, result.finalization)

        self.assertTrue(self.db.get_user(order.telegram_id).is_active)
        self.assertEqual(self.db.get_payment_order(order.id).status, "succeeded")

    def test_stats_do_not_mix_xtr_and_rub(self) -> None:
        user = self.user(1001)
        self.db.add_payment(
            telegram_id=user.telegram_id,
            plan_code="month",
            amount=80,
            currency="XTR",
            provider_payment_charge_id=None,
            telegram_payment_charge_id="stars-1",
            raw_payload="{}",
            provider="telegram_stars",
            external_payment_id="stars-1",
        )
        order = self.db.create_or_reuse_payment_order(
            telegram_id=user.telegram_id,
            plan_code="month",
            plan_days=30,
            amount_kopecks=15000,
            provider="yookassa_sbp",
        )
        self.db.attach_payment_order_provider_data(
            order_id=order.id,
            external_payment_id="yk-1",
            confirmation_url="https://pay",
            status="pending",
            raw_response="{}",
        )
        self.db.finalize_payment_order_success(order_id=order.id, external_payment_id="yk-1", raw_payload="{}")

        amounts = self.db.stats()["payments_by_currency"]
        self.assertEqual(amounts["XTR"], 80)
        self.assertEqual(amounts["RUB"], 15000)

    def test_migration_is_idempotent_and_keeps_users(self) -> None:
        self.user(1001)
        self.db.init()
        self.db.init()

        self.assertEqual(self.db.get_user(1001).telegram_id, 1001)


if __name__ == "__main__":
    unittest.main()
