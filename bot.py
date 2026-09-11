"""
GameOver Movie Hub — Main Bot Entry Point
Dedicated movie/VOD bot — streams movies inside group voice chats.
Uses same API_ID, API_HASH, OWNER_ID as Music Bot.
Different: BOT_TOKEN (Gameovermovie_bot) + STRING3 (new assistant session).
"""

import sys
import io
import asyncio
import os
import inspect
import sqlite3

# Global SQLite patch to prevent "database is locked" errors in Pyrogram session & local DBs
_orig_sqlite_connect = sqlite3.connect
def _patched_sqlite_connect(*args, **kwargs):
    kwargs.setdefault("timeout", 30.0)
    conn = _orig_sqlite_connect(*args, **kwargs)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
    except Exception:
        pass
    return conn
sqlite3.connect = _patched_sqlite_connect

# Dynamic module wrappers to prevent pytgcalls import errors on standard/fork pyrogram versions
import pyrogram.errors
import pyrogram.raw.types

class RawTypesModuleWrapper:
    def __init__(self, original_module):
        self._original_module = original_module
    def __getattr__(self, name):
        try:
            return getattr(self._original_module, name)
        except AttributeError:
            class DummyClass:
                pass
            DummyClass.__name__ = name
            setattr(self._original_module, name, DummyClass)
            return DummyClass

if not isinstance(pyrogram.raw.types, RawTypesModuleWrapper):
    sys.modules["pyrogram.raw.types"] = RawTypesModuleWrapper(pyrogram.raw.types)

class ErrorsModuleWrapper:
    def __init__(self, original_module):
        self._original_module = original_module
    def __getattr__(self, name):
        try:
            return getattr(self._original_module, name)
        except AttributeError:
            # Case-insensitive mismatch fallback (e.g., GroupcallInvalid -> GroupCallInvalid)
            for key in dir(self._original_module):
                if key.lower() == name.lower():
                    val = getattr(self._original_module, key)
                    setattr(self._original_module, name, val)
                    return val
            class DummyError(Exception):
                pass
            DummyError.__name__ = name
            setattr(self._original_module, name, DummyError)
            return DummyError

if not isinstance(pyrogram.errors, ErrorsModuleWrapper):
    sys.modules["pyrogram.errors"] = ErrorsModuleWrapper(pyrogram.errors)

# Patch pyrogram JoinGroupCall and JoinGroupCallPresentation to drop unsupported arguments (like public_key)
import pyrogram.raw.functions.phone
for call_class_name in ("JoinGroupCall", "JoinGroupCallPresentation"):
    call_cls = getattr(pyrogram.raw.functions.phone, call_class_name, None)
    if call_cls and hasattr(call_cls, "__init__") and not getattr(call_cls, "__patched__", False):
        orig_init = call_cls.__init__
        def make_patched_init(old_init):
            def patched_init(self, *args, **kwargs):
                sig = inspect.signature(old_init)
                clean_kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
                old_init(self, *args, **clean_kwargs)
            return patched_init
        call_cls.__init__ = make_patched_init(orig_init)
        call_cls.__patched__ = True

# Patch pyrogram.utils.get_peer_type to prevent ValueError crash in handle_updates on un-cached IDs
import pyrogram.utils
if not getattr(pyrogram.utils, "__patched__", False):
    _orig_get_peer_type = pyrogram.utils.get_peer_type
    def _patched_get_peer_type(peer_id: int) -> str:
        try:
            return _orig_get_peer_type(peer_id)
        except ValueError:
            # Safe fallback based on typical ID ranges:
            # -100xxxxxx is channel/supergroup, -xxxxxx is group chat, positive is user
            pid_str = str(peer_id)
            if pid_str.startswith("-100"):
                return "channel"
            elif pid_str.startswith("-"):
                return "chat"
            else:
                return "user"
    pyrogram.utils.get_peer_type = _patched_get_peer_type
    pyrogram.utils.__patched__ = True

