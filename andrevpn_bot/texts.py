from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from math import ceil
from urllib.parse import quote

from .config import Config, VpnProfile
from .db import User
from .xui import TrafficSummary


def welcome(config: Config) -> str:
    return (
        f"<b>{escape(config.brand_name)}</b>\n\n"
        "Добро пожаловать в ANDREVPN.\n\n"
        "VPN-сервис для стабильного и приватного подключения. "
        "В меню ниже можно проверить подписку, оплатить доступ, получить подключение и открыть инструкцию."
    )


def home_card(user: User, config: Config) -> str:
    if user.is_active and user.subscription_until is not None:
        return (
            f"🟢 <b>{escape(config.brand_name)} активен</b>\n"
            f"До: <b>{format_date(user.subscription_until)}</b>\n"
            f"Осталось: <b>{remaining_days_text(user.subscription_until)}</b>"
        )
    return (
        "🔴 <b>Подписка не активна</b>\n"
        "Выберите пробный период или тариф."
    )


def profile_card(user: User, traffic: TrafficSummary | None = None) -> str:
    if user.subscription_until is None:
        status = "🔴 Не активна"
        until = "нет"
        days_line = ""
    elif user.is_active:
        status = "🟢 Активна"
        until = format_date(user.subscription_until)
        days_line = f"\nОсталось: <b>{remaining_days_text(user.subscription_until)}</b>"
    else:
        status = "🔴 Закончилась"
        until = format_date(user.subscription_until)
        days_line = ""

    traffic_text = traffic_summary_text(traffic) if traffic and user.is_active else ""
    return (
        "👤 <b>Моя подписка</b>\n\n"
        f"Статус: <b>{status}</b>\n"
        f"Дата окончания: <b>{until}</b>{days_line}\n\n"
        f"{traffic_text}"
        f"Telegram ID: <code>{user.telegram_id}</code>"
    )


def cabinet(user: User) -> str:
    return profile_card(user)


def traffic_summary_text(traffic: TrafficSummary) -> str:
    if traffic.total_bytes > 0:
        remaining = format_gigabytes(traffic.remaining_bytes)
        total = format_gigabytes(traffic.total_bytes)
        used = format_gigabytes(traffic.used_bytes)
        limit_line = f"Остаток трафика: <b>{remaining} из {total}</b>\n"
        used_line = f"Использовано: <b>{used}</b>\n"
    else:
        limit_line = "Остаток трафика: <b>без лимита</b>\n"
        used_line = f"Использовано: <b>{format_gigabytes(traffic.used_bytes)}</b>\n"

    return (
        f"{limit_line}"
        f"{used_line}"
        f"Сброс трафика: <b>{format_date(traffic.next_reset_at)}</b>\n"
    )


def connection_text(user: User, config: Config) -> str:
    if not user.is_active:
        return (
            "🔗 <b>Подключение ANDREVPN</b>\n\n"
            "Сначала активируйте подписку. После этого здесь появится персональная ссылка для HAPP."
        )

    link = connection_link(user, config)
    if link:
        return (
            "🔗 <b>Подключение ANDREVPN</b>\n\n"
            "Скопируйте персональную ссылку и добавьте ее в HAPP через «Из буфера».\n\n"
            f"<code>{escape(link)}</code>"
        )

    if not user.xui_sub_id:
        support = f" @{escape(config.support_username)}" if config.support_username else ""
        return (
            "🔗 <b>Подключение ANDREVPN</b>\n\n"
            "Подписка активна, но ссылка подключения еще не сформирована. "
            f"Напишите администратору{support}."
        )

    return "🔗 <b>Подключение ANDREVPN</b>\n\nНастройки подключения еще не заполнены администратором."


def happ_instruction(config: Config) -> str:
    return (
        "<b>Инструкция для HAPP</b>\n\n"
        "1. Установите приложение HAPP на телефон.\n"
        "2. В боте откройте раздел <b>Подключить VPN</b> и скопируйте персональную ссылку.\n"
        "3. В HAPP нажмите <b>Из буфера</b> и разрешите вставку.\n"
        "4. Обновите подписку и выберите любой доступный профиль ANDREVPN."
    )


