"""
GAMEOVER MOVIE HUB — Welcome Plugin
Welcomes new group members with a styled card and welcome video from disk.
Caches Welcome.mp4 file_id in SQLite, auto re-uploading if disk file changes.
Music references removed — Movie Hub only.
"""

import os
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from config import Config
from core.db import get_setting, set_setting
from core.fonts import HEADER as ROYAL_HEADER


def register(app: Client):

    @app.on_message(filters.new_chat_members & filters.group)
    async def welcome_new_members(client: Client, message: Message):
        chat_id = message.chat.id

        # Avoid welcoming the bot itself or other bots
        me = await client.get_me()
        new_members = message.new_chat_members

        target_members = []
        for m in new_members:
            if m.id == me.id:
                # Alert Owner via PM
                owner_id = Config.OWNER_ID or 6805412676
                added_by = message.from_user
                added_by_name = added_by.first_name if added_by and added_by.first_name else "Unknown User"
                added_by_id = added_by.id if added_by else 0
                added_by_username = f"@{added_by.username}" if added_by and added_by.username else "N/A"
                
                alert_text = (
                    f"{ROYAL_HEADER}"
                    f"<b>Bᴏᴛ Aᴅᴅᴇᴅ Tᴏ Nᴇᴡ Gʀᴏᴜᴘ!</b>\n\n"
                    f"‣ <b>Group Name:</b> <code>{message.chat.title}</code>\n"
                    f"‣ <b>Group ID:</b> <code>{chat_id}</code>\n\n"
                    f"‣ <b>Added By:</b> <a href=\"tg://user?id={added_by_id}\">{added_by_name}</a> [{added_by_username}]\n"
                    f"‣ <b>User ID:</b> <code>{added_by_id}</code>"
                )
                try:
                    from bot import send_styled
                    await send_styled(chat_id=owner_id, text=alert_text)
                except Exception as e:
                    print(f"[Group Add Alert] Error: {e}")

                # Bot itself joined a group — send intro message
                intro_text = (
                    f"{ROYAL_HEADER}"
                    "<b>GᴀᴍᴇOᴠᴇʀ Mᴏᴠɪᴇ Hᴜʙ</b> yahan aa gaya hai!\n\n"
                    "Main group mein <b>Movies aur Web Series</b> stream kar sakta hoon.\n\n"
                    "‣ <b>Movie ya Series dhoondne ke liye:</b>\n"
                    "<code>/movie [movie name]</code>\n\n"
                    "‣ <b>Example:</b>\n"
                    "<code>/movie Avengers</code>\n"
                    "<code>/movie The Boys S2</code>"
                )
                await message.reply_text(intro_text, parse_mode=enums.ParseMode.HTML)
                return
            if not m.is_bot:
                target_members.append(m)

        if not target_members:
            return

        # Check if welcome is enabled for this group
        from core.db import is_group_welcome_enabled
        if not is_group_welcome_enabled(chat_id):
            return

        # Format user mentions
        mentions_str = ", ".join(m.mention for m in target_members)
        group_name = message.chat.title

        welcome_text = (
            f"<b>Welcome to {group_name}!</b>\n\n"
            f"Swagat hai, {mentions_str}!\n\n"
            f"‣ <b>Movies dhoondne ke liye:</b>\n"
            f"<code>/movie [movie name]</code>\n\n"
            f"‣ <b>Series dhoondne ke liye:</b>\n"
            f"<code>/movie [series name]</code>\n"
        )

        # Quick access buttons
        welcome_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Mᴏᴠɪᴇ Sᴇᴀʀᴄʜ", callback_data="help_all")],
            [InlineKeyboardButton("Aᴅᴅ Mᴇ Tᴏ Yᴏᴜʀ Gʀᴏᴜᴘ", url=f"https://t.me/{Config.BOT_USERNAME}?startgroup=true")]
        ])

        # Retrieve or Upload Welcome Video from root folder
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        video_path = os.path.join(base_dir, "welcome.mp4")
        if not os.path.exists(video_path):
            video_path = os.path.join(base_dir, "Welcome.mp4")

        from core.media_helper import send_cached_video
        await send_cached_video(
            client=client,
            chat_id=chat_id,
            video_path=video_path,
            cache_key_prefix="welcome_video",
            caption=welcome_text,
            reply_markup=welcome_markup,
            parse_mode=enums.ParseMode.HTML
        )
