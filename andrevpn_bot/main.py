from __future__ import annotations

import asyncio
import logging
import ssl

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web

from .config import load_config
from .db import Database
from .handlers import build_router
from .texts import build_vless_reality_link
from .xui import XuiApi


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    config = load_config()
    db = Database(config.database_path)
    db.init()

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(config, db, XuiApi(config)))

    subscription_runner = await start_subscription_server(config, db)
    logging.info("ANDREVPN bot started")
    try:
        await dispatcher.start_polling(bot)
    finally:
        if subscription_runner:
            await subscription_runner.cleanup()


async def start_subscription_server(config, db: Database):
    if not config.subscription_port:
        return None

    app = web.Application()

    async def subscription(request: web.Request) -> web.Response:
        sub_id = request.match_info["sub_id"]
        try:
            user = _find_user_by_sub_id(db, sub_id)
        except LookupError:
            raise web.HTTPNotFound()

        if not user.is_active:
            raise web.HTTPForbidden(text="Subscription expired")

        link = build_vless_reality_link(user, config)
        if not link:
            raise web.HTTPNotFound()

        body = __import__("base64").b64encode((link + "\n").encode()).decode()
        headers = {
            "Profile-Update-Interval": "12",
            "Subscription-Userinfo": (
                f"upload=0; download=0; total={config.xui_total_gb}; "
                f"expire={int(user.subscription_until.timestamp()) if user.subscription_until else 0}"
            ),
        }
        return web.Response(text=body, content_type="text/plain", headers=headers)

    app.router.add_get("/sub/{sub_id}", subscription)

    runner = web.AppRunner(app)
    await runner.setup()
    ssl_context = None
    if config.subscription_cert_file and config.subscription_key_file:
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(config.subscription_cert_file, config.subscription_key_file)

    site = web.TCPSite(runner, config.subscription_listen_host, config.subscription_port, ssl_context=ssl_context)
    await site.start()
    logging.info("Subscription server started on %s:%s", config.subscription_listen_host, config.subscription_port)
    return runner


def _find_user_by_sub_id(db: Database, sub_id: str):
    with db.connect() as conn:
        row = conn.execute("SELECT telegram_id FROM users WHERE xui_sub_id = ?", (sub_id,)).fetchone()
    if row is None:
        raise LookupError(sub_id)
    return db.get_user(row["telegram_id"])


def main() -> None:
    asyncio.run(run())
