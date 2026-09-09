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

def patched_init_v1(self, *args, **kwargs):
    orig_init_v1(self, *args, **kwargs)
    from core.domain_manager import get_domain
    domain = get_domain()
    self._client.headers.update({
        "Origin": f"https://{domain}",
        "Referer": f"https://{domain}/"
    })

def patched_init_v2(self, *args, **kwargs):
    orig_init_v2(self, *args, **kwargs)
    from core.domain_manager import get_domain
    domain = get_domain()
    self._client.headers.update({
        "Origin": f"https://{domain}",
        "Referer": f"https://{domain}/"
    })

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


async def search_vod(query: str, language: str = "en"):
    """
    Search MovieBox for a query and return ranked list of SearchResultsItem objects.
    Uses fuzzy matching and score ranking so titles like 'The Witcher' or 'witcer'
    always resolve cleanly without false negatives.
    """
    session = Session()
    
    # Clean query for search endpoint (strip season/ep markers)
    clean_query = re.sub(r'\s+S\d+(-S\d+)?\b', '', query, flags=re.IGNORECASE)
    clean_query = re.sub(r'\s+Season\s+\d+\b', '', clean_query, flags=re.IGNORECASE)
    clean_query = re.sub(r'\s+Ep?\s*\d+\b', '', clean_query, flags=re.IGNORECASE)
    clean_query = clean_query.strip()

    is_hi = (language == "hi") or bool(re.search(r'\b(hindi|dubbed|dub)\b', query, re.IGNORECASE))
    base_title = re.sub(r'\b(hindi|dubbed|dub|eng|english)\b', '', clean_query, flags=re.IGNORECASE).strip()
    base_title = re.sub(r'\s+', ' ', base_title).strip()
    if not base_title:
        base_title = clean_query
    
    seen_ids = set()
    raw_items = []

    # 1. Search queries based on intent
    queries_to_try = []
    if is_hi:
        queries_to_try.append(f"{base_title} Hindi")
        queries_to_try.append(base_title)
        if clean_query != base_title:
            queries_to_try.append(clean_query)
    else:
        queries_to_try.append(clean_query)
        queries_to_try.append(f"{clean_query} Hindi")

    for q in queries_to_try:
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

    # 3. Fuzzy score ranking algorithm
    query_lower = base_title.lower()
    query_words = [w for w in query_lower.split() if len(w) > 1]

    def rank_score(item: SearchResultsItem) -> float:
        title_lower = item.title.lower()
        clean_title = re.sub(r'\[.*?\]', '', title_lower).replace("dubbed", "").strip()
        clean_title = re.sub(r'\s+s\d+(-s\d+)?', '', clean_title).strip()
        
        # Base ratio using difflib against base_title
        score = difflib.SequenceMatcher(None, query_lower, clean_title).ratio()
        
        # Exact match boost
        if query_lower == clean_title:
            score += 0.5
        elif query_lower in clean_title:
            score += 0.35

        # Word overlap boost
        matched_words = sum(1 for w in query_words if w in clean_title)
        if query_words:
            score += (matched_words / len(query_words)) * 0.3

        # Hindi preference boost if requested
        if is_hi and "hindi" in title_lower:
            score += 0.6
        elif not is_hi and "hindi" not in title_lower:
            score += 0.1

        return score

    raw_items.sort(key=rank_score, reverse=True)
    return raw_items


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
    """
    tv_details_client = TVSeriesDetails(session=session)
    details = await tv_details_client.get_content_model(item)
    return details


async def resolve_stream_link(session: Session, item: SearchResultsItem, season: int = 0, episode: int = 0, quality: str = None):
    """
    Resolve the direct streaming URL for a movie or specific TV episode based on admin quality preferences.
    """
    from core.db import get_setting
    if not quality:
        q_setting = get_setting("quality_pref") or "1080p"
        res_map = {
            "4K": "2160",
            "2K": "1440",
            "1080p": "1080",
            "720p": "720",
            "480p": "480"
        }
        quality = res_map.get(q_setting, "1080")

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
                req_val = int(quality) if quality.isdigit() else 1080
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


async def get_available_languages(session: Session, clean_title: str, is_series: bool = True) -> list[dict]:
    """
    Search MovieBox for all available language dubs/releases of a title (Hindi, Japanese, English, Russian, etc.).
    Returns deduplicated list of available language items.
    """
    seen_subjects = set()
    lang_map = {}

    queries = [clean_title, f"{clean_title} Hindi", f"{clean_title} English"]
    for q in queries:
        try:
            search_client = Search(session=session, query=q)
            res = await search_client.get_content_model()
            if not res or not res.items:
                continue
            for it in res.items:
                if it.subjectId in seen_subjects:
                    continue
                seen_subjects.add(it.subjectId)

                it_is_series = it.subjectType == SubjectType.TV_SERIES or int(getattr(it, "subjectType", 1)) == 2
                if is_series != it_is_series:
                    continue

                it_clean = re.sub(r'\[.*?\]', '', it.title).strip()
                it_clean = re.sub(r'\s+S\d+(-S\d+)?', '', it_clean, flags=re.IGNORECASE).strip()
                sim = difflib.SequenceMatcher(None, clean_title.lower(), it_clean.lower()).ratio()
                if sim < 0.70 and clean_title.lower() not in it_clean.lower() and it_clean.lower() not in clean_title.lower():
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
                        "title": it.title
                    }
        except Exception as e:
            print(f"[VOD Scraper] Lang detection error for query '{q}': {e}")

    order = ["hi", "en", "ja", "ko", "es", "ru", "ta", "te", "orig"]
    sorted_langs = [lang_map[o] for o in order if o in lang_map]
    for c, info in lang_map.items():
        if info not in sorted_langs:
            sorted_langs.append(info)

    return sorted_langs
