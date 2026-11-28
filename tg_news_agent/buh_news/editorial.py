"""Editable editorial guidance and merged, bounded learning examples."""
from __future__ import annotations

import json
from pathlib import Path


EDITORIAL_DIR = Path(__file__).resolve().parent.parent / 'editorial'


def guidance(name: str) -> str:
    return (EDITORIAL_DIR / 'prompts' / f'{name}.md').read_text(encoding='utf-8').strip()


def examples(kind: str, limit: int = 2, max_chars: int = 5000) -> str:
    """Only files present in the deployed (merged) checkout influence prompts."""
    root = EDITORIAL_DIR / 'examples'
    rows = []
    for path in root.glob('*.json'):
        record = json.loads(path.read_text(encoding='utf-8'))
        if kind in record:
            rows.append((record.get('approved_at', ''), record[kind]))
    rows.sort(key=lambda item: item[0], reverse=True)
    selected = []
    for _, row in rows:
        candidate = json.dumps(row, ensure_ascii=False, separators=(',', ':'))
        if len(candidate) + sum(len(item) for item in selected) > max_chars:
            continue
        selected.append(candidate)
        if len(selected) >= limit:
            break
    return '\n'.join(selected)
