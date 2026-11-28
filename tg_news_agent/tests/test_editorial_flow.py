from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from buh_news.db import FileStore
from buh_news.ai import RANKING_SCHEMA, STYLE
from buh_news.pipeline import (
    DraftValidationError, ResearchPipeline, _concise_post, _needs_primary_verification, _official_source,
    _ranking_prompt, _ranking_recommendation, _ranking_score, _writing_prompt,
)
from buh_news.telegram import OwnerBot


class FakeTelegram:
    def __init__(self):
        self.sent = []
        self.callbacks = []
        self.messages = []

    def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text, kwargs))

    def answer_callback_query(self, _):
        pass

    def callback_query_handler(self, **_):
        return self.callbacks.append

    def message_handler(self, **_):
        return self.messages.append


def test_editorial_ranking_score_and_thresholds():
    item = dict.fromkeys(('personal_relevance', 'practical_impact', 'surprise', 'shareability', 'service_relevance'), 2)
    item.update(recommendation='select', needs_primary_verification=False)
    assert _ranking_score(item) == 10
    assert _ranking_recommendation(item) == 'select'
    item['shareability'] = 0
    assert _ranking_score(item) == 8
    assert _ranking_recommendation(item) == 'hold'
    item['surprise'] = 1
    assert _ranking_recommendation(item) == 'reject'
    item['surprise'] = 2
    item['shareability'] = 2
    item['needs_primary_verification'] = True
    assert _ranking_recommendation(item) == 'hold'
    item['needs_primary_verification'] = False
    item['source_id'] = 'podnikajte'
    assert _ranking_recommendation(item) == 'hold'
    fields = RANKING_SCHEMA['properties']['rankings']['items']['properties']
    assert all(fields[key]['maximum'] == 2 for key in ('personal_relevance', 'practical_impact', 'surprise', 'shareability', 'service_relevance'))


def test_trusted_editorial_sources_pass_ranking_gate_but_not_relevance_gate():
    candidate = dict.fromkeys(('personal_relevance', 'practical_impact', 'surprise',
                               'shareability', 'service_relevance'), 2)
    candidate.update(recommendation='hold', needs_primary_verification=True)
    for source_id in ('kros_legislation', 'fs_news', 'fs_press'):
        candidate['source_id'] = source_id
        assert not _needs_primary_verification(candidate)
        assert _ranking_recommendation(candidate) == 'hold'
    for source_id in ('kros_payroll', 'podnikajte'):
        candidate['source_id'] = source_id
        assert _needs_primary_verification(candidate)
    candidate.update(source_id='fs_news', recommendation='select',
                     personal_relevance=0, practical_impact=0, surprise=0)
    assert _ranking_recommendation(candidate) == 'reject'


def test_editorial_prompts_do_not_force_generic_footer():
    article = {'source_id': 'nbs', 'title': 'Example'}
    prompt = _writing_prompt(article, 'https://nbs.sk/example', 'Source article')
    assert 'effective and transitional dates' in prompt
    assert 'Do not append a fixed generic footer' in STYLE
    assert 'Питання щодо вашої ситуації' not in prompt
    assert _concise_post('ї' * 900)
    assert not _concise_post('ї' * 901)
    assert 'RECENT_TOPICS=' in _ranking_prompt([], [{'topic_key': 'old', 'summary': 'Earlier topic'}])
    assert 'kros_legislation' in _ranking_prompt([])
    assert 'reliable professional source' in _writing_prompt({'source_id': 'kros_legislation', 'title': 'Example'},
                                                              'https://www.kros.sk/blog/news', 'Source article')


