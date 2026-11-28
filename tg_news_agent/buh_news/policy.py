from __future__ import annotations
from datetime import datetime

def approval_valid(*, actor_user_id: int, actor_chat_id: int, owner_user_id: int, owner_chat_id: int, draft_status: str, current_version: int, callback_version: int, expires_at: datetime, review_passed: bool) -> bool:
    return (actor_user_id == owner_user_id and actor_chat_id == owner_chat_id and review_passed
            and draft_status in {'pending', 'revision_requested'} and current_version == callback_version
            and expires_at > datetime.now(expires_at.tzinfo))

def publish_allowed(*, mode: str, enabled: bool, review_passed: bool, approved: bool, unexpired: bool, already_published: bool) -> bool:
    return mode == 'production' and enabled and review_passed and approved and unexpired and not already_published

def evidence_ready(status: str, passed: bool, unsupported_claims: list[str]) -> bool:
    return status == 'ready' and passed and not unsupported_claims

def budget_available(spent_or_reserved: float, requested: float, monthly_limit: float) -> bool:
    return spent_or_reserved + requested <= monthly_limit

def run_outcome(source_failures: int, candidate_count: int) -> str:
    return 'research_partial' if source_failures else ('no_suitable_news' if not candidate_count else 'candidates_found')

def resend_allowed(outbox_status: str) -> bool:
    return outbox_status == 'queued'

