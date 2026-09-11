"""
GameOver Movie Hub — Local SQLite Database Helper
Handles persistent storage for Sudo Admins, Auth Groups, Allowed Groups, and User Playlists.
"""

import sqlite3
import json
import time
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(BASE_DIR, "gameover_db.sqlite3")

def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Table for Sudo users
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sudo_users (
            user_id INTEGER PRIMARY KEY
        )
    """)
    
    # Table for Authorized users in groups
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS auth_users (
            chat_id INTEGER,
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            added_by INTEGER,
            timestamp REAL,
            PRIMARY KEY (chat_id, user_id)
        )
    """)

    # Table for Chat Settings (play_mode: user, admin, auth)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_settings (
            chat_id INTEGER PRIMARY KEY,
            play_mode TEXT DEFAULT 'user'
        )
    """)
    
    # Table for User Playlists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS playlists (
            user_id INTEGER,
            playlist_name TEXT,
            songs TEXT,  -- JSON string of songs
            PRIMARY KEY (user_id, playlist_name)
        )
    """)
    
    # Table for Allowed Groups (groups where bot is allowed to run/stream)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS allowed_groups (
            chat_id INTEGER PRIMARY KEY
        )
    """)
    
    # Table for bot settings / file ID cache
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Table for VOD link cache
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vod_cache (
            key TEXT PRIMARY KEY,
            url TEXT,
            timestamp REAL
        )
    """)
    
    # Table for broadcast groups
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS broadcast_groups (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            enabled INTEGER DEFAULT 1,
            welcome_enabled INTEGER DEFAULT 1,
            bot_active INTEGER DEFAULT 1
        )
    """)
    
    # Table for users who started the bot
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS started_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            timestamp REAL
        )
    """)

    # Table for VOD playback resume history
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vod_history (
            chat_id INTEGER,
            subject_id INTEGER,
            title TEXT,
            season INTEGER,
            episode INTEGER,
            progress_seconds INTEGER,
            last_played REAL,
            PRIMARY KEY (chat_id, subject_id, season, episode)
        )
    """)

    # Table for API users authorization
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS api_users (
            api_key TEXT PRIMARY KEY,
            owner_name TEXT,
            is_active INTEGER DEFAULT 1,
            rate_limit INTEGER DEFAULT 30,
            total_hits INTEGER DEFAULT 0,
            expires_at INTEGER DEFAULT 0
        )
    """)

    # Check if columns exist in api_users (migration for existing database)
    cursor.execute("PRAGMA table_info(api_users)")
    columns = [col[1] for col in cursor.fetchall()]
    if columns and "rate_limit" not in columns:
        cursor.execute("ALTER TABLE api_users ADD COLUMN rate_limit INTEGER DEFAULT 30")
    if columns and "total_hits" not in columns:
        cursor.execute("ALTER TABLE api_users ADD COLUMN total_hits INTEGER DEFAULT 0")
    if columns and "expires_at" not in columns:
        cursor.execute("ALTER TABLE api_users ADD COLUMN expires_at INTEGER DEFAULT 0")

    # Table for global stats
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS global_stats (
            stat_key TEXT PRIMARY KEY,
            stat_value INTEGER DEFAULT 0
        )
    """)

    # Table for user movie requests
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movie_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            chat_id INTEGER,
            chat_title TEXT,
            movie_name TEXT,
            status TEXT DEFAULT 'Pending',
            timestamp REAL
        )
    """)
    
    # Check if columns exist in broadcast_groups (migration for existing database)
    cursor.execute("PRAGMA table_info(broadcast_groups)")
    bg_columns = [col[1] for col in cursor.fetchall()]
    if bg_columns and "welcome_enabled" not in bg_columns:
        cursor.execute("ALTER TABLE broadcast_groups ADD COLUMN welcome_enabled INTEGER DEFAULT 1")
    if bg_columns and "bot_active" not in bg_columns:
        cursor.execute("ALTER TABLE broadcast_groups ADD COLUMN bot_active INTEGER DEFAULT 1")
    
    # Insert total_hits default if not exists
    cursor.execute("INSERT OR IGNORE INTO global_stats (stat_key, stat_value) VALUES ('total_hits', 0)")
    
    # Table for trending cache
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trending_cache (
            category TEXT,
            subject_id INTEGER,
            title TEXT,
            release_date TEXT,
            rating REAL,
            has_hindi INTEGER DEFAULT 0,
            PRIMARY KEY (category, subject_id)
        )
    """)
    
    # Table for cloned bots
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cloned_bots (
            bot_id INTEGER PRIMARY KEY,
            bot_token TEXT NOT NULL,
            bot_username TEXT,
            bot_name TEXT,
            owner_id INTEGER NOT NULL,
            owner_name TEXT,
            created_at REAL,
            status TEXT DEFAULT 'active'
        )
    """)

    # Table for globally authorized users
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS global_auth_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            added_by INTEGER,
            timestamp REAL
        )
    """)

    # Table for API Search Items cache
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS api_items (
            subject_id TEXT PRIMARY KEY,
            title TEXT,
            data_json TEXT,
            timestamp REAL
        )
    """)

    # Check if columns exist in auth_users (migration for existing database)
    cursor.execute("PRAGMA table_info(auth_users)")
    auth_cols = [col[1] for col in cursor.fetchall()]
    if auth_cols and "username" not in auth_cols:
        cursor.execute("ALTER TABLE auth_users ADD COLUMN username TEXT")
    if auth_cols and "first_name" not in auth_cols:
        cursor.execute("ALTER TABLE auth_users ADD COLUMN first_name TEXT")
    if auth_cols and "added_by" not in auth_cols:
        cursor.execute("ALTER TABLE auth_users ADD COLUMN added_by INTEGER")
    if auth_cols and "timestamp" not in auth_cols:
        cursor.execute("ALTER TABLE auth_users ADD COLUMN timestamp REAL")

    conn.commit()
    conn.close()

