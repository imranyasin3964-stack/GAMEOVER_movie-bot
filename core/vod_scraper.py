"""
MovieBox — VOD Scraper Backend
Connects directly to moviebox.ph using the moviebox-api Python package.
100% independent of Node.js servers,
"""

# ─── Dynamic API Rerouting Patch ──────────────────────────────────────────
import moviebox_api.v1.requests as r_mod_v1
import moviebox_api.v2.requests as r_mod_v2

orig_get_v1 = r_mod_v1.Session.get
orig_post_v1 = r_mod_v1.Session.post
orig_get_with_cookies_v1 = r_mod_v1.Session.get_with_cookies

orig_get_v2 = r_mod_v2.Session.get
orig_post_v2 = r_mod_v2.Session.post
orig_get_with_cookies_v2 = r_mod_v2.Session.get_with_cookies

def redirect_url(url: str) -> str:
    if not url:
        return url
    from core.domain_manager import get_domain
    domain = get_domain()
    # ONLY replace h5-api.aoneroom.com (search backend) which is blocked on moviebox.ph
    # Keep h5.aoneroom.com (play/download backend) untouched
    if "h5-api.aoneroom.com" in url:
        new_url = url.replace("h5-api.aoneroom.com", domain)
        return new_url
    return url

def prepare_search_payload(url: str, kwargs: dict):
    if "subject/search" in url:
        keyword = ""
        if "json" in kwargs and isinstance(kwargs["json"], dict):
            keyword = kwargs["json"].get("keyword", "")
        elif "data" in kwargs and isinstance(kwargs["data"], dict):
            keyword = kwargs["data"].get("keyword", "")
            
        kwargs["json"] = {"keyword": keyword, "page": 1}
        if "data" in kwargs:
            del kwargs["data"]
            
        vod_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://themoviebox.org",
            "Referer": "https://themoviebox.org/",
        }
        if "headers" not in kwargs:
            kwargs["headers"] = {}
        kwargs["headers"].update(vod_headers)

# Patched request methods for V1
async def patched_get_v1(self, url: str, *args, **kwargs):
    url = redirect_url(url)
    return await orig_get_v1(self, url, *args, **kwargs)

async def patched_post_v1(self, url: str, *args, **kwargs):
    url = redirect_url(url)
    prepare_search_payload(url, kwargs)
    return await orig_post_v1(self, url, *args, **kwargs)

async def patched_get_with_cookies_v1(self, url: str, *args, **kwargs):
    url = redirect_url(url)
    return await orig_get_with_cookies_v1(self, url, *args, **kwargs)

# Patched request methods for V2
async def patched_get_v2(self, url: str, *args, **kwargs):
    url = redirect_url(url)
    return await orig_get_v2(self, url, *args, **kwargs)

async def patched_post_v2(self, url: str, *args, **kwargs):
    url = redirect_url(url)
    prepare_search_payload(url, kwargs)
    return await orig_post_v2(self, url, *args, **kwargs)

async def patched_get_with_cookies_v2(self, url: str, *args, **kwargs):
    url = redirect_url(url)
    return await orig_get_with_cookies_v2(self, url, *args, **kwargs)

# Apply patches to session methods
r_mod_v1.Session.get = patched_get_v1
r_mod_v1.Session.post = patched_post_v1
r_mod_v1.Session.get_with_cookies = patched_get_with_cookies_v1

r_mod_v2.Session.get = patched_get_v2
r_mod_v2.Session.post = patched_post_v2
r_mod_v2.Session.get_with_cookies = patched_get_with_cookies_v2

# Patch __init__ for both to set Origin/Referer headers
orig_init_v1 = r_mod_v1.Session.__init__
orig_init_v2 = r_mod_v2.Session.__init__

import httpx

def patched_init_v1(self, *args, **kwargs):
    orig_init_v1(self, *args, **kwargs)
    from core.domain_manager import get_domain
    domain = get_domain()
    self._client.headers.update({
        "Origin": f"https://{domain}",
        "Referer": f"https://{domain}/"
    })
    self._client.timeout = httpx.Timeout(20.0, connect=10.0)

def patched_init_v2(self, *args, **kwargs):
    orig_init_v2(self, *args, **kwargs)
    from core.domain_manager import get_domain
    domain = get_domain()
    self._client.headers.update({
        "Origin": f"https://{domain}",
        "Referer": f"https://{domain}/"
    })
    self._client.timeout = httpx.Timeout(20.0, connect=10.0)

r_mod_v1.Session.__init__ = patched_init_v1
r_mod_v2.Session.__init__ = patched_init_v2

