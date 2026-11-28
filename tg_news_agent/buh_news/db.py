"""Atomic low-volume file store.

State is guarded by an inter-process lock and written with atomic rename. AI
usage and agent handoffs are additionally kept in separate append-only JSONL
ledgers.
"""
from __future__ import annotations
from contextlib import contextmanager
from decimal import Decimal
import json, os, tempfile
from pathlib import Path
import portalocker

def _initial():
    return {'sources':{},'articles':{},'url_index':{},'topics':{},'drafts':{},'versions':{},'approval_events':[], 'feedback_prs':{},'outbox':{},'publications':[],'research_runs':{},'ai_reservations':{},'next_article_id':1}

class FileStore:
    def __init__(self, root: Path):
        self.root=root; self.state_path=root/'state.json'; self.lock_path=root/'state.lock'; self.usage_path=root/'ai_usage.jsonl'; self.agent_trace_path=root/'agent_trace.jsonl'
    def init(self):
        self.root.mkdir(parents=True,exist_ok=True)
        with self.locked() as state: state.setdefault('sources',{})
    @contextmanager
    def locked(self):
        self.root.mkdir(parents=True,exist_ok=True)
        with portalocker.Lock(str(self.lock_path),'a+',timeout=15):
            try: state=json.loads(self.state_path.read_text(encoding='utf-8'))
            except (FileNotFoundError,json.JSONDecodeError): state=_initial()
            yield state
            fd,tmp=tempfile.mkstemp(dir=self.root,prefix='.state-',suffix='.json')
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as f:
                    json.dump(state,f,ensure_ascii=False,indent=2,sort_keys=True); f.flush(); os.fsync(f.fileno())
                os.replace(tmp,self.state_path)
            finally:
                if os.path.exists(tmp): os.unlink(tmp)
    def _append_jsonl(self, path: Path, record: dict):
        self.root.mkdir(parents=True,exist_ok=True)
        with portalocker.Lock(str(path),'a',timeout=15,encoding='utf-8') as f:
            f.write(json.dumps(record,ensure_ascii=False,sort_keys=True)+'\n'); f.flush(); os.fsync(f.fileno())
        # The trace contains editorial/source text. On Linux this restricts it
        # to the service account; Windows keeps its normal ACL behaviour.
        try: os.chmod(path,0o600)
        except OSError: pass
    def append_usage(self, record: dict):
        self._append_jsonl(self.usage_path,record)
    def append_agent_trace(self, record: dict):
        self._append_jsonl(self.agent_trace_path,record)
    def run_cost(self, run_id: str) -> Decimal:
        with self.locked() as s:
            return sum((Decimal(str(x.get('actual_usd') if x.get('actual_usd') is not None else x['reserved_usd'])) for x in s['ai_reservations'].values() if x['run_id']==run_id),Decimal('0'))
