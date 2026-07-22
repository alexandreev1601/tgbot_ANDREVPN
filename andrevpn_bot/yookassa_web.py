from __future__ import annotations

import logging
import ssl

from aiohttp import web

from .config import Config
from .db import Database
from .handlers import _after_successful_external_payment, _notify_admins
from .xui import XuiApi
from .yookassa import YookassaError, YookassaPaymentService, YookassaVerificationError


logger = logging.getLogger(__name__)


async def start_yookassa_server(config: Config, db: Database, bot, xui: XuiApi):
    if not config.yookassa_enabled or not config.yookassa_listen_port:
        return None

    service = YookassaPaymentService(config, db)
    app = web.Application()

    async def return_page(request: web.Request) -> web.Response:
        return web.Response(
            text=(
                "<!doctype html><html><head><meta charset=\"utf-8\">"
                "<title>ANDREVPN</title></head><body>"
                "<h1>Оплата отправлена на проверку</h1>"
                "<p>Вернитесь в Telegram и нажмите кнопку «Проверить оплату».</p>"
                "</body></html>"
            ),
            content_type="text/html",
        )

    async def webhook(request: web.Request) -> web.Response:
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise YookassaVerificationError("Webhook payload is not an object")
            result = await service.process_webhook(payload)
            if result.finalization is not None and not result.finalization.already_processed:
                await _after_successful_external_payment(bot, config, db, xui, service, result.finalization)
            return web.json_response({"ok": True})
        except YookassaVerificationError as exc:
            logger.warning("YooKassa webhook verification failed: %s", exc)
            await _notify_admins(bot, config, f"YooKassa webhook verification failed: {exc}")
            return web.json_response({"ok": True})
        except YookassaError as exc:
            logger.warning("YooKassa webhook temporary error: %s", exc)
            return web.json_response({"ok": False}, status=503)
        except Exception as exc:
            logger.exception("YooKassa webhook internal error")
            await _notify_admins(bot, config, f"YooKassa webhook internal error: {type(exc).__name__}")
            return web.json_response({"ok": False}, status=500)

    app.router.add_get("/payments/yookassa/return", return_page)
    app.router.add_post("/payments/yookassa/webhook", webhook)

    runner = web.AppRunner(app)
    await runner.setup()
    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain(config.yookassa_cert_file, config.yookassa_key_file)

    site = web.TCPSite(runner, config.yookassa_listen_host, config.yookassa_listen_port, ssl_context=ssl_context)
    await site.start()
    logger.info("YooKassa payment server started on %s:%s", config.yookassa_listen_host, config.yookassa_listen_port)
    return runner