def test_trusted_source_skips_trust_check_but_gets_editorial_review():
    stages = []
    class ReviewAI:
        def call(self, _run_id, stage, *_args, **_kwargs):
            stages.append(stage)
            return {'passed': True, 'unsupported_claims': [], 'notes': []}

    pipeline = object.__new__(ResearchPipeline)
    pipeline.ai = ReviewAI()
    pipeline.s = SimpleNamespace(writing_model='test')
    article = {'source_id': 'nbs'}
    url = 'https://nbs.sk/aktuality/priklad'
    draft = {
        'status': 'ready',
        'post': '<b>Зміни для підприємців</b>\nНові правила оприлюднено сьогодні в офіційному повідомленні. Деталі стосуються підприємців у Словаччині.\nПитання щодо вашої ситуації — пишіть @buh_sk\nbuh.sk',
        'evidence': {'claims': [{'claim': 'example'}], 'source_urls': [url]},
    }
    assert _official_source(article, url)
    assert not _official_source(article, 'https://nbs.sk.evil.example/aktuality')
    assert _official_source({'source_id': 'fs_news'}, 'https://www.financnasprava.sk/sk/news')
    assert _official_source({'source_id': 'fs_press'}, 'https://www.financnasprava.sk/sk/press')
    assert not _official_source({'source_id': 'kros_legislation'}, 'https://www.kros.sk/blog/news')
    result = pipeline._review('run', article, url, draft, 'Fetched official article')
    assert result['method'] == 'editorial_review'
    assert result['trust_review'] == 'skipped_registered_source'
    assert stages == ['editorial_review']


def test_other_source_gets_separate_trust_and_editorial_review():
    calls = []

    class ReviewAI:
        def call(self, _run_id, stage, _model, prompt, *_args, **_kwargs):
            calls.append((stage, prompt))
            return {'passed': True, 'unsupported_claims': [], 'notes': []}

    pipeline = object.__new__(ResearchPipeline)
    pipeline.ai = ReviewAI()
    pipeline.s = SimpleNamespace(writing_model='test')
    url = 'https://podnikajte.sk/clanok'
    draft = {
        'status': 'ready',
        'post': '<b>Нові правила для підприємців</b>\nОфіційно оприлюднено зміни для бізнесу у Словаччині. Деталі важливі для роботодавців.\nПитання щодо вашої ситуації — пишіть @buh_sk\nbuh.sk',
        'evidence': {'claims': [{'claim': 'example'}], 'source_urls': [url]},
    }
    result = pipeline._review('run', {'source_id': 'podnikajte'}, url, draft, 'Fetched secondary article')
    assert result['method'] == 'editorial_review'
    assert [stage for stage, _ in calls] == ['trust_review', 'editorial_review']
    kros_url = 'https://www.kros.sk/blog/legislativa'
    kros_draft = {**draft, 'evidence': {**draft['evidence'], 'source_urls': [kros_url]}}
    result = pipeline._review('run', {'source_id': 'kros_legislation'}, kros_url, kros_draft,
                              'The fetched KROS article')
    assert result['trust_review'] == 'skipped_registered_source'
    assert [stage for stage, _ in calls] == ['trust_review', 'editorial_review', 'editorial_review']
    assert 'SOURCE_ARTICLE=The fetched KROS article' in calls[-1][1]
    try:
        pipeline._review('run', {'source_id': 'kros_legislation'},
                         'https://kros.sk.evil.example/news', kros_draft)
    except DraftValidationError as exc:
        assert 'registered HTTPS domain' in str(exc)
    else:
        raise AssertionError('redirect outside the trusted domain must be rejected')
    assert len(calls) == 3


def test_failed_source_trust_prevents_editorial_call():
    stages = []
    pipeline = object.__new__(ResearchPipeline)
    pipeline.s = SimpleNamespace(writing_model='test')
    class RejectAI:
        def call(self, _run_id, stage, *_args):
            stages.append(stage)
            return {'passed': False, 'unsupported_claims': ['No primary support'], 'notes': []}
    pipeline.ai = RejectAI()
    url = 'https://podnikajte.sk/clanok'
    draft = {'status': 'ready', 'post': '<b>Новини для підприємців</b> ' + 'Важлива новина для підприємців. ' * 7,
             'evidence': {'claims': [{'claim': 'example'}], 'source_urls': [url]}}
    import pytest
    with pytest.raises(DraftValidationError, match='trust review'):
        pipeline._review('run', {'source_id': 'podnikajte'}, url, draft, 'Fetched article')
    assert stages == ['trust_review']


def _owner_bot(tmp_path):
    store = FileStore(tmp_path)
    bot = object.__new__(OwnerBot)
    bot.store = store
    bot.s = SimpleNamespace(timezone=ZoneInfo('Europe/Bratislava'), owner_user_id=123, owner_chat_id=123, max_revisions=2, user_agent='test')
    bot.bot = FakeTelegram()
    return bot


