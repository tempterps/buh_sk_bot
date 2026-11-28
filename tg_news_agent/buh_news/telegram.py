from __future__ import annotations
from datetime import datetime
from hashlib import sha256
from html import escape
from uuid import uuid4
from telebot import TeleBot, types
from telebot.apihelper import ApiTelegramException
from .publication import Publisher
from .policy import approval_valid

class OwnerBot:
    def __init__(self,store,settings): self.store=store; self.s=settings; self.bot=TeleBot(settings.telegram_token); self.publisher=Publisher(store,settings,self.bot); self._register()
    def _owner(self,user_id,chat_id): return user_id==self.s.owner_user_id and chat_id==self.s.owner_chat_id
    def _alternatives(self,run,draft):
        return [x for x in run.get('ranked_candidates',[]) if x.get('article_id')!=draft['article_id'] and x.get('recommendation')!='reject'][:3]
    def _choice_text(self,alternatives):
        return '\n\n'.join(
            f"{position}. <b>{escape(item.get('title_uk') or item['summary'])}</b>"+
            (f"\n{escape(item['summary'])}" if item.get('title_uk') else '')
            for position,item in enumerate(alternatives,1)
        )
    def _buttons(self,draft_id,version,content_hash):
        ref=sha256(f'{draft_id}:{version}:{content_hash}'.encode()).hexdigest()[:18]
        with self.store.locked() as s:s['approval_events'].append({'draft_id':draft_id,'version':version,'event_type':'preview_created','callback_ref':ref,'created_at':datetime.now(self.s.timezone).isoformat(),'details':{}})
        return types.InlineKeyboardMarkup().row(*[types.InlineKeyboardButton(label,callback_data=f'n:{action}:{ref}') for label,action in [('Опублікувати','approve'),('Відхилити','reject'),('Змінити','change'),('Виправити','correct')]])
    def _selection_buttons(self,ref,count):
        return types.InlineKeyboardMarkup().row(*[
            types.InlineKeyboardButton(f'Варіант {position}',callback_data=f'n:pick:{ref}:{position}')
            for position in range(1,count+1)
        ])
    def _offer_choices(self,draft_id,actor_user_id,actor_chat_id):
        with self.store.locked() as s:
            draft=s['drafts'].get(draft_id)
            if not draft or draft['status'] not in {'pending','revision_requested'} or datetime.fromisoformat(draft['approval_expires_at'])<=datetime.now(self.s.timezone):
                return False
            alternatives=self._alternatives(s['research_runs'].get(draft['run_id'],{}),draft)
            if alternatives:
                ref=uuid4().hex[:18]
                draft['status']='revision_requested'
                s['approval_events'].append({'draft_id':draft_id,'version':draft['current_version'],'event_type':'article_selection_requested','actor_user_id':actor_user_id,'actor_chat_id':actor_chat_id,'callback_ref':ref,'created_at':datetime.now(self.s.timezone).isoformat(),'details':{'article_ids':[x['article_id'] for x in alternatives]}})
            else:
                draft['status']='pending'
        if not alternatives:
            self.bot.send_message(actor_chat_id,'Інших доступних тем у цьому запуску немає. Можна виправити поточну статтю або дочекатися наступного запуску.')
            return False
        self.bot.send_message(actor_chat_id,'<b>Оберіть іншу тему</b>\n\n'+self._choice_text(alternatives),parse_mode='HTML',reply_markup=self._selection_buttons(ref,len(alternatives)))
        return True
    def _pick_article(self,call,ref,position):
        with self.store.locked() as s:
            request=next((x for x in reversed(s['approval_events']) if x['event_type']=='article_selection_requested' and x.get('callback_ref')==ref and not x['details'].get('selected_article_id')),None)
            if not request:
                return
            article_ids=request['details'].get('article_ids',[])
            draft=s['drafts'].get(request['draft_id'])
            latest=next((x for x in reversed(s['approval_events']) if x['event_type']=='article_selection_requested' and x.get('draft_id')==request['draft_id']),None)
            valid=draft and request is latest and request['version']==draft['current_version'] and draft['status']=='revision_requested' and datetime.fromisoformat(draft['approval_expires_at'])>datetime.now(self.s.timezone) and 1<=position<=len(article_ids)
            if valid:
                article_id=article_ids[position-1]; request['details']['selected_article_id']=article_id
                request['details']['selected_at']=datetime.now(self.s.timezone).isoformat(); draft_id=request['draft_id']
        if not valid:
            self.bot.send_message(call.message.chat.id,'Цей вибір уже недійсний. Відкрийте актуальний перегляд чернетки.'); return
        self.bot.send_message(call.message.chat.id,'Готую новий варіант за вибраною статтею…')
        try:
            from .pipeline import ResearchPipeline
            ResearchPipeline(self.store,self.s,self).redraft(draft_id,article_id)
        except Exception as exc:
            # A failed replacement must never strand the owner in an
            # un-actionable state. Restore the last reviewed version.
            from .pipeline import DraftValidationError
            validation_failed=isinstance(exc,DraftValidationError)
            with self.store.locked() as s:
                draft=s['drafts'].get(draft_id)
                if draft and draft['status']=='revision_requested': draft['status']='pending'
                if validation_failed and draft:
                    for candidate in s['research_runs'][draft['run_id']]['ranked_candidates']:
                        if candidate['article_id']==article_id: candidate['recommendation']='reject'
                s['approval_events'].append({'draft_id':draft_id,'version':None,'event_type':'article_selection_failed','actor_user_id':call.from_user.id,'actor_chat_id':call.message.chat.id,'created_at':datetime.now(self.s.timezone).isoformat(),'details':{'selected_article_id':article_id,'reason':type(exc).__name__}})
            if validation_failed:
                self.bot.send_message(call.message.chat.id,'Ця тема не пройшла редакційну перевірку та вилучена з вибору. Ось наступні теми:')
            else:
                self.bot.send_message(call.message.chat.id,'Не вдалося підготувати новий варіант. Спробуйте іншу тему або повторіть вибір пізніше.')
            self._offer_choices(draft_id,call.from_user.id,call.message.chat.id)
    def send_preview(self,draft_id):
        with self.store.locked() as s:
            d=s['drafts'][draft_id]; v=s['versions'][draft_id][str(d['current_version'])]
            content=v['content']; expiry=d['approval_expires_at']; run_id=d['run_id']; version=d['current_version']; content_hash=v['content_hash']
            run=s['research_runs'].get(run_id,{})
            alternatives=self._alternatives(run,d)
        run_cost=self.store.run_cost(run_id)
        alternatives_text=self._choice_text(alternatives) or 'Немає інших релевантних тем у цьому запуску.'
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
            # Telegram only allows a short acknowledgement window.  A delayed
            # or replayed callback can have an expired query ID, but the
            # authenticated version/expiry checks below still decide whether
            # it may affect a draft.
            try:
                self.bot.answer_callback_query(call.id)
            except ApiTelegramException:
                pass
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
            if len(parts)!=3 or action not in {'approve','reject','change','correct'}:return
            with self.store.locked() as s:
                event=next((x for x in reversed(s['approval_events']) if x['event_type']=='preview_created' and x['callback_ref']==ref),None)
                if not event:return
                d=s['drafts'].get(event['draft_id']); v=s['versions'].get(event['draft_id'],{}).get(str(event['version']))
                if not d or not v or not approval_valid(actor_user_id=call.from_user.id,actor_chat_id=call.message.chat.id,owner_user_id=self.s.owner_user_id,owner_chat_id=self.s.owner_chat_id,draft_status=d['status'],current_version=d['current_version'],callback_version=event['version'],expires_at=datetime.fromisoformat(d['approval_expires_at']),review_passed=v['review_passed']):
                    self.bot.send_message(self.s.owner_chat_id,'Цей перегляд уже недійсний.'); return
                draft_id=d['id']
                s['approval_events'].append({'draft_id':draft_id,'version':event['version'],'event_type':action,'actor_user_id':call.from_user.id,'actor_chat_id':call.message.chat.id,'callback_ref':ref,'created_at':datetime.now(self.s.timezone).isoformat(),'details':{}})
                if action=='approve': d['status']='approved'; enqueue=(d['id'],event['version'],v['content_hash'])
                elif action=='reject':d['status']='rejected'
                elif action=='correct':
                    if d['revision_count']>=self.s.max_revisions:
                        correction_limit=True
                    else:
                        correction_limit=False
                        d['status']='revision_requested'
                        s['approval_events'].append({'draft_id':draft_id,'version':event['version'],'event_type':'correction_requested','actor_user_id':call.from_user.id,'actor_chat_id':call.message.chat.id,'created_at':datetime.now(self.s.timezone).isoformat(),'details':{}})
            if action=='approve': self.publisher.enqueue(*enqueue)
            if action=='approve':
                outcome=self.publisher.process_one(); self.bot.send_message(self.s.owner_chat_id,'Схвалено. У preview-режимі публікацію не надіслано.' if outcome=='preview_acknowledged' else 'Схвалено.')
            elif action=='reject':self.bot.send_message(self.s.owner_chat_id,'Чернетку відхилено.')
            elif action=='change':self._offer_choices(draft_id,call.from_user.id,call.message.chat.id)
            elif correction_limit:self.bot.send_message(self.s.owner_chat_id,'Ліміт виправлень для цієї статті вичерпано. Можна обрати іншу тему або відхилити чернетку.')
            else:self.bot.send_message(self.s.owner_chat_id,'Напишіть одним повідомленням, що саме виправити в поточній статті. Автор підготує повний новий варіант із перевіркою джерела.')

        @self.bot.message_handler(content_types=['text'])
        def correct_article(message):
            if not self._owner(message.from_user.id,message.chat.id):
                return
            value=(message.text or '').strip()
            if not value or value.startswith('/'):
                return
            with self.store.locked() as s:
                request=next((x for x in reversed(s['approval_events']) if x['event_type']=='correction_requested' and x.get('actor_user_id')==message.from_user.id and x.get('actor_chat_id')==message.chat.id and not x['details'].get('submitted_at')),None)
                if not request:
                    return
                draft=s['drafts'].get(request['draft_id'])
                valid=draft and draft['status']=='revision_requested' and request['version']==draft['current_version'] and datetime.fromisoformat(draft['approval_expires_at'])>datetime.now(self.s.timezone)
                if not valid:return
                if len(value)>1000:
                    self.bot.send_message(message.chat.id,'Скоротіть інструкцію до 1000 символів і надішліть ще раз.')
                    return
                request['details'].update(instructions=value,submitted_at=datetime.now(self.s.timezone).isoformat())
                draft_id=request['draft_id']
            self.bot.send_message(message.chat.id,'Готую виправлений варіант…')
            try:
                from .pipeline import ResearchPipeline
                ResearchPipeline(self.store,self.s,self).redraft(draft_id,instructions=value)
            except Exception as exc:
                with self.store.locked() as s:
                    draft=s['drafts'].get(draft_id)
                    if draft and draft['status']=='revision_requested':
                        draft['status']='pending'; draft['updated_at']=datetime.now(self.s.timezone).isoformat()
                    s['approval_events'].append({'draft_id':draft_id,'version':None,'event_type':'correction_failed','actor_user_id':message.from_user.id,'actor_chat_id':message.chat.id,'created_at':datetime.now(self.s.timezone).isoformat(),'details':{'reason':type(exc).__name__}})
                self.bot.send_message(message.chat.id,'Виправлений варіант не пройшов перевірку або сталася помилка. Попередня чернетка лишається доступною; натисніть «Виправити» ще раз або оберіть іншу тему.')
    def run(self): self.bot.infinity_polling(skip_pending=True,allowed_updates=['message','callback_query'])
    def expire(self):
        now=datetime.now(self.s.timezone)
        with self.store.locked() as s:
            for d in s['drafts'].values():
                if d['status'] in {'pending','revision_requested'} and datetime.fromisoformat(d['approval_expires_at'])<=now:d['status']='expired'; d['updated_at']=now.isoformat()
            for r in s['research_runs'].values():
                if r['status']=='running':r.update(status='research_failed',finished_at=now.isoformat(),error='stale run recovered by maintenance')