# Initialize database tables
init_db()


# ─── API Items Helpers ──────────────────────────────────
def save_api_item(item):
    """Save a SearchResultsItem to SQLite for instant lookup by subjectId."""
    if not item:
        return
    sub_id = str(getattr(item, "subjectId", "") or "")
    if not sub_id and isinstance(item, dict):
        sub_id = str(item.get("subjectId") or item.get("id") or "")
    if not sub_id:
        return
    title = str(getattr(item, "title", "") or "")
    if not title and isinstance(item, dict):
        title = str(item.get("title") or "")

    try:
        if hasattr(item, "model_dump_json"):
            item_json = item.model_dump_json()
        elif hasattr(item, "json"):
            item_json = item.json()
        elif isinstance(item, dict):
            item_json = json.dumps(item)
        else:
            item_json = json.dumps(getattr(item, "__dict__", {}))
    except Exception:
        item_json = ""

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO api_items (subject_id, title, data_json, timestamp)
            VALUES (?, ?, ?, ?)
        """, (sub_id, title, item_json, time.time()))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error saving api_item {sub_id}: {e}")
    finally:
        conn.close()


def get_api_item(subject_id: str):
    """Retrieve a SearchResultsItem from SQLite by subjectId."""
    if not subject_id:
        return None
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT data_json FROM api_items WHERE subject_id = ?", (str(subject_id).strip(),))
        row = cursor.fetchone()
        if row and row["data_json"]:
            from moviebox_api.v2.models import SearchResultsItem
            try:
                return SearchResultsItem.model_validate_json(row["data_json"])
            except Exception:
                return SearchResultsItem.parse_raw(row["data_json"])
        return None
    except Exception as e:
        print(f"[DB] Error loading api_item {subject_id}: {e}")
        return None
    finally:
        conn.close()


# ─── Settings Helpers ───────────────────────────────────
def get_setting(key: str) -> str:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row["value"] if row else None
    finally:
        conn.close()

def set_setting(key: str, value: str):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
    finally:
        conn.close()

# ─── Auth Users Helpers ─────────────────────────────────
def add_auth_user(chat_id: int, user_id: int, username: str = "", first_name: str = "", added_by: int = 0):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO auth_users (chat_id, user_id, username, first_name, added_by, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                added_by = excluded.added_by,
                timestamp = excluded.timestamp
        """, (chat_id, user_id, username, first_name, added_by, time.time()))
        conn.commit()
    finally:
        conn.close()