# Update absolute URLs
for cls in (r_mod_v1.Session, r_mod_v2.Session):
    if hasattr(cls, "_moviebox_app_info_url"):
        cls._moviebox_app_info_url = redirect_url(cls._moviebox_app_info_url)
    if hasattr(cls, "_user_info_endpoint"):
        cls._user_info_endpoint = redirect_url(cls._user_info_endpoint)

# Apply _fetch_user_info patch
import json as _json

async def patched_fetch_user_info(self):
    from core.domain_manager import get_domain
    domain = get_domain()
    original_endpoint = getattr(self, "_user_info_endpoint", "https://h5-api.aoneroom.com/wefeed-h5api-bff/subject/search-suggest")
    redirected_endpoint = redirect_url(original_endpoint)
    
    response = await self._client.post(
        url=redirected_endpoint, json={"keyword": "avatar", "perPage": 0}
    )
    response.raise_for_status()

    user_info_header = response.headers.get("x-user")
    if not user_info_header:
        raise Exception("App-info response misses x-user key in headers (MissingAuthError)")
    
    from moviebox_api.v1.requests import UserInfo
    self.user_info = UserInfo(**_json.loads(user_info_header))
    self._client.headers.update({"Authorization": f"Bearer {self.user_info.token}"})
    return self.user_info

r_mod_v1.Session._fetch_user_info = patched_fetch_user_info
r_mod_v2.Session._fetch_user_info = patched_fetch_user_info
# ──────────────────────────────────────────────────────────────────────────

from moviebox_api.v2 import Session, Search, TVSeriesDetails
from moviebox_api.v1.stream import StreamFilesDetail
from moviebox_api.v2.models import SearchResultsItem
from moviebox_api.v2.constants import SubjectType
import re

# Fix packaging bug in moviebox_api.v1.stream.StreamFilesDetail at runtime
class FixedStreamFilesDetail(StreamFilesDetail):
    async def get_content_model(self, season: int, episode: int):
        return await self.get_modelled_content(season, episode)


import difflib


def normalize_search_query(q: str) -> str:
    """Normalizes compound names and common movie variations (e.g. spiderman -> spider-man)."""
    q_norm = re.sub(r'\bspiderman\b', 'spider-man', q, flags=re.IGNORECASE)
    q_norm = re.sub(r'\bspider\s+man\b', 'spider-man', q_norm, flags=re.IGNORECASE)
    q_norm = re.sub(r'\bironman\b', 'iron man', q_norm, flags=re.IGNORECASE)
    q_norm = re.sub(r'\bantman\b', 'ant-man', q_norm, flags=re.IGNORECASE)
    q_norm = re.sub(r'\bxmen\b', 'x-men', q_norm, flags=re.IGNORECASE)
    return q_norm


def extract_sequel_numbers(title: str) -> set:
    """Extract standalone digits and Roman numerals representing sequel/part numbers."""
    clean = re.sub(r'\[.*?\]', '', title).lower()
    clean = re.sub(r'\b(?:season|s|ep|episode)\s*\d+\b', '', clean)
    nums = set(re.findall(r'\b(?:\d+|ii|iii|iv|v|vi|vii|viii|ix|x)\b', clean))
    return nums


