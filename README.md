# ANDREVPN Telegram Bot

Telegram bot for selling and managing ANDREVPN subscriptions with 3X-UI integration.

## What is included

- Welcome screen and ANDREVPN service description.
- User cabinet with subscription expiration date.
- Payment and subscription renewal through Telegram invoices.
- HAPP setup instructions.
- 3X-UI client provisioning through one selected inbound/protocol.
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

Create or choose one inbound in 3X-UI, for example VLESS. Put its ID into `XUI_INBOUND_ID`.
All bot-created users will be added to this inbound, so every user receives the same protocol type.

Current ANDREVPN inbound settings:

- Inbound ID: `2`
- Protocol: `VLESS`
- Transport: `RAW`
- Security: `reality`
- Port: `55804`
- User traffic limit: `107374182400` bytes, about 100 GB

For HAPP, it is best to enable the 3X-UI subscription service and put its public base URL into
`VPN_SUBSCRIPTION_BASE_URL`, for example:

```env
VPN_SUBSCRIPTION_BASE_URL=https://panel-l.andreev-it.ru:2096/user/
```

The bot will show users a personal subscription link based on their `subId`.

## Payments

The bot supports Telegram Payments. Add your provider token to:

```env
PAYMENT_PROVIDER_TOKEN=...
PAYMENT_CURRENCY=RUB
```

If `PAYMENT_PROVIDER_TOKEN` is empty, the bot will show payment options as unavailable and will ask the
user to contact the administrator.

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

Without this token, the bot can show tariffs but cannot accept automatic payments.

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
PLANS=month:1 месяц:199:30,quarter:3 месяца:499:90,year:1 год:1490:365
```

Each tariff is:

```text
code:title:price:days
```

For `RUB`, price is in rubles. For currencies without minor units, set exact integer values.