from pyrogram import Client, idle, enums, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from config import Config
from core.player import stream_manager

# Set UTF-8 encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Verify credentials before loading clients
Config.validate()

# Initialize bot client
bot = Client(
    name="GameOverMovieBot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
)

# Initialize assistant client
assistant = Client(
    name="GameOverMovieAssistant",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    session_string=Config.STRING3,
    in_memory=True,
)

# ─── Native Colored Button Support (Telegram Bot API 9.4) ────────────────────
# pyrogram/pyrofork doesn't serialize the 'style' field through MTProto.
# We patch InlineKeyboardButton to store style, then use the Bot HTTP API
# directly (via aiohttp) when sending/editing messages with styled keyboards.
import pyrogram.types

_orig_btn_init = pyrogram.types.InlineKeyboardButton.__init__
def _patched_btn_init(self, *args, **kwargs):
    style = kwargs.pop("style", None)
    _orig_btn_init(self, *args, **kwargs)
    self.style = style  # always store, even if None
pyrogram.types.InlineKeyboardButton.__init__ = _patched_btn_init

def _markup_to_bot_api_json(markup) -> list:
    """Convert Pyrogram InlineKeyboardMarkup or row list → Bot API JSON with style support."""
    if not markup:
        return []
    raw_rows = getattr(markup, "inline_keyboard", markup)
    if not isinstance(raw_rows, (list, tuple)):
        return []
    rows = []
    for row in raw_rows:
        btn_row = []
        for btn in row:
            if isinstance(btn, dict):
                btn_row.append(btn)
                continue
            obj = {"text": getattr(btn, "text", str(btn))}
            if getattr(btn, "callback_data", None) is not None:
                obj["callback_data"] = btn.callback_data
            elif getattr(btn, "url", None) is not None:
                obj["url"] = btn.url
            if getattr(btn, "style", None):
                obj["style"] = btn.style
            btn_row.append(obj)
        rows.append(btn_row)
    return rows

