from datetime import datetime
import json
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from buh_news.db import FileStore
from buh_news.discovery import Item
from buh_news.pipeline import ResearchPipeline
from buh_news.ai import AIResponseFormatError


def test_manual_run_bypasses_only_daily_draft_limit(tmp_path, monkeypatch):
    store = FileStore(tmp_path)
    tz = ZoneInfo('Europe/Bratislava')
    today = datetime.now(tz).isoformat()
    with store.locked() as state:
        state['drafts']['earlier'] = {'created_at': today}
        state['sources']['kros_legislation'] = {'id': 'kros_legislation', 'enabled': True,
                                                'priority': 1, 'method': 'rss'}

    settings = SimpleNamespace(user_agent='test', timezone=tz, max_candidates=30,
                               max_articles=3, max_daily_drafts=1, approval_hours=24,
                               ranking_model='rank', writing_model='write')
    sent = []
    pipeline = ResearchPipeline(store, settings, SimpleNamespace(send_preview=sent.append))
    item = Item('kros_legislation', 'Test headline', 'https://www.kros.sk/blog/news', datetime.now(tz),
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
                                  'needs_primary_verification': True, 'recommendation': 'hold'}]}
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
        runs = sorted(state['research_runs'].values(), key=lambda run: run['started_at'])
        assert [run['manual'] for run in runs] == [False, True]
    entries = [json.loads(line) for line in store.run_log_path.read_text(encoding='utf-8').splitlines()]
    assert [(entry['event'], entry['manual']) for entry in entries] == [
        ('started', False), ('finished', False), ('started', True), ('finished', True)]
    assert entries[1]['stop_reason'] == 'daily_draft_limit_reached'
    assert entries[3]['stop_reason'] == 'draft_sent_for_approval'
    assert entries[3]['draft_id'] == sent[0]
    assert entries[3]['ranked_candidates'][0]['recommendation'] == 'hold'
    assert entries[3]['ranked_candidates'][0]['needs_primary_verification'] is False


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


def test_low_ranked_stories_are_offered_when_none_qualify(tmp_path, monkeypatch):
    from buh_news.telegram import OwnerBot
    store = FileStore(tmp_path)
    tz = ZoneInfo('Europe/Bratislava')
    with store.locked() as state:
        state['sources']['kros_legislation'] = {'id': 'kros_legislation', 'enabled': True,
                                                'priority': 1, 'method': 'rss'}
    settings = SimpleNamespace(user_agent='test', timezone=tz, max_candidates=30,
                               ranking_model='rank', approval_hours=24, owner_chat_id=123)
    owner = object.__new__(OwnerBot)
    owner.store = store
    owner.s = settings
    sent = []
    owner.bot = SimpleNamespace(send_message=lambda _chat_id, text, **kwargs: sent.append((text, kwargs)))
    pipeline = ResearchPipeline(store, settings, owner)
    items = [Item('kros_legislation', f'Headline {i}', f'https://www.kros.sk/blog/news-{i}',
                  datetime.now(tz), None, [], f'Summary {i}') for i in range(1, 5)]
    monkeypatch.setattr('buh_news.pipeline.seed_sources', lambda _store: None)
    monkeypatch.setattr(pipeline.fetcher, 'feed', lambda _source: (items, SimpleNamespace(headers={})))
    def rank(_run_id, stage, *_args):
        assert stage == 'ranking'
        return {'rankings': [
            {'candidate_id': i, 'topic_key': f'topic-{i}', 'owner_title': f'Тема {i}',
             'audience_impact': f'Суть {i}', 'personal_relevance': 1, 'practical_impact': 1,
             'surprise': 1, 'shareability': 1, 'service_relevance': 0,
             'needs_primary_verification': True, 'recommendation': 'reject'}
            for i in range(1, 5)]}
    monkeypatch.setattr(pipeline.ai, 'call', rank)
    assert pipeline.run(manual=True) == 'owner_choice_pending'
    with store.locked() as state:
        run = next(iter(state['research_runs'].values()))
        assert run['owner_choice']['candidate_ids'] == [1, 2, 3]
        assert state['drafts'] == {}
    assert 'Тема 3' in sent[-1][0]
    assert 'Тема 4' not in sent[-1][0]


