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

Example multi-profile setup. Emoji at the start of `title` is shown by HAPP as a profile icon,
while the visible name stays short: `vpn1`, `vpn2`, `vpn3`.

```env
VPN_PROFILES_JSON=[{"code":"xhttp","title":"🇫🇷 vpn1","inbound_id":4,"host":"panel-l.andreev-it.ru","port":16347,"transport_type":"xhttp","security":"none","xhttp_path":"/","xhttp_mode":"auto"},{"code":"reality_tcp_1","title":"🇺🇸 vpn2","inbound_id":5,"host":"panel-l.andreev-it.ru","port":443,"transport_type":"tcp","security":"reality","flow":"xtls-rprx-vision","reality_public_key":"...","reality_short_id":"...","reality_server_name":"www.cloudflare.com","reality_fingerprint":"firefox","reality_spider_x":"/"},{"code":"reality_tcp_2","title":"🇳🇱 vpn3","inbound_id":6,"host":"panel-l.andreev-it.ru","port":2443,"transport_type":"tcp","security":"reality","flow":"xtls-rprx-vision","reality_public_key":"...","reality_short_id":"...","reality_server_name":"www.cloudflare.com","reality_fingerprint":"firefox","reality_spider_x":"/"}]
```

## Payments

The bot supports Telegram Payments. By default, payments use Telegram Stars:

```env
PAYMENT_CURRENCY=XTR
PAYMENT_PROVIDER_TOKEN=
```

For fiat payments, switch the currency and add a provider token:

```env
PAYMENT_PROVIDER_TOKEN=...
PAYMENT_CURRENCY=RUB
```

If `PAYMENT_CURRENCY=XTR`, `PAYMENT_PROVIDER_TOKEN` must stay empty. If another currency is used and
`PAYMENT_PROVIDER_TOKEN` is empty, the bot will show payment options as unavailable and will ask the user
to contact the administrator.

### What is a payment provider token?

Telegram does not process card payments by itself. A payment provider token is a secret key that connects
your bot to a payment provider supported by Telegram, for example YooKassa, Stripe, PayMaster, Robokassa,
or another provider available in BotFather.

Typical setup:

1. Open BotFather.
2. Choose your bot.
3. Open payments.
4. Choose a provider.
5. Connect your merchant account.
6. Copy the provider token into `PAYMENT_PROVIDER_TOKEN`.

Without this token, the bot can still accept Telegram Stars payments, but cannot accept automatic fiat
payments.

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
