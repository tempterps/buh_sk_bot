from __future__ import annotations
from datetime import datetime
from decimal import Decimal
import json, uuid
import requests
from .config import Settings

RANKING_SCHEMA={"type":"object","additionalProperties":False,"properties":{"rankings":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{"candidate_id":{"type":"integer"},"topic_key":{"type":"string"},"owner_title":{"type":"string"},"relevance":{"type":"integer","minimum":0,"maximum":3},"consequence":{"type":"integer","minimum":0,"maximum":3},"novelty":{"type":"integer","minimum":0,"maximum":2},"source_quality":{"type":"integer","minimum":0,"maximum":2},"audience_impact":{"type":"string"},"novelty_reason":{"type":"string"},"missing_information":{"type":"string"},"needs_primary_verification":{"type":"boolean"},"recommendation":{"type":"string","enum":["select","reject","hold"]}},"required":["candidate_id","topic_key","owner_title","relevance","consequence","novelty","source_quality","audience_impact","novelty_reason","missing_information","needs_primary_verification","recommendation"]}}},"required":["rankings"]}
WRITING_SCHEMA={"type":"object","additionalProperties":False,"properties":{"post":{"type":"string"},"evidence":{"type":"object","additionalProperties":False,"properties":{"source_urls":{"type":"array","items":{"type":"string"}},"claims":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{"claim":{"type":"string"},"support":{"type":"string"}},"required":["claim","support"]}},"publication_status":{"type":"string"},"affected_audience":{"type":"string"},"missing_info":{"type":"string"}},"required":["source_urls","claims","publication_status","affected_audience","missing_info"]},"status":{"type":"string","enum":["ready","insufficient_evidence"]}},"required":["post","evidence","status"]}
REVIEW_SCHEMA={"type":"object","additionalProperties":False,"properties":{"passed":{"type":"boolean"},"unsupported_claims":{"type":"array","items":{"type":"string"}},"notes":{"type":"array","items":{"type":"string"}}},"required":["passed","unsupported_claims","notes"]}
PROOFREAD_SCHEMA={"type":"object","additionalProperties":False,"properties":{"post":{"type":"string"},"status":{"type":"string","enum":["ready","insufficient_evidence"]}},"required":["post","status"]}
class BudgetError(RuntimeError): pass