def test_owner_options_include_low_ranked_topics_but_exclude_editorial_failures(tmp_path):
    bot = _owner_bot(tmp_path)
    run = {'ranked_candidates': [
        {'article_id': 1, 'score': 10, 'recommendation': 'select'},
        {'article_id': 2, 'score': 10, 'recommendation': 'hold', 'needs_primary_verification': True},
        {'article_id': 3, 'score': 7, 'recommendation': 'select'},
        {'article_id': 4, 'score': 8, 'recommendation': 'hold', 'needs_primary_verification': False, 'editorial_failed': True},
    ]}
    assert [x['article_id'] for x in bot._alternatives(run, {'article_id': 1})] == [2, 3]


def test_failed_choice_is_removed_and_next_three_offered(tmp_path, monkeypatch):
    bot = _owner_bot(tmp_path)
    now = datetime.now(bot.s.timezone)
    with bot.store.locked() as state:
        state['drafts']['d'] = {
            'id': 'd', 'run_id': 'r', 'article_id': 1, 'current_version': 1,
            'status': 'revision_requested', 'approval_expires_at': (now + timedelta(hours=1)).isoformat(),
        }
        state['research_runs']['r'] = {'ranked_candidates': [
            {'article_id': i, 'title_uk': f'Тема {i}', 'summary': f'Підсумок {i}', 'recommendation': 'publish'}
            for i in range(1, 6)
        ]}
        state['approval_events'].append({
            'draft_id': 'd', 'version': 1, 'event_type': 'article_selection_requested',
            'callback_ref': 'old', 'details': {'article_ids': [2, 3, 4]},
        })

    def fail(*_args, **_kwargs):
        raise DraftValidationError('unsupported claim')

    monkeypatch.setattr(ResearchPipeline, 'redraft', fail)
    call = SimpleNamespace(from_user=SimpleNamespace(id=123), message=SimpleNamespace(chat=SimpleNamespace(id=123)))
    bot._pick_article(call, 'old', 1)
    with bot.store.locked() as state:
        assert state['research_runs']['r']['ranked_candidates'][1]['editorial_failed'] is True
        assert state['drafts']['d']['status'] == 'revision_requested'
        assert state['approval_events'][-1]['details']['article_ids'] == [3, 4, 5]
    assert 'Тема 5' in bot.bot.sent[-1][1]


def test_no_valuable_news_offers_top_three_then_owner_selects_one(tmp_path, monkeypatch):
    bot = _owner_bot(tmp_path)
    bot.s.approval_hours = 24
    bot._register()
    with bot.store.locked() as state:
        state['research_runs']['r'] = {'status': 'owner_choice_pending', 'ranked_candidates': [
            {'article_id': i, 'title_uk': f'Тема {i}', 'summary': f'Суть {i}',
             'score': 8-i, 'recommendation': 'reject', 'needs_primary_verification': True}
            for i in range(1, 5)
        ]}
    assert bot.send_fallback_offer('r')
    with bot.store.locked() as state:
        choice = state['research_runs']['r']['owner_choice']
        assert choice['candidate_ids'] == [1, 2, 3]
        offer_ref = choice['offer_ref']
    assert 'Тема 3' in bot.bot.sent[-1][1]
    assert 'Тема 4' not in bot.bot.sent[-1][1]
    assert [button.callback_data for button in bot.bot.sent[-1][2]['reply_markup'].keyboard[0]] == [
        f'n:offer:{offer_ref}', f'n:offerclose:{offer_ref}']

    def call(data):
        return SimpleNamespace(id='callback', data=data, from_user=SimpleNamespace(id=123),
                               message=SimpleNamespace(chat=SimpleNamespace(id=123)))
    bot.bot.callbacks[0](call(f'n:offer:{offer_ref}'))
    with bot.store.locked() as state:
        choice = state['research_runs']['r']['owner_choice']
        assert choice['stage'] == 'selecting'
        selection_ref = choice['selection_ref']
    assert [button.callback_data for button in bot.bot.sent[-1][2]['reply_markup'].keyboard[0]] == [
        f'n:offerpick:{selection_ref}:1', f'n:offerpick:{selection_ref}:2', f'n:offerpick:{selection_ref}:3']
    selected = []
    monkeypatch.setattr(ResearchPipeline, 'draft_selected', lambda _self, run_id, article_id: selected.append((run_id, article_id)))
    bot.bot.callbacks[0](call(f'n:offerpick:{selection_ref}:2'))
    assert selected == [('r', 2)]
    with bot.store.locked() as state:
        assert state['research_runs']['r']['owner_choice']['selected_article_id'] == 2
        assert any(event['event_type'] == 'fallback_article_selected' for event in state['approval_events'])


