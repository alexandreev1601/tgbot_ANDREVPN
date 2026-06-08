from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import load_config
from .db import Database
from .handlers import build_router
from .xui import XuiApi


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    config = load_config()
    db = Database(config.database_path)
    db.init()

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(config, db, XuiApi(config)))

    logging.info("ANDREVPN bot started")
    await dispatcher.start_polling(bot)


def main() -> None:
    asyncio.run(run())