def test_incomplete_ranking_is_retried_in_small_batches(tmp_path, monkeypatch):
    from buh_news.telegram import OwnerBot
    store = FileStore(tmp_path)
    tz = ZoneInfo('Europe/Bratislava')
    with store.locked() as state:
        state['sources']['kros_legislation'] = {'id': 'kros_legislation', 'enabled': True,
                                                'priority': 1, 'method': 'rss'}
    settings = SimpleNamespace(user_agent='test', timezone=tz, max_candidates=30,
                               ranking_model='rank', approval_hours=24, owner_chat_id=123)
    owner = object.__new__(OwnerBot)
    owner.store = store
    owner.s = settings
    sent = []
    owner.bot = SimpleNamespace(send_message=lambda _chat_id, text, **kwargs: sent.append(text))
    pipeline = ResearchPipeline(store, settings, owner)
    items = [Item('kros_legislation', f'Headline {i}', f'https://www.kros.sk/blog/news-{i}',
                  datetime.now(tz), None, [], f'Summary {i}') for i in range(1, 13)]
    monkeypatch.setattr('buh_news.pipeline.seed_sources', lambda _store: None)
    monkeypatch.setattr(pipeline.fetcher, 'feed', lambda _source: (items, SimpleNamespace(headers={})))
    calls = []
    def rank(_run_id, stage, _model, prompt, _schema, _max_input, max_output):
        calls.append(max_output)
        if len(calls) == 1:
            raise AIResponseFormatError('incomplete ranking response: max_output_tokens')
        import json
        candidates = json.loads(prompt.split('CANDIDATES=', 1)[1].split('\n', 1)[0])
        return {'rankings': [
            {'candidate_id': candidate['candidate_id'], 'topic_key': f"topic-{candidate['candidate_id']}",
             'owner_title': f"Тема {candidate['candidate_id']}", 'audience_impact': 'Суть',
             'personal_relevance': 1, 'practical_impact': 1, 'surprise': 1,
             'shareability': 1, 'service_relevance': 0,
             'needs_primary_verification': True, 'recommendation': 'reject'}
            for candidate in candidates]}
    monkeypatch.setattr(pipeline.ai, 'call', rank)
    assert pipeline.run(manual=True) == 'owner_choice_pending'
    assert calls == [6000, 3000, 3000, 3000]
    with store.locked() as state:
        run = next(iter(state['research_runs'].values()))
        assert len(run['ranked_candidates']) == 12
    assert sent
    entries = [json.loads(line) for line in store.run_log_path.read_text(encoding='utf-8').splitlines()]
    assert any(entry['event'] == 'ranking_retry' for entry in entries)


def test_permanent_ranking_error_notifies_owner(tmp_path, monkeypatch):
    store = FileStore(tmp_path)
    tz = ZoneInfo('Europe/Bratislava')
    with store.locked() as state:
        state['sources']['test'] = {'id': 'test', 'enabled': True, 'priority': 1, 'method': 'rss'}
    settings = SimpleNamespace(user_agent='test', timezone=tz, max_candidates=30, ranking_model='rank')
    notified = []
    pipeline = ResearchPipeline(store, settings, SimpleNamespace(send_ranking_error=notified.append))
    item = Item('test', 'Test headline', 'https://example.org/news', datetime.now(tz), None, [], 'Summary')
    monkeypatch.setattr('buh_news.pipeline.seed_sources', lambda _store: None)
    monkeypatch.setattr(pipeline.fetcher, 'feed', lambda _source: ([item], SimpleNamespace(headers={})))
    monkeypatch.setattr(pipeline.ai, 'call', lambda *_args: (_ for _ in ()).throw(AIResponseFormatError('bad JSON')))
    assert pipeline.run(manual=True) == 'research_partial'
    with store.locked() as state:
        run = next(iter(state['research_runs'].values()))
        assert run['stop_reason'] == 'ranking_error'
        assert notified == [run['id']]


