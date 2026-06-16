from __future__ import annotations

import json
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
class VpnProfile:
    code: str
    title: str
    inbound_id: int
    host: str
    port: int
    transport_type: str
    security: str
    flow: str
    xhttp_path: str
    xhttp_mode: str
    reality_public_key: str
    reality_short_id: str
    reality_pqv: str
    reality_server_name: str
    reality_fingerprint: str
    reality_spider_x: str


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
    xhttp_path: str
    xhttp_mode: str
    reality_public_key: str
    reality_short_id: str
    reality_pqv: str
    reality_server_name: str
    reality_fingerprint: str
    reality_spider_x: str
    vpn_profiles: list[VpnProfile]
    subscription_listen_host: str
    subscription_port: int | None
    subscription_cert_file: str
    subscription_key_file: str
    support_username: str


def load_config() -> Config:
    load_dotenv()

    bot_token = _env("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is required. Fill it in .env.")

    xui_inbound_id = _parse_optional_int(_env("XUI_INBOUND_ID"))
    xui_client_flow = _env("XUI_CLIENT_FLOW")
    vpn_public_host = _env("VPN_PUBLIC_HOST")
    vless_port = _parse_optional_int(_env("VLESS_PORT"))
    vless_transport_type = _env("VLESS_TRANSPORT_TYPE", "raw")
    xhttp_path = _env("XHTTP_PATH", "/")
    xhttp_mode = _env("XHTTP_MODE", "auto")
    reality_public_key = _env("REALITY_PUBLIC_KEY")
    reality_short_id = _env("REALITY_SHORT_ID")
    reality_pqv = _env("REALITY_PQV")
    reality_server_name = _env("REALITY_SERVER_NAME", "www.cloudflare.com")
    reality_fingerprint = _env("REALITY_FINGERPRINT", "chrome")
    reality_spider_x = _env("REALITY_SPIDER_X", "/")

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
        xui_inbound_id=xui_inbound_id,
        xui_protocol=_env("XUI_PROTOCOL", "vless").lower(),
        xui_client_flow=xui_client_flow,
        xui_total_gb=int(_env("XUI_TOTAL_GB", "0")),
        xui_limit_ip=int(_env("XUI_LIMIT_IP", "0")),
        vpn_subscription_base_url=_env("VPN_SUBSCRIPTION_BASE_URL").rstrip("/"),
        vpn_public_host=vpn_public_host,
        vless_port=vless_port,
        vless_transport_type=vless_transport_type,
        xhttp_path=xhttp_path,
        xhttp_mode=xhttp_mode,
        reality_public_key=reality_public_key,
        reality_short_id=reality_short_id,
        reality_pqv=reality_pqv,
        reality_server_name=reality_server_name,
        reality_fingerprint=reality_fingerprint,
        reality_spider_x=reality_spider_x,
        vpn_profiles=_parse_vpn_profiles(
            _env("VPN_PROFILES_JSON"),
            xui_inbound_id=xui_inbound_id,
            vpn_public_host=vpn_public_host,
            vless_port=vless_port,
            vless_transport_type=vless_transport_type,
            xui_client_flow=xui_client_flow,
            xhttp_path=xhttp_path,
            xhttp_mode=xhttp_mode,
            reality_public_key=reality_public_key,
            reality_short_id=reality_short_id,
            reality_pqv=reality_pqv,
            reality_server_name=reality_server_name,
            reality_fingerprint=reality_fingerprint,
            reality_spider_x=reality_spider_x,
        ),
        subscription_listen_host=_env("SUBSCRIPTION_LISTEN_HOST", "0.0.0.0"),
        subscription_port=_parse_optional_int(_env("SUBSCRIPTION_PORT")),
        subscription_cert_file=_env("SUBSCRIPTION_CERT_FILE"),
        subscription_key_file=_env("SUBSCRIPTION_KEY_FILE"),
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


def _parse_vpn_profiles(
    value: str,
    *,
    xui_inbound_id: int | None,
    vpn_public_host: str,
    vless_port: int | None,
    vless_transport_type: str,
    xui_client_flow: str,
    xhttp_path: str,
    xhttp_mode: str,
    reality_public_key: str,
    reality_short_id: str,
    reality_pqv: str,
    reality_server_name: str,
    reality_fingerprint: str,
    reality_spider_x: str,
) -> list[VpnProfile]:
    if value:
        raw_profiles = json.loads(value)
        if not isinstance(raw_profiles, list):
            raise RuntimeError("VPN_PROFILES_JSON must be a JSON array.")
        profiles = [_vpn_profile_from_dict(item) for item in raw_profiles]
        if not profiles:
            raise RuntimeError("VPN_PROFILES_JSON must contain at least one profile.")
        return profiles

    if xui_inbound_id is None or not vpn_public_host or vless_port is None:
        return []

    return [
        VpnProfile(
            code="default",
            title="ANDREVPN",
            inbound_id=xui_inbound_id,
            host=vpn_public_host,
            port=vless_port,
            transport_type=vless_transport_type,
            security="reality" if reality_public_key else "none",
            flow=xui_client_flow,
            xhttp_path=xhttp_path,
            xhttp_mode=xhttp_mode,
            reality_public_key=reality_public_key,
            reality_short_id=reality_short_id,
            reality_pqv=reality_pqv,
            reality_server_name=reality_server_name,
            reality_fingerprint=reality_fingerprint,
            reality_spider_x=reality_spider_x,
        )
    ]


def _vpn_profile_from_dict(item: object) -> VpnProfile:
    if not isinstance(item, dict):
        raise RuntimeError("Every VPN profile must be a JSON object.")

    return VpnProfile(
        code=str(item["code"]).strip(),
        title=str(item["title"]).strip(),
        inbound_id=int(item["inbound_id"]),
        host=str(item["host"]).strip(),
        port=int(item["port"]),
        transport_type=str(item.get("transport_type", "tcp")).strip().lower(),
        security=str(item.get("security", "none")).strip().lower(),
        flow=str(item.get("flow", "")).strip(),
        xhttp_path=str(item.get("xhttp_path", "/")).strip() or "/",
        xhttp_mode=str(item.get("xhttp_mode", "auto")).strip() or "auto",
        reality_public_key=str(item.get("reality_public_key", "")).strip(),
        reality_short_id=str(item.get("reality_short_id", "")).strip(),
        reality_pqv=str(item.get("reality_pqv", "")).strip(),
        reality_server_name=str(item.get("reality_server_name", "www.cloudflare.com")).strip(),
        reality_fingerprint=str(item.get("reality_fingerprint", "chrome")).strip(),
        reality_spider_x=str(item.get("reality_spider_x", "/")).strip() or "/",
    )