async def search_vod(query: str, language: str = "hi"):
    """
    Search MovieBox for a query and return ranked list of SearchResultsItem objects.
    Defaults to Hindi preference (language="hi").
    Uses normalized alias expansion, stem title querying, sequel conflict checks, and fuzzy score ranking.
    """
    session = Session()
    
    norm_query = normalize_search_query(query)
    # Clean query for search endpoint (strip season/ep markers)
    clean_query = re.sub(r'\s+S\d+(-S\d+)?\b', '', norm_query, flags=re.IGNORECASE)
    clean_query = re.sub(r'\s+Season\s+\d+\b', '', clean_query, flags=re.IGNORECASE)
    clean_query = re.sub(r'\s+Ep?\s*\d+\b', '', clean_query, flags=re.IGNORECASE)
    clean_query = clean_query.strip()

    is_hi = (language == "hi") or bool(re.search(r'\b(hindi|dubbed|dub)\b', query, re.IGNORECASE))
    base_title = re.sub(r'\b(hindi|dubbed|dub|eng|english)\b', '', clean_query, flags=re.IGNORECASE).strip()
    base_title = re.sub(r'\s+', ' ', base_title).strip()
    if not base_title:
        base_title = clean_query

    # Also extract stem title without sequel digits (e.g. 'spider-man' from 'spider-man 2')
    stem_title = re.sub(r'\b(?:\d+|ii|iii|iv|v|vi|vii|viii|ix|x)\b', '', base_title, flags=re.IGNORECASE).strip()
    stem_title = re.sub(r'\s+', ' ', stem_title).strip()

    seen_ids = set()
    raw_items = []

    # 1. Multi-target queries based on intent
    queries_to_try = []
    # Hindi targeted variations first
    queries_to_try.append(f"{base_title} Hindi")
    if stem_title and stem_title != base_title:
        queries_to_try.append(f"{stem_title} Hindi")
    # Base title variations
    queries_to_try.append(base_title)
    if stem_title and stem_title != base_title:
        queries_to_try.append(stem_title)
    # Hyphen/space alternatives (e.g. spider man 2 vs spider-man 2)
    if "-" in base_title:
        queries_to_try.append(f"{base_title.replace('-', ' ')} Hindi")
        queries_to_try.append(base_title.replace('-', ' '))
        queries_to_try.append(base_title.replace('-', ''))
    if clean_query != base_title:
        queries_to_try.append(clean_query)

    # Deduplicate queries preserving order
    seen_queries = set()
    dedup_queries = []
    for q in queries_to_try:
        q_str = q.strip()
        if q_str and q_str.lower() not in seen_queries:
            seen_queries.add(q_str.lower())
            dedup_queries.append(q_str)

    for q in dedup_queries:
        try:
            search_client = Search(session=session, query=q)
            results = await search_client.get_content_model()
            if results and results.items:
                for item in results.items:
                    if item.subjectId not in seen_ids:
                        seen_ids.add(item.subjectId)
                        raw_items.append(item)
        except Exception as err:
            print(f"[VOD Scraper] Search attempt '{q}' failed: {err}")

    # 2. If still no items, try toggling "The " prefix for fuzzy match
    if not raw_items:
        alt_query = base_title[4:] if base_title.lower().startswith("the ") else f"The {base_title}"
        try:
            search_client = Search(session=session, query=alt_query)
            results = await search_client.get_content_model()
            if results and results.items:
                for item in results.items:
                    if item.subjectId not in seen_ids:
                        seen_ids.add(item.subjectId)
                        raw_items.append(item)
        except Exception as err:
            print(f"[VOD Scraper] Alt search attempt failed: {err}")

    if not raw_items:
        return []

    # 3. Fuzzy score ranking algorithm with sequel conflict detection
    q_nums = extract_sequel_numbers(base_title)
    query_lower = base_title.lower()
    query_words = [w for w in query_lower.split() if len(w) > 1]

    def rank_score(item: SearchResultsItem) -> float:
        title_lower = item.title.lower()
        clean_title = re.sub(r'\[.*?\]', '', title_lower).replace("dubbed", "").strip()
        clean_title = re.sub(r'\s+s\d+(-s\d+)?', '', clean_title).strip()

        # Sequel number conflict check
        c_nums = extract_sequel_numbers(clean_title)
        if q_nums:
            if not c_nums:
                return -5.0  # Query asked for sequel number, candidate has none
            if not q_nums.issubset(c_nums):
                return -10.0  # Conflict (e.g. 2 vs 3)

        # Disqualify items that share zero words and low similarity
        matched_words = sum(1 for w in query_words if w in clean_title)
        ratio = difflib.SequenceMatcher(None, query_lower, clean_title).ratio()
        if not matched_words and ratio < 0.45 and (query_lower not in clean_title):
            return -15.0

        score = ratio

        # Exact / Substring match boost
        if query_lower == clean_title:
            score += 1.0
        elif query_lower in clean_title:
            score += 0.5

        # Word overlap boost
        if query_words:
            score += (matched_words / len(query_words)) * 0.4

        # Exact sequel number match bonus
        if q_nums and q_nums.issubset(c_nums):
            score += 0.8

        # Hindi preference boost
        if is_hi and ("hindi" in title_lower or "hindi" in getattr(item, "countryName", "").lower()):
            score += 1.2
        elif not is_hi and "hindi" not in title_lower:
            score += 0.2

        return score

    # Filter out heavily penalized / disqualified items
    ranked_items = [it for it in raw_items if rank_score(it) > -4.0]
    ranked_items.sort(key=rank_score, reverse=True)
    return ranked_items if ranked_items else raw_items


