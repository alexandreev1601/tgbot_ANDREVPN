from __future__ import annotations

import sqlite3
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
    xui_email: str | None
    xui_uuid: str | None
    xui_sub_id: str | None
    xui_inbound_id: int | None

    @property
    def is_active(self) -> bool:
        return self.subscription_until is not None and self.subscription_until > datetime.now(UTC)


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
                    xui_email TEXT,
                    xui_uuid TEXT,
                    xui_sub_id TEXT,
                    xui_inbound_id INTEGER
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
                    raw_payload TEXT
                );

                CREATE TABLE IF NOT EXISTS subscription_reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    reminder_key TEXT NOT NULL,
                    subscription_until TEXT NOT NULL,
                    sent_at TEXT NOT NULL,
                    UNIQUE (telegram_id, reminder_key, subscription_until)
                );
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
        provider_payment_charge_id: str,
        telegram_payment_charge_id: str,
        raw_payload: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO payments (
                    telegram_id, plan_code, amount, currency,
                    provider_payment_charge_id, telegram_payment_charge_id,
                    created_at, raw_payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    telegram_id,
                    plan_code,
                    amount,
                    currency,
                    provider_payment_charge_id,
                    telegram_payment_charge_id,
                    _to_iso(datetime.now(UTC)),
                    raw_payload,
                ),
            )

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


def _user_from_row(row: sqlite3.Row) -> User:
    return User(
        telegram_id=row["telegram_id"],
        username=row["username"],
        first_name=row["first_name"],
        subscription_until=_from_iso(row["subscription_until"]),
        xui_email=row["xui_email"],
        xui_uuid=row["xui_uuid"],
        xui_sub_id=row["xui_sub_id"],
        xui_inbound_id=row["xui_inbound_id"],
    )


def _to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
