import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
from core.vod_scraper import Session, get_available_languages

async def test():
    session = Session()
    langs = await get_available_languages(session, "Weak Hero", is_series=True)
    print("Detected languages:")
    for l in langs:
        print(l["code"], l["name"], l["title"], "ep_count:", l.get("ep_count"))

asyncio.run(test())