async def send_styled(chat_id: int, text: str, markup: InlineKeyboardMarkup = None, parse_mode: str = "HTML", message_id: int = None) -> dict:
    """
    Send or edit a message using Bot HTTP API so that native button 'style'
    (success/danger/primary) is preserved — Telegram Bot API 9.4+.
    Returns the response JSON dict.
    """
    import aiohttp, json
    token = Config.BOT_TOKEN
    endpoint = f"https://api.telegram.org/bot{token}/"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }
    if markup:
        payload["reply_markup"] = json.dumps({
            "inline_keyboard": _markup_to_bot_api_json(markup)
        })
    method = "editMessageText" if message_id else "sendMessage"
    if message_id:
        payload["message_id"] = message_id
    try:
        timeout = aiohttp.ClientTimeout(total=10.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(endpoint + method, json=payload) as resp:
                return await resp.json()
    except Exception as e:
        print(f"[BotAPI] send_styled error: {e}")
        return {}


# ── /start handler for Private Chats ───────────────────────────────────────
@bot.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    user = message.from_user
    user_id = user.id if user else 0
    username = user.username if user and user.username else ""
    first_name = user.first_name if user and user.first_name else ""
    
    # Track user and alert owner
    try:
        from core.db import add_started_user
        is_new = add_started_user(user_id, username, first_name)
        
        owner_id = Config.OWNER_ID or 6805412676
        tag = "<b>NEW USER STARTED BOT!</b>" if is_new else "<b>USER STARTED BOT!</b>"
        user_link = f"<a href=\"tg://user?id={user_id}\">{first_name}</a>"
        alert_text = (
            f"<b>GᴀᴍᴇOᴠᴇʀ Mᴏᴠɪᴇ Hᴜʙ</b>\n\n"
            f"{tag}\n\n"
            f"‣ <b>Nᴀᴍᴇ :</b> {user_link}\n"
            f"‣ <b>Usᴇʀ ID :</b> <code>{user_id}</code>\n"
            f"‣ <b>Usᴇʀɴᴀᴍᴇ :</b> @{username or 'N/A'}"
        )
        try:
            await send_styled(chat_id=owner_id, text=alert_text)
        except Exception as alert_err:
            print(f"[Start Alert] Failed to alert owner: {alert_err}")
    except Exception as db_err:
        print(f"[Start Alert] DB error: {db_err}")

    # Handle deep-link for /start clone
    if message.command and len(message.command) > 1 and message.command[1].lower() == "clone":
        from plugins.clone import get_clone_guide_text, get_clone_guide_markup
        await message.reply_text(
            get_clone_guide_text(),
            parse_mode=enums.ParseMode.HTML,
            reply_markup=get_clone_guide_markup(),
            disable_web_page_preview=True
        )
        return

    from core.db import get_setting
    start_video_file_id = get_setting("start_video_file_id")

    owner_id = Config.OWNER_ID or 6805412676
    owner_link = f"tg://user?id={owner_id}"
    try:
        owner_user = await client.get_users(owner_id)
        if owner_user and owner_user.username:
            owner_link = f"https://t.me/{owner_user.username}"
    except Exception:
        pass

    caption_text = (
        "<b>GᴀᴍᴇOᴠᴇʀ Mᴏᴠɪᴇ Hᴜʙ</b>\n\n"
        "I Aᴍ Tʜᴇ Fᴀsᴛ Aɴᴅ PᴏᴡᴇʀFᴜʟ Mᴏᴠɪᴇ Pʟᴀʏᴇʀ Bᴏᴛ Wɪᴛʜ Sᴏᴍᴇ Aᴡᴇsᴏᴍᴇ Fᴇᴀᴛᴜʀᴇs.\n\n"
        "Cʟɪᴄᴋ Oɴ Tʜᴇ Hᴇʟᴘ Bᴜᴛᴛᴏɴ Tᴏ Gᴇᴛ Iɴғᴏʀᴍᴀᴛɪᴏɴ Aʙᴏᴜᴛ Mʏ Mᴏᴅᴜʟᴇs Aɴᴅ Cᴏᴍᴍᴀɴᴅs."
    )

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("Aᴅᴅ Mᴇ Iɴ Yᴏᴜʀ Gʀᴏᴜᴘ", url=f"https://t.me/{Config.BOT_USERNAME}?startgroup=true", style="primary")],
        [InlineKeyboardButton("Hᴇʟᴘ Aɴᴅ Cᴏᴍᴍᴀɴᴅs", callback_data="help_all", style="primary")],
        [
            InlineKeyboardButton("Oᴡɴᴇʀ", url=owner_link, style="primary"),
            InlineKeyboardButton("Cʟᴏɴᴇ Bᴏᴛ", callback_data="clone_start", style="primary")
        ]
    ])

    if start_video_file_id:
        try:
            await client.send_video(
                chat_id=message.chat.id,
                video=start_video_file_id,
                caption=caption_text,
                parse_mode=enums.ParseMode.HTML,
                reply_markup=markup,
                supports_streaming=True
            )
            return
        except Exception as e:
            print(f"[Start] Cached video failed: {e}")

    # Fallback: check disk for start.mp4 / Welcome.mp4
    base_dir = os.path.dirname(os.path.abspath(__file__))
    for fname in ["start.mp4", "Start.mp4", "welcome.mp4", "Welcome.mp4"]:
        video_path = os.path.join(base_dir, fname)
        if os.path.exists(video_path):
            try:
                sent = await client.send_video(
                    chat_id=message.chat.id,
                    video=video_path,
                    caption=caption_text,
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=markup,
                    supports_streaming=True
                )
                if sent and sent.video:
                    from core.db import set_setting
                    set_setting("start_video_file_id", sent.video.file_id)
                return
            except Exception as e:
                print(f"[Start] Local video send failed: {e}")
            break

    # Final fallback: text only — guaranteed to work
    try:
        await message.reply_text(
            caption_text,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=markup,
            disable_web_page_preview=True
        )
    except Exception as e:
        print(f"[Start] Even text reply failed: {e}")
        # Last resort — no markup
        try:
            await message.reply_text(caption_text, parse_mode=enums.ParseMode.HTML)
        except Exception:
            pass



