from __future__ import annotations
from datetime import datetime
from hashlib import sha256
from html import escape
from telebot import TeleBot, types
from .publication import Publisher
from .policy import approval_valid

class OwnerBot:
    def __init__(self,store,settings): self.store=store; self.s=settings; self.bot=TeleBot(settings.telegram_token); self.publisher=Publisher(store,settings,self.bot); self._register()
    def _owner(self,user_id,chat_id): return user_id==self.s.owner_user_id and chat_id==self.s.owner_chat_id
    def _alternatives(self,run,draft):
        return [x for x in run.get('ranked_candidates',[]) if x.get('article_id')!=draft['article_id'] and x.get('recommendation')!='reject'][:3]
    def _buttons(self,draft_id,version,content_hash):
        ref=sha256(f'{draft_id}:{version}:{content_hash}'.encode()).hexdigest()[:18]
        with self.store.locked() as s:s['approval_events'].append({'draft_id':draft_id,'version':version,'event_type':'preview_created','callback_ref':ref,'created_at':datetime.now(self.s.timezone).isoformat(),'details':{}})
        return types.InlineKeyboardMarkup().row(*[types.InlineKeyboardButton(label,callback_data=f'n:{action}:{ref}') for label,action in [('Опублікувати','approve'),('Відхилити','reject'),('Змінити','change')]])
    def _selection_buttons(self,ref,count):
        return types.InlineKeyboardMarkup().row(*[
            types.InlineKeyboardButton(f'Варіант {position}',callback_data=f'n:pick:{ref}:{position}')
            for position in range(1,count+1)
        ])
    def _pick_article(self,call,ref,position):
        with self.store.locked() as s:
            request=next((x for x in reversed(s['approval_events']) if x['event_type']=='article_selection_requested' and x.get('callback_ref')==ref and not x['details'].get('selected_article_id')),None)
            if not request:
                return
            article_ids=request['details'].get('article_ids',[])
            draft=s['drafts'].get(request['draft_id'])
            valid=draft and draft['status']=='revision_requested' and datetime.fromisoformat(draft['approval_expires_at'])>datetime.now(self.s.timezone) and 1<=position<=len(article_ids)
            if valid:
                article_id=article_ids[position-1]; request['details']['selected_article_id']=article_id
                request['details']['selected_at']=datetime.now(self.s.timezone).isoformat(); draft_id=request['draft_id']
        if not valid:
            self.bot.send_message(call.message.chat.id,'Цей вибір уже недійсний. Відкрийте актуальний перегляд чернетки.'); return
        self.bot.send_message(call.message.chat.id,'Готую новий варіант за вибраною статтею…')
        try:
            from .pipeline import ResearchPipeline
            ResearchPipeline(self.store,self.s,self).redraft(draft_id,article_id)
        except Exception:
            # A failed replacement must never strand the owner in an
            # un-actionable state. Restore the last reviewed version.
            with self.store.locked() as s:
                draft=s['drafts'].get(draft_id)
                if draft and draft['status']=='revision_requested':
                    draft['status']='pending'; draft['updated_at']=datetime.now(self.s.timezone).isoformat()
                s['approval_events'].append({'draft_id':draft_id,'version':None,'event_type':'article_selection_failed','actor_user_id':call.from_user.id,'actor_chat_id':call.message.chat.id,'created_at':datetime.now(self.s.timezone).isoformat(),'details':{'selected_article_id':article_id}})
            self.bot.send_message(call.message.chat.id,'Новий варіант не пройшов перевірку фактів і не був надісланий. Попередній перевірений варіант залишається безпечним; оберіть іншу тему через «Змінити».')
    def send_preview(self,draft_id):
        with self.store.locked() as s:
            d=s['drafts'][draft_id]; v=s['versions'][draft_id][str(d['current_version'])]
            content=v['content']; expiry=d['approval_expires_at']; run_id=d['run_id']; version=d['current_version']; content_hash=v['content_hash']
            run=s['research_runs'].get(run_id,{})
            alternatives=self._alternatives(run,d)
        run_cost=self.store.run_cost(run_id)
        alternatives_text='\n\n'.join(
            f"{index}. <b>{escape(item.get('title_uk') or item['summary'])}</b>"+
            (f"\n{escape(item['summary'])}" if item.get('title_uk') else '')
            for index,item in enumerate(alternatives,1)
        ) or 'Немає інших релевантних тем у цьому запуску.'
        note=(f"<b>Редакційна нотатка</b>\n💳 AI за цей запуск: <b>${run_cost:.6f}</b>\n\n"
              f"<b>Ще 3 сильні теми</b>\n{alternatives_text}\n\n"
              f"Дійсне до: {datetime.fromisoformat(expiry).strftime('%Y-%m-%d %H:%M %Z')}")
        message=self.bot.send_message(self.s.owner_chat_id,content,parse_mode='HTML',disable_web_page_preview=True)
        note_message=self.bot.send_message(self.s.owner_chat_id,note,parse_mode='HTML',reply_markup=self._buttons(draft_id,version,content_hash),disable_web_page_preview=True)
        with self.store.locked() as s:s['versions'][draft_id][str(version)].update(preview_message_id=message.message_id,note_message_id=note_message.message_id)
    def _register(self):
        @self.bot.callback_query_handler(func=lambda c:(c.data or '').startswith('n:'))
        def callback(call):
            # Record receipt before authorization so an owner-ID mismatch can be
            # diagnosed without exposing a callback to publication.
            with self.store.locked() as s:
                s['approval_events'].append({'draft_id':None,'version':None,'event_type':'callback_received','actor_user_id':call.from_user.id,'actor_chat_id':call.message.chat.id,'callback_ref':(call.data or '')[-18:],'created_at':datetime.now(self.s.timezone).isoformat(),'details':{}})
            self.bot.answer_callback_query(call.id)
            if not self._owner(call.from_user.id,call.message.chat.id):
                with self.store.locked() as s:
                    s['approval_events'].append({'draft_id':None,'version':None,'event_type':'callback_unauthorized','actor_user_id':call.from_user.id,'actor_chat_id':call.message.chat.id,'callback_ref':(call.data or '')[-18:],'created_at':datetime.now(self.s.timezone).isoformat(),'details':{}})
                self.bot.send_message(call.message.chat.id,'This approval control is not authorized for this Telegram account.')
                return
            parts=call.data.split(':')
            if len(parts)<3:return
            action,ref=parts[1],parts[2]
            if action=='pick':
                try: position=int(parts[3])
                except (IndexError,ValueError): return
                self._pick_article(call,ref,position)
                return
            if len(parts)!=3:return
            with self.store.locked() as s:
                event=next((x for x in reversed(s['approval_events']) if x['event_type']=='preview_created' and x['callback_ref']==ref),None)
                if not event:return
                d=s['drafts'].get(event['draft_id']); v=s['versions'].get(event['draft_id'],{}).get(str(event['version']))
                if not d or not v or not approval_valid(actor_user_id=call.from_user.id,actor_chat_id=call.message.chat.id,owner_user_id=self.s.owner_user_id,owner_chat_id=self.s.owner_chat_id,draft_status=d['status'],current_version=d['current_version'],callback_version=event['version'],expires_at=datetime.fromisoformat(d['approval_expires_at']),review_passed=v['review_passed']):
                    self.bot.send_message(self.s.owner_chat_id,'Цей перегляд уже недійсний.'); return
                s['approval_events'].append({'draft_id':d['id'],'version':event['version'],'event_type':action,'actor_user_id':call.from_user.id,'actor_chat_id':call.message.chat.id,'callback_ref':ref,'created_at':datetime.now(self.s.timezone).isoformat(),'details':{}})
                if action=='approve': d['status']='approved'; enqueue=(d['id'],event['version'],v['content_hash'])
                elif action=='reject':d['status']='rejected'
                elif action=='change':
                    alternatives=self._alternatives(s['research_runs'].get(d['run_id'],{}),d)
                    if not alternatives:
                        self.bot.send_message(self.s.owner_chat_id,'Немає інших релевантних статей для вибору.'); return
                    d['status']='revision_requested'
                    s['approval_events'].append({'draft_id':d['id'],'version':event['version'],'event_type':'article_selection_requested','actor_user_id':call.from_user.id,'actor_chat_id':call.message.chat.id,'callback_ref':ref,'created_at':datetime.now(self.s.timezone).isoformat(),'details':{'article_ids':[x['article_id'] for x in alternatives]}})
            if action=='approve': self.publisher.enqueue(*enqueue)
            if action=='approve':
                outcome=self.publisher.process_one(); self.bot.send_message(self.s.owner_chat_id,'Схвалено. У preview-режимі публікацію не надіслано.' if outcome=='preview_acknowledged' else 'Схвалено.')
            elif action=='reject':self.bot.send_message(self.s.owner_chat_id,'Чернетку відхилено.')
            else:self.bot.send_message(self.s.owner_chat_id,'Оберіть іншу тему:',reply_markup=self._selection_buttons(ref,len(alternatives)))

        @self.bot.message_handler(content_types=['text'])
        def choose_article(message):
            if not self._owner(message.from_user.id,message.chat.id):
                return
            value=(message.text or '').strip()
            if value not in {'1','2','3'}:
                return
            with self.store.locked() as s:
                request=next((x for x in reversed(s['approval_events']) if x['event_type']=='article_selection_requested' and x.get('actor_user_id')==message.from_user.id and x.get('actor_chat_id')==message.chat.id and not x['details'].get('selected_article_id')),None)
                if not request:
                    return
                article_ids=request['details'].get('article_ids',[]); position=int(value)-1
                if position>=len(article_ids):
                    self.bot.send_message(message.chat.id,'Доступні лише номери: '+', '.join(str(i) for i in range(1,len(article_ids)+1))+'.')
                    return
                request['details']['selected_article_id']=article_ids[position]
                request['details']['selected_at']=datetime.now(self.s.timezone).isoformat()
                draft_id=request['draft_id']; article_id=article_ids[position]
            self.bot.send_message(message.chat.id,'Готую новий варіант за вибраною статтею…')
            try:
                from .pipeline import ResearchPipeline
                ResearchPipeline(self.store,self.s,self).redraft(draft_id,article_id)
            except Exception:
                # A failed replacement must never strand the owner in an
                # un-actionable state.  Restore the last reviewed version so
                # its existing controls can be used to choose another topic.
                with self.store.locked() as s:
                    draft=s['drafts'].get(draft_id)
                    if draft and draft['status']=='revision_requested':
                        draft['status']='pending'; draft['updated_at']=datetime.now(self.s.timezone).isoformat()
                    s['approval_events'].append({'draft_id':draft_id,'version':None,'event_type':'article_selection_failed','actor_user_id':message.from_user.id,'actor_chat_id':message.chat.id,'created_at':datetime.now(self.s.timezone).isoformat(),'details':{'selected_article_id':article_id}})
                self.bot.send_message(message.chat.id,'Новий варіант не пройшов перевірку фактів і не був надісланий. Попередній перевірений варіант залишається безпечним; оберіть іншу тему через «Змінити».')
    def run(self): self.bot.infinity_polling(skip_pending=True,allowed_updates=['message','callback_query'])
    def expire(self):
        now=datetime.now(self.s.timezone)
        with self.store.locked() as s:
            for d in s['drafts'].values():
                if d['status'] in {'pending','revision_requested'} and datetime.fromisoformat(d['approval_expires_at'])<=now:d['status']='expired'; d['updated_at']=now.isoformat()
            for r in s['research_runs'].values():
                if r['status']=='running':r.update(status='research_failed',finished_at=now.isoformat(),error='stale run recovered by maintenance')
