from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}

def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))

@dataclass(frozen=True)
class Settings:
    data_dir: Path
    telegram_token: str
    owner_user_id: int
    owner_chat_id: int
    openai_key: str
    mode: str
    publishing_enabled: bool
    production_channel_id: str
    test_channel_id: str | None
    timezone: ZoneInfo
    max_candidates: int
    max_queries: int
    max_articles: int
    max_daily_drafts: int
    approval_hours: int
    max_revisions: int
    monthly_budget: Decimal
    ranking_model: str
    writing_model: str
    api_url: str
    searxng_url: str | None
    user_agent: str
    price_verified_on: str | None
    ranking_input_price: Decimal | None
    ranking_output_price: Decimal | None
    writing_input_price: Decimal | None
    writing_output_price: Decimal | None
    feedback_pr_enabled: bool
    feedback_github_token: str
    feedback_github_repo: str
    feedback_pr_base_branch: str
    feedback_allow_public_repo: bool

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openai_key and self.price_verified_on and all((
            self.ranking_input_price, self.ranking_output_price,
            self.writing_input_price, self.writing_output_price,
        )))

def _price(name: str) -> Decimal | None:
    value = os.getenv(name, "").strip()
    return Decimal(value) if value else None

def settings(require_runtime: bool = True) -> Settings:
    # The dedicated approval bot owns callback updates.  Retain the former name
    # solely so existing deployments continue to start during migration.
    token = os.getenv("SEPARATE_TELEGRAM_BOT_TOKEN", "") or os.getenv("NEWS_TELEGRAM_BOT_TOKEN", "")
    owner_id = os.getenv("OWNER_TELEGRAM_USER_ID", "")
    owner_chat = os.getenv("OWNER_TELEGRAM_CHAT_ID", "")
    missing = [name for name, value in {
        "SEPARATE_TELEGRAM_BOT_TOKEN (or legacy NEWS_TELEGRAM_BOT_TOKEN)": token,
        "OWNER_TELEGRAM_USER_ID": owner_id, "OWNER_TELEGRAM_CHAT_ID": owner_chat,
    }.items() if not value]
    if require_runtime and missing:
        raise RuntimeError("Missing required environment variables: " + ", ".join(missing))
    return Settings(
        data_dir=Path(os.getenv("NEWS_DATA_DIR", "./data")), telegram_token=token, owner_user_id=int(owner_id or 0),
        owner_chat_id=int(owner_chat or 0), openai_key=os.getenv("OPENAI_API_KEY", ""),
        mode=os.getenv("NEWS_MODE", "preview").lower(), publishing_enabled=_bool("PUBLISHING_ENABLED"),
        production_channel_id=os.getenv("PRODUCTION_CHANNEL_ID", "@buh_sk_ua"),
        test_channel_id=os.getenv("TEST_CHANNEL_ID") or None, timezone=ZoneInfo(os.getenv("TIMEZONE", "Europe/Bratislava")),
        max_candidates=_int("MAX_CANDIDATES_PER_RUN", 30), max_queries=_int("MAX_SEARCH_QUERIES_PER_RUN", 6),
        max_articles=_int("MAX_FULL_ARTICLES_PER_RUN", 3), max_daily_drafts=_int("MAX_NEW_DRAFTS_PER_DAY", 1),
        approval_hours=_int("APPROVAL_EXPIRY_HOURS", 24), max_revisions=_int("MAX_AI_REVISIONS_PER_DRAFT", 2),
        monthly_budget=Decimal(os.getenv("MONTHLY_AI_BUDGET_USD", "5")),
        ranking_model=os.getenv("OPENAI_RANKING_MODEL", "gpt-5.4-nano"), writing_model=os.getenv("OPENAI_WRITING_MODEL", "gpt-5.4-mini"),
        api_url=os.getenv("OPENAI_API_URL", "https://api.openai.com/v1/responses"),
        searxng_url=os.getenv("SEARXNG_URL") or None, user_agent=os.getenv("USER_AGENT", "BUH.SK news research bot/1.0"),
        price_verified_on=os.getenv("PRICE_TABLE_VERIFIED_ON") or None,
        ranking_input_price=_price("RANKING_INPUT_USD_PER_1M"), ranking_output_price=_price("RANKING_OUTPUT_USD_PER_1M"),
        writing_input_price=_price("WRITING_INPUT_USD_PER_1M"), writing_output_price=_price("WRITING_OUTPUT_USD_PER_1M"),
        feedback_pr_enabled=_bool("FEEDBACK_PR_ENABLED"),
        feedback_github_token=os.getenv("FEEDBACK_GITHUB_TOKEN", ""),
        feedback_github_repo=os.getenv("FEEDBACK_GITHUB_REPO", ""),
        feedback_pr_base_branch=os.getenv("FEEDBACK_PR_BASE_BRANCH", "Stage1"),
        feedback_allow_public_repo=_bool("FEEDBACK_ALLOW_PUBLIC_REPO"),
    )

