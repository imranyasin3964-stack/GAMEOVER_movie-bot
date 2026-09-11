import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
from core.vod_scraper import Session, Search, SubjectType
import difflib, re

async def test_lang_detect(clean_title, is_series=True, existing_items=None):
    session = Session()
    await session.ensure_cookies_are_assigned()
    
    seen_subjects = set()
    lang_map = {}
    
    # First inspect existing items
    candidates = list(existing_items or [])
    
    queries = [clean_title, f"{clean_title} Hindi", f"{clean_title} English"]
    clean_words = set(clean_title.lower().split())
    
    async def fetch(q):
        try:
            s = Search(session=session, query=q)
            return await s.get_content_model()
        except Exception as e:
            print(f"Fetch err for {q}: {e}")
            return None

    results = await asyncio.gather(*(fetch(q) for q in queries))
    for r in results:
        if r and r.items:
            candidates.extend(r.items)
            
    for it in candidates:
        if it.subjectId in seen_subjects:
            continue
        seen_subjects.add(it.subjectId)
        
        t_lower = it.title.lower()
        c_lower = getattr(it, "countryName", "").lower()
        
        # Check title overlap
        clean_it = re.sub(r'\[.*?\]', '', it.title).strip()
        clean_it = re.sub(r'\s+S\d+(-S\d+)?', '', clean_it, flags=re.IGNORECASE).strip().lower()
        
        # Words match
        it_words = set(clean_it.split())
        overlap = clean_words.intersection(it_words)
        if not overlap and difflib.SequenceMatcher(None, clean_title.lower(), clean_it).ratio() < 0.5:
            continue
            
        if "hindi" in t_lower:
            code, name = "hi", "Hindi"
        elif "english" in t_lower:
            code, name = "en", "English"
        elif "japanese" in t_lower or ("japan" in c_lower and "hindi" not in t_lower):
            code, name = "ja", "Japanese"
        elif "korean" in t_lower or ("korea" in c_lower and "hindi" not in t_lower):
            code, name = "ko", "Korean"
        elif "spanish" in t_lower:
            code, name = "es", "Spanish"
        elif "russian" in t_lower:
            code, name = "ru", "Russian"
        elif "tamil" in t_lower:
            code, name = "ta", "Tamil"
        elif "telugu" in t_lower:
            code, name = "te", "Telugu"
        else:
            code, name = "orig", "Original"
            
        if code not in lang_map:
            lang_map[code] = {"code": code, "name": name, "title": it.title}
            
    print("Detected:", lang_map.keys())
    for k, v in lang_map.items():
        print(f"  {k}: {v['name']} ({v['title']})")

asyncio.run(test_lang_detect("Weak Hero", True))
