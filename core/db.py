"""
GameOver Movie Hub — Local SQLite Database Helper
Handles persistent storage for Sudo Admins, Auth Groups, Allowed Groups, and User Playlists.
"""

import sqlite3
import json
import time

DB_FILE = "gameover_db.sqlite3"

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
            PRIMARY KEY (chat_id, user_id)
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
    
    conn.commit()
    conn.close()

# Initialize database tables
init_db()


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
def add_auth_user(chat_id: int, user_id: int):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR IGNORE INTO auth_users (chat_id, user_id) VALUES (?, ?)", (chat_id, user_id))
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
        cursor.execute("SELECT user_id FROM auth_users WHERE chat_id = ?", (chat_id,))
        rows = cursor.fetchall()
        return [row["user_id"] for row in rows]
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
