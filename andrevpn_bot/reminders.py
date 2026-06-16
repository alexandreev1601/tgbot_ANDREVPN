from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from aiogram import Bot

from .db import Database, User
from .texts import format_dt


@dataclass(frozen=True)
class ReminderRule:
    key: str
    title: str
    upper_bound: timedelta
    lower_bound: timedelta


REMINDER_RULES = (
    ReminderRule("3_days", "3 дня", timedelta(days=3), timedelta(days=1)),
    ReminderRule("1_day", "1 день", timedelta(days=1), timedelta(hours=1)),
    ReminderRule("1_hour", "1 час", timedelta(hours=1), timedelta()),
)


async def run_subscription_reminders(bot: Bot, db: Database, interval_seconds: int = 900) -> None:
    while True:
        try:
            await send_due_subscription_reminders(bot, db)
        except Exception:
            logging.exception("Subscription reminder check failed")
        await asyncio.sleep(interval_seconds)


async def send_due_subscription_reminders(bot: Bot, db: Database) -> None:
    now = datetime.now(UTC)
    for user in db.list_active_users():
        if not user.subscription_until:
            continue

        remaining = user.subscription_until - now
        rule = _matching_rule(remaining)
        if rule is None:
            continue
        if db.reminder_was_sent(user.telegram_id, rule.key, user.subscription_until):
            continue

        try:
            await bot.send_message(user.telegram_id, subscription_reminder_text(user, rule))
        except Exception:
            logging.exception("Failed to send subscription reminder to %s", user.telegram_id)
            continue

        db.mark_reminder_sent(user.telegram_id, rule.key, user.subscription_until)


def subscription_reminder_text(user: User, rule: ReminderRule) -> str:
    until = format_dt(user.subscription_until) if user.subscription_until else ""
    return (
        "<b>ANDREVPN: подписка скоро закончится</b>\n\n"
        f"До окончания VPN осталось примерно <b>{rule.title}</b>.\n"
        f"Подписка активна до: <b>{until}</b>\n\n"
        "Чтобы интернет через VPN не прерывался, продлите подписку в разделе <b>Оплатить</b>."
    )


def _matching_rule(remaining: timedelta) -> ReminderRule | None:
    if remaining <= timedelta():
        return None

    for rule in REMINDER_RULES:
        if rule.lower_bound < remaining <= rule.upper_bound:
            return rule
    return None
