import json
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from buh_news.ai import AI, AIResponseFormatError, RANKING_SCHEMA
from buh_news.db import FileStore


def test_incomplete_output_is_logged_and_charged_at_reported_usage(tmp_path, monkeypatch):
    store = FileStore(tmp_path)
    settings = SimpleNamespace(
        ai_enabled=True, ranking_input_price=Decimal('1'),
        ranking_output_price=Decimal('1'), writing_input_price=Decimal('2'),
        writing_output_price=Decimal('2'), monthly_budget=Decimal('5'),
        timezone=ZoneInfo('Europe/Bratislava'), api_url='https://example.invalid/responses',
        openai_key='test-key',
    )
    class FakeResponse:
        ok = True
        def json(self):
            return {'id': 'response-1', 'status': 'incomplete',
                    'incomplete_details': {'reason': 'max_output_tokens'},
                    'output': [{'content': [{'type': 'output_text', 'text': '{"rankings":[{"candidate_id":1'}]}],
                    'usage': {'input_tokens': 100, 'output_tokens': 2000,
                              'output_tokens_details': {'reasoning_tokens': 0}}}
    monkeypatch.setattr('buh_news.ai.requests.post', lambda *_args, **_kwargs: FakeResponse())
    with pytest.raises(AIResponseFormatError, match='max_output_tokens'):
        AI(store, settings).call('run-1', 'ranking', 'rank-model', 'Rank these', RANKING_SCHEMA, 12000, 2000)
    with store.locked() as state:
        reservation = next(iter(state['ai_reservations'].values()))
        assert reservation['status'] == 'reconciled'
        assert Decimal(reservation['actual_usd']) == Decimal('0.0021')
    events = [json.loads(line)['event'] for line in store.usage_path.read_text(encoding='utf-8').splitlines()]
    assert events == ['reserved', 'reconciled']
    trace = [json.loads(line) for line in store.agent_trace_path.read_text(encoding='utf-8').splitlines()]
    assert [item['event'] for item in trace] == ['agent_request', 'agent_response_invalid', 'agent_error']
    assert trace[1]['incomplete_details']['reason'] == 'max_output_tokens'
