# ANDREVPN Telegram Bot

Telegram bot for selling and managing ANDREVPN subscriptions with 3X-UI integration.

## What is included

- Welcome screen and ANDREVPN service description.
- User cabinet with subscription expiration date.
- Payment and subscription renewal through Telegram invoices.
- HAPP setup instructions.
- 3X-UI client provisioning through one or more selected inbounds/protocols.
- Automatic subscription expiration reminders 3 days, 1 day, and 1 hour before expiration.
- SQLite storage for users and payments.

## Quick Start

1. Create a bot with BotFather and get `BOT_TOKEN`.
2. Copy `.env.example` to `.env`.
3. Fill in Telegram, payment, and 3X-UI settings.
4. Install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

5. Start the bot:

```powershell
.\.venv\Scripts\python.exe -m andrevpn_bot
```

On Ubuntu:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m andrevpn_bot
```

## 3X-UI Notes

Create or choose one or more inbounds in 3X-UI, for example VLESS XHTTP and VLESS Reality.
For one inbound, put its ID into `XUI_INBOUND_ID`. For several variants in one HAPP subscription,
configure `VPN_PROFILES_JSON`.

Current ANDREVPN inbound settings:

- Inbound ID: `4`
- Protocol: `VLESS`
- Transport: `XHTTP`
- Security: `none`
- Port: `16347`
- User traffic limit: `107374182400` bytes, about 100 GB

For HAPP, use the bot subscription endpoint and put its public base URL into
`VPN_SUBSCRIPTION_BASE_URL`:

```env
VPN_SUBSCRIPTION_BASE_URL=https://panel-l.andreev-it.ru:2097/sub
```

The bot will show users a personal subscription link based on their `subId`. If `VPN_PROFILES_JSON`
contains several profiles, the same subscription link will return several VLESS nodes, and HAPP will
let the user choose between them.

### Monthly Traffic Reset

Every active user gets a monthly traffic reset for every configured VPN inbound/profile. The bot stores
successful resets in its own SQLite table `traffic_resets`, keyed by Telegram user, inbound id, and month.
This makes the job idempotent: a bot restart or repeated check will not reset the same user twice for the
same month.

The task runs every 3 hours by default and also runs once soon after bot startup:

```env
XUI_DB_PATH=/etc/x-ui/x-ui.db
TRAFFIC_RESET_INTERVAL_SECONDS=10800
```

For each active user and inbound, the bot resets 3X-UI `client_traffics.up` and `client_traffics.down`
to `0`, restores `enable=1`, keeps the configured `XUI_TOTAL_GB` limit, and refreshes the client through
the existing 3X-UI provisioning path. If a reset fails for one inbound, it is not marked as done and the
bot will retry later. The administrator receives a Telegram notification about failures.

If a client reached the 100 GB limit before reset, they may need to reconnect or refresh the HAPP
subscription after the reset.

Example multi-profile setup. Emoji at the start of `title` is shown by HAPP as a profile icon,
while the visible name stays short: `vpn1`, `vpn2`, `vpn3`.

```env
VPN_PROFILES_JSON=[{"code":"xhttp","title":"🇫🇷 vpn1","inbound_id":4,"host":"panel-l.andreev-it.ru","port":16347,"transport_type":"xhttp","security":"none","xhttp_path":"/","xhttp_mode":"auto"},{"code":"reality_tcp_1","title":"🇺🇸 vpn2","inbound_id":5,"host":"panel-l.andreev-it.ru","port":443,"transport_type":"tcp","security":"reality","flow":"xtls-rprx-vision","reality_public_key":"...","reality_short_id":"...","reality_server_name":"www.cloudflare.com","reality_fingerprint":"firefox","reality_spider_x":"/"},{"code":"reality_tcp_2","title":"🇳🇱 vpn3","inbound_id":6,"host":"panel-l.andreev-it.ru","port":2443,"transport_type":"tcp","security":"reality","flow":"xtls-rprx-vision","reality_public_key":"...","reality_short_id":"...","reality_server_name":"www.cloudflare.com","reality_fingerprint":"firefox","reality_spider_x":"/"}]
```

## Payments

The bot supports two automatic payment scenarios:

- Telegram Stars through Telegram invoices.
- SBP through YooKassa redirect payments and webhook verification.

By default, Telegram Stars stay enabled through `PLANS`:

```env
PAYMENT_CURRENCY=XTR
PAYMENT_PROVIDER_TOKEN=
PLANS=month:1 месяц:80:30,two_months:2 месяца:150:60,quarter:3 месяца:200:90
```

SBP tariffs are configured separately and do not reuse Stars prices:

```env
SBP_PLANS=month:1 месяц:150:30,two_months:2 месяца:250:60,quarter:3 месяца:350:90
```

If `YOOKASSA_ENABLED=false`, the SBP button is hidden from users. Telegram Stars continue to work.

### YooKassa SBP

YooKassa SBP uses direct YooKassa API calls, not Telegram provider tokens. The bot creates a local
`payment_orders` record first, then creates a YooKassa payment with `payment_method_data.type=sbp`,
`confirmation.type=redirect`, `capture=true`, and a stored `Idempotence-Key`.

The subscription is extended only after a server-side `GET /payments/{payment_id}` confirms:

- `status=succeeded` and `paid=true`;
- amount and currency match the local order;
- payment method is `sbp`;
- YooKassa metadata matches local order id, Telegram id, and plan code.

Required `.env` values:

```env
YOOKASSA_ENABLED=true
YOOKASSA_SHOP_ID=
YOOKASSA_SECRET_KEY=
YOOKASSA_API_BASE_URL=https://api.yookassa.ru/v3
YOOKASSA_RETURN_URL=https://panel-l.andreev-it.ru:8443/payments/yookassa/return
YOOKASSA_WEBHOOK_PUBLIC_URL=https://panel-l.andreev-it.ru:8443/payments/yookassa/webhook
YOOKASSA_LISTEN_HOST=0.0.0.0
YOOKASSA_LISTEN_PORT=8443
YOOKASSA_CERT_FILE=/root/cert/panel-l.andreev-it.ru/fullchain.pem
YOOKASSA_KEY_FILE=/root/cert/panel-l.andreev-it.ru/privkey.pem
YOOKASSA_TIMEOUT_SECONDS=15
SBP_PLANS=month:1 месяц:150:30,two_months:2 месяца:250:60,quarter:3 месяца:350:90
```

Webhook must be publicly available through HTTPS on TCP port `443` or `8443`. Do not use the existing
subscription port `2097` for YooKassa notifications. If port `443` is already used by Xray/VLESS Reality,
use `8443` with the same domain certificate.

Setup in YooKassa:

1. Open the YooKassa merchant cabinet.
2. Make sure SBP is enabled for the shop.
3. Copy `shopId` into `YOOKASSA_SHOP_ID` and the secret key into `YOOKASSA_SECRET_KEY`.
4. In Integration -> HTTP notifications, set `YOOKASSA_WEBHOOK_PUBLIC_URL`.
5. Enable at least `payment.succeeded` and `payment.canceled`.
6. Restart the bot and check logs:

```bash
systemctl restart andrevpn-bot
systemctl status andrevpn-bot
journalctl -u andrevpn-bot -n 100 --no-pager
```

Run a real production payment only after you separately decide to do so. For test shops, SBP availability
depends on the current YooKassa account settings.

Important for self-employed sellers: accepting payment in YooKassa and issuing a fiscal receipt are
different processes. Automatic YooKassa receipts for self-employed sellers were discontinued on
2025-12-29. This bot does not create receipts in "My Tax"; decide the receipt process separately according
to current YooKassa settings and FNS requirements.

### What is a payment provider token?

`PAYMENT_PROVIDER_TOKEN` is only for Telegram fiat invoices. ANDREVPN currently uses Telegram Stars
through Telegram invoices and SBP through direct YooKassa API, so this value can stay empty when
`PAYMENT_CURRENCY=XTR`.

## Server Deploy From GitHub

After the project is pushed to GitHub, run this on the Ubuntu server:

```bash
export REPO_URL=https://github.com/<user>/<repo>.git
bash deploy/install_server.sh
```

Then fill `/opt/andrevpn-bot/.env` and restart:

```bash
systemctl restart andrevpn-bot
systemctl status andrevpn-bot
```

## Tariffs

Default tariffs are configured in `.env.example` through `PLANS`.

Format:

```env
PLANS=month:1 месяц:80:30,two_months:2 месяца:150:60,quarter:3 месяца:200:90
```

Each tariff is:

```text
code:title:price:days
```

For `RUB`, price is in rubles. For currencies without minor units, set exact integer values.
