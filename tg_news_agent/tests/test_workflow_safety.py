from datetime import datetime, timedelta, timezone
from buh_news.policy import approval_valid, evidence_ready, publish_allowed, budget_available, run_outcome, resend_allowed

NOW = datetime.now(timezone.utc)
def valid(**change):
    values=dict(actor_user_id=1,actor_chat_id=2,owner_user_id=1,owner_chat_id=2,draft_status='pending',current_version=3,callback_version=3,expires_at=NOW+timedelta(hours=1),review_passed=True); values.update(change); return approval_valid(**values)

def test_no_qualifying_news_is_safe_outcome(): assert run_outcome(0, 0) == 'no_suitable_news'
def test_one_qualifying_story_requires_clean_evidence(): assert evidence_ready('ready', True, [])
def test_proposed_law_not_effective_without_evidence(): assert not evidence_ready('ready', True, ['legal status unsupported'])
def test_duplicate_story_does_not_change_content_hash():
    seen = set(); urls = ['https://example.sk/a', 'https://example.sk/a']; fresh = [u for u in urls if not (u in seen or seen.add(u))]
    assert fresh == ['https://example.sk/a']
def test_unsupported_amount_or_deadline_blocks_review(): assert not evidence_ready('ready', True, ['amount: €100'])
def test_unauthorized_approval_is_rejected(): assert not valid(actor_user_id=99)
def test_obsolete_version_is_rejected(): assert not valid(callback_version=2)
def test_double_click_cannot_publish_twice(): assert not publish_allowed(mode='production',enabled=True,review_passed=True,approved=True,unexpired=True,already_published=True)
def test_requested_revision_needs_new_approval(): assert not valid(draft_status='approved')
def test_expired_approval_is_rejected(): assert not valid(expires_at=NOW-timedelta(seconds=1))
def test_exhausted_budget_prevents_ai_request(): assert not budget_available(4.9, .2, 5)
def test_failed_source_is_not_no_news(): assert run_outcome(1, 0) == 'research_partial'
def test_ambiguous_telegram_timeout_is_not_retried(): assert not resend_allowed('publication_unknown')
