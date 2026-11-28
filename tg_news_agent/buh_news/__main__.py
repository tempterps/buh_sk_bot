from __future__ import annotations
import argparse,json
from .config import settings
from .db import FileStore
from .pipeline import ResearchPipeline,seed_sources
from .telegram import OwnerBot
from .discovery import Fetcher

def main():
    parser=argparse.ArgumentParser(description='BUH.SK news agent'); parser.add_argument('command',choices=['migrate','seed-sources','source-test','run','redraft','bot','expire']); parser.add_argument('--source'); parser.add_argument('--draft'); args=parser.parse_args()
    s=settings(require_runtime=args.command in {'run','bot','expire'}); store=FileStore(s.data_dir); store.init()
    if args.command=='migrate': print(f'file store initialised: {store.root.resolve()}'); return
    seed_sources(store)
    if args.command=='seed-sources': print('source registry seeded; all sources are disabled until tested'); return
    if args.command=='source-test':
        with store.locked() as state:sources=[x.copy() for x in state['sources'].values() if args.source is None or x['id']==args.source]
        fetcher=Fetcher(s.user_agent); failed=False
        for source in sources:
            try:
                items,response=(fetcher.feed(source) if source['method']=='rss' else fetcher.html_listing(source)); checked=[]
                for item in items[:3]:
                    try: article=fetcher.get(item.canonical_url); checked.append({'title':item.title,'date':item.raw_date,'normalized':item.published_at.isoformat() if item.published_at else None,'url':item.canonical_url,'article_http':article.status_code,'final_url':article.url})
                    except Exception as exc: checked.append({'title':item.title,'url':item.canonical_url,'article_error':str(exc)})
                print(json.dumps({'source':source['id'],'http':response.status_code,'items':checked,'count':len(items)},ensure_ascii=False))
            except Exception as exc: failed=True; print(json.dumps({'source':source['id'],'unavailable':str(exc)},ensure_ascii=False))
        raise SystemExit(1 if failed else 0)
    bot=OwnerBot(store,s)
    if args.command=='run': print(ResearchPipeline(store,s,bot).run())
    elif args.command=='redraft':
        if not args.draft: parser.error('--draft is required with redraft')
        print(ResearchPipeline(store,s,bot).redraft(args.draft))
    elif args.command=='expire': bot.expire(); print('expired pending approvals')
    else: bot.run()
if __name__=='__main__':main()