def remove_auth_user(chat_id: int, user_id: int):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM auth_users WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        conn.commit()
    finally:
        conn.close()

def get_auth_users(chat_id: int) -> list:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT user_id, username, first_name, added_by, timestamp FROM auth_users WHERE chat_id = ?", (chat_id,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

def is_auth_user(chat_id: int, user_id: int) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM auth_users WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        return cursor.fetchone() is not None
    finally:
        conn.close()

# ─── Chat Settings & Play Mode Helpers ──────────────────
def get_play_mode(chat_id: int) -> str:
    """Returns 'user', 'admin', or 'auth' (default 'user')."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT play_mode FROM chat_settings WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        return str(row["play_mode"]).lower() if row and row["play_mode"] else "user"
    finally:
        conn.close()

def set_play_mode(chat_id: int, mode: str):
    """Sets play_mode to 'user', 'admin', or 'auth'."""
    mode = str(mode).lower().strip()
    if mode not in ("user", "admin", "auth"):
        mode = "user"
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO chat_settings (chat_id, play_mode) VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET play_mode = excluded.play_mode
        """, (chat_id, mode))
        conn.commit()
    finally:
        conn.close()

async def is_group_admin(client, chat_id: int, user_id: int) -> bool:
    if not user_id:
        return False
    from config import Config
    if user_id in (Config.OWNER_ID, 6805412676):
        return True
    if is_sudo_user(user_id):
        return True
    try:
        from pyrogram import enums
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER)
    except Exception:
        return False

async def check_user_play_permission(client, chat_id: int, user) -> tuple[bool, str]:
    """
    Checks if a user is allowed to play or control media according to the group's play_mode:
    - 'user' (Everyone): allowed
    - 'admin': only group admins / owner / sudo allowed
    - 'auth': only auth users + group admins / owner / sudo allowed
    Returns (is_allowed, reason_msg)
    """
    from config import Config
    user_id = user.id if user else 0
    if not user_id:
        return False, "User not found."

    # Bot Owner and Sudo Users always have full permission
    if user_id in (Config.OWNER_ID, 6805412676) or is_sudo_user(user_id):
        return True, ""

    mode = get_play_mode(chat_id)
    if mode == "user":
        return True, ""

    # Check if user is a group admin
    admin_ok = await is_group_admin(client, chat_id, user_id)
    if admin_ok:
        return True, ""

    if mode == "admin":
        return False, "<b>Aᴅᴍɪɴ Mᴏᴅᴇ Active Hai!</b>\n\nIs group mein sirf <b>Group Admins</b> movie search ya controls use kar sakte hain."

    if mode == "auth":
        if is_auth_user(chat_id, user_id) or is_global_auth_user(user_id):
            return True, ""
        return False, "<b>Aᴜᴛʜ Mᴏᴅᴇ Active Hai!</b>\n\nAap is group mein authorized nahi hain. Movie play karne ke liye group admin se <code>/auth</code> lene ko kahein."

    return True, ""

# ─── Allowed Groups Helpers ─────────────────────────────
def add_allowed_group(chat_id: int):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR IGNORE INTO allowed_groups (chat_id) VALUES (?)", (chat_id,))
        conn.commit()
    finally:
        conn.close()

def remove_allowed_group(chat_id: int):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM allowed_groups WHERE chat_id = ?", (chat_id,))
        conn.commit()
    finally:
        conn.close()

def is_group_allowed(chat_id: int) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM allowed_groups WHERE chat_id = ?", (chat_id,))
        return cursor.fetchone() is not None
    finally:
        conn.close()

# ─── Sudo Users Helpers ─────────────────────────────────
def add_sudo_user(user_id: int):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR IGNORE INTO sudo_users (user_id) VALUES (?)", (user_id,))
        conn.commit()
    finally:
        conn.close()

def remove_sudo_user(user_id: int):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM sudo_users WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()

def is_sudo_user(user_id: int) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM sudo_users WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None
    finally:
        conn.close()

