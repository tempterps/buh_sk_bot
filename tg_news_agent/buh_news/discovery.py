from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, time
from email.utils import parsedate_to_datetime
from hashlib import sha256
import re
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo
import feedparser, requests
from bs4 import BeautifulSoup

BRATISLAVA = ZoneInfo('Europe/Bratislava')
@dataclass
class Item:
    source_id: str; title: str; canonical_url: str; published_at: datetime | None; raw_date: str | None; categories: list[str]; summary: str

def clean(text: str) -> str: return re.sub(r'\s+', ' ', BeautifulSoup(text or '', 'html.parser').get_text(' ', strip=True)).strip()
def canonical(url: str) -> str:
    p = urlsplit(url); return urlunsplit((p.scheme.lower() or 'https', p.netloc.lower(), p.path.rstrip('/') or '/', p.query, ''))
def parse_date(value: str | None) -> datetime | None:
    if not value: return None
    value = value.strip()
    for fmt in ('%d.%m.%Y','%d.%m.%Y %H:%M','%Y-%m-%d','%Y-%m-%dT%H:%M:%S%z'):
        try:
            d = datetime.strptime(value, fmt)
            return d.replace(tzinfo=BRATISLAVA) if d.tzinfo is None else d.astimezone(BRATISLAVA)
        except ValueError: pass
    try:
        d = parsedate_to_datetime(value); return d.replace(tzinfo=BRATISLAVA) if d.tzinfo is None else d.astimezone(BRATISLAVA)
    except (TypeError, ValueError): return None

class Fetcher:
    def __init__(self, user_agent: str): self.session = requests.Session(); self.headers={'User-Agent': user_agent, 'Accept':'application/rss+xml,application/xml,text/html'}
    def get(self, url: str, etag: str | None = None, last_modified: str | None = None) -> requests.Response:
        h=dict(self.headers)
        if etag: h['If-None-Match']=etag
        if last_modified: h['If-Modified-Since']=last_modified
        return self.session.get(url, headers=h, timeout=(5,25), allow_redirects=True)
    def feed(self, source: dict) -> tuple[list[Item], requests.Response]:
        response=self.get(source['discovery_url'],source.get('etag'),source.get('last_modified'))
        if response.status_code == 304: return [], response
        response.raise_for_status(); parsed=feedparser.parse(response.content)
        if parsed.bozo and not parsed.entries: raise ValueError(f"unparseable RSS: {parsed.bozo_exception}")
        result=[]
        for e in parsed.entries:
            link=e.get('link'); title=clean(e.get('title',''))
            if not link or not title: continue
            raw=e.get('published') or e.get('updated') or e.get('date')
            result.append(Item(source['id'],title,canonical(urljoin(response.url,link)),parse_date(raw),raw,[clean(t.get('term','')) for t in e.get('tags',[]) if clean(t.get('term',''))],clean(e.get('summary',''))[:350]))
        return result,response
    def html_listing(self, source: dict) -> tuple[list[Item], requests.Response]:
        response=self.get(source['discovery_url'],source.get('etag'),source.get('last_modified'))
        if response.status_code == 304:return [],response
        response.raise_for_status(); soup=BeautifulSoup(response.text,'html.parser'); result=[]
        # Conservative generic extraction. A source is not enabled until its extracted rows are reviewed.
        for a in soup.select('main article a[href], main .news a[href], main .actuality a[href]'):
            title=clean(a.get_text(' ',strip=True)); href=a.get('href')
            if len(title)<20 or not href: continue
            container=a.find_parent(['article','li','div']); text=clean(container.get_text(' ',strip=True)) if container else title
            dates=re.findall(r'\b\d{1,2}\.\d{1,2}\.\d{4}\b',text)
            result.append(Item(source['id'],title,canonical(urljoin(response.url,href)),parse_date(dates[0]) if dates else None,dates[0] if dates else None,[],text[:350]))
        return result,response

def url_hash(url: str) -> str: return sha256(url.encode()).hexdigest()
def extract_article(fetcher: Fetcher, url: str) -> tuple[str,str]:
    response=fetcher.get(url); response.raise_for_status(); soup=BeautifulSoup(response.text,'html.parser')
    for x in soup(['script','style','nav','footer','aside','form']): x.decompose()
    node=soup.find('article') or soup.find('main') or soup.body
    return canonical(response.url), clean(node.get_text(' ',strip=True))[:50000]