async def search_hindi_version(session: Session, original_title: str):
    """
    Do a secondary background search to find a Hindi dubbed/original version of the title.
    """
    clean_query = re.sub(r'\s+S\d+\b', '', original_title, flags=re.IGNORECASE)
    clean_query = re.sub(r'\s+Season\s+\d+\b', '', clean_query, flags=re.IGNORECASE)
    clean_query = clean_query.strip()
    
    query = f"{clean_query} Hindi"
    search_client = Search(session=session, query=query)
    results = await search_client.get_content_model()
    
    if not results.items:
        return None
        
    orig_clean = original_title.lower().replace("[hindi]", "").replace("[english]", "").strip()
    orig_words = [w for w in orig_clean.split() if w]
    
    for item in results.items:
        title_lower = item.title.lower()
        if "hindi" in title_lower:
            target_clean = title_lower.replace("[hindi]", "").replace("[english]", "")
            if all(word in target_clean for word in orig_words):
                return item
            
    return None


async def search_english_version(session: Session, original_title: str):
    """
    Do a secondary background search to find an English dubbed version of the title.
    """
    clean_query = re.sub(r'\s+S\d+\b', '', original_title, flags=re.IGNORECASE)
    clean_query = re.sub(r'\s+Season\s+\d+\b', '', clean_query, flags=re.IGNORECASE)
    clean_query = clean_query.strip()
    
    query = f"{clean_query} English"
    search_client = Search(session=session, query=query)
    results = await search_client.get_content_model()
    
    if not results.items:
        return None
        
    orig_clean = original_title.lower().replace("[hindi]", "").replace("[english]", "").strip()
    orig_words = [w for w in orig_clean.split() if w]
    
    for item in results.items:
        title_lower = item.title.lower()
        if "english" in title_lower:
            target_clean = title_lower.replace("[hindi]", "").replace("[english]", "")
            if all(word in target_clean for word in orig_words):
                return item
            
    return None


async def fetch_tv_details(session: Session, item: SearchResultsItem):
    """
    Fetch specific details (seasons, episodes) for a TV Series item.
    Ensures seasons are sorted ascending (Season 1, Season 2, etc.).
    """
    tv_details_client = TVSeriesDetails(session=session)
    details = await tv_details_client.get_content_model(item)
    if details and details.resource and details.resource.seasons:
        details.resource.seasons.sort(key=lambda s: getattr(s, 'se', 0))
    return details


async def resolve_stream_link(session: Session, item: SearchResultsItem, season: int = 0, episode: int = 0, quality: str = None):
    """
    Resolve the direct streaming URL for a movie or specific TV episode based on admin quality preferences.
    """
    from core.db import get_setting
    if not quality:
        q_setting = get_setting("quality_pref") or "720p"
        res_map = {
            "4K": "2160",
            "2K": "1440",
            "1080p": "1080",
            "720p": "720",
            "480p": "480"
        }
        quality = res_map.get(q_setting, "720")

    cache_key = f"{item.subjectId}|{season}|{episode}|{quality}"
    from core.db import get_cached_vod, set_cached_vod
    
    cached_url = get_cached_vod(cache_key)
    if cached_url:
        print(f"[VOD Scraper] Using cached URL for '{item.title}' (S{season}E{episode} - {quality}P)")
        return {
            "url": cached_url,
            "resolution": quality,
            "format": "MP4"
        }

    resolver = FixedStreamFilesDetail(session=session, item=item)
    stream_info = await resolver.get_content_model(season=season, episode=episode)
    
    if stream_info.streams:
        matched = None
        for stream in stream_info.streams:
            if str(stream.resolutions) == str(quality):
                matched = stream
                break
                
        if not matched:
            try:
                streams_sorted = sorted(
                    stream_info.streams,
                    key=lambda s: int(s.resolutions) if str(s.resolutions).isdigit() else 0
                )
                req_val = int(quality) if quality.isdigit() else 720
                for s in reversed(streams_sorted):
                    val = int(s.resolutions) if str(s.resolutions).isdigit() else 0
                    if val <= req_val:
                        matched = s
                        break
                if not matched and streams_sorted:
                    matched = streams_sorted[-1]  # Pick highest available
            except Exception:
                matched = stream_info.best_stream_file
                
        if not matched:
            matched = stream_info.best_stream_file
            
        if matched:
            resolved_url = str(matched.url)
            set_cached_vod(cache_key, resolved_url)
            return {
                "url": resolved_url,
                "resolution": matched.resolutions,
                "format": matched.format
            }
            
    raise Exception("No active video streams found on servers.")