# ─── Playlists Helpers ──────────────────────────────────
def get_playlist(user_id: int, playlist_name: str) -> list:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT songs FROM playlists WHERE user_id = ? AND playlist_name = ?", (user_id, playlist_name))
        row = cursor.fetchone()
        if row:
            return json.loads(row["songs"])
        return []
    finally:
        conn.close()

def save_playlist(user_id: int, playlist_name: str, songs: list):
    conn = get_db()
    cursor = conn.cursor()
    songs_json = json.dumps(songs)
    try:
        cursor.execute(
            "INSERT OR REPLACE INTO playlists (user_id, playlist_name, songs) VALUES (?, ?, ?)",
            (user_id, playlist_name, songs_json)
        )
        conn.commit()
    finally:
        conn.close()

def delete_playlist(user_id: int, playlist_name: str):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM playlists WHERE user_id = ? AND playlist_name = ?", (user_id, playlist_name))
        conn.commit()
    finally:
        conn.close()

# ─── VOD Cache Helpers ──────────────────────────────────
def get_cached_vod(key: str) -> str:
    """Return cached stream URL if it exists and is less than 3 hours old."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT url, timestamp FROM vod_cache WHERE key = ?", (key,))
        row = cursor.fetchone()
        if row:
            # 3 hours = 10800 seconds
            if time.time() - row["timestamp"] < 10800:
                print(f"[VOD Cache] Hit for key: {key}")
                return row["url"]
            else:
                # Delete expired
                print(f"[VOD Cache] Expired key: {key}")
                cursor.execute("DELETE FROM vod_cache WHERE key = ?", (key,))
                conn.commit()
        return None
    finally:
        conn.close()

def set_cached_vod(key: str, url: str):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR REPLACE INTO vod_cache (key, url, timestamp) VALUES (?, ?, ?)", (key, url, time.time()))
        conn.commit()
        print(f"[VOD Cache] Saved key: {key}")
    finally:
        conn.close()

# ─── Broadcast Groups Helpers ───────────────────────────
def update_group_info(chat_id: int, title: str):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR IGNORE INTO broadcast_groups (chat_id, title, enabled) VALUES (?, ?, 1)", (chat_id, title))
        cursor.execute("UPDATE broadcast_groups SET title = ? WHERE chat_id = ?", (title, chat_id))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error update_group_info: {e}")
    finally:
        conn.close()

def remove_group_info(chat_id: int):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM broadcast_groups WHERE chat_id = ?", (chat_id,))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error remove_group_info: {e}")
    finally:
        conn.close()

def get_broadcast_groups() -> list:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT chat_id, title, enabled, welcome_enabled, bot_active FROM broadcast_groups")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"[DB] Error get_broadcast_groups: {e}")
        return []
    finally:
        conn.close()

def set_group_broadcast_enabled(chat_id: int, enabled: bool):
    conn = get_db()
    cursor = conn.cursor()
    val = 1 if enabled else 0
    try:
        cursor.execute("UPDATE broadcast_groups SET enabled = ? WHERE chat_id = ?", (val, chat_id))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error set_group_broadcast_enabled: {e}")
    finally:
        conn.close()

def set_group_welcome_enabled(chat_id: int, enabled: bool):
    conn = get_db()
    cursor = conn.cursor()
    val = 1 if enabled else 0
    try:
        cursor.execute("UPDATE broadcast_groups SET welcome_enabled = ? WHERE chat_id = ?", (val, chat_id))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error set_group_welcome_enabled: {e}")
    finally:
        conn.close()

def is_group_welcome_enabled(chat_id: int) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT welcome_enabled FROM broadcast_groups WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        if row and row["welcome_enabled"] is not None:
            return bool(row["welcome_enabled"])
        return True
    except Exception:
        return True
    finally:
        conn.close()

def set_group_bot_active(chat_id: int, active: bool):
    conn = get_db()
    cursor = conn.cursor()
    val = 1 if active else 0
    try:
        cursor.execute("UPDATE broadcast_groups SET bot_active = ? WHERE chat_id = ?", (val, chat_id))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error set_group_bot_active: {e}")
    finally:
        conn.close()

def is_group_bot_active(chat_id: int) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT bot_active FROM broadcast_groups WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        if row and row["bot_active"] is not None:
            return bool(row["bot_active"])
        return True
    except Exception:
        return True
    finally:
        conn.close()

# ─── Started Users Helpers ──────────────────────────────
def add_started_user(user_id: int, username: str, first_name: str) -> bool:
    """
    Insert a user into started_users table if not already present.
    Returns True if it was a new user, False otherwise.
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM started_users WHERE user_id = ?", (user_id,))
        if cursor.fetchone():
            return False
        cursor.execute(
            "INSERT OR IGNORE INTO started_users (user_id, username, first_name, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, username, first_name, time.time())
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] Error add_started_user: {e}")
        return False
    finally:
        conn.close()


