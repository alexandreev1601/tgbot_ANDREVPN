from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from andrevpn_bot.db import Database
from andrevpn_bot.traffic_resets import reset_due_monthly_traffic
from andrevpn_bot.xui import XuiApi


class Bot:
    def __init__(self) -> None:
        self.messages = []

    async def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))


class FakeXui:
    def __init__(self) -> None:
        self.reset_calls = []
        self.provision_calls = []

    async def resolve_inbound_ids(self):
        return [4, 5]

    async def provision_user(self, db, user):
        self.provision_calls.append(user.telegram_id)
        return None

    async def reset_client_traffic(self, user, inbound_id):
        self.reset_calls.append((user.telegram_id, inbound_id))


def config(**kwargs):
    values = {
        "admin_ids": {1738661194},
        "xui_db_path": Path("missing.sqlite3"),
        "xui_total_gb": 107374182400,
        "xui_inbound_id": None,
        "xui_limit_ip": 0,
        "xui_base_url": "",
        "xui_api_token": "",
        "xui_username": "",
        "xui_password": "",
        "vpn_profiles": [],
        "xui_client_flow": "",
    }
    values.update(kwargs)
    return SimpleNamespace(**values)


class TrafficResetTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmpdir.name) / "bot.sqlite3")
        self.db.init()

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def active_user(self, telegram_id: int = 1001):
        user = self.db.upsert_user(telegram_id, f"user{telegram_id}", "User")
        user = self.db.extend_subscription(user.telegram_id, 30)
        return self.db.save_xui_client(
            user.telegram_id,
            f"tg_{telegram_id}",
            "11111111-1111-4111-8111-111111111111",
            "subid",
            4,
        )

    def test_traffic_reset_mark_is_idempotent(self) -> None:
        self.assertFalse(self.db.traffic_reset_was_done(1001, 4, "2026-08"))
        self.assertTrue(self.db.mark_traffic_reset_done(1001, 4, "2026-08"))
        self.assertFalse(self.db.mark_traffic_reset_done(1001, 4, "2026-08"))
        self.assertTrue(self.db.traffic_reset_was_done(1001, 4, "2026-08"))

    async def test_due_reset_runs_once_per_user_inbound_month(self) -> None:
        self.active_user()
        fake_xui = FakeXui()

        first = await reset_due_monthly_traffic(
            Bot(),
            config(),
            self.db,
            fake_xui,
            now=datetime(2026, 8, 1, tzinfo=UTC),
        )
        second = await reset_due_monthly_traffic(
            Bot(),
            config(),
            self.db,
            fake_xui,
            now=datetime(2026, 8, 2, tzinfo=UTC),
        )

        self.assertEqual(first, 2)
        self.assertEqual(second, 0)
        self.assertEqual(fake_xui.reset_calls, [(1001, 4), (1001, 5)])

    def test_xui_local_db_reset_zeroes_traffic_and_enables_client(self) -> None:
        xui_db = Path(self.tmpdir.name) / "x-ui.sqlite3"
        self.create_xui_db(xui_db)
        user = self.active_user()
        user = self.db.extend_subscription(user.telegram_id, 30)

        xui = XuiApi(config(xui_db_path=xui_db))
        changed = xui._reset_client_traffic_in_local_db(user, 4)

        self.assertTrue(changed)
        conn = sqlite3.connect(xui_db)
        conn.row_factory = sqlite3.Row
        traffic = conn.execute(
            "SELECT up, down, enable, total, expiry_time FROM client_traffics WHERE inbound_id = 4 AND email = ?",
            (user.xui_email,),
        ).fetchone()
        self.assertEqual(dict(traffic)["up"], 0)
        self.assertEqual(dict(traffic)["down"], 0)
        self.assertEqual(dict(traffic)["enable"], 1)
        self.assertEqual(dict(traffic)["total"], 107374182400)
        inbound = conn.execute("SELECT settings FROM inbounds WHERE id = 4").fetchone()
        self.assertIn('"enable":true', inbound["settings"])
        conn.close()

    def test_xui_traffic_summary_sums_usage_and_monthly_remaining(self) -> None:
        xui_db = Path(self.tmpdir.name) / "x-ui.sqlite3"
        self.create_xui_db(xui_db)
        user = self.active_user()
        total = 100 * 1024 ** 3
        conn = sqlite3.connect(xui_db)
        conn.execute(
            """
            INSERT INTO client_traffics (
                inbound_id, enable, email, up, down, expiry_time, total, reset, last_online
            )
            VALUES (5, 1, 'tg_1001', ?, ?, 0, ?, 0, 0)
            """,
            (2 * 1024 ** 3, 3 * 1024 ** 3, total),
        )
        conn.commit()
        conn.close()

        xui = XuiApi(config(xui_db_path=xui_db, xui_total_gb=total))
        summary = xui.traffic_summary(user)

        self.assertIsNotNone(summary)
        self.assertEqual(summary.used_bytes, 123 + 456 + 5 * 1024 ** 3)
        self.assertEqual(summary.total_bytes, total)
        self.assertEqual(summary.remaining_bytes, total - summary.used_bytes)
        self.assertEqual(summary.next_reset_at.day, 1)
        self.assertEqual(summary.profiles_count, 2)

    def test_migration_is_idempotent(self) -> None:
        self.active_user()
        self.db.init()
        self.db.init()

        self.assertEqual(self.db.get_user(1001).telegram_id, 1001)

    def create_xui_db(self, path: Path) -> None:
        conn = sqlite3.connect(path)
        conn.execute(
            """
            CREATE TABLE client_traffics (
                id INTEGER PRIMARY KEY,
                inbound_id INTEGER,
                enable numeric,
                email TEXT,
                up INTEGER,
                down INTEGER,
                expiry_time INTEGER,
                total INTEGER,
                reset INTEGER DEFAULT 0,
                last_online INTEGER DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE clients (
                id INTEGER PRIMARY KEY,
                email TEXT NOT NULL,
                total_gb INTEGER,
                expiry_time INTEGER,
                enable numeric,
                updated_at INTEGER
            )
            """
        )
        conn.execute("CREATE TABLE inbounds (id INTEGER PRIMARY KEY, settings TEXT)")
        settings = (
            '{"clients":[{"email":"tg_1001","enable":false,"totalGB":1,'
            '"expiryTime":0,"reset":0}]}'
        )
        conn.execute(
            """
            INSERT INTO client_traffics (
                inbound_id, enable, email, up, down, expiry_time, total, reset, last_online
            )
            VALUES (4, 0, 'tg_1001', 123, 456, 0, 1, 0, 0)
            """
        )
        conn.execute(
            "INSERT INTO clients (email, total_gb, expiry_time, enable, updated_at) VALUES ('tg_1001', 1, 0, 0, 0)"
        )
        conn.execute("INSERT INTO inbounds (id, settings) VALUES (4, ?)", (settings,))
        conn.commit()
        conn.close()


if __name__ == "__main__":
    unittest.main()
