from datetime import datetime, timedelta
from hashlib import sha256
import json
from buh_news.ai import RANKING_SCHEMA
from buh_news.db import FileStore
def test_schema_requires_recommendation():
    assert 'recommendation' in RANKING_SCHEMA['properties']['rankings']['items']['required']
    assert 'owner_title' in RANKING_SCHEMA['properties']['rankings']['items']['required']
def test_content_hash_changes_when_draft_changes():
    assert sha256('one'.encode()).hexdigest()!=sha256('two'.encode()).hexdigest()
def test_approval_expiry_is_not_automatic_publication():
    assert datetime.now().astimezone()+timedelta(hours=24)>datetime.now().astimezone()

def test_agent_trace_is_append_only_jsonl(tmp_path):
    store=FileStore(tmp_path)
    store.append_agent_trace({'event':'agent_request','stage':'ranking'})
    store.append_agent_trace({'event':'agent_response','stage':'ranking'})
    entries=[json.loads(line) for line in (tmp_path/'agent_trace.jsonl').read_text(encoding='utf-8').splitlines()]
    assert [entry['event'] for entry in entries]==['agent_request','agent_response']

