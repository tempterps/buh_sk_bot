# BUH.SK standalone news agent

This agent is independent of the customer-service bot and persists its low-volume state in local files. It does not require PostgreSQL or n8n.

`data/state.json` contains sources, articles, drafts, approvals and outbox state. Writes are inter-process locked and atomic. `data/ai_usage.jsonl` is an append-only ledger containing each AI reservation, returned token use, reconciled cost, and held/failed call. `data/agent_trace.jsonl` records the full prompt and response for each ranking, writing, proofreading, and factual-review handoff. It can contain source/article content, so keep `data/` out of Git and back it up on the Ubuntu host. The agent sets its JSONL log files to owner-read/write only on Linux.

### Editorial learning from owner feedback

Owner actions (including rejected drafts, alternative selections, correction instructions, and final approvals) remain in the private, ignored `data/state.json`. Only an alternative eventually approved by the owner, or a correction followed by an approved revised post, becomes an active example. `data/editorial_examples.jsonl` stores the before/after Telegram text and correction instructions and/or the previous versus chosen ranked candidate. It does **not** include the source article's full text. A choice is a preference signal, not an explanation of *why* the owner chose it.

`editorial/prompts/*.md` contains editable editorial addenda. The ranking, writing, and proofreading stages read recent examples directly from `data/editorial_examples.jsonl` on the same server. At most two short examples and 5,000 characters are supplied per main prompt, keeping token use bounded. The next run can use newly approved feedback without a Git push, PR, or redeploy. Core evidence and publication safety checks remain in Python.

An approved example is saved immediately by the Telegram listener; hourly maintenance retries if that write failed or the bot was interrupted. To backfill past approvals manually, run `.venv/bin/python -m buh_news feedback-sync` as the `buhnews` service user. `data/` is ignored by Git: do not commit the example file, which can contain private owner instructions. Back it up with `data/state.json` on the Ubuntu host. The obsolete GitHub feedback timer is disabled by the updated installer.

## Essential Telegram constraint

The agent needs to receive approval callbacks and revision replies. Give it a **dedicated Telegram bot token** in `SEPARATE_TELEGRAM_BOT_TOKEN`. Do not run its `bot` command with the same token as a customer-service bot that is already polling/webhooking on another server: Telegram delivers a bot's updates to one consumer, so approval controls would be unreliable.

If the existing customer bot must be used, its server must securely forward only authenticated owner callback/revision events to this agent; that integration is not included here.

## Deploy on Ubuntu

Use the supplied systemd deployment, not a permanently sleeping worker container. The Telegram approval bot must stay online for callbacks; the research worker runs once per day and exits. Docker Compose remains available for local development, but systemd is the production setup for `/opt/buh_sk_news_bot/tg_news_agent`.

```bash
mkdir -p /opt/buh_sk_news_bot
# clone/copy the repository into /opt/buh_sk_news_bot and place .env in tg_news_agent
cd /opt/buh_sk_news_bot/tg_news_agent
sudo bash deploy/ubuntu/setup_ubuntu.sh
```

The one-time installer creates the `buhnews` service user, Python environment, persistent approval listener, daily 18:00 Europe/Bratislava research timer, hourly expiry timer, and systemd units. Put the private Healthchecks URL in `HEALTHCHECKS_PING_URL` in `.env`; it is pinged only after a successful daily worker run. Keep `NEWS_MODE=preview` and `PUBLISHING_ENABLED=false` until production is explicitly ready.

### Runtime responsibilities

`buh-news-agent.service` is the always-on Telegram listener. It receives only owner approval/change callbacks and, after a change selection, creates a new checked draft. `buh-news-research.service` is a one-shot complete research workflow: discovery, ranking, article writing, proofreading, factual review, and Telegram preview delivery. It automatically requires the listener and is normally started by the daily timer; manually starting this one service runs the same end-to-end workflow. `buh-news-maintenance.service` expires old approvals hourly. The OpenAI ranking, writing, proofreading, and review stages are sequential calls inside the research worker, not additional Linux services.

Official sources in the allowlist (MF SR, Finančná správa, Sociálna poisťovňa, NBS) skip the extra AI factual-review call only when the fetched final URL is HTTPS on that source's registered domain. Source evidence, proofreading, Ukrainian-language and length checks still apply. If a replacement topic fails editorial validation, it is excluded from that run's choices and the owner immediately gets the next three available topics. The owner can press **Виправити**, send one text instruction, and receive a fully revised post for review; the instruction does not directly replace the post. Corrections are limited by `MAX_AI_REVISIONS_PER_DRAFT`.

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
