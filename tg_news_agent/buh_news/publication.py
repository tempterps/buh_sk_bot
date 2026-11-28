from __future__ import annotations
from datetime import datetime
from uuid import uuid4
from telebot import TeleBot
from .policy import publish_allowed

class Publisher:
    def __init__(self,store,settings,bot:TeleBot): self.store=store; self.s=settings; self.bot=bot
    def enqueue(self,draft_id,version,content_hash):
        with self.store.locked() as s:
            if any(x['draft_id']==draft_id and x['version']==version for x in s['outbox'].values()): return
            job=str(uuid4()); s['outbox'][job]={'id':job,'draft_id':draft_id,'version':version,'content_hash':content_hash,'status':'queued','claimed_at':None,'created_at':datetime.now(self.s.timezone).isoformat()}
    def process_one(self):
        with self.store.locked() as s:
            job=next((x for x in s['outbox'].values() if x['status']=='queued'),None)
            if not job:return None
            draft=s['drafts'].get(job['draft_id']); version=s['versions'].get(job['draft_id'],{}).get(str(job['version']))
            unexpired=draft and datetime.fromisoformat(draft['approval_expires_at'])>datetime.now(self.s.timezone)
            allowed=draft and version and version['review_passed'] and publish_allowed(mode='production',enabled=True,review_passed=True,approved=draft['status']=='approved',unexpired=unexpired,already_published=any(x['draft_id']==job['draft_id'] and x['version']==job['version'] for x in s['publications']))
            if not allowed: job['status']='cancelled'; return 'cancelled'
            job['status']='claimed'; job['claimed_at']=datetime.now(self.s.timezone).isoformat(); content=version['content']
        if self.s.mode!='production' or not self.s.publishing_enabled:
            with self.store.locked() as s: s['outbox'][job['id']]['status']='previewed'
            return 'preview_acknowledged'
        try: sent=self.bot.send_message(self.s.production_channel_id,content,parse_mode=None,disable_web_page_preview=True)
        except Exception:
            with self.store.locked() as s:s['outbox'][job['id']]['status']='publication_unknown'
            self.bot.send_message(self.s.owner_chat_id,f'⚠️ Статус публікації невідомий для {job["draft_id"]}. Не надсилайте повторно до ручної звірки.')
            return 'publication_unknown'
        with self.store.locked() as s:
            s['publications'].append({'draft_id':job['draft_id'],'version':job['version'],'content_hash':job['content_hash'],'channel_id':self.s.production_channel_id,'telegram_message_id':sent.message_id,'published_at':datetime.now(self.s.timezone).isoformat()}); s['outbox'][job['id']]['status']='sent'; s['topics'][draft['topic_key']]['last_published_at']=datetime.now(self.s.timezone).isoformat()
        self.bot.send_message(self.s.owner_chat_id,'Опубліковано.'); return 'sent'
