"""
Trending & Latest Movies Manager
Fetches trending content from the MovieBox homepage, checks for Hindi versions,
and caches results to SQLite to ensure zero-latency replies.
"""

import asyncio
import time
from moviebox_api.v2 import Session, Homepage
from core.domain_manager import detect_working_domain
from core.db import save_cached_trending_items, get_cached_trending_items, get_setting, set_setting
from core.vod_scraper import search_hindi_version

# Background lock to prevent concurrent fetches
_update_lock = asyncio.Lock()

async def update_trending_cache():
    """Fetch popular items from Homepage API, detect Hindi availability in parallel, and cache them."""
    async with _update_lock:
        print("[TrendingManager] Fetching latest trending content from MovieBox...")
        try:
            # 1. Ensure working mirror is initialized
            await detect_working_domain()
            
            # 2. Get Homepage model
            session = Session()
            homepage = Homepage(session=session)
            content = await homepage.get_content_model()
            if not content or not content.operatingList:
                print("[TrendingManager] Homepage list empty or unreachable.")
                return False

            # Collect items from all movie & series categories on Homepage
            movie_keywords = ["movie", "cinema", "hollywood", "bollywood", "south indian", "top20", "trending now", "popular movie"]
            series_keywords = ["series", "tv", "drama", "anime", "k-drama", "c-drama", "top series", "popular series", "western tv", "indian drama"]

            seen_movie_ids = set()
            seen_series_ids = set()
            movies = []
            series = []

            for op in content.operatingList:
                if not op.subjects:
                    continue
                op_title = str(op.title or "").lower()

                is_movie_cat = any(kw in op_title for kw in movie_keywords)
                is_series_cat = any(kw in op_title for kw in series_keywords)

                for itm in op.subjects:
                    sub_id = int(getattr(itm, "subjectId", 0) or 0)
                    if not sub_id:
                        continue
                    sub_type = int(getattr(itm, "subjectType", 0) or 0)
                    if sub_type == 1 or (is_movie_cat and not is_series_cat):
                        if sub_id not in seen_movie_ids:
                            seen_movie_ids.add(sub_id)
                            movies.append(itm)
                    elif sub_type == 2 or is_series_cat:
                        if sub_id not in seen_series_ids:
                            seen_series_ids.add(sub_id)
                            series.append(itm)
                    else:
                        if sub_id not in seen_movie_ids:
                            seen_movie_ids.add(sub_id)
                            movies.append(itm)

            # Keep top 40 unique items each for rich variety
            movies = movies[:40]
            series = series[:40]

            # 3. Process items and verify Hindi availability in parallel
            async def process_item(item):
                title = str(item.title)
                clean_title = title.replace("[Hindi]", "").replace("[English]", "").strip()
                has_hindi = "hindi" in title.lower()
                
                # Parse release date to year
                year = ""
                if getattr(item, "releaseDate", None):
                    date_str = str(item.releaseDate)
                    if "-" in date_str:
                        year = date_str.split("-")[0]
                    else:
                        year = date_str[:4]
                        
                # Extract rating
                rating = 0.0
                if getattr(item, "imdbRatingValue", None):
                    try:
                        rating = float(item.imdbRatingValue)
                    except ValueError:
                        pass

                return {
                    "subject_id": int(item.subjectId),
                    "title": clean_title,
                    "release_date": year,
                    "rating": rating,
                    "has_hindi": has_hindi
                }

            # Run verification tasks in parallel
            movie_tasks = [process_item(m) for m in movies]
            series_tasks = [process_item(s) for s in series]

            verified_movies = await asyncio.gather(*movie_tasks) if movie_tasks else []
            verified_series = await asyncio.gather(*series_tasks) if series_tasks else []

            # 4. Save to SQLite database cache
            save_cached_trending_items("trending_movies", verified_movies)
            save_cached_trending_items("trending_series", verified_series)
            
            # Update cache timestamp
            set_setting("trending_cache_time", str(time.time()))
            print(f"[TrendingManager] Caching successful! Saved {len(verified_movies)} movies & {len(verified_series)} series.")
            return True
            
        except Exception as e:
            print(f"[TrendingManager] Error updating cache: {e}")
            return False

async def get_trending_list(category: str, limit: int = 10, shuffle: bool = True) -> list:
    """
    Get cached trending items.
    Returns a shuffled selection so that every call returns a different set of blockbusters!
    """
    import random
    cache_time_str = get_setting("trending_cache_time")
    cache_age = 9999999.0
    if cache_time_str:
        try:
            cache_age = time.time() - float(cache_time_str)
        except ValueError:
            pass

    items = get_cached_trending_items(category)
    
    # Trigger refresh if empty or expired (> 6 hours / 21600 seconds)
    if not items or cache_age > 21600:
        if not _update_lock.locked():
            if not items:
                print("[TrendingManager] Cache empty! Fetching trending content synchronously...")
                await update_trending_cache()
                items = get_cached_trending_items(category)
            else:
                print("[TrendingManager] Cache expired. Triggering background refresh...")
                asyncio.create_task(update_trending_cache())
                
    if not items:
        return []

    items_list = list(items)
    if shuffle and len(items_list) > limit:
        random.shuffle(items_list)

    return items_list[:limit]
