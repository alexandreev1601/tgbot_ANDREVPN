#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/andrevpn-bot}"
REPO_URL="${REPO_URL:-}"
SERVICE_NAME="${SERVICE_NAME:-andrevpn-bot}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ -z "$REPO_URL" ]]; then
  echo "REPO_URL is required, for example:"
  echo "REPO_URL=https://github.com/<user>/<repo>.git bash deploy/install_server.sh"
  exit 1
fi

apt-get update
apt-get install -y git python3 python3-venv ca-certificates

if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" pull --ff-only
else
  rm -rf "$APP_DIR"
  git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
$PYTHON_BIN -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

if [[ ! -f "$APP_DIR/.env" ]]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
  echo "Created $APP_DIR/.env. Fill it before starting the service."
fi

cat >"/etc/systemd/system/${SERVICE_NAME}.service" <<UNIT
[Unit]
Description=ANDREVPN Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/python -m andrevpn_bot
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
systemctl --no-pager --full status "$SERVICE_NAME"

