from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Plan:
    code: str
    title: str
    price: int
    days: int


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: set[int]
    brand_name: str
    database_path: Path
    payment_provider_token: str
    payment_currency: str
    payment_title: str
    payment_description: str
    plans: list[Plan]
    xui_base_url: str
    xui_api_token: str
    xui_username: str
    xui_password: str
    xui_inbound_id: int | None
    xui_protocol: str
    xui_client_flow: str
    xui_total_gb: int
    xui_limit_ip: int
    vpn_subscription_base_url: str
    vpn_public_host: str
    vless_port: int | None
    vless_transport_type: str
    reality_public_key: str
    reality_short_id: str
    reality_server_name: str
    reality_fingerprint: str
    reality_spider_x: str
    support_username: str


def load_config() -> Config:
    load_dotenv()

    bot_token = _env("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is required. Fill it in .env.")

    return Config(
        bot_token=bot_token,
        admin_ids=_parse_admin_ids(_env("ADMIN_IDS")),
        brand_name=_env("BRAND_NAME", "ANDREVPN"),
        database_path=Path(_env("DATABASE_PATH", "data/andrevpn.sqlite3")),
        payment_provider_token=_env("PAYMENT_PROVIDER_TOKEN"),
        payment_currency=_env("PAYMENT_CURRENCY", "RUB").upper(),
        payment_title=_env("PAYMENT_TITLE", "ANDREVPN"),
        payment_description=_env("PAYMENT_DESCRIPTION", "Продление VPN-подписки ANDREVPN"),
        plans=_parse_plans(_env("PLANS", "month:1 месяц:199:30,quarter:3 месяца:499:90,year:1 год:1490:365")),
        xui_base_url=_env("XUI_BASE_URL").rstrip("/"),
        xui_api_token=_env("XUI_API_TOKEN"),
        xui_username=_env("XUI_USERNAME"),
        xui_password=_env("XUI_PASSWORD"),
        xui_inbound_id=_parse_optional_int(_env("XUI_INBOUND_ID")),
        xui_protocol=_env("XUI_PROTOCOL", "vless").lower(),
        xui_client_flow=_env("XUI_CLIENT_FLOW"),
        xui_total_gb=int(_env("XUI_TOTAL_GB", "0")),
        xui_limit_ip=int(_env("XUI_LIMIT_IP", "0")),
        vpn_subscription_base_url=_env("VPN_SUBSCRIPTION_BASE_URL").rstrip("/"),
        vpn_public_host=_env("VPN_PUBLIC_HOST"),
        vless_port=_parse_optional_int(_env("VLESS_PORT")),
        vless_transport_type=_env("VLESS_TRANSPORT_TYPE", "raw"),
        reality_public_key=_env("REALITY_PUBLIC_KEY"),
        reality_short_id=_env("REALITY_SHORT_ID"),
        reality_server_name=_env("REALITY_SERVER_NAME", "www.cloudflare.com"),
        reality_fingerprint=_env("REALITY_FINGERPRINT", "chrome"),
        reality_spider_x=_env("REALITY_SPIDER_X", "/"),
        support_username=_env("SUPPORT_USERNAME").lstrip("@"),
    )


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _parse_admin_ids(value: str) -> set[int]:
    ids: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if item:
            ids.add(int(item))
    return ids


def _parse_optional_int(value: str) -> int | None:
    return int(value) if value else None


def _parse_plans(value: str) -> list[Plan]:
    plans: list[Plan] = []
    for raw_plan in value.split(","):
        raw_plan = raw_plan.strip()
        if not raw_plan:
            continue

        parts = raw_plan.split(":")
        if len(parts) != 4:
            raise RuntimeError(f"Invalid tariff plan format: {raw_plan}")

        code, title, price, days = parts
        plans.append(Plan(code=code.strip(), title=title.strip(), price=int(price), days=int(days)))

    if not plans:
        raise RuntimeError("At least one tariff plan must be configured in PLANS.")
    return plans
