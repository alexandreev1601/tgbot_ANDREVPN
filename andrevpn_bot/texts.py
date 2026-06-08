from __future__ import annotations

from datetime import UTC
from urllib.parse import quote

from .config import Config
from .db import User


def welcome(config: Config) -> str:
    return (
        f"<b>{config.brand_name}</b>\n\n"
        "Добро пожаловать в ANDREVPN.\n\n"
        "Это VPN-сервис для стабильного и приватного подключения к интернету. "
        "Здесь можно посмотреть срок подписки, продлить доступ, получить ссылку подключения "
        "и открыть инструкцию для приложения HAPP.\n\n"
        "Выберите нужный раздел ниже."
    )


def cabinet(user: User) -> str:
    if user.subscription_until is None:
        status = "Подписка пока не активна."
    elif user.is_active:
        status = f"Подписка активна до: <b>{format_dt(user.subscription_until)}</b>"
    else:
        status = f"Подписка закончилась: <b>{format_dt(user.subscription_until)}</b>"

    return (
        "<b>Личный кабинет</b>\n\n"
        f"Telegram ID: <code>{user.telegram_id}</code>\n"
        f"{status}"
    )


def happ_instruction(config: Config) -> str:
    return (
        "<b>Инструкция для HAPP</b>\n\n"
        "1. Установите приложение HAPP на телефон.\n"
        "2. В боте откройте раздел <b>Получить подключение</b> и скопируйте персональную ссылку.\n"
        "3. В HAPP нажмите добавление подписки или профиля.\n"
        "4. Вставьте ссылку, сохраните профиль и обновите подписку.\n"
        "5. Выберите добавленный профиль ANDREVPN и нажмите подключение.\n\n"
        "Если приложение просит выбрать тип подключения, используйте профиль, который импортировался "
        "из ссылки ANDREVPN. Все подключения выдаются через один настроенный входящий протокол 3X-UI."
    )


def connection_text(user: User, config: Config) -> str:
    if not user.is_active:
        return (
            "<b>Подключение ANDREVPN</b>\n\n"
            "Сначала оплатите или продлите подписку. После активации здесь появится персональная ссылка."
        )

    if user.xui_sub_id and config.vpn_subscription_base_url:
        link = f"{config.vpn_subscription_base_url}/{user.xui_sub_id}"
        return (
            "<b>Подключение ANDREVPN</b>\n\n"
            "Ваша персональная ссылка подписки для HAPP:\n"
            f"<code>{link}</code>\n\n"
            "Удалите старый профиль, затем добавьте эту ссылку в HAPP как подписку и обновите её."
        )

    direct_link = build_vless_reality_link(user, config)
    if direct_link:
        return (
            "<b>Подключение ANDREVPN</b>\n\n"
            "Ваша персональная ссылка для HAPP:\n"
            f"<code>{direct_link}</code>\n\n"
            "Скопируйте её и импортируйте в HAPP как профиль."
        )

    if not user.xui_sub_id:
        support = f" @{config.support_username}" if config.support_username else ""
        return (
            "<b>Подключение ANDREVPN</b>\n\n"
            "Подписка активна, но ссылка подключения ещё не сформирована. "
            f"Напишите администратору{support}."
        )

    return "<b>Подключение ANDREVPN</b>\n\nНастройки подключения ещё не заполнены администратором."


def build_vless_reality_link(user: User, config: Config) -> str:
    if not user.xui_uuid:
        return ""
    if not (config.vpn_public_host and config.vless_port and config.reality_public_key):
        return ""

    params = {
        "type": config.vless_transport_type,
        "security": "reality",
        "encryption": "none",
        "pbk": config.reality_public_key,
        "fp": config.reality_fingerprint,
        "sni": config.reality_server_name,
        "spx": config.reality_spider_x,
    }
    if config.reality_short_id:
        params["sid"] = config.reality_short_id
    if config.reality_pqv:
        params["pqv"] = config.reality_pqv
    if config.xui_client_flow:
        params["flow"] = config.xui_client_flow

    query = "&".join(f"{quote(str(key))}={quote(str(value), safe='')}" for key, value in params.items())
    label = quote(f"ANDREVPN-{user.telegram_id}", safe="")
    return f"vless://{user.xui_uuid}@{config.vpn_public_host}:{config.vless_port}?{query}#{label}"


def format_dt(value) -> str:
    local = value.astimezone(UTC)
    return local.strftime("%d.%m.%Y %H:%M UTC")
