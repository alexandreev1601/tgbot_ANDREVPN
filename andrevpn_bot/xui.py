from __future__ import annotations

import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime

import httpx

from .config import Config
from .db import Database, User


@dataclass(frozen=True)
class XuiClient:
    inbound_id: int
    email: str
    uuid: str
    sub_id: str
    flow: str


class XuiError(RuntimeError):
    pass


class XuiApi:
    def __init__(self, config: Config) -> None:
        self.config = config

    async def provision_user(self, db: Database, user: User) -> XuiClient | None:
        if not self._is_configured:
            return None

        inbound_ids = await self._resolve_inbound_ids()
        if not inbound_ids:
            raise XuiError("No VPN profiles are configured.")

        client_uuid = user.xui_uuid or str(uuid.uuid4())
        sub_id = user.xui_sub_id or _new_sub_id()
        email = user.xui_email or f"tg_{user.telegram_id}"

        primary_client = None
        for inbound_id, flow in await self._resolve_inbound_flows():
            client = XuiClient(inbound_id=inbound_id, email=email, uuid=client_uuid, sub_id=sub_id, flow=flow)
            await self._upsert_client(client, user.subscription_until)
            if primary_client is None:
                primary_client = client

        db.save_xui_client(user.telegram_id, email, client_uuid, sub_id, inbound_ids[0])
        return primary_client

    async def _resolve_inbound_flows(self) -> list[tuple[int, str]]:
        if self.config.vpn_profiles:
            return [(profile.inbound_id, profile.flow) for profile in self.config.vpn_profiles]

        inbound_id = await self._resolve_inbound_id()
        if inbound_id is None:
            return []
        return [(inbound_id, self.config.xui_client_flow)]

    async def _resolve_inbound_ids(self) -> list[int]:
        if self.config.vpn_profiles:
            return [profile.inbound_id for profile in self.config.vpn_profiles]

        inbound_id = await self._resolve_inbound_id()
        if inbound_id is None:
            return []
        return [inbound_id]

    @property
    def _is_configured(self) -> bool:
        return bool(
            self.config.xui_base_url
            and (self.config.xui_api_token or (self.config.xui_username and self.config.xui_password))
        )

    async def _client(self) -> httpx.AsyncClient:
        headers = {}
        if self.config.xui_api_token:
            headers["Authorization"] = f"Bearer {self.config.xui_api_token}"

        client = httpx.AsyncClient(
            base_url=self.config.xui_base_url,
            timeout=20.0,
            follow_redirects=True,
            headers=headers,
        )
        if self.config.xui_api_token:
            return client

        response = await client.post(
            "/login",
            json={"username": self.config.xui_username, "password": self.config.xui_password},
        )
        response.raise_for_status()
        data = _safe_json(response)
        if isinstance(data, dict) and data.get("success") is False:
            await client.aclose()
            raise XuiError(f"3X-UI login failed: {data.get('msg') or data}")
        return client

    async def _resolve_inbound_id(self) -> int:
        if self.config.xui_inbound_id is not None:
            return self.config.xui_inbound_id

        async with await self._client() as client:
            response = await client.get("/panel/api/inbounds/list")
            response.raise_for_status()
            data = response.json()

        inbounds = data.get("obj", []) if isinstance(data, dict) else []
        for inbound in inbounds:
            if str(inbound.get("protocol", "")).lower() == self.config.xui_protocol:
                return int(inbound["id"])

        raise XuiError(f"No 3X-UI inbound found for protocol {self.config.xui_protocol!r}")

    async def _upsert_client(self, client_info: XuiClient, subscription_until: datetime | None) -> None:
        payload = self._client_payload(client_info, subscription_until)
        async with await self._client() as client:
            await self._upsert_client_via_inbound_update(client, client_info.inbound_id, payload)

    async def _try_update_client(
        self,
        client: httpx.AsyncClient,
        client_info: XuiClient,
        payload: dict,
    ) -> bool:
        response = await client.post(
            f"/panel/api/inbounds/updateClient/{client_info.uuid}",
            json={"id": client_info.inbound_id, "settings": json.dumps({"clients": [payload]})},
        )
        if response.status_code == 404:
            return False

        if not response.content:
            return False

        data = _safe_json(response)
        if isinstance(data, dict) and data.get("success") is True:
            return True
        return False

    async def _add_client(self, client: httpx.AsyncClient, inbound_id: int, payload: dict) -> None:
        response = await client.post(
            "/panel/api/inbounds/addClient",
            json={"inboundId": inbound_id, "client": payload},
        )

        if _looks_successful(response):
            return

        legacy_response = await client.post(
            "/panel/api/inbounds/addClient",
            json={"id": inbound_id, "settings": json.dumps({"clients": [payload]})},
        )
        if _looks_successful(legacy_response):
            return

        raise XuiError(f"3X-UI addClient failed: {legacy_response.status_code} {legacy_response.text[:300]}")

    async def _upsert_client_via_inbound_update(
        self,
        client: httpx.AsyncClient,
        inbound_id: int,
        payload: dict,
    ) -> None:
        response = await client.get(f"/panel/api/inbounds/get/{inbound_id}")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not data.get("success") or not data.get("obj"):
            raise XuiError(f"3X-UI get inbound failed: {data}")

        inbound = data["obj"]
        settings = inbound.get("settings") or {}
        if isinstance(settings, str):
            settings = json.loads(settings)

        clients = settings.setdefault("clients", [])
        replacement_index = next(
            (
                index
                for index, existing in enumerate(clients)
                if existing.get("id") == payload["id"] or existing.get("email") == payload["email"]
            ),
            None,
        )
        if replacement_index is None:
            clients.append(payload)
        else:
            clients[replacement_index] = payload

        update_payload = {
            "up": inbound.get("up", 0),
            "down": inbound.get("down", 0),
            "total": inbound.get("total", 0),
            "remark": inbound.get("remark", ""),
            "enable": inbound.get("enable", True),
            "expiryTime": inbound.get("expiryTime", 0),
            "listen": inbound.get("listen", ""),
            "port": inbound.get("port"),
            "protocol": inbound.get("protocol"),
            "settings": json.dumps(settings, separators=(",", ":")),
            "streamSettings": json.dumps(inbound.get("streamSettings") or {}, separators=(",", ":")),
            "tag": inbound.get("tag", ""),
            "sniffing": json.dumps(inbound.get("sniffing") or {}, separators=(",", ":")),
        }
        if inbound.get("trafficReset"):
            update_payload["trafficReset"] = inbound["trafficReset"]

        update_response = await client.post(f"/panel/api/inbounds/update/{inbound_id}", json=update_payload)
        if not _looks_successful(update_response):
            raise XuiError(f"3X-UI update inbound failed: {update_response.status_code} {update_response.text[:300]}")

    def _client_payload(self, client_info: XuiClient, subscription_until: datetime | None) -> dict:
        expiry_ms = int(subscription_until.timestamp() * 1000) if subscription_until else 0
        return {
            "id": client_info.uuid,
            "flow": client_info.flow,
            "email": client_info.email,
            "limitIp": self.config.xui_limit_ip,
            "totalGB": self.config.xui_total_gb,
            "expiryTime": expiry_ms,
            "enable": True,
            "tgId": str(client_info.email).replace("tg_", ""),
            "subId": client_info.sub_id,
            "reset": 0,
        }


def _safe_json(response: httpx.Response) -> object | None:
    try:
        return response.json()
    except json.JSONDecodeError:
        return None


def _looks_successful(response: httpx.Response) -> bool:
    if response.status_code >= 400:
        return False
    if not response.content:
        return True
    data = _safe_json(response)
    if isinstance(data, dict):
        return data.get("success") is not False
    return True


def _new_sub_id() -> str:
    return secrets.token_urlsafe(12).replace("_", "").replace("-", "").lower()
