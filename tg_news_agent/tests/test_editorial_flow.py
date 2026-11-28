from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from buh_news.db import FileStore
from buh_news.ai import RANKING_SCHEMA, STYLE
from buh_news.pipeline import (
    DraftValidationError, ResearchPipeline, _concise_post, _official_source,
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


def test_editorial_prompts_do_not_force_generic_footer():
    article = {'source_id': 'nbs', 'title': 'Example'}
    prompt = _writing_prompt(article, 'https://nbs.sk/example', 'Source article')
    assert 'effective and transitional dates' in prompt
    assert 'Do not append a fixed generic footer' in STYLE
    assert 'Питання щодо вашої ситуації' not in prompt
    assert _concise_post('ї' * 900)
    assert not _concise_post('ї' * 901)
    assert 'RECENT_TOPICS=' in _ranking_prompt([], [{'topic_key': 'old', 'summary': 'Earlier topic'}])


def test_official_source_skips_extra_ai_review():
    class NoReviewAI:
        def call(self, *_args, **_kwargs):
            raise AssertionError('AI factual review must not run for official source')

    pipeline = object.__new__(ResearchPipeline)
    pipeline.ai = NoReviewAI()
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
    assert pipeline._review('run', article, url, draft)['method'] == 'official_source'


def test_other_source_still_gets_factual_review():
    calls = []

    class ReviewAI:
        def call(self, *_args, **_kwargs):
            calls.append(True)
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
    assert pipeline._review('run', {'source_id': 'podnikajte'}, url, draft)['method'] == 'ai_review'
    assert calls == [True]


def _owner_bot(tmp_path):
    store = FileStore(tmp_path)
    bot = object.__new__(OwnerBot)
    bot.store = store
    bot.s = SimpleNamespace(timezone=ZoneInfo('Europe/Bratislava'), owner_user_id=123, owner_chat_id=123, max_revisions=2, user_agent='test')
    bot.bot = FakeTelegram()
    return bot


def test_owner_options_exclude_unverified_and_weak_topics(tmp_path):
    bot = _owner_bot(tmp_path)
    run = {'ranked_candidates': [
        {'article_id': 1, 'score': 10, 'recommendation': 'select'},
        {'article_id': 2, 'score': 10, 'recommendation': 'hold', 'needs_primary_verification': True},
        {'article_id': 3, 'score': 7, 'recommendation': 'select'},
        {'article_id': 4, 'score': 8, 'recommendation': 'hold', 'needs_primary_verification': False},
    ]}
    assert [x['article_id'] for x in bot._alternatives(run, {'article_id': 1})] == [4]


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
        assert state['research_runs']['r']['ranked_candidates'][1]['recommendation'] == 'reject'
        assert state['drafts']['d']['status'] == 'revision_requested'
        assert state['approval_events'][-1]['details']['article_ids'] == [3, 4, 5]
    assert 'Тема 5' in bot.bot.sent[-1][1]


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
