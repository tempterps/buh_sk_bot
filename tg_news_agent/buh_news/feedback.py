"""Turn approved editorial decisions into reviewable GitHub examples.

The server's local approval history is the source of truth. Nothing in this
module edits the deployed checkout or changes live prompts before a PR merges.
"""
from __future__ import annotations

from base64 import b64decode, b64encode
from datetime import datetime, timezone
import json
import re
from urllib.parse import quote

import requests


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
        first = corrections[0]
        before = versions.get(str(first['version']))
        if before:
            example['writing'] = {
                'before': before['content'],
                'owner_instructions': [x['details']['instructions'] for x in corrections],
                'approved_post': final['content'],
            }
    if last_selection:
        original_id = last_selection.get('details', {}).get('from_article_id')
        if original_id is None:
            original = versions.get(str(last_selection['version']), {})
            original_id = original.get('article_id')
        if original_id and original_id != draft['article_id']:
            example['preference'] = {
                'previous_candidate': _candidate(run, original_id),
                'chosen_candidate': _candidate(run, draft['article_id']),
                'offered_article_ids': last_selection.get('details', {}).get('article_ids', []),
                'interpretation': 'Owner chose this alternative and approved its final draft; reason unknown.',
            }
    return example if 'writing' in example or 'preference' in example else None


class FeedbackPRPublisher:
    def __init__(self, store, settings, session=None):
        self.store, self.s = store, settings
        self.http = session or requests.Session()

    def _api(self, method: str, path: str, *, expected=(200,), **kwargs):
        response = self.http.request(
            method, 'https://api.github.com' + path,
            headers={'Accept': 'application/vnd.github+json',
                     'Authorization': f'Bearer {self.s.feedback_github_token}',
                     'X-GitHub-Api-Version': '2022-11-28'},
            timeout=(10, 30), **kwargs,
        )
        if response.status_code not in expected:
            raise RuntimeError(f'GitHub {method} {path} returned HTTP {response.status_code}')
        return response

    def _publish(self, example: dict) -> str:
        repo = self.s.feedback_github_repo
        base = self.s.feedback_pr_base_branch
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo or ''):
            raise ValueError('FEEDBACK_GITHUB_REPO must be owner/repository')
        if not re.fullmatch(r'[A-Za-z0-9_.\-/]+', base or '') or '..' in base:
            raise ValueError('invalid FEEDBACK_PR_BASE_BRANCH')
        root = f'/repos/{repo}'
        metadata = self._api('GET', root).json()
        if metadata.get('private') is not True and not self.s.feedback_allow_public_repo:
            raise RuntimeError('feedback PR blocked: repository is public; private owner instructions may be exposed')
        draft_id = example['draft_id']
        branch = f'editorial-feedback/{draft_id}'
        path = f'tg_news_agent/editorial/examples/{draft_id}.json'
        owner = repo.split('/')[0]
        # Look for a previously created PR before touching the remote branch.
        pulls = self._api('GET', root + '/pulls', params={'head': f'{owner}:{branch}', 'state': 'all'}).json()
        if pulls:
            return pulls[0]['html_url']
        ref_path = root + '/git/ref/heads/' + quote(branch, safe='/')
        existing_ref = self._api('GET', ref_path, expected=(200, 404))
        if existing_ref.status_code == 404:
            base_ref = self._api('GET', root + '/git/ref/heads/' + quote(base, safe='/')).json()
            self._api('POST', root + '/git/refs', expected=(201,),
                      json={'ref': f'refs/heads/{branch}', 'sha': base_ref['object']['sha']})
        contents_path = root + '/contents/' + path
        content = json.dumps(example, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
        existing = self._api('GET', contents_path, expected=(200, 404), params={'ref': branch})
        if existing.status_code == 404:
            self._api('PUT', contents_path, expected=(201,), json={
                'message': f'Propose editorial feedback example {draft_id}',
                'content': b64encode(content.encode('utf-8')).decode('ascii'), 'branch': branch,
            })
        else:
            # A previous attempt may have committed the file before PR creation.
            # Never overwrite an existing file from this automation.
            row = existing.json()
            if row.get('type') != 'file' or b64decode(row.get('content', '')).decode('utf-8') != content:
                raise RuntimeError('feedback branch contains unexpected content; refusing to overwrite it')
        pr = self._api('POST', root + '/pulls', expected=(201,), json={
            'title': f'Editorial feedback: {draft_id[:8]}', 'head': branch, 'base': base,
            'body': ('Proposed example from an owner-approved BUH.SK news draft. '
                     'Review the wording, facts, and privacy before merging. '
                     'Merging makes this example available to future prompts; closing does not.'),
        }).json()
        return pr['html_url']

    def run(self) -> list[str]:
        if not self.s.feedback_pr_enabled:
            return []
        if not self.s.feedback_github_token:
            raise RuntimeError('FEEDBACK_GITHUB_TOKEN is required when FEEDBACK_PR_ENABLED=true')
        with self.store.locked() as state:
            ids = [draft_id for draft_id in state['drafts']
                   if draft_id not in state.setdefault('feedback_prs', {})
                   and approved_example(state, draft_id) is not None]
        created = []
        for draft_id in ids:
            with self.store.locked() as state:
                if draft_id in state.setdefault('feedback_prs', {}):
                    continue
                example = approved_example(state, draft_id)
            if not example:
                continue
            url = self._publish(example)
            with self.store.locked() as state:
                state.setdefault('feedback_prs', {})[draft_id] = {
                    'url': url, 'created_at': datetime.now(timezone.utc).isoformat(),
                }
            created.append(url)
        return created