async def get_available_languages(session: Session, clean_title: str, is_series: bool = True, existing_items: list = None) -> list[dict]:
    """
    Search MovieBox in parallel for all available language releases (Hindi, Japanese, English, Korean, etc.).
    Returns deduplicated list of available language items with pre-fetched seasons and episode counts.
    Never misses Hindi because existing_items from initial search are inspected first.
    """
    import asyncio
    seen_subjects = set()
    lang_map = {}

    clean_words = set(clean_title.lower().split())

    # Pre-assign session cookies so concurrent requests don't hit race conditions
    try:
        await session.ensure_cookies_are_assigned()
    except Exception:
        pass

    all_candidate_items = list(existing_items or [])

    queries = [clean_title, f"{clean_title} Hindi", f"{clean_title} English"]
    stem = re.sub(r'\b(class|season|s\d+)\b', '', clean_title, flags=re.IGNORECASE).strip()
    if stem and stem.lower() != clean_title.lower():
        queries.append(f"{stem} Hindi")

    async def fetch_search_res(q_text: str):
        try:
            sc = Search(session=session, query=q_text)
            return await sc.get_content_model()
        except Exception as err:
            print(f"[VOD Scraper] Lang detection query '{q_text}' err: {err}")
            return None

    # Run all search queries concurrently for instant speed
    search_results = await asyncio.gather(*(fetch_search_res(q) for q in queries))

    for res in search_results:
        if res and res.items:
            all_candidate_items.extend(res.items)

    for it in all_candidate_items:
        if it.subjectId in seen_subjects:
            continue
        seen_subjects.add(it.subjectId)

        it_is_series = it.subjectType == SubjectType.TV_SERIES or int(getattr(it, "subjectType", 1)) == 2
        if is_series != it_is_series:
            continue

        it_clean = re.sub(r'\[.*?\]', '', it.title).strip()
        it_clean = re.sub(r'\s+S\d+(-S\d+)?', '', it_clean, flags=re.IGNORECASE).strip()

        it_words = set(it_clean.lower().split())
        overlap = clean_words.intersection(it_words)
        sim = difflib.SequenceMatcher(None, clean_title.lower(), it_clean.lower()).ratio()

        if not overlap and sim < 0.45 and clean_title.lower() not in it_clean.lower() and it_clean.lower() not in clean_title.lower():
            continue

        t_lower = it.title.lower()
        c_lower = getattr(it, "countryName", "").lower()

        if "hindi" in t_lower:
            code, name = "hi", "Hindi"
        elif "english" in t_lower:
            code, name = "en", "English"
        elif "japanese" in t_lower or ("japan" in c_lower and "hindi" not in t_lower):
            code, name = "ja", "Japanese"
        elif "korean" in t_lower or ("korea" in c_lower and "hindi" not in t_lower):
            code, name = "ko", "Korean"
        elif "spanish" in t_lower or ("spain" in c_lower and "hindi" not in t_lower):
            code, name = "es", "Spanish"
        elif "russian" in t_lower or ("russia" in c_lower):
            code, name = "ru", "Russian"
        elif "tamil" in t_lower:
            code, name = "ta", "Tamil"
        elif "telugu" in t_lower:
            code, name = "te", "Telugu"
        elif any(w in c_lower for w in ["united states", "united kingdom", "canada", "australia"]):
            code, name = "en", "English"
        else:
            code, name = "orig", "Original"

        if code not in lang_map:
            lang_map[code] = {
                "code": code,
                "name": name,
                "item": it,
                "title": it.title,
                "seasons": [],
                "ep_count": 0
            }

    order = ["hi", "en", "ja", "ko", "es", "ru", "ta", "te", "orig"]
    sorted_langs = [lang_map[o] for o in order if o in lang_map]
    for c, info in lang_map.items():
        if info not in sorted_langs:
            sorted_langs.append(info)

    # Concurrently pre-fetch TV series seasons and episode counts
    async def fetch_details_for_lang(lang_info: dict):
        try:
            it = lang_info.get("item")
            if not it:
                return
            it_is_series = it.subjectType == SubjectType.TV_SERIES or int(getattr(it, "subjectType", 1)) == 2
            if it_is_series:
                ep_session = Session()
                tv_client = TVSeriesDetails(session=ep_session)
                details = await tv_client.get_content_model(it)
                if details and details.resource and details.resource.seasons:
                    seasons = sorted(details.resource.seasons, key=lambda s: getattr(s, 'se', 0))
                    lang_info["seasons"] = seasons
                    lang_info["ep_count"] = sum(getattr(s, "maxEp", 0) for s in seasons)
            else:
                lang_info["ep_count"] = 0  # Movie
        except Exception as err:
            print(f"[VOD Scraper] details fetch error for {lang_info.get('name')}: {err}")

    if sorted_langs:
        await asyncio.gather(*(fetch_details_for_lang(l) for l in sorted_langs))

    return sorted_langs
