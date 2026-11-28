#!/usr/bin/env bash
# Runs once under systemd.  A successful safe outcome (including no suitable
# news) pings Healthchecks; an exception leaves the timer run failed.
set -Eeuo pipefail

readonly APP_DIR=/opt/buh_sk_news_bot/tg_news_agent
readonly PYTHON_BIN="$APP_DIR/.venv/bin/python"

cd "$APP_DIR"
"$PYTHON_BIN" -m buh_news run

if [[ -n "${HEALTHCHECKS_PING_URL:-}" ]]; then
  curl --fail --silent --show-error --max-time 15 --proto '=https' \
    "$HEALTHCHECKS_PING_URL" >/dev/null
fi
