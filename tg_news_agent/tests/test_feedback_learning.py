import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from buh_news.db import FileStore
from buh_news.editorial import examples, guidance
from buh_news.feedback import FeedbackExampleWriter, approved_example
from buh_news.pipeline import _ranking_prompt, _writing_prompt
from buh_news.telegram import OwnerBot


def _state(store):
    with store.locked() as state:
        state['drafts']['draft-1'] = {'id': 'draft-1', 'run_id': 'run-1', 'article_id': 2, 'current_version': 3}
        state['articles']['2'] = {'canonical_url': 'https://nbs.sk/news'}
        state['research_runs']['run-1'] = {'ranked_candidates': [
            {'article_id': 1, 'title_uk': 'Початкова тема', 'summary': 'Перший варіант', 'score': 9},
            {'article_id': 2, 'title_uk': 'Краща тема', 'summary': 'Другий варіант', 'score': 8},
        ]}
        state['versions']['draft-1'] = {
            '1': {'article_id': 1, 'content': 'Початкова чернетка'},
            '2': {'article_id': 2, 'content': 'Зайвий вступ'},
            '3': {'article_id': 2, 'content': 'Стислий схвалений текст', 'review_passed': True},
        }
        state['approval_events'] = [
            {'draft_id': 'draft-1', 'version': 1, 'event_type': 'article_selection_requested',
             'details': {'from_article_id': 1, 'article_ids': [2], 'selected_article_id': 2, 'result_version': 2}},
            {'draft_id': 'draft-1', 'version': 2, 'event_type': 'correction_requested',
             'details': {'instructions': 'Приберіть зайвий вступ', 'submitted_at': 'now', 'result_version': 3}},
        ]


def _approve(store):
    with store.locked() as state:
        state['approval_events'].append({'draft_id': 'draft-1', 'version': 3, 'event_type': 'approve',
                                         'created_at': '2026-11-28T13:00:00+01:00'})


def test_unapproved_feedback_stays_raw_and_does_not_reach_prompts(tmp_path):
    store = FileStore(tmp_path)
    _state(store)
    with store.locked() as state:
        assert approved_example(state, 'draft-1') is None
    assert FeedbackExampleWriter(store).run() == 0
    assert examples('writing', store) == ''
    assert not store.examples_path.exists()


def test_approval_saves_one_local_example_and_prompts_use_it(tmp_path):
    store = FileStore(tmp_path)
    _state(store)
    _approve(store)
    writer = FeedbackExampleWriter(store)
    assert writer.run() == 1
    assert writer.run() == 0
    rows = store.read_examples()
    assert len(rows) == 1
    row = rows[0]
    assert row['writing']['before'] == 'Зайвий вступ'
    assert row['writing']['approved_post'] == 'Стислий схвалений текст'
    assert row['preference']['previous_candidate']['article_id'] == 1
    assert row['preference']['chosen_candidate']['article_id'] == 2
    assert 'Краща тема' in _ranking_prompt([], preference_examples=examples('preference', store))
    article = {'source_id': 'nbs', 'title': 'Example'}
    assert 'Приберіть зайвий вступ' in _writing_prompt(
        article, 'https://nbs.sk/news', 'Source body', writing_examples=examples('writing', store))
    assert json.loads(store.examples_path.read_text(encoding='utf-8').strip())['draft_id'] == 'draft-1'


def test_failed_correction_is_not_promoted(tmp_path):
    store = FileStore(tmp_path)
    _state(store)
    _approve(store)
    with store.locked() as state:
        state['approval_events'][1]['details']['failed_at'] = 'now'
        example = approved_example(state, 'draft-1')
    assert 'writing' not in example
    assert 'preference' in example


def test_stale_approval_version_does_not_train(tmp_path):
    store = FileStore(tmp_path)
    _state(store)
    with store.locked() as state:
        state['approval_events'].append({'draft_id': 'draft-1', 'version': 2, 'event_type': 'approve',
                                         'created_at': '2026-11-28T13:00:00+01:00'})
    assert FeedbackExampleWriter(store).run() == 0


def test_example_limit_and_prompt_guidance(tmp_path):
    store = FileStore(tmp_path)
    for index in range(4):
        store.append_example_once({'draft_id': str(index), 'approved_at': f'2026-11-2{index}T00:00:00+01:00',
                                   'writing': {'approved_post': f'Example {index}'}})
    prompt = examples('writing', store, limit=2)
    assert 'Example 3' in prompt and 'Example 2' in prompt
    assert 'Example 1' not in prompt
    assert examples('writing', store, max_chars=5) == ''
    assert 'weak preference signals' in guidance('ranking_addendum')


def test_owner_approval_immediately_activates_example(tmp_path):
    store = FileStore(tmp_path)
    _state(store)
    zone = ZoneInfo('Europe/Bratislava')
    with store.locked() as state:
        state['drafts']['draft-1'].update(
            status='pending', approval_expires_at=(datetime.now(zone) + timedelta(hours=1)).isoformat())
        state['versions']['draft-1']['3']['content_hash'] = 'content-hash'
        state['approval_events'].append({
            'draft_id': 'draft-1', 'version': 3, 'event_type': 'preview_created',
            'callback_ref': 'preview-ref', 'details': {},
        })

    callbacks = []
    messages = []

    class FakeBot:
        def callback_query_handler(self, **_kwargs):
            return callbacks.append

        def message_handler(self, **_kwargs):
            return lambda _handler: None

        def answer_callback_query(self, _id):
            pass

        def send_message(self, _chat, text, **_kwargs):
            messages.append(text)

    class FakePublisher:
        def enqueue(self, *_args):
            pass

        def process_one(self):
            return 'preview_acknowledged'

    bot = object.__new__(OwnerBot)
    bot.store = store
    bot.s = SimpleNamespace(timezone=zone, owner_user_id=123, owner_chat_id=123, max_revisions=2)
    bot.bot = FakeBot()
    bot.publisher = FakePublisher()
    bot._register()
    call = SimpleNamespace(id='callback', data='n:approve:preview-ref',
                           from_user=SimpleNamespace(id=123),
                           message=SimpleNamespace(chat=SimpleNamespace(id=123)))
    callbacks[0](call)
    assert len(store.read_examples()) == 1
    assert messages