# Group message auto-registration
@bot.on_message(filters.group, group=-1)
async def global_group_message_handler(client: Client, message: Message):
    chat_id = message.chat.id
    title = message.chat.title or "Unknown Group"
    if chat_id and title:
        from core.db import update_group_info
        update_group_info(chat_id, title)


async def main():
    # Initialize working domain detection for VOD/MOVIES engine
    try:
        from core.domain_manager import detect_working_domain
        await detect_working_domain()
    except Exception as e:
        print(f"[DomainManager] Failed to detect working domain: {e}")

    print("\n" + "="*52)
    print("   GameOver Movie Hub Bot")
    print("   Starting clients...")
    print("="*52)

    await bot.start()
    bot_me = await bot.get_me()
    Config.BOT_USERNAME = bot_me.username or ""
    print(f"[Bot]       Started as: @{bot_me.username}")

    await assistant.start()
    me = await assistant.get_me()
    print(f"[Assistant] Logged in as: {me.first_name} (@{me.username or 'no username'})")

    # Set default quality to 1080p @ 60 FPS on every startup
    try:
        from core.db import get_setting, set_setting
        if not get_setting("quality_pref"):
            set_setting("quality_pref", "1080p")
            print("[Bot] Quality default set: 1080p")
        if not get_setting("fps_pref"):
            set_setting("fps_pref", "60")
            print("[Bot] FPS default set: 60")
    except Exception as qs_err:
        print(f"[Bot] Quality/FPS default setup error: {qs_err}")

    # Set Telegram native menu button commands
    try:
        await bot.set_bot_commands([
            BotCommand("start", "Bot start karein"),
            BotCommand("movie", "Movie ya series stream karein"),
            BotCommand("vod", "Movie ya series stream karein"),
            BotCommand("trending", "Trending Movies & Series list dekhein"),
            BotCommand("latest", "Latest Movies & Series list dekhein"),
            BotCommand("random", "Random Hindi movie stream karein (Surprise Me)"),
            BotCommand("history", "Recent watch history aur saved progress dekhein"),
            BotCommand("request", "Request any missing movie/series to admin"),
            BotCommand("clone", "Apna bot clone karein"),
        ])
        print("[Bot] Native menu commands set successfully!")
    except Exception as e:
        print(f"[Bot] Failed to set native menu commands: {e}")

    # Register plugins
    from plugins import movies, welcome, admin, controls, clone
    movies.register(bot)
    welcome.register(bot)
    admin.register(bot)
    controls.register(bot)
    clone.register(bot)

    # Initialize PyTgCalls streamer
    await stream_manager.init(assistant, bot)

    # Initialize and load all active cloned bots
    from core.clone_manager import clone_manager
    clone_manager.init(bot)
    await clone_manager.load_and_start_all()

    print("\n" + "="*52)
    print("   Movie Hub Bot is running LIVE!")
    print("="*52 + "\n")

    try:
        await idle()
    except BaseException:
        pass
    finally:
        print("\nShutting down...")
        try:
            await clone_manager.stop_all()
        except Exception:
            pass
        try:
            for chat_id in list(stream_manager._active_chats):
                try:
                    await stream_manager.stop(chat_id)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            await asyncio.wait_for(assistant.stop(), timeout=2.0)
        except BaseException:
            pass
        try:
            await asyncio.wait_for(bot.stop(), timeout=2.0)
        except BaseException:
            pass
        print("[Bot] Exited cleanly. Goodbye!")


if __name__ == "__main__":
    bot.run(main())
