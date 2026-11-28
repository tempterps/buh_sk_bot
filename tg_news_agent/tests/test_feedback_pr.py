from types import SimpleNamespace

import pytest

from buh_news.db import FileStore
from buh_news.editorial import examples
from buh_news.feedback import FeedbackPRPublisher, approved_example


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


def _settings(**overrides):
    values = dict(feedback_pr_enabled=True, feedback_github_token='test-token',
                  feedback_github_repo='owner/repo', feedback_pr_base_branch='Stage1',
                  feedback_allow_public_repo=False)
    values.update(overrides)
    return SimpleNamespace(**values)


class Response:
    def __init__(self, status, data):
        self.status_code, self.data = status, data

    def json(self):
        return self.data


class FakeGitHub:
    def __init__(self, private=True):
        self.calls = []
        self.private = private
        self.created = False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.endswith('/repos/owner/repo'):
            return Response(200, {'private': self.private})
        if url.endswith('/pulls') and method == 'GET':
            return Response(200, [])
        if '/git/ref/heads/editorial-feedback/' in url:
            return Response(404, {})
        if url.endswith('/git/ref/heads/Stage1'):
            return Response(200, {'object': {'sha': 'base-sha'}})
        if url.endswith('/git/refs'):
            return Response(201, {})
        if '/contents/' in url and method == 'GET':
            return Response(404, {})
        if '/contents/' in url and method == 'PUT':
            self.created = True
            return Response(201, {})
        if url.endswith('/pulls') and method == 'POST':
            return Response(201, {'html_url': 'https://github.com/owner/repo/pull/1'})
        raise AssertionError((method, url))


def test_no_learning_from_unapproved_actions(tmp_path):
    store = FileStore(tmp_path)
    _state(store)
    with store.locked() as state:
        assert approved_example(state, 'draft-1') is None
    github = FakeGitHub()
    assert FeedbackPRPublisher(store, _settings(), github).run() == []
    assert github.calls == []


def test_approved_correction_and_choice_create_one_private_pr(tmp_path):
    store = FileStore(tmp_path)
    _state(store)
    with store.locked() as state:
        state['approval_events'].append({'draft_id': 'draft-1', 'version': 3, 'event_type': 'approve',
                                         'created_at': '2026-11-28T13:00:00+01:00'})
        example = approved_example(state, 'draft-1')
    assert example['writing']['before'] == 'Зайвий вступ'
    assert example['writing']['approved_post'] == 'Стислий схвалений текст'
    assert example['preference']['previous_candidate']['article_id'] == 1
    assert example['preference']['chosen_candidate']['article_id'] == 2
    github = FakeGitHub()
    publisher = FeedbackPRPublisher(store, _settings(), github)
    assert publisher.run() == ['https://github.com/owner/repo/pull/1']
    assert publisher.run() == []
    assert github.created
    put = next(call for call in github.calls if call[0] == 'PUT')
    assert put[2]['json']['branch'] == 'editorial-feedback/draft-1'
    assert 'test-token' not in str(put[2]['json'])


def test_public_repo_blocks_feedback_before_any_write(tmp_path):
    store = FileStore(tmp_path)
    _state(store)
    with store.locked() as state:
        state['approval_events'].append({'draft_id': 'draft-1', 'version': 3, 'event_type': 'approve',
                                         'created_at': '2026-11-28T13:00:00+01:00'})
    github = FakeGitHub(private=False)
    with pytest.raises(RuntimeError, match='repository is public'):
        FeedbackPRPublisher(store, _settings(), github).run()
    assert len(github.calls) == 1


def test_merged_examples_are_bounded_and_prompt_addenda_exist():
    assert examples('writing') == ''
    from buh_news.editorial import guidance
    assert 'weak preference signals' in guidance('ranking_addendum')


def test_failed_correction_is_not_proposed(tmp_path):
    store = FileStore(tmp_path)
    _state(store)
    with store.locked() as state:
        state['approval_events'][1]['details']['failed_at'] = 'now'
        state['approval_events'].append({'draft_id': 'draft-1', 'version': 3, 'event_type': 'approve',
                                         'created_at': '2026-11-28T13:00:00+01:00'})
        example = approved_example(state, 'draft-1')
    assert 'writing' not in example
    assert 'preference' in example


def test_ineligible_approval_version_does_not_train(tmp_path):
    store = FileStore(tmp_path)
    _state(store)
    with store.locked() as state:
        state['approval_events'].append({'draft_id': 'draft-1', 'version': 2, 'event_type': 'approve',
                                         'created_at': '2026-11-28T13:00:00+01:00'})
        assert approved_example(state, 'draft-1') is None