def test_failed_fallback_story_is_removed_and_next_ranked_story_offered(tmp_path, monkeypatch):
    bot = _owner_bot(tmp_path)
    bot.s.approval_hours = 24
    now = datetime.now(bot.s.timezone)
    with bot.store.locked() as state:
        state['research_runs']['r'] = {'status': 'owner_choice_pending', 'ranked_candidates': [
            {'article_id': i, 'title_uk': f'Тема {i}', 'summary': f'Суть {i}', 'score': 7-i}
            for i in range(1, 5)
        ], 'owner_choice': {'stage': 'selecting', 'selection_ref': 'pickref',
                            'candidate_ids': [1, 2, 3],
                            'expires_at': (now+timedelta(hours=1)).isoformat()}}
    def fail(*_args, **_kwargs):
        raise DraftValidationError('unsupported claim')
    monkeypatch.setattr(ResearchPipeline, 'draft_selected', fail)
    call = SimpleNamespace(from_user=SimpleNamespace(id=123), message=SimpleNamespace(chat=SimpleNamespace(id=123)))
    bot._fallback_pick(call, 'pickref', 1)
    with bot.store.locked() as state:
        run = state['research_runs']['r']
        assert run['ranked_candidates'][0]['editorial_failed'] is True
        assert run['owner_choice']['candidate_ids'] == [2, 3, 4]
        assert run['owner_choice']['stage'] == 'selecting'
    assert 'Тема 4' in bot.bot.sent[-1][1]


def test_fallback_close_does_not_create_draft(tmp_path):
    bot = _owner_bot(tmp_path)
    bot.s.approval_hours = 24
    with bot.store.locked() as state:
        state['research_runs']['r'] = {'ranked_candidates': [
            {'article_id': 1, 'title_uk': 'Тема', 'summary': 'Суть', 'score': 2}]}
    assert bot.send_fallback_offer('r')
    with bot.store.locked() as state:
        ref = state['research_runs']['r']['owner_choice']['offer_ref']
    call = SimpleNamespace(from_user=SimpleNamespace(id=123), message=SimpleNamespace(chat=SimpleNamespace(id=123)))
    bot._fallback_action(call, 'offerclose', ref)
    with bot.store.locked() as state:
        assert state['research_runs']['r']['owner_choice']['stage'] == 'closed'
        assert state['drafts'] == {}


def test_correct_button_requests_written_instructions(tmp_path, monkeypatch):
    bot = _owner_bot(tmp_path)
    bot._register()
    now = datetime.now(bot.s.timezone)
    with bot.store.locked() as state:
        state['drafts']['d'] = {
            'id': 'd', 'run_id': 'r', 'article_id': 1, 'current_version': 1,
            'status': 'pending', 'revision_count': 0,
            'approval_expires_at': (now + timedelta(hours=1)).isoformat(),
        }
        state['versions']['d'] = {'1': {'review_passed': True}}
        state['approval_events'].append({
            'draft_id': 'd', 'version': 1, 'event_type': 'preview_created',
            'callback_ref': 'preview', 'details': {},
        })
    call = SimpleNamespace(id='callback', data='n:correct:preview', from_user=SimpleNamespace(id=123), message=SimpleNamespace(chat=SimpleNamespace(id=123)))
    bot.bot.callbacks[0](call)
    with bot.store.locked() as state:
        assert state['drafts']['d']['status'] == 'revision_requested'
        assert state['approval_events'][-1]['event_type'] == 'correction_requested'
    assert 'Напишіть' in bot.bot.sent[-1][1]
    received = []
    monkeypatch.setattr(ResearchPipeline, 'redraft', lambda _self, draft_id, **kwargs: received.append((draft_id, kwargs['instructions'])))
    message = SimpleNamespace(text='Приберіть зайве вступне речення', from_user=SimpleNamespace(id=123), chat=SimpleNamespace(id=123))
    bot.bot.messages[0](message)
    assert received == [('d', message.text)]
    with bot.store.locked() as state:
        assert state['approval_events'][-1]['details']['instructions'] == message.text