def test_owner_selected_low_ranked_topic_gets_full_editorial_review(tmp_path, monkeypatch):
    store = FileStore(tmp_path)
    tz = ZoneInfo('Europe/Bratislava')
    url = 'https://www.kros.sk/blog/news'
    with store.locked() as state:
        state['articles']['1'] = {'id': 1, 'source_id': 'kros_legislation', 'canonical_url': url,
                                  'title': 'Source article'}
        state['research_runs']['r'] = {
            'status': 'owner_choice_pending',
            'ranked_candidates': [{'article_id': 1, 'topic_key': 'topic', 'summary': 'Суть',
                                   'score': 2, 'recommendation': 'reject'}],
            'owner_choice': {'stage': 'drafting', 'selected_article_id': 1}}
    settings = SimpleNamespace(user_agent='test', timezone=tz, writing_model='write', approval_hours=24)
    previews = []
    pipeline = ResearchPipeline(store, settings, SimpleNamespace(send_preview=previews.append))
    monkeypatch.setattr('buh_news.pipeline.extract_article', lambda _fetcher, _url: (url, 'Fetched article'))
    stages = []
    post = '<b>Новини для підприємців</b> ' + 'Важлива новина для підприємців. ' * 7
    def ai_call(_run_id, stage, *_args):
        stages.append(stage)
        if stage == 'writing':
            return {'status': 'ready', 'post': post,
                    'evidence': {'claims': [{'claim': 'example'}], 'source_urls': [url]}}
        return {'passed': True, 'unsupported_claims': [], 'notes': []}
    monkeypatch.setattr(pipeline.ai, 'call', ai_call)
    monkeypatch.setattr(pipeline, '_proofread', lambda _run_id, draft: draft['post'])
    draft_id = pipeline.draft_selected('r', 1)
    assert stages == ['writing', 'editorial_review']
    assert previews == [draft_id]
    with store.locked() as state:
        assert state['articles']['1']['source_id'] == 'kros_legislation'
        assert state['articles']['1']['full_text'] == 'Fetched article'
        assert state['drafts'][draft_id]['status'] == 'pending'
        assert state['versions'][draft_id]['1']['review_passed'] is True


def test_run_log_explains_no_ranked_choices_and_source_failure(tmp_path, monkeypatch):
    store = FileStore(tmp_path)
    tz = ZoneInfo('Europe/Bratislava')
    with store.locked() as state:
        for source_id in ('good', 'bad'):
            state['sources'][source_id] = {'id': source_id, 'enabled': True,
                                           'priority': 1, 'method': 'rss'}
    settings = SimpleNamespace(user_agent='test', timezone=tz, max_candidates=30,
                               max_articles=3, ranking_model='rank')
    pipeline = ResearchPipeline(store, settings)
    item = Item('good', 'Test headline', 'https://example.org/news', datetime.now(tz),
                None, [], 'Test summary')
    monkeypatch.setattr('buh_news.pipeline.seed_sources', lambda _store: None)

    def fetch(source):
        if source['id'] == 'bad':
            raise ValueError('source unavailable')
        return [item], SimpleNamespace(headers={})

    monkeypatch.setattr(pipeline.fetcher, 'feed', fetch)
    monkeypatch.setattr(pipeline.ai, 'call', lambda *_args: {'rankings': []})
    assert pipeline.run(manual=True) == 'research_partial'
    entries = [json.loads(line) for line in store.run_log_path.read_text(encoding='utf-8').splitlines()]
    result = entries[-1]
    assert result['event'] == 'finished'
    assert result['status'] == 'research_partial'
    assert result['stop_reason'] == 'no_ranked_candidates_eligible'
    assert result['source_errors'] == [{'source_id': 'bad', 'error_type': 'ValueError',
                                        'error': 'source unavailable'}]
    assert result['ranking_considered_count'] == 1
    assert result['ranked_candidates'] == []
    assert result['attempted_candidates'] == []


def test_unhandled_research_error_is_logged(tmp_path, monkeypatch):
    store = FileStore(tmp_path)
    settings = SimpleNamespace(user_agent='test', timezone=ZoneInfo('Europe/Bratislava'))
    pipeline = ResearchPipeline(store, settings)
    monkeypatch.setattr('buh_news.pipeline.seed_sources', lambda _store: None)

    def fail(*_args):
        raise RuntimeError('unexpected test failure')

    monkeypatch.setattr('buh_news.pipeline._save_items', fail)
    import pytest
    with pytest.raises(RuntimeError, match='unexpected test failure'):
        pipeline.run()
    entries = [json.loads(line) for line in store.run_log_path.read_text(encoding='utf-8').splitlines()]
    assert [entry['event'] for entry in entries] == ['started', 'failed']
    assert entries[-1]['status'] == 'research_failed'
    assert entries[-1]['stop_reason'] == 'unhandled_exception'


def test_run_log_redacts_configured_credentials(tmp_path):
    store = FileStore(tmp_path)
    settings = SimpleNamespace(user_agent='test', openai_key='private-api-key',
                               telegram_token='private-bot-token', searxng_url=None)
    pipeline = ResearchPipeline(store, settings)
    pipeline._append_run_log({'event': 'failed', 'details': ['private-api-key',
                                                             {'error': 'private-bot-token'}]})
    content = store.run_log_path.read_text(encoding='utf-8')
    assert 'private-api-key' not in content
    assert 'private-bot-token' not in content
    assert content.count('[REDACTED]') == 2
