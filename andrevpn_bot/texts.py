from __future__ import annotations

from datetime import UTC
from urllib.parse import quote

from .config import Config, VpnProfile
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
        "Если после обновления подписки появилось несколько вариантов ANDREVPN, выберите любой доступный "
        "профиль. Если один вариант работает нестабильно, переключитесь на другой."
    )


def connection_text(user: User, config: Config) -> str:
    if not user.is_active:
        return (
            "<b>Подключение ANDREVPN</b>\n\n"
            "Сначала оплатите или продлите подписку. После активации здесь появится персональная ссылка."
        )

    if user.xui_sub_id and config.vpn_subscription_base_url:
        return (
            "<b>Подключение ANDREVPN</b>\n\n"
            "Персональная ссылка для подключения отправлена отдельным сообщением ниже.\n\n"
            "Внутри подписки может быть несколько вариантов подключения.\n\n"
            "Скопируйте данную ссылку, зайдите в приложение Happ - Proxy Utility "
            "и выберите внизу слева \"Из буфера\"."
        )

    direct_link = build_vless_reality_link(user, config)
    if direct_link:
        return (
            "<b>Подключение ANDREVPN</b>\n\n"
            "Персональная ссылка для подключения отправлена отдельным сообщением ниже.\n\n"
            "Скопируйте данную ссылку, зайдите в приложение Happ - Proxy Utility "
            "и выберите внизу слева \"Из буфера\"."
        )

    if not user.xui_sub_id:
        support = f" @{config.support_username}" if config.support_username else ""
        return (
            "<b>Подключение ANDREVPN</b>\n\n"
            "Подписка активна, но ссылка подключения ещё не сформирована. "
            f"Напишите администратору{support}."
        )

    return "<b>Подключение ANDREVPN</b>\n\nНастройки подключения ещё не заполнены администратором."


def trial_text(user: User) -> str:
    if user.trial_used_at is not None:
        return (
            "<b>Пробная версия ANDREVPN</b>\n\n"
            "Пробный период уже был активирован ранее. Он доступен только один раз."
        )
    if user.is_active:
        return (
            "<b>Пробная версия ANDREVPN</b>\n\n"
            "У вас уже есть активная подписка. Пробный период доступен только новым пользователям без активной подписки."
        )
    return (
        "<b>Пробная версия ANDREVPN</b>\n\n"
        "Вы можете получить пробный период на <b>3 дня</b>. "
        "После активации подключение появится в разделе <b>Получить подключение</b>.\n\n"
        "Пробный период доступен только один раз."
    )


def trial_success_text(user: User) -> str:
    until = format_dt(user.subscription_until) if user.subscription_until else ""
    return (
        "<b>Пробная подписка активирована</b>\n\n"
        f"Доступ ANDREVPN выдан на 3 дня, до: <b>{until}</b>.\n\n"
        "Подключение уже находится в разделе <b>Получить подключение</b>."
    )


def connection_link_message(user: User, config: Config) -> str:
    link = connection_link(user, config)
    if not link:
        return ""

    return f"<code>{link}</code>"


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
