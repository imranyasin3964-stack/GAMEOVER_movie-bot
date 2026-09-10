"""
🎮 GameOver Cloud Cinema & Anime API
High-performance REST API wrapper for movies, TV series, and anime.
Zero local storage required, on-the-fly streaming resolution, and Cloudflare reverse proxy ready.
"""

import os
import sys
import asyncio
import re
from typing import Optional, Dict, Any, List

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import uvicorn

from moviebox_api.v2 import Session
from moviebox_api.v2.models import SearchResultsItem
from moviebox_api.v2.constants import SubjectType
from core.vod_scraper import (
    search_vod,
    fetch_tv_details,
    resolve_stream_link,
    get_available_languages,
    normalize_search_query
)
from core.db import init_db, save_api_item, get_api_item

# Initialize local SQLite tables
init_db()

# Global shared session and in-memory cache for ultra-fast response
shared_session = Session()
items_cache: Dict[str, SearchResultsItem] = {}

app = FastAPI(
    title="GameOver Cloud Cinema & Anime API",
    description="Public High-Performance VOD & Streaming REST API. Provides clean JSON search, details with full episode lists, and dynamic direct stream links.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Enable CORS for all frontends/apps
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Enable GZip compression for large responses (e.g. anime with 300+ episodes)
app.add_middleware(GZipMiddleware, minimum_size=1000)


def extract_poster_url(item: Any) -> str:
    """Safely extracts image poster URL from item model."""
    cov = getattr(item, "cover", None)
    if not cov:
        return ""
    if hasattr(cov, "url") and cov.url:
        return str(cov.url)
    if isinstance(cov, dict):
        return str(cov.get("url", ""))
    if isinstance(cov, str):
        return cov
    return ""


@app.get("/", response_class=HTMLResponse)
async def root_index():
    """Clean API landing page with Swagger docs link."""
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>GameOver Cinema & Anime API</title>
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body {
                font-family: 'Outfit', sans-serif;
                background: linear-gradient(135deg, #0d1117 0%, #161b22 100%);
                color: #e6edf3;
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }
            .card {
                background: rgba(22, 27, 34, 0.85);
                backdrop-filter: blur(12px);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 16px;
                padding: 40px;
                max-width: 650px;
                width: 100%;
                box-shadow: 0 20px 40px rgba(0,0,0,0.5);
                text-align: center;
            }
            .badge {
                display: inline-block;
                background: #238636;
                color: #ffffff;
                font-size: 12px;
                font-weight: 600;
                padding: 4px 12px;
                border-radius: 20px;
                margin-bottom: 20px;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            h1 { font-size: 32px; font-weight: 700; margin-bottom: 12px; color: #58a6ff; }
            p { color: #8b949e; font-size: 16px; line-height: 1.6; margin-bottom: 25px; }
            .endpoints {
                text-align: left;
                background: rgba(13, 17, 23, 0.6);
                border-radius: 10px;
                padding: 16px 20px;
                margin-bottom: 30px;
                font-family: monospace;
                font-size: 14px;
            }
            .endpoint-row { padding: 6px 0; color: #79c0ff; border-bottom: 1px solid rgba(255,255,255,0.05); }
            .endpoint-row:last-child { border-bottom: none; }
            .method { color: #7ee787; font-weight: bold; margin-right: 8px; }
            .btn {
                display: inline-block;
                background: #1f6feb;
                color: #ffffff;
                text-decoration: none;
                padding: 12px 28px;
                border-radius: 8px;
                font-weight: 600;
                font-size: 15px;
                transition: background 0.2s ease, transform 0.1s ease;
            }
            .btn:hover { background: #388bfd; transform: translateY(-2px); }
        </style>
    </head>
    <body>
        <div class="card">
            <span class="badge">Online & Ready</span>
            <h1>GameOver Cinema API</h1>
            <p>High-speed reverse VOD API for movies, multi-season TV shows, and anime. Delivers clean JSON metadata and on-demand direct streaming links with zero storage load.</p>
            
            <div class="endpoints">
                <div class="endpoint-row"><span class="method">GET</span> /api/v1/search?query=spiderman</div>
                <div class="endpoint-row"><span class="method">GET</span> /api/v1/details?id={movie_id}</div>
                <div class="endpoint-row"><span class="method">GET</span> /api/v1/stream?id={movie_id}&quality=720</div>
                <div class="endpoint-row"><span class="method">GET</span> /api/v1/languages?title={movie_title}</div>
            </div>

            <a href="/docs" class="btn">Explore Interactive Swagger Docs</a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.get("/api/v1/search")
async def api_search(
    query: str = Query(..., description="Movie, Series or Anime name to search (e.g. 'spiderman', 'bleach', 'sweet home')"),
    lang: str = Query("hi", description="Preferred audio language (defaults to 'hi' for Hindi preference, 'en' for English)"),
    limit: int = Query(20, ge=1, le=50, description="Max results to return")
):
    """
    Search MovieBox database and return ranked results.
    Automatically handles alias normalization and defaults to Hindi dub preference.
    """
    if not query.strip():
        raise HTTPException(status_code=400, detail="Query parameter cannot be empty.")

    try:
        results = await search_vod(query.strip(), language=lang)
        if not results:
            return {
                "success": True,
                "query": query,
                "total": 0,
                "results": []
            }

        out_list = []
        for itm in results[:limit]:
            sub_id = str(itm.subjectId)
            items_cache[sub_id] = itm  # Cache item in memory
            save_api_item(itm)          # Persist in SQLite for long-term direct lookup

            is_ser = itm.subjectType == SubjectType.TV_SERIES or int(getattr(itm, "subjectType", 1)) == 2
            t_lower = itm.title.lower()
            
            if "hindi" in t_lower:
                lang_detected = "Hindi"
            elif "english" in t_lower:
                lang_detected = "English"
            elif "japanese" in t_lower:
                lang_detected = "Japanese"
            elif "korean" in t_lower:
                lang_detected = "Korean"
            else:
                lang_detected = "Original"

            clean_name = re.sub(r'\[.*?\]', '', itm.title).strip()
            clean_name = re.sub(r'\s+S\d+(-S\d+)?', '', clean_name, flags=re.IGNORECASE).strip()

            rel_year = ""
            rel_date = str(getattr(itm, "releaseDate", "") or "")
            if len(rel_date) >= 4 and rel_date[:4].isdigit():
                rel_year = rel_date[:4]

            rating_val = str(getattr(itm, "imdbRatingValue", "") or "").strip()
            duration_val = str(getattr(itm, "duration", "") or "").strip()
            poster_url = extract_poster_url(itm)

            item_dict = {
                "id": sub_id,
                "title": clean_name.title(),
                "original_title": itm.title,
                "type": "series" if is_ser else "movie",
                "language": lang_detected,
                "year": rel_year,
                "rating": rating_val,
                "duration": duration_val,
                "poster": poster_url,
                "details_url": f"/api/v1/details?id={sub_id}",
                "stream_url": f"/api/v1/stream?id={sub_id}&quality=720" if not is_ser else None
            }
            out_list.append(item_dict)

        return {
            "success": True,
            "query": query,
            "total": len(out_list),
            "results": out_list
        }

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Search execution failed: {str(e)}"}
        )


@app.get("/api/v1/details")
async def api_details(
    id: str = Query(..., description="Subject ID of the movie or series (e.g. from /search endpoint)")
):
    """
    Fetch comprehensive metadata for a specific title.
    For TV Series and Anime (e.g. Bleach, Sweet Home), returns all seasons and complete episode lists.
    """
    sub_id = id.strip()
    item = items_cache.get(sub_id)

    # If item not in memory cache, check persistent SQLite DB
    if not item:
        item = get_api_item(sub_id)
        if item:
            items_cache[sub_id] = item

    # If still not found, search MovieBox upstream by ID
    if not item:
        try:
            from moviebox_api.v2 import Search
            search_client = Search(session=shared_session, query=sub_id)
            res = await search_client.get_content_model()
            if res and res.items:
                item = next((it for it in res.items if str(it.subjectId) == sub_id), res.items[0])
                items_cache[sub_id] = item
                save_api_item(item)
        except Exception:
            pass

    if not item:
        raise HTTPException(status_code=404, detail=f"Item with ID '{sub_id}' not found. Please search first.")

    is_ser = item.subjectType == SubjectType.TV_SERIES or int(getattr(item, "subjectType", 1)) == 2
    clean_name = re.sub(r'\[.*?\]', '', item.title).strip()
    clean_name = re.sub(r'\s+S\d+(-S\d+)?', '', clean_name, flags=re.IGNORECASE).strip().title()

    response_data = {
        "success": True,
        "id": sub_id,
        "title": clean_name,
        "original_title": item.title,
        "type": "series" if is_ser else "movie",
        "description": getattr(item, "description", "") or "",
        "poster": extract_poster_url(item),
        "rating": str(getattr(item, "imdbRatingValue", "") or "").strip(),
        "year": str(getattr(item, "releaseDate", "") or "")[:4],
        "genres": [g.name for g in getattr(item, "genre", []) if hasattr(g, "name")] if hasattr(item, "genre") else [],
        "seasons": [],
        "stream_url": None
    }

    if not is_ser:
        response_data["stream_url"] = f"/api/v1/stream?id={sub_id}&season=0&episode=0&quality=720"
        return response_data

    # Series/Anime handling: fetch all seasons and build episode models
    try:
        details = await fetch_tv_details(shared_session, item)
        if details and details.resource and details.resource.seasons:
            sorted_seasons = sorted(details.resource.seasons, key=lambda s: getattr(s, 'se', 0))
            seasons_list = []
            for s in sorted_seasons:
                episodes = []
                max_ep = int(getattr(s, "maxEp", 1) or 1)
                for ep in range(1, max_ep + 1):
                    episodes.append({
                        "episode_number": ep,
                        "stream_url": f"/api/v1/stream?id={sub_id}&season={s.se}&episode={ep}&quality=720"
                    })
                seasons_list.append({
                    "season_number": s.se,
                    "total_episodes": max_ep,
                    "episodes": episodes
                })
            response_data["seasons"] = seasons_list
            response_data["total_seasons"] = len(seasons_list)
        else:
            # Fallback if no seasons object
            response_data["stream_url"] = f"/api/v1/stream?id={sub_id}&season=1&episode=1&quality=720"

        return response_data

    except Exception as e:
        # Graceful fallback instead of unhandled 500
        print(f"[API] Warning: fetch_tv_details failed for {sub_id}: {e}")
        response_data["stream_url"] = f"/api/v1/stream?id={sub_id}&season=1&episode=1&quality=720"
        return response_data


@app.get("/api/v1/stream")
async def api_stream(
    id: str = Query(..., description="Subject ID of the movie or series"),
    season: int = Query(0, ge=0, description="Season number (0 for movies)"),
    episode: int = Query(0, ge=0, description="Episode number (0 for movies)"),
    quality: str = Query("720", description="Desired quality: 1080, 720, 480, 360"),
    redirect: bool = Query(True, description="If true, returns HTTP 302 redirect for direct playback in video players. If false, returns JSON with stream metadata.")
):
    """
    Resolves the direct video streaming URL on the fly.
    Uses zero disk space on the server.
    """
    sub_id = id.strip()
    item = items_cache.get(sub_id)

    # If item not in memory cache, check SQLite DB
    if not item:
        item = get_api_item(sub_id)
        if item:
            items_cache[sub_id] = item

    # If still not found, search MovieBox upstream by ID
    if not item:
        try:
            from moviebox_api.v2 import Search
            search_client = Search(session=shared_session, query=sub_id)
            res = await search_client.get_content_model()
            if res and res.items:
                item = next((it for it in res.items if str(it.subjectId) == sub_id), res.items[0])
                items_cache[sub_id] = item
                save_api_item(item)
        except Exception:
            pass

    if not item:
        raise HTTPException(status_code=404, detail=f"Subject ID '{sub_id}' not found in active session or database. Please search first.")

    try:
        stream_res = await resolve_stream_link(
            shared_session,
            item,
            season=season,
            episode=episode,
            quality=quality
        )

        stream_url = stream_res.get("url")
        if not stream_url:
            raise HTTPException(status_code=404, detail="No active streamable source found for this title/episode.")

        if redirect:
            # 302 Temporary Redirect lets VLC / HTML5 / MX Player play the stream directly
            return RedirectResponse(url=stream_url, status_code=302)

        return {
            "success": True,
            "id": sub_id,
            "title": item.title,
            "season": season,
            "episode": episode,
            "resolution": stream_res.get("resolution"),
            "format": stream_res.get("format", "MP4"),
            "stream_url": stream_url
        }

    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Failed to resolve stream: {str(e)}"}
        )


@app.get("/api/v1/languages")
async def api_languages(
    title: str = Query(..., description="Clean movie or series title (e.g. 'Spider-Man 2', 'Sweet Home')"),
    type: str = Query("movie", description="'movie' or 'series'")
):
    """
    Finds all available language dubs/variants (Hindi, English, Japanese, etc.) for a title.
    """
    is_series = (type.lower() == "series")
    try:
        langs = await get_available_languages(shared_session, title.strip(), is_series=is_series)
        out = []
        for l in langs:
            itm = l.get("item")
            sub_id = str(itm.subjectId) if itm else ""
            if itm:
                items_cache[sub_id] = itm
                save_api_item(itm)
            out.append({
                "code": l["code"],
                "name": l["name"],
                "id": sub_id,
                "title": l["title"],
                "details_url": f"/api/v1/details?id={sub_id}" if sub_id else None,
                "stream_url": f"/api/v1/stream?id={sub_id}&quality=720" if (sub_id and not is_series) else None
            })

        return {
            "success": True,
            "title": title,
            "type": "series" if is_series else "movie",
            "available_languages": out
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Failed to fetch languages: {str(e)}"}
        )


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    print(f"\n[+] Starting GameOver Cinema API on port {port}...")
    print(f"[+] Interactive Docs: http://localhost:{port}/docs\n")
    uvicorn.run("api:app", host="0.0.0.0", port=port, reload=False, workers=1)