class AI:
    def __init__(self, store, settings: Settings): self.store=store; self.s=settings
    def _price(self,stage,inp,out):
        i,o=(self.s.ranking_input_price,self.s.ranking_output_price) if stage=='ranking' else (self.s.writing_input_price,self.s.writing_output_price)
        if i is None or o is None: raise BudgetError('price table is not verified')
        return (Decimal(inp)*i+Decimal(out)*o)/Decimal(1_000_000)
    def reserve(self,run_id,stage,model,max_input,max_output):
        if not self.s.ai_enabled: raise BudgetError('AI disabled: set key and verified price table')
        reservation=str(uuid.uuid4()); amount=self._price(stage,max_input,max_output); now=datetime.now(self.s.timezone)
        with self.store.locked() as state:
            month=now.strftime('%Y-%m'); consumed=sum((Decimal(str(x.get('actual_usd') if x.get('actual_usd') is not None else x['reserved_usd'])) for x in state['ai_reservations'].values() if x['month']==month and x['status'] in {'reserved','reconciled','held'}),Decimal('0'))
            if consumed+amount>self.s.monthly_budget: raise BudgetError('monthly AI budget would be exceeded')
            state['ai_reservations'][reservation]={'id':reservation,'run_id':run_id,'stage':stage,'model':model,'month':month,'reserved_usd':str(amount),'actual_usd':None,'input_tokens':None,'output_tokens':None,'reasoning_tokens':None,'status':'reserved','created_at':now.isoformat()}
        self.store.append_usage({'event':'reserved','reservation_id':reservation,'run_id':run_id,'stage':stage,'model':model,'estimated_usd':str(amount),'at':now.isoformat()})
        return reservation
    def call(self,run_id,stage,model,prompt,schema,max_input,max_output):
        if len(prompt)>max_input*3: raise ValueError('prompt exceeds stage input bound')
        rid=self.reserve(run_id,stage,model,max_input,max_output)
        body={'model':model,'input':[{'role':'user','content':[{'type':'input_text','text':prompt}]}],'max_output_tokens':max_output,'text':{'format':{'type':'json_schema','name':f'{stage}_result','strict':True,'schema':schema}}}
        self.store.append_agent_trace({'event':'agent_request','reservation_id':rid,'run_id':run_id,'stage':stage,'model':model,'prompt':prompt,'max_input_tokens':max_input,'max_output_tokens':max_output,'schema_name':f'{stage}_result','at':datetime.now(self.s.timezone).isoformat()})
        try:
            response=requests.post(self.s.api_url,headers={'Authorization':f'Bearer {self.s.openai_key}','Content-Type':'application/json'},json=body,timeout=(10,90))
            if not response.ok:
                try: detail=response.json().get('error',{}).get('message',response.text)
                except ValueError: detail=response.text
                raise RuntimeError(f'OpenAI HTTP {response.status_code}: {detail[:1000]}')
            data=response.json()
            text=''.join(part.get('text','') for output in data.get('output',[]) for part in output.get('content',[]) if part.get('type')=='output_text'); result=json.loads(text)
            usage=data.get('usage',{}); inp=int(usage.get('input_tokens',0)); out=int(usage.get('output_tokens',0)); reasoning=int(usage.get('output_tokens_details',{}).get('reasoning_tokens',0)); actual=self._price(stage,inp,out+reasoning)
            with self.store.locked() as state: state['ai_reservations'][rid].update(actual_usd=str(actual),input_tokens=inp,output_tokens=out,reasoning_tokens=reasoning,status='reconciled')
            self.store.append_usage({'event':'reconciled','reservation_id':rid,'run_id':run_id,'stage':stage,'model':model,'input_tokens':inp,'output_tokens':out,'reasoning_tokens':reasoning,'actual_usd':str(actual),'at':datetime.now(self.s.timezone).isoformat()})
            self.store.append_agent_trace({'event':'agent_response','reservation_id':rid,'run_id':run_id,'stage':stage,'model':model,'response_id':data.get('id'),'raw_output_text':text,'parsed_response':result,'usage':{'input_tokens':inp,'output_tokens':out,'reasoning_tokens':reasoning},'actual_usd':str(actual),'at':datetime.now(self.s.timezone).isoformat()})
            return result
        except Exception as exc:
            with self.store.locked() as state: state['ai_reservations'][rid]['status']='held'
            self.store.append_usage({'event':'held','reservation_id':rid,'run_id':run_id,'stage':stage,'model':model,'reason':type(exc).__name__,'at':datetime.now(self.s.timezone).isoformat()})
            self.store.append_agent_trace({'event':'agent_error','reservation_id':rid,'run_id':run_id,'stage':stage,'model':model,'error_type':type(exc).__name__,'error_message':str(exc)[:2000],'at':datetime.now(self.s.timezone).isoformat()})
            raise

STYLE='''Write a finished, publication-ready Ukrainian Telegram post for Ukrainians in Slovakia who run or consider živnosť or s.r.o. Use clean Telegram HTML: one concise <b>headline</b> followed by exactly two short body paragraphs; use only <b> and </b> tags, with no Markdown, links, tables, hashtags, emojis or editorial notes. HARD LIMIT: no more than 700 visible characters including the footer. Be direct: lead with the change and date, then who is affected and the concrete consequence. Do not repeat facts or dates. Delete every sentence that adds no specific, sourced value. Do not add facts, legal advice, invented links, generic filler, recommendations or action checklists. The only permitted non-evidenced text is the fixed footer. End exactly with: Питання щодо вашої ситуації — пишіть @buh_sk\nbuh.sk'''
