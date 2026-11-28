# BUH.SK standalone news agent

This agent is independent of the customer-service bot and persists its low-volume state in local files. It does not require PostgreSQL or n8n.

`data/state.json` contains sources, articles, drafts, approvals and outbox state. Writes are inter-process locked and atomic. `data/ai_usage.jsonl` is an append-only ledger containing each AI reservation, returned token use, reconciled cost, and held/failed call. `data/agent_trace.jsonl` records the full prompt and response for each ranking, writing, proofreading, and factual-review handoff. It can contain source/article content, so keep `data/` out of Git and back it up on the Ubuntu host. The agent sets its JSONL log files to owner-read/write only on Linux.

## Essential Telegram constraint

The agent needs to receive approval callbacks and revision replies. Give it a **dedicated Telegram bot token** in `SEPARATE_TELEGRAM_BOT_TOKEN`. Do not run its `bot` command with the same token as a customer-service bot that is already polling/webhooking on another server: Telegram delivers a bot's updates to one consumer, so approval controls would be unreliable.

If the existing customer bot must be used, its server must securely forward only authenticated owner callback/revision events to this agent; that integration is not included here.

## Deploy on Ubuntu

```bash
sudo useradd --system --create-home buhnews
sudo mkdir -p /opt/buh-news-agent
sudo chown buhnews:buhnews /opt/buh-news-agent
cd /opt/buh-news-agent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env && chmod 600 .env
# fill the required values; keep NEWS_MODE=preview and PUBLISHING_ENABLED=false
.venv/bin/python -m buh_news migrate
.venv/bin/python -m buh_news seed-sources
```

Docker Compose mounts `./data` into the application container, so state survives container replacement.

## Validate sources and test privately

```bash
.venv/bin/python -m buh_news source-test --source social_insurance
```

The command prints retrieved titles, raw/normalized dates, HTTP status and resolved final article URLs. After two successful checks, enable a source by changing its `enabled` field in `data/state.json` while the bot/worker is stopped. Start with primary official feeds only.

For the private preview test, start the dedicated approval bot, then run the worker separately:

```bash
.venv/bin/python -m buh_news bot
# separate terminal
.venv/bin/python -m buh_news run
```

The editorial note includes the run's AI cost. Its exact content is also durably recorded in `data/ai_usage.jsonl`. `preview` mode only acknowledges approval privately; it does not post to a channel.

## Pricing and production

Set `PRICE_TABLE_VERIFIED_ON` and all four per-million-token price values from the current official OpenAI pricing page before any AI call. Until then, the agent blocks the call rather than assuming it is free.

Enable real publishing only after a private test: set `NEWS_MODE=production` and `PUBLISHING_ENABLED=true`, verify the bot is an administrator of `@buh_sk_ua`, and restart the service. To pause immediately, set `PUBLISHING_ENABLED=false` and restart. A Telegram send with ambiguous outcome becomes `publication_unknown` and is never retried automatically.

Use the supplied systemd services/timers after changing their `WorkingDirectory` and virtualenv paths to match the deployment location. An external heartbeat monitor is still needed to detect a complete VPS outage.
