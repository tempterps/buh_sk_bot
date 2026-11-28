from datetime import datetime
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from buh_news.db import FileStore
from buh_news.discovery import Item
from buh_news.pipeline import ResearchPipeline


def test_manual_run_bypasses_only_daily_draft_limit(tmp_path, monkeypatch):
    store = FileStore(tmp_path)
    tz = ZoneInfo('Europe/Bratislava')
    today = datetime.now(tz).isoformat()
    with store.locked() as state:
        state['drafts']['earlier'] = {'created_at': today}
        state['sources']['test'] = {'id': 'test', 'enabled': True, 'priority': 1, 'method': 'rss'}

    settings = SimpleNamespace(user_agent='test', timezone=tz, max_candidates=30,
                               max_articles=3, max_daily_drafts=1, approval_hours=24,
                               ranking_model='rank', writing_model='write')
    sent = []
    pipeline = ResearchPipeline(store, settings, SimpleNamespace(send_preview=sent.append))
    item = Item('test', 'Test headline', 'https://example.org/news', datetime.now(tz),
                None, [], 'Test summary')
    monkeypatch.setattr('buh_news.pipeline.seed_sources', lambda _store: None)
    monkeypatch.setattr(pipeline.fetcher, 'feed', lambda _source: ([item], SimpleNamespace(headers={})))
    monkeypatch.setattr('buh_news.pipeline.extract_article', lambda _fetcher, url: (url, 'Full article'))

    def fake_ai(_run_id, stage, *_args):
        if stage == 'ranking':
            return {'rankings': [{'candidate_id': 1, 'topic_key': 'test-topic',
                                  'owner_title': 'Test', 'audience_impact': 'Test impact',
                                  'personal_relevance': 2, 'practical_impact': 2, 'surprise': 2,
                                  'shareability': 2, 'service_relevance': 2,
                                  'needs_primary_verification': False, 'recommendation': 'select'}]}
        return {'status': 'ready', 'post': '<b>Test post</b>', 'evidence': {}}

    monkeypatch.setattr(pipeline.ai, 'call', fake_ai)
    monkeypatch.setattr(pipeline, '_proofread', lambda _run_id, draft: draft['post'])
    monkeypatch.setattr(pipeline, '_review', lambda *_args: {'passed': True, 'unsupported_claims': []})

    assert pipeline.run() == 'no_suitable_news'
    assert sent == []
    assert pipeline.run(manual=True) == 'draft_created'
    assert len(sent) == 1
    with store.locked() as state:
        assert len(state['drafts']) == 2
        assert [run['manual'] for run in state['research_runs'].values()] == [False, True]


def test_manual_flag_reaches_pipeline(tmp_path, monkeypatch, capsys):
    from buh_news import __main__ as cli

    seen = []
    monkeypatch.setattr(sys, 'argv', ['buh_news', 'run', '--manual'])
    monkeypatch.setattr(cli, 'settings', lambda **_kwargs: SimpleNamespace(data_dir=tmp_path))
    monkeypatch.setattr(cli, 'seed_sources', lambda _store: None)
    monkeypatch.setattr(cli, 'OwnerBot', lambda *_args: object())

    class FakePipeline:
        def __init__(self, *_args):
            pass

        def run(self, manual=False):
            seen.append(manual)
            return 'draft_created'

    monkeypatch.setattr(cli, 'ResearchPipeline', FakePipeline)
    cli.main()
    assert seen == [True]
    assert capsys.readouterr().out.strip() == 'draft_created'
