from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class User:
    telegram_id: int
    username: str | None
    first_name: str | None
    subscription_until: datetime | None
    trial_used_at: datetime | None
    xui_email: str | None
    xui_uuid: str | None
    xui_sub_id: str | None
    xui_inbound_id: int | None
    referral_code: str | None
    referred_by: int | None
    referred_at: datetime | None

    @property
    def is_active(self) -> bool:
        return self.subscription_until is not None and self.subscription_until > datetime.now(UTC)


@dataclass(frozen=True)
class Payment:
    id: int
    telegram_id: int
    plan_code: str
    amount: int
    currency: str
    provider: str
    status: str
    provider_payment_charge_id: str | None
    telegram_payment_charge_id: str | None
    external_payment_id: str | None
    confirmed_by: int | None
    confirmed_at: datetime | None
    admin_comment: str | None
    created_at: datetime | None


@dataclass(frozen=True)
class ReferralReward:
    id: int
    referrer_id: int
    referred_user_id: int
    event_type: str
    idempotency_key: str
    reward_days: int
    payment_id: int | None
    created_at: datetime | None


@dataclass(frozen=True)
class PaymentOrder:
    id: int
    telegram_id: int
    plan_code: str
    plan_days: int
    amount_kopecks: int
    currency: str
    provider: str
    status: str
    idempotency_key: str
    external_payment_id: str | None
    confirmation_url: str | None
    created_at: datetime | None
    updated_at: datetime | None
    expires_at: datetime | None
    raw_response: str | None
    last_error: str | None