# ─── VOD Playback Resume History Helpers ──────────────────
def get_vod_progress(chat_id: int, subject_id: int, season: int, episode: int) -> int:
    """Return the saved progress in seconds for the given VOD item."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT progress_seconds FROM vod_history WHERE chat_id = ? AND subject_id = ? AND season = ? AND episode = ?",
            (chat_id, subject_id, season, episode)
        )
        row = cursor.fetchone()
        return row["progress_seconds"] if row else 0
    except Exception as e:
        print(f"[DB] Error get_vod_progress: {e}")
        return 0
    finally:
        conn.close()

def set_vod_progress(chat_id: int, subject_id: int, title: str, season: int, episode: int, progress: int):
    """Save the current VOD progress to the database."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR REPLACE INTO vod_history (chat_id, subject_id, title, season, episode, progress_seconds, last_played) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (chat_id, subject_id, title, season, episode, progress, time.time())
        )
        conn.commit()
    except Exception as e:
        print(f"[DB] Error set_vod_progress: {e}")
    finally:
        conn.close()

def clear_vod_progress(chat_id: int, subject_id: int, season: int, episode: int):
    """Delete progress history for the given VOD item."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM vod_history WHERE chat_id = ? AND subject_id = ? AND season = ? AND episode = ?",
            (chat_id, subject_id, season, episode)
        )
        conn.commit()
    except Exception as e:
        print(f"[DB] Error clear_vod_progress: {e}")
    finally:
        conn.close()

# ─── Trending Cache Helpers ─────────────────────────────
def get_cached_trending_items(category: str) -> list:
    """Retrieve all cached trending movies/series for a given category."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT subject_id, title, release_date, rating, has_hindi FROM trending_cache WHERE category = ?",
            (category,)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"[DB] Error get_cached_trending_items: {e}")
        return []
    finally:
        conn.close()

def save_cached_trending_items(category: str, items: list):
    """Overwrite the cached trending list for a category."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM trending_cache WHERE category = ?", (category,))
        for item in items:
            cursor.execute(
                "INSERT INTO trending_cache (category, subject_id, title, release_date, rating, has_hindi) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    category,
                    item["subject_id"],
                    item["title"],
                    item.get("release_date", ""),
                    item.get("rating", 0.0),
                    1 if item.get("has_hindi", False) else 0
                )
            )
        conn.commit()
    except Exception as e:
        print(f"[DB] Error save_cached_trending_items: {e}")
    finally:
        conn.close()

def get_chat_vod_history(chat_id: int) -> list:
    """Retrieve all VOD progress items for a given chat, ordered by last_played descending."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT subject_id, title, season, episode, progress_seconds FROM vod_history "
            "WHERE chat_id = ? ORDER BY last_played DESC LIMIT 10",
            (chat_id,)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"[DB] Error get_chat_vod_history: {e}")
        return []
    finally:
        conn.close()

# ─── Movie Requests Helpers ──────────────────────────────
def add_movie_request(user_id: int, username: str, first_name: str, chat_id: int, chat_title: str, movie_name: str) -> int:
    """Insert a new movie request. Returns the auto-generated request ID."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO movie_requests (user_id, username, first_name, chat_id, chat_title, movie_name, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, username, first_name, chat_id, chat_title, movie_name, time.time())
        )
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        print(f"[DB] Error add_movie_request: {e}")
        return 0
    finally:
        conn.close()

def get_movie_request(req_id: int) -> dict:
    """Retrieve request details by ID."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, user_id, username, first_name, chat_id, chat_title, movie_name, status FROM movie_requests WHERE id = ?",
            (req_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DB] Error get_movie_request: {e}")
        return None
    finally:
        conn.close()

