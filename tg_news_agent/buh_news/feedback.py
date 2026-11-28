"""Persist owner-approved editorial feedback for the next local AI run."""
from __future__ import annotations


def _candidate(run: dict, article_id: int) -> dict:
    row = next((x for x in run.get('ranked_candidates', []) if x['article_id'] == article_id), {})
    return {key: row.get(key) for key in ('article_id', 'title_uk', 'summary', 'score', 'topic_key')}


def approved_example(state: dict, draft_id: str) -> dict | None:
    """Only a final owner approval can promote correction/selection evidence."""
    draft = state['drafts'].get(draft_id)
    if not draft:
        return None
    events = [x for x in state['approval_events'] if x.get('draft_id') == draft_id]
    approved = next((x for x in reversed(events) if x['event_type'] == 'approve'), None)
    if not approved or draft['current_version'] != approved['version']:
        return None
    versions = state['versions'].get(draft_id, {})
    final = versions.get(str(approved['version']))
    if not final or not final.get('review_passed'):
        return None
    run = state['research_runs'].get(draft['run_id'], {})
    last_selection = next((x for x in reversed(events) if x['event_type'] == 'article_selection_requested'
                           and x.get('details', {}).get('selected_article_id') == draft['article_id']
                           and x['version'] < approved['version']), None)
    start_version = last_selection['version'] + 1 if last_selection else 1
    corrections = [x for x in events if x['event_type'] == 'correction_requested'
                   and x.get('details', {}).get('submitted_at')
                   and not x.get('details', {}).get('failed_at')
                   and (x.get('details', {}).get('result_version') or x['version'] + 1) <= approved['version']
                   and start_version <= x['version'] < approved['version']]
    example = {
        'schema_version': 1, 'draft_id': draft_id, 'approved_at': approved['created_at'],
        'approved_version': approved['version'], 'source_article_id': draft['article_id'],
        'source_url': state['articles'].get(str(draft['article_id']), {}).get('canonical_url'),
    }
    if corrections:
        before = versions.get(str(corrections[0]['version']))
        if before:
            example['writing'] = {
                'before': before['content'],
                'owner_instructions': [x['details']['instructions'] for x in corrections],
                'approved_post': final['content'],
            }
    if last_selection:
        original_id = last_selection.get('details', {}).get('from_article_id')
        if original_id is None:
            original_id = versions.get(str(last_selection['version']), {}).get('article_id')
        if original_id and original_id != draft['article_id']:
            example['preference'] = {
                'previous_candidate': _candidate(run, original_id),
                'chosen_candidate': _candidate(run, draft['article_id']),
                'offered_article_ids': last_selection.get('details', {}).get('article_ids', []),
                'interpretation': 'Owner chose this alternative and approved its final draft; reason unknown.',
            }
    return example if 'writing' in example or 'preference' in example else None


class FeedbackExampleWriter:
    def __init__(self, store):
        self.store = store

    def run(self) -> int:
        """Backfill after downtime and deduplicate by draft ID in the file lock."""
        with self.store.locked() as state:
            rows = [example for draft_id in state['drafts']
                    if (example := approved_example(state, draft_id)) is not None]
        return sum(self.store.append_example_once(row) for row in rows)
