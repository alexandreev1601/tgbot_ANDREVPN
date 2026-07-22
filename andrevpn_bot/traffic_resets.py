from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from aiogram import Bot

from .config import Config
from .db import Database, User
from .xui import XuiApi


logger = logging.getLogger(__name__)


async def run_monthly_traffic_resets(
    bot: Bot,
    config: Config,
    db: Database,
    xui: XuiApi,
) -> None:
    interval_seconds = max(config.traffic_reset_interval_seconds, 300)
    while True:
        try:
            await reset_due_monthly_traffic(bot, config, db, xui)
        except Exception:
            logger.exception("Monthly traffic reset check failed")
        await asyncio.sleep(interval_seconds)


async def reset_due_monthly_traffic(
    bot: Bot,
    config: Config,
    db: Database,
    xui: XuiApi,
    *,
    now: datetime | None = None,
) -> int:
    current = now or datetime.now(UTC)
    reset_month = current.strftime("%Y-%m")
    inbound_ids = await xui.resolve_inbound_ids()
    if not inbound_ids:
        return 0

    reset_count = 0
    for user in db.list_active_users():
        if not user.xui_email or not user.xui_uuid or not user.xui_sub_id:
            try:
                await xui.provision_user(db, user)
                user = db.get_user(user.telegram_id)
            except Exception as exc:
                logger.exception("Failed to provision user %s before traffic reset", user.telegram_id)
                await _notify_admins(
                    bot,
                    config,
                    f"Traffic reset: failed to provision user {user.telegram_id}: {type(exc).__name__}",
                )
                continue

        for inbound_id in inbound_ids:
            if db.traffic_reset_was_done(user.telegram_id, inbound_id, reset_month):
                continue

            try:
                await xui.reset_client_traffic(user, inbound_id)
            except Exception as exc:
                logger.exception(
                    "Failed to reset traffic for user %s inbound %s",
                    user.telegram_id,
                    inbound_id,
                )
                await _notify_admins(
                    bot,
                    config,
                    (
                        "Traffic reset failed\n"
                        f"User: {user.telegram_id}\n"
                        f"Inbound: {inbound_id}\n"
                        f"Error: {type(exc).__name__}"
                    ),
                )
                continue

            if db.mark_traffic_reset_done(user.telegram_id, inbound_id, reset_month):
                reset_count += 1
                logger.info(
                    "Monthly traffic reset completed: user=%s inbound=%s month=%s",
                    user.telegram_id,
                    inbound_id,
                    reset_month,
                )

    return reset_count


async def reset_user_traffic_for_current_month(
    db: Database,
    xui: XuiApi,
    user: User,
    *,
    now: datetime | None = None,
) -> int:
    current = now or datetime.now(UTC)
    reset_month = current.strftime("%Y-%m")
    reset_count = 0
    for inbound_id in await xui.resolve_inbound_ids():
        if db.traffic_reset_was_done(user.telegram_id, inbound_id, reset_month):
            continue
        await xui.reset_client_traffic(user, inbound_id)
        if db.mark_traffic_reset_done(user.telegram_id, inbound_id, reset_month):
            reset_count += 1
    return reset_count


async def _notify_admins(bot: Bot, config: Config, text: str) -> None:
    for admin_id in config.admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            logger.exception("Failed to notify admin %s about traffic reset", admin_id)