def update_request_status(req_id: int, status: str):
    """Update status of a request."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE movie_requests SET status = ? WHERE id = ?", (status, req_id))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error update_request_status: {e}")
    finally:
        conn.close()

def delete_movie_request(req_id: int):
    """Delete a request."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM movie_requests WHERE id = ?", (req_id,))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error delete_movie_request: {e}")
    finally:
        conn.close()


# ─── Cloned Bots Helper Functions ──────────────────────────────────────────

def add_cloned_bot(bot_id: int, bot_token: str, bot_username: str, bot_name: str, owner_id: int, owner_name: str) -> bool:
    """Register or update a cloned bot in the database."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO cloned_bots (bot_id, bot_token, bot_username, bot_name, owner_id, owner_name, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
            ON CONFLICT(bot_id) DO UPDATE SET
                bot_token = excluded.bot_token,
                bot_username = excluded.bot_username,
                bot_name = excluded.bot_name,
                owner_id = excluded.owner_id,
                owner_name = excluded.owner_name,
                status = 'active'
        """, (bot_id, bot_token, bot_username, bot_name, owner_id, owner_name, time.time()))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] Error add_cloned_bot: {e}")
        return False
    finally:
        conn.close()

def get_cloned_bot(bot_id: int) -> dict | None:
    """Retrieve details of a single cloned bot by bot_id."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM cloned_bots WHERE bot_id = ?", (bot_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DB] Error get_cloned_bot: {e}")
        return None
    finally:
        conn.close()

def get_all_cloned_bots(status: str = "active") -> list:
    """Get list of all cloned bots matching status, or all if status is None."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        if status:
            cursor.execute("SELECT * FROM cloned_bots WHERE status = ? ORDER BY created_at DESC", (status,))
        else:
            cursor.execute("SELECT * FROM cloned_bots ORDER BY created_at DESC")
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[DB] Error get_all_cloned_bots: {e}")
        return []
    finally:
        conn.close()

def get_user_cloned_bots(owner_id: int) -> list:
    """Get all cloned bots belonging to a specific owner_id."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM cloned_bots WHERE owner_id = ? AND status = 'active' ORDER BY created_at DESC", (owner_id,))
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[DB] Error get_user_cloned_bots: {e}")
        return []
    finally:
        conn.close()

def delete_cloned_bot(bot_id: int) -> bool:
    """Permanently delete a cloned bot record."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM cloned_bots WHERE bot_id = ?", (bot_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] Error delete_cloned_bot: {e}")
        return False
    finally:
        conn.close()

def update_cloned_bot_status(bot_id: int, status: str) -> bool:
    """Update status of a cloned bot ('active', 'stopped')."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE cloned_bots SET status = ? WHERE bot_id = ?", (status, bot_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] Error update_cloned_bot_status: {e}")
        return False
    finally:
        conn.close()


# ─── Global Auth Users Helper Functions ───────────────────────────────────

def add_global_auth_user(user_id: int, username: str = "", first_name: str = "", added_by: int = 0) -> bool:
    """Add a user to global authorization list."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO global_auth_users (user_id, username, first_name, added_by, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, username, first_name, added_by, time.time()))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] Error add_global_auth_user: {e}")
        return False
    finally:
        conn.close()

def remove_global_auth_user(user_id: int) -> bool:
    """Remove a user from global authorization list."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM global_auth_users WHERE user_id = ?", (user_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB] Error remove_global_auth_user: {e}")
        return False
    finally:
        conn.close()

def get_global_auth_users() -> list:
    """Get list of all globally authorized users."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM global_auth_users ORDER BY timestamp DESC")
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[DB] Error get_global_auth_users: {e}")
        return []
    finally:
        conn.close()

def is_global_auth_user(user_id: int) -> bool:
    """Check if a user is globally authorized."""
    if not user_id:
        return False
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM global_auth_users WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None
    except Exception as e:
        print(f"[DB] Error is_global_auth_user: {e}")
        return False
    finally:
        conn.close()