def trial_text(user: User) -> str:
    if user.trial_used_at is not None:
        return (
            "🎁 <b>Пробный период</b>\n\n"
            "Пробный период уже был активирован ранее. Он доступен только один раз."
        )
    if user.is_active:
        return (
            "🎁 <b>Пробный период</b>\n\n"
            "У вас уже есть активная подписка. Пробный период доступен только новым пользователям без активной подписки."
        )
    return (
        "🎁 <b>Пробный период</b>\n\n"
        "Можно получить ANDREVPN на <b>3 дня</b>. "
        "После активации ссылка появится в разделе <b>Подключить VPN</b>.\n\n"
        "Пробный период доступен один раз."
    )


def trial_success_text(user: User) -> str:
    until = format_date(user.subscription_until) if user.subscription_until else ""
    return (
        "✅ <b>Пробная подписка активирована</b>\n\n"
        f"Доступ ANDREVPN выдан на 3 дня, до: <b>{until}</b>.\n\n"
        "Подключение уже находится в разделе <b>Подключить VPN</b>."
    )


def connection_link_message(user: User, config: Config) -> str:
    link = connection_link(user, config)
    if not link:
        return ""
    return f"<code>{escape(link)}</code>"


def connection_link(user: User, config: Config) -> str:
    if not user.is_active:
        return ""
    if user.xui_sub_id and config.vpn_subscription_base_url:
        return f"{config.vpn_subscription_base_url}/{user.xui_sub_id}"
    return build_vless_reality_link(user, config)


def build_vless_reality_link(user: User, config: Config) -> str:
    links = build_vless_links(user, config)
    return links[0] if links else ""


def build_vless_links(user: User, config: Config) -> list[str]:
    if not user.xui_uuid:
        return []

    links = []
    for profile in config.vpn_profiles:
        link = build_vless_profile_link(user, profile)
        if link:
            links.append(link)
    return links


def build_vless_profile_link(user: User, profile: VpnProfile) -> str:
    if not user.xui_uuid:
        return ""
    if not (profile.host and profile.port):
        return ""

    params = {"type": profile.transport_type, "encryption": "none"}
    if profile.transport_type == "xhttp":
        params.update({
            "path": profile.xhttp_path,
            "mode": profile.xhttp_mode,
        })

    if profile.security == "reality" and profile.reality_public_key:
        params.update({
            "security": "reality",
            "pbk": profile.reality_public_key,
            "fp": profile.reality_fingerprint,
            "sni": profile.reality_server_name,
            "spx": profile.reality_spider_x,
        })
        if profile.reality_short_id:
            params["sid"] = profile.reality_short_id
        if profile.reality_pqv:
            params["pqv"] = profile.reality_pqv
    else:
        params["security"] = "none"

    if profile.flow:
        params["flow"] = profile.flow

    query = "&".join(f"{quote(str(key))}={quote(str(value), safe='')}" for key, value in params.items())
    label = quote(profile.title, safe="")
    return f"vless://{user.xui_uuid}@{profile.host}:{profile.port}?{query}#{label}"


def format_dt(value) -> str:
    local = value.astimezone(UTC)
    return local.strftime("%d.%m.%Y %H:%M UTC")


def format_date(value) -> str:
    local = value.astimezone(UTC)
    return local.strftime("%d.%m.%Y")


def format_gigabytes(value: int) -> str:
    gib = max(0, value) / (1024 ** 3)
    if gib >= 10 or gib.is_integer():
        return f"{gib:.0f} ГБ"
    return f"{gib:.1f} ГБ"


def remaining_days_text(until: datetime) -> str:
    seconds = max(0, (until.astimezone(UTC) - datetime.now(UTC)).total_seconds())
    days = max(1, ceil(seconds / 86400)) if seconds > 0 else 0
    return _plural_days(days)


def _plural_days(days: int) -> str:
    if days % 10 == 1 and days % 100 != 11:
        word = "день"
    elif days % 10 in {2, 3, 4} and days % 100 not in {12, 13, 14}:
        word = "дня"
    else:
        word = "дней"
    return f"{days} {word}"
