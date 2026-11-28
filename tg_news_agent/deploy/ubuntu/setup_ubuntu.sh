#!/usr/bin/env bash
# One-time Ubuntu installation. Run as root from /opt/buh_sk_news_bot/tg_news_agent after
# copying this repository and its populated .env file to the server.
set -Eeuo pipefail

readonly APP_DIR=/opt/buh_sk_news_bot/tg_news_agent
readonly SERVICE_USER=buhnews
readonly SERVICE_GROUP=buhnews
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo 'Run with: sudo bash deploy/ubuntu/setup_ubuntu.sh' >&2
  exit 1
fi
if [[ "$PROJECT_DIR" != "$APP_DIR" ]]; then
  echo "Copy the project to $APP_DIR first; current project is $PROJECT_DIR" >&2
  exit 1
fi
if [[ ! -f "$APP_DIR/.env" ]]; then
  echo "Missing $APP_DIR/.env. Copy .env.example to .env and fill its values first." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends python3 python3-venv curl ca-certificates

if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --user-group --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0700 "$APP_DIR/data"
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$APP_DIR"
chmod 0600 "$APP_DIR/.env"
chmod 0750 "$APP_DIR/deploy/ubuntu/run-research.sh"

if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
  runuser -u "$SERVICE_USER" -- python3 -m venv "$APP_DIR/.venv"
fi
runuser -u "$SERVICE_USER" -- "$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
runuser -u "$SERVICE_USER" -- "$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

# Validate runtime values without printing secrets. Healthchecks is mandatory
# because the daily timer is otherwise invisible when a VPS fails silently.
runuser -u "$SERVICE_USER" -- env APP_DIR="$APP_DIR" "$APP_DIR/.venv/bin/python" - <<'PY'
import os
from pathlib import Path
os.chdir(os.environ['APP_DIR'])
from buh_news.config import settings
settings(require_runtime=True)
url=os.getenv('HEALTHCHECKS_PING_URL','')
if not url.startswith('https://hc-ping.com/'):
    raise SystemExit('HEALTHCHECKS_PING_URL must be an https://hc-ping.com/... URL')
PY

install -m 0644 "$APP_DIR/systemd/buh-news-agent.service" /etc/systemd/system/buh-news-agent.service
install -m 0644 "$APP_DIR/systemd/buh-news-research.service" /etc/systemd/system/buh-news-research.service
install -m 0644 "$APP_DIR/systemd/buh-news-research.timer" /etc/systemd/system/buh-news-research.timer
install -m 0644 "$APP_DIR/systemd/buh-news-maintenance.service" /etc/systemd/system/buh-news-maintenance.service
install -m 0644 "$APP_DIR/systemd/buh-news-maintenance.timer" /etc/systemd/system/buh-news-maintenance.timer

systemctl daemon-reload
systemctl enable --now buh-news-agent.service buh-news-research.timer buh-news-maintenance.timer
systemctl restart buh-news-agent.service

echo 'Installation complete.'
systemctl --no-pager --full status buh-news-agent.service
systemctl list-timers --all 'buh-news-*'