@dataclass(frozen=True)
class PaymentFinalization:
    user: User
    payment: Payment | None
    referral_reward: ReferralReward | None
    referrer: User | None
    order: PaymentOrder
    already_processed: bool = False


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    created_at TEXT NOT NULL,
                    subscription_until TEXT,
                    trial_used_at TEXT,
                    xui_email TEXT,
                    xui_uuid TEXT,
                    xui_sub_id TEXT,
                    xui_inbound_id INTEGER,
                    referral_code TEXT UNIQUE,
                    referred_by INTEGER,
                    referred_at TEXT
                );

                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    plan_code TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    provider_payment_charge_id TEXT,
                    telegram_payment_charge_id TEXT,
                    created_at TEXT NOT NULL,
                    raw_payload TEXT,
                    provider TEXT NOT NULL DEFAULT 'telegram_stars',
                    status TEXT NOT NULL DEFAULT 'succeeded',
                    external_payment_id TEXT,
                    confirmed_by INTEGER,
                    confirmed_at TEXT,
                    admin_comment TEXT
                );

                CREATE TABLE IF NOT EXISTS subscription_reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    reminder_key TEXT NOT NULL,
                    subscription_until TEXT NOT NULL,
                    sent_at TEXT NOT NULL,
                    UNIQUE (telegram_id, reminder_key, subscription_until)
                );

                CREATE TABLE IF NOT EXISTS referral_rewards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer_id INTEGER NOT NULL,
                    referred_user_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    idempotency_key TEXT,
                    payment_id INTEGER,
                    reward_days INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (referrer_id, referred_user_id, event_type, payment_id)
                );

                CREATE TABLE IF NOT EXISTS payment_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    plan_code TEXT NOT NULL,
                    plan_days INTEGER NOT NULL,
                    amount_kopecks INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    external_payment_id TEXT UNIQUE,
                    confirmation_url TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT,
                    raw_response TEXT,
                    last_error TEXT
                );

                CREATE TABLE IF NOT EXISTS traffic_resets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    inbound_id INTEGER NOT NULL,
                    reset_month TEXT NOT NULL,
                    reset_at TEXT NOT NULL,
                    UNIQUE (telegram_id, inbound_id, reset_month)
                );
                """
            )
            user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
            if "trial_used_at" not in user_columns:
                conn.execute("ALTER TABLE users ADD COLUMN trial_used_at TEXT")
            if "referral_code" not in user_columns:
                conn.execute("ALTER TABLE users ADD COLUMN referral_code TEXT")
            if "referred_by" not in user_columns:
                conn.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER")
            if "referred_at" not in user_columns:
                conn.execute("ALTER TABLE users ADD COLUMN referred_at TEXT")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code)")

            payment_columns = {row["name"] for row in conn.execute("PRAGMA table_info(payments)").fetchall()}
            if "provider" not in payment_columns:
                conn.execute("ALTER TABLE payments ADD COLUMN provider TEXT NOT NULL DEFAULT 'telegram_stars'")
            if "status" not in payment_columns:
                conn.execute("ALTER TABLE payments ADD COLUMN status TEXT NOT NULL DEFAULT 'succeeded'")
            if "external_payment_id" not in payment_columns:
                conn.execute("ALTER TABLE payments ADD COLUMN external_payment_id TEXT")
            if "confirmed_by" not in payment_columns:
                conn.execute("ALTER TABLE payments ADD COLUMN confirmed_by INTEGER")
            if "confirmed_at" not in payment_columns:
                conn.execute("ALTER TABLE payments ADD COLUMN confirmed_at TEXT")
            if "admin_comment" not in payment_columns:
                conn.execute("ALTER TABLE payments ADD COLUMN admin_comment TEXT")
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_telegram_charge
                ON payments(telegram_payment_charge_id)
                WHERE telegram_payment_charge_id IS NOT NULL AND telegram_payment_charge_id != ''
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_external_id
                ON payments(provider, external_payment_id)
                WHERE external_payment_id IS NOT NULL AND external_payment_id != ''
                """
            )

            reward_columns = {row["name"] for row in conn.execute("PRAGMA table_info(referral_rewards)").fetchall()}
            if "idempotency_key" not in reward_columns:
                conn.execute("ALTER TABLE referral_rewards ADD COLUMN idempotency_key TEXT")
                conn.execute(
                    """
                    UPDATE referral_rewards
                    SET idempotency_key = 'legacy:' || id
                    WHERE idempotency_key IS NULL
                    """
                )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_referral_rewards_idempotency_key
                ON referral_rewards(idempotency_key)
                WHERE idempotency_key IS NOT NULL AND idempotency_key != ''
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_payment_orders_user_plan_status
                ON payment_orders(telegram_id, plan_code, provider, status)
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_orders_external_id
                ON payment_orders(external_payment_id)
                WHERE external_payment_id IS NOT NULL AND external_payment_id != ''
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_traffic_resets_month
                ON traffic_resets(reset_month)
                """
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def upsert_user(self, telegram_id: int, username: str | None, first_name: str | None) -> User:
        now = _to_iso(datetime.now(UTC))
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO users (telegram_id, username, first_name, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name
                """,
                (telegram_id, username, first_name, now),
            )
        return self.get_user(telegram_id)

    def get_user(self, telegram_id: int) -> User:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        if row is None:
            raise LookupError(f"User {telegram_id} does not exist")
        return _user_from_row(row)

    def user_exists(self, telegram_id: int) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        return row is not None

    def get_or_create_user(self, telegram_id: int) -> User:
        if self.user_exists(telegram_id):
            return self.get_user(telegram_id)
        return self.upsert_user(telegram_id, None, None)

    def get_user_by_referral_code(self, referral_code: str) -> User | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE referral_code = ?", (referral_code,)).fetchone()
        return _user_from_row(row) if row is not None else None

    def save_referral_code(self, telegram_id: int, referral_code: str) -> User:
        with self.connect() as conn:
            conn.execute(
                "UPDATE users SET referral_code = ? WHERE telegram_id = ? AND referral_code IS NULL",
                (referral_code, telegram_id),
            )
        return self.get_user(telegram_id)

    def set_referrer_once(self, telegram_id: int, referrer_id: int) -> bool:
        if telegram_id == referrer_id:
            return False
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE users
                SET referred_by = ?, referred_at = ?
                WHERE telegram_id = ? AND referred_by IS NULL
                """,
                (referrer_id, _to_iso(datetime.now(UTC)), telegram_id),
            )
            return cursor.rowcount > 0

    def list_active_users(self) -> list[User]:
        now = _to_iso(datetime.now(UTC))
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM users
                WHERE subscription_until IS NOT NULL
                    AND subscription_until > ?
                ORDER BY subscription_until
                """,
                (now,),
            ).fetchall()
        return [_user_from_row(row) for row in rows]

    def stats(self) -> dict[str, int]:
        now = _to_iso(datetime.now(UTC))
        month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_users,
                    SUM(CASE WHEN subscription_until IS NOT NULL AND subscription_until > ? THEN 1 ELSE 0 END) AS active_users,
                    SUM(CASE WHEN subscription_until IS NOT NULL AND subscription_until <= ? THEN 1 ELSE 0 END) AS expired_users,
                    SUM(CASE WHEN trial_used_at IS NOT NULL THEN 1 ELSE 0 END) AS trial_users
                FROM users
                """,
                (now, now),
            ).fetchone()
            payments = conn.execute(
                """
                SELECT COUNT(*) AS payments_count
                FROM payments
                WHERE created_at >= ? AND status = 'succeeded'
                """,
                (_to_iso(month_start),),
            ).fetchone()
            payment_amounts = conn.execute(
                """
                SELECT
                    currency,
                    COALESCE(SUM(
                        CASE
                            WHEN currency = 'RUB' AND provider = 'manual_transfer' THEN amount * 100
                            ELSE amount
                        END
                    ), 0) AS amount
                FROM payments
                WHERE created_at >= ? AND status = 'succeeded'
                GROUP BY currency
                """,
                (_to_iso(month_start),),
            ).fetchall()
            referrals = conn.execute(
                """
                SELECT COUNT(*) AS rewards_count, COALESCE(SUM(reward_days), 0) AS reward_days
                FROM referral_rewards
                """
            ).fetchone()

        return {
            "total_users": int(row["total_users"] or 0),
            "active_users": int(row["active_users"] or 0),
            "expired_users": int(row["expired_users"] or 0),
            "trial_users": int(row["trial_users"] or 0),
            "payments_count": int(payments["payments_count"] or 0),
            "payments_by_currency": {str(item["currency"]): int(item["amount"] or 0) for item in payment_amounts},
            "referral_rewards_count": int(referrals["rewards_count"] or 0),
            "referral_reward_days": int(referrals["reward_days"] or 0),
        }

    def extend_subscription(self, telegram_id: int, days: int) -> User:
        user = self.get_user(telegram_id)
        now = datetime.now(UTC)
        current = user.subscription_until if user.subscription_until and user.subscription_until > now else now
        new_until = current + timedelta(days=days)
        with self.connect() as conn:
            conn.execute(
                "UPDATE users SET subscription_until = ? WHERE telegram_id = ?",
                (_to_iso(new_until), telegram_id),
            )
        return self.get_user(telegram_id)

    def activate_trial(self, telegram_id: int, days: int = 3) -> User:
        user = self.get_user(telegram_id)
        if user.trial_used_at is not None:
            raise TrialAlreadyUsedError
        if user.is_active:
            raise ActiveSubscriptionError

        now = datetime.now(UTC)
        new_until = now + timedelta(days=days)
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET subscription_until = ?, trial_used_at = ?
                WHERE telegram_id = ? AND trial_used_at IS NULL
                """,
                (_to_iso(new_until), _to_iso(now), telegram_id),
            )
        updated = self.get_user(telegram_id)
        if updated.trial_used_at is None:
            raise TrialAlreadyUsedError
        return updated

    def save_xui_client(self, telegram_id: int, email: str, uuid: str, sub_id: str, inbound_id: int) -> User:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET xui_email = ?, xui_uuid = ?, xui_sub_id = ?, xui_inbound_id = ?
                WHERE telegram_id = ?
                """,
                (email, uuid, sub_id, inbound_id, telegram_id),
            )
        return self.get_user(telegram_id)

    def add_payment(
        self,
        telegram_id: int,
        plan_code: str,
        amount: int,
        currency: str,
        provider_payment_charge_id: str | None,
        telegram_payment_charge_id: str | None,
        raw_payload: str,
        *,
        provider: str = "telegram_stars",
        status: str = "succeeded",
        external_payment_id: str | None = None,
        confirmed_by: int | None = None,
        confirmed_at: datetime | None = None,
        admin_comment: str | None = None,
    ) -> Payment:
        created_at = datetime.now(UTC)
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO payments (
                    telegram_id, plan_code, amount, currency,
                    provider_payment_charge_id, telegram_payment_charge_id,
                    created_at, raw_payload, provider, status, external_payment_id,
                    confirmed_by, confirmed_at, admin_comment
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    telegram_id,
                    plan_code,
                    amount,
                    currency,
                    provider_payment_charge_id,
                    telegram_payment_charge_id,
                    _to_iso(created_at),
                    raw_payload,
                    provider,
                    status,
                    external_payment_id,
                    confirmed_by,
                    _to_iso(confirmed_at or created_at) if confirmed_by is not None else (
                        _to_iso(confirmed_at) if confirmed_at is not None else None
                    ),
                    admin_comment,
                ),
            )
            payment_id = int(cursor.lastrowid)
        return self.get_payment(payment_id)

    def get_payment(self, payment_id: int) -> Payment:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        if row is None:
            raise LookupError(f"Payment {payment_id} does not exist")
        return _payment_from_row(row)

    def get_payment_by_telegram_charge_id(self, charge_id: str | None) -> Payment | None:
        if not charge_id:
            return None
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM payments WHERE telegram_payment_charge_id = ?",
                (charge_id,),
            ).fetchone()
        return _payment_from_row(row) if row is not None else None

    def get_payment_by_external_id(self, provider: str, external_payment_id: str | None) -> Payment | None:
        if not external_payment_id:
            return None
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM payments WHERE provider = ? AND external_payment_id = ?",
                (provider, external_payment_id),
            ).fetchone()
        return _payment_from_row(row) if row is not None else None

    def create_or_reuse_payment_order(
        self,
        *,
        telegram_id: int,
        plan_code: str,
        plan_days: int,
        amount_kopecks: int,
        currency: str = "RUB",
        provider: str = "yookassa_sbp",
    ) -> PaymentOrder:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM payment_orders
                WHERE telegram_id = ? AND plan_code = ? AND provider = ?
                    AND status IN ('created', 'pending')
                    AND plan_days = ? AND amount_kopecks = ? AND currency = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (telegram_id, plan_code, provider, plan_days, amount_kopecks, currency),
            ).fetchone()
            if row is not None:
                return _payment_order_from_row(row)

            now = _to_iso(datetime.now(UTC))
            cursor = conn.execute(
                """
                INSERT INTO payment_orders (
                    telegram_id, plan_code, plan_days, amount_kopecks, currency,
                    provider, status, idempotency_key, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'created', ?, ?, ?)
                """,
                (
                    telegram_id,
                    plan_code,
                    plan_days,
                    amount_kopecks,
                    currency,
                    provider,
                    str(uuid.uuid4()),
                    now,
                    now,
                ),
            )
            order_id = int(cursor.lastrowid)
        return self.get_payment_order(order_id)

    def get_payment_order(self, order_id: int) -> PaymentOrder:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM payment_orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            raise LookupError(f"Payment order {order_id} does not exist")
        return _payment_order_from_row(row)

    def get_payment_order_by_external_id(self, external_payment_id: str) -> PaymentOrder | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM payment_orders WHERE external_payment_id = ?",
                (external_payment_id,),
            ).fetchone()
        return _payment_order_from_row(row) if row is not None else None

    def attach_payment_order_provider_data(
        self,
        *,
        order_id: int,
        external_payment_id: str,
        confirmation_url: str | None,
        status: str,
        raw_response: str,
        expires_at: datetime | None = None,
    ) -> PaymentOrder:
        now = _to_iso(datetime.now(UTC))
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE payment_orders
                SET external_payment_id = ?, confirmation_url = ?, status = ?,
                    raw_response = ?, expires_at = ?, updated_at = ?, last_error = NULL
                WHERE id = ?
                """,
                (
                    external_payment_id,
                    confirmation_url,
                    status,
                    raw_response,
                    _to_iso(expires_at) if expires_at else None,
                    now,
                    order_id,
                ),
            )
        return self.get_payment_order(order_id)

    def update_payment_order_status(
        self,
        order_id: int,
        status: str,
        *,
        raw_response: str | None = None,
        last_error: str | None = None,
    ) -> PaymentOrder:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE payment_orders
                SET status = ?, raw_response = COALESCE(?, raw_response),
                    last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, raw_response, last_error, _to_iso(datetime.now(UTC)), order_id),
            )
        return self.get_payment_order(order_id)

    def finalize_payment_order_success(
        self,
        *,
        order_id: int,
        external_payment_id: str,
        raw_payload: str,
    ) -> PaymentFinalization:
        conn = sqlite3.connect(self.path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            order_row = conn.execute("SELECT * FROM payment_orders WHERE id = ?", (order_id,)).fetchone()
            if order_row is None:
                raise LookupError(f"Payment order {order_id} does not exist")
            order = _payment_order_from_row(order_row)

            if order.status == "succeeded":
                payment_row = conn.execute(
                    "SELECT * FROM payments WHERE provider = ? AND external_payment_id = ?",
                    (order.provider, order.external_payment_id or external_payment_id),
                ).fetchone()
                user_row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (order.telegram_id,)).fetchone()
                conn.execute("COMMIT")
                return PaymentFinalization(
                    user=_user_from_row(user_row),
                    payment=_payment_from_row(payment_row) if payment_row is not None else None,
                    referral_reward=None,
                    referrer=None,
                    order=order,
                    already_processed=True,
                )

            if order.status not in {"created", "pending"}:
                conn.execute("COMMIT")
                return PaymentFinalization(
                    user=self.get_user(order.telegram_id),
                    payment=None,
                    referral_reward=None,
                    referrer=None,
                    order=order,
                    already_processed=True,
                )

            existing_payment = conn.execute(
                "SELECT * FROM payments WHERE provider = ? AND external_payment_id = ?",
                (order.provider, external_payment_id),
            ).fetchone()
            if existing_payment is not None:
                conn.execute(
                    "UPDATE payment_orders SET status = 'succeeded', updated_at = ? WHERE id = ?",
                    (_to_iso(datetime.now(UTC)), order.id),
                )
                user_row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (order.telegram_id,)).fetchone()
                order_row = conn.execute("SELECT * FROM payment_orders WHERE id = ?", (order.id,)).fetchone()
                conn.execute("COMMIT")
                return PaymentFinalization(
                    user=_user_from_row(user_row),
                    payment=_payment_from_row(existing_payment),
                    referral_reward=None,
                    referrer=None,
                    order=_payment_order_from_row(order_row),
                    already_processed=True,
                )

            user_row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (order.telegram_id,)).fetchone()
            if user_row is None:
                raise LookupError(f"User {order.telegram_id} does not exist")

            now = datetime.now(UTC)
            current_until = _from_iso(user_row["subscription_until"])
            base_until = current_until if current_until and current_until > now else now
            new_until = base_until + timedelta(days=order.plan_days)
            conn.execute(
                "UPDATE users SET subscription_until = ? WHERE telegram_id = ?",
                (_to_iso(new_until), order.telegram_id),
            )

            cursor = conn.execute(
                """
                INSERT INTO payments (
                    telegram_id, plan_code, amount, currency,
                    provider_payment_charge_id, telegram_payment_charge_id,
                    created_at, raw_payload, provider, status, external_payment_id,
                    confirmed_by, confirmed_at, admin_comment
                )
                VALUES (?, ?, ?, ?, NULL, NULL, ?, ?, ?, 'succeeded', ?, NULL, ?, NULL)
                """,
                (
                    order.telegram_id,
                    order.plan_code,
                    order.amount_kopecks,
                    order.currency,
                    _to_iso(now),
                    raw_payload,
                    order.provider,
                    external_payment_id,
                    _to_iso(now),
                ),
            )
            payment_id = int(cursor.lastrowid)

            referral_reward = None
            referrer = None
            referred_by = user_row["referred_by"]
            reward_days = _payment_reward_days(order.plan_days)
            if referred_by is not None and reward_days:
                reward_cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO referral_rewards (
                        referrer_id, referred_user_id, event_type, idempotency_key,
                        payment_id, reward_days, created_at
                    )
                    VALUES (?, ?, 'payment_succeeded', ?, ?, ?, ?)
                    """,
                    (
                        referred_by,
                        order.telegram_id,
                        f"payment:{payment_id}",
                        payment_id,
                        reward_days,
                        _to_iso(now),
                    ),
                )
                if reward_cursor.rowcount:
                    reward_id = int(reward_cursor.lastrowid)
                    referrer_row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (referred_by,)).fetchone()
                    if referrer_row is not None:
                        referrer_until = _from_iso(referrer_row["subscription_until"])
                        referrer_base = referrer_until if referrer_until and referrer_until > now else now
                        referrer_new_until = referrer_base + timedelta(days=reward_days)
                        conn.execute(
                            "UPDATE users SET subscription_until = ? WHERE telegram_id = ?",
                            (_to_iso(referrer_new_until), referred_by),
                        )
                        reward_row = conn.execute("SELECT * FROM referral_rewards WHERE id = ?", (reward_id,)).fetchone()
                        referrer_row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (referred_by,)).fetchone()
                        referral_reward = _referral_reward_from_row(reward_row)
                        referrer = _user_from_row(referrer_row)

            conn.execute(
                """
                UPDATE payment_orders
                SET status = 'succeeded', external_payment_id = ?,
                    raw_response = ?, updated_at = ?, last_error = NULL
                WHERE id = ?
                """,
                (external_payment_id, raw_payload, _to_iso(now), order.id),
            )

            payment_row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
            user_row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (order.telegram_id,)).fetchone()
            order_row = conn.execute("SELECT * FROM payment_orders WHERE id = ?", (order.id,)).fetchone()
            conn.execute("COMMIT")
            return PaymentFinalization(
                user=_user_from_row(user_row),
                payment=_payment_from_row(payment_row),
                referral_reward=referral_reward,
                referrer=referrer,
                order=_payment_order_from_row(order_row),
                already_processed=False,
            )
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def create_referral_reward(
        self,
        *,
        referrer_id: int,
        referred_user_id: int,
        event_type: str,
        idempotency_key: str,
        reward_days: int,
        payment_id: int | None = None,
    ) -> ReferralReward | None:
        created_at = datetime.now(UTC)
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO referral_rewards (
                    referrer_id, referred_user_id, event_type, idempotency_key,
                    payment_id, reward_days, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    referrer_id,
                    referred_user_id,
                    event_type,
                    idempotency_key,
                    payment_id,
                    reward_days,
                    _to_iso(created_at),
                ),
            )
            if cursor.rowcount == 0:
                return None
            reward_id = int(cursor.lastrowid)
        return self.get_referral_reward(reward_id)

    def get_referral_reward(self, reward_id: int) -> ReferralReward:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM referral_rewards WHERE id = ?", (reward_id,)).fetchone()
        if row is None:
            raise LookupError(f"Referral reward {reward_id} does not exist")
        return _referral_reward_from_row(row)

    def referral_stats(self, telegram_id: int) -> dict[str, int]:
        with self.connect() as conn:
            invited = conn.execute(
                "SELECT COUNT(*) AS total FROM users WHERE referred_by = ?",
                (telegram_id,),
            ).fetchone()
            rewards = conn.execute(
                """
                SELECT
                    COUNT(*) AS rewards_count,
                    COALESCE(SUM(reward_days), 0) AS reward_days,
                    SUM(CASE WHEN event_type = 'trial_started' THEN 1 ELSE 0 END) AS trial_rewards,
                    SUM(CASE WHEN event_type = 'payment_succeeded' THEN 1 ELSE 0 END) AS payment_rewards
                FROM referral_rewards
                WHERE referrer_id = ?
                """,
                (telegram_id,),
            ).fetchone()
        return {
            "invited_users": int(invited["total"] or 0),
            "rewards_count": int(rewards["rewards_count"] or 0),
            "reward_days": int(rewards["reward_days"] or 0),
            "trial_rewards": int(rewards["trial_rewards"] or 0),
            "payment_rewards": int(rewards["payment_rewards"] or 0),
        }

    def reminder_was_sent(self, telegram_id: int, reminder_key: str, subscription_until: datetime) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM subscription_reminders
                WHERE telegram_id = ? AND reminder_key = ? AND subscription_until = ?
                """,
                (telegram_id, reminder_key, _to_iso(subscription_until)),
            ).fetchone()
        return row is not None

    def mark_reminder_sent(self, telegram_id: int, reminder_key: str, subscription_until: datetime) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO subscription_reminders (
                    telegram_id, reminder_key, subscription_until, sent_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    telegram_id,
                    reminder_key,
                    _to_iso(subscription_until),
                    _to_iso(datetime.now(UTC)),
                ),
            )

    def traffic_reset_was_done(self, telegram_id: int, inbound_id: int, reset_month: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM traffic_resets
                WHERE telegram_id = ? AND inbound_id = ? AND reset_month = ?
                """,
                (telegram_id, inbound_id, reset_month),
            ).fetchone()
        return row is not None

    def mark_traffic_reset_done(self, telegram_id: int, inbound_id: int, reset_month: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO traffic_resets (
                    telegram_id, inbound_id, reset_month, reset_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (telegram_id, inbound_id, reset_month, _to_iso(datetime.now(UTC))),
            )
            return cursor.rowcount > 0


def _user_from_row(row: sqlite3.Row) -> User:
    return User(
        telegram_id=row["telegram_id"],
        username=row["username"],
        first_name=row["first_name"],
        subscription_until=_from_iso(row["subscription_until"]),
        trial_used_at=_from_iso(row["trial_used_at"]),
        xui_email=row["xui_email"],
        xui_uuid=row["xui_uuid"],
        xui_sub_id=row["xui_sub_id"],
        xui_inbound_id=row["xui_inbound_id"],
        referral_code=row["referral_code"],
        referred_by=row["referred_by"],
        referred_at=_from_iso(row["referred_at"]),
    )


def _payment_from_row(row: sqlite3.Row) -> Payment:
    return Payment(
        id=row["id"],
        telegram_id=row["telegram_id"],
        plan_code=row["plan_code"],
        amount=row["amount"],
        currency=row["currency"],
        provider=row["provider"],
        status=row["status"],
        provider_payment_charge_id=row["provider_payment_charge_id"],
        telegram_payment_charge_id=row["telegram_payment_charge_id"],
        external_payment_id=row["external_payment_id"],
        confirmed_by=row["confirmed_by"],
        confirmed_at=_from_iso(row["confirmed_at"]),
        admin_comment=row["admin_comment"],
        created_at=_from_iso(row["created_at"]),
    )


def _referral_reward_from_row(row: sqlite3.Row) -> ReferralReward:
    return ReferralReward(
        id=row["id"],
        referrer_id=row["referrer_id"],
        referred_user_id=row["referred_user_id"],
        event_type=row["event_type"],
        idempotency_key=row["idempotency_key"],
        reward_days=row["reward_days"],
        payment_id=row["payment_id"],
        created_at=_from_iso(row["created_at"]),
    )


def _payment_order_from_row(row: sqlite3.Row) -> PaymentOrder:
    return PaymentOrder(
        id=row["id"],
        telegram_id=row["telegram_id"],
        plan_code=row["plan_code"],
        plan_days=row["plan_days"],
        amount_kopecks=row["amount_kopecks"],
        currency=row["currency"],
        provider=row["provider"],
        status=row["status"],
        idempotency_key=row["idempotency_key"],
        external_payment_id=row["external_payment_id"],
        confirmation_url=row["confirmation_url"],
        created_at=_from_iso(row["created_at"]),
        updated_at=_from_iso(row["updated_at"]),
        expires_at=_from_iso(row["expires_at"]),
        raw_response=row["raw_response"],
        last_error=row["last_error"],
    )


def _payment_reward_days(plan_days: int) -> int:
    if plan_days >= 90:
        return 21
    if plan_days >= 60:
        return 14
    if plan_days >= 30:
        return 7
    return 0


def _to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class TrialAlreadyUsedError(RuntimeError):
    pass


class ActiveSubscriptionError(RuntimeError):
    pass
