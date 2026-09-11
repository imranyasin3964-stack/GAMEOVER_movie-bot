import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
from core.vod_scraper import Session, Search, SubjectType

async def test():
    session = Session()
    for q in ['Weak Hero', 'Weak Hero Hindi']:
        s = Search(session=session, query=q)
        res = await s.get_content_model()
        print(f"=== Results for query: '{q}' ===")
        for it in (res.items if res else []):
            print(f'{it.subjectId}: "{it.title}" | type={it.subjectType} | country={getattr(it, "countryName", None)}')

asyncio.run(test())
