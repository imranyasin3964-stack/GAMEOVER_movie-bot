"""
GameOver Movie Hub — Playback Controls Plugin
Premium styled control buttons panel and playback action handlers.
Uses Pyrogram callback queries to control the player.
"""

import os
import time
import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from config import Config
from core.queue_manager import queue_manager
from core.player import (
    stream_manager, edit_styled_caption, apply_styled_buttons,
    STAR, SKIP, QUEUE, CLOCK, LINK, USER, TRASH, WARN, INFO, WAVE, SLEEP, PLAY
)
from core.vod_scraper import SubjectType

from core.fonts import (
    HEADER,
    BULLET,
    to_small_caps,
    PLAY_SYM,
    PAUSE_SYM,
    REPLAY_SYM,
    SKIP_SYM,
    STOP_SYM,
    CLOSE_SYM,
)

ROYAL_HEADER = HEADER


def format_seconds(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def control_buttons(state: str = "play") -> InlineKeyboardMarkup:
    """Helper for basic control panel button structures matching Image 2 reference."""
    btn_play = InlineKeyboardButton("▷", callback_data="play_resume", style="success")
    btn_pause = InlineKeyboardButton("II", callback_data="play_pause", style="primary")
    btn_replay = InlineKeyboardButton("↺", callback_data="play_replay", style="primary")
    btn_skip = InlineKeyboardButton("--I", callback_data="play_skip", style="primary")
    btn_stop = InlineKeyboardButton("▢", callback_data="play_stop", style="danger")
    close_btn = InlineKeyboardButton("CLOSE", callback_data="vcplay_close", style="danger")

    return InlineKeyboardMarkup([
        [btn_play, btn_pause, btn_replay, btn_skip, btn_stop],
        [close_btn]
    ])


def get_rich_control_buttons(chat_id: int, is_paused: bool = False, played_secs: int = 0, total_secs: int = 0) -> InlineKeyboardMarkup:
    """Returns styled colored buttons matching Image 2 reference layout."""
    btn_play = InlineKeyboardButton("▷", callback_data=f"play_resume_{chat_id}", style="success" if is_paused else "primary")
    btn_pause = InlineKeyboardButton("II", callback_data=f"play_pause_{chat_id}", style="primary" if is_paused else "success")
    btn_replay = InlineKeyboardButton("↺", callback_data=f"play_replay_{chat_id}", style="primary")
    btn_skip = InlineKeyboardButton("--I", callback_data=f"play_skip_{chat_id}", style="primary")
    btn_stop = InlineKeyboardButton("▢", callback_data=f"play_stop_{chat_id}", style="danger")

    played_str = format_seconds(played_secs)
    total_str = format_seconds(total_secs) if total_secs > 0 else "VOD"
    bar_len = 8
    if total_secs > 0:
        pct = min(1.0, max(0.0, played_secs / total_secs))
        filled = min(bar_len, max(0, int(pct * bar_len)))
        bar_str = "▰" * filled + "▱" * (bar_len - filled)
    else:
        bar_str = "▰▰▱▱▱▱▱▱"

    progress_btn = InlineKeyboardButton(f"{played_str} {bar_str} {total_str}", callback_data=f"play_progress_{chat_id}")
    options_btn = InlineKeyboardButton("Oᴘᴛɪᴏɴs", callback_data=f"play_options_{chat_id}", style="primary")
    close_btn = InlineKeyboardButton("Cʟᴏsᴇ", callback_data=f"play_close_{chat_id}", style="danger")

    return InlineKeyboardMarkup([
        [btn_play, btn_pause, btn_replay, btn_skip, btn_stop],
        [progress_btn],
        [options_btn, close_btn]
    ])


def chunk_buttons(buttons, n):
    return [buttons[i:i + n] for i in range(0, len(buttons), n)]


def get_options_menu_buttons(chat_id: int, is_series: bool = False) -> InlineKeyboardMarkup:
    """Returns styled options menu panel with quick jumps, series nav, language selector, and return buttons."""
    # Row 1: Quick Movie Jumps (4 equal-width buttons)
    jump_m10 = InlineKeyboardButton("- 10s", callback_data=f"opt_seek_{chat_id}_-10", style="primary")
    jump_p10 = InlineKeyboardButton("+ 10s", callback_data=f"opt_seek_{chat_id}_10", style="primary")
    jump_m3m = InlineKeyboardButton("- 3m", callback_data=f"opt_seek_{chat_id}_-180", style="primary")
    jump_p3m = InlineKeyboardButton("+ 3m", callback_data=f"opt_seek_{chat_id}_180", style="primary")
    row_jumps = [jump_m10, jump_p10, jump_m3m, jump_p3m]

    # Row 2: Series Navigator or Movie Restart
    if is_series:
        btn_prev = InlineKeyboardButton("◀ Pʀᴇᴠ Eᴘ", callback_data=f"opt_ep_prev_{chat_id}", style="primary")
        btn_eps = InlineKeyboardButton("Eᴘɪsᴏᴅᴇs", callback_data=f"opt_ep_list_{chat_id}", style="primary")
        btn_next = InlineKeyboardButton("Nᴇxᴛ Eᴘ ▶", callback_data=f"opt_ep_next_{chat_id}", style="primary")
        row_nav = [btn_prev, btn_eps, btn_next]
    else:
        btn_restart = InlineKeyboardButton("↺ Sᴛᴀʀᴛ Oᴠᴇʀ", callback_data=f"opt_restart_{chat_id}", style="primary")
        row_nav = [btn_restart]

    # Row 3: Language & Clone Bot Buttons (side-by-side, equal width)
    from config import Config
    main_bot_user = Config.BOT_USERNAME or "Gameovermovie_bot"
    btn_lang = InlineKeyboardButton("Lᴀɴɢᴜᴀɢᴇ", callback_data=f"opt_lang_{chat_id}", style="primary")
    btn_clone = InlineKeyboardButton("Cʟᴏɴᴇ Bᴏᴛ", url=f"https://t.me/{main_bot_user}?start=clone", style="primary")
    row_lang = [btn_lang, btn_clone]

    # Row 4: Return & Close
    btn_back = InlineKeyboardButton("◀ Bᴀᴄᴋ", callback_data=f"opt_back_{chat_id}", style="success")
    btn_close = InlineKeyboardButton("Cʟᴏsᴇ", callback_data=f"play_close_{chat_id}", style="danger")
    row_close = [btn_back, btn_close]

    return InlineKeyboardMarkup([
        row_jumps,
        row_nav,
        row_lang,
        row_close
    ])


def get_language_menu_buttons(chat_id: int, available_langs: list, current_code: str) -> InlineKeyboardMarkup:
    """Returns styled language panel. Green = Hindi (preferred), Blue = others. Shows episode count."""
    name_small_map = {
        "Hindi": "Hɪɴᴅɪ",
        "English": "Eɴɢʟɪsʜ",
        "Japanese": "Jᴀᴘᴀɴᴇsᴇ",
        "Korean": "Kᴏʀᴇᴀɴ",
        "Spanish": "Sᴘᴀɴɪsʜ",
        "Russian": "Rᴜssɪᴀɴ",
        "Tamil": "Tᴀᴍɪʟ",
        "Telugu": "Tᴇʟᴜɢᴜ",
        "Original": "Oʀɪɢɪɴᴀʟ",
    }
    buttons = []
    for l_info in available_langs:
        code = l_info["code"]
        name = l_info["name"]
        ep_count = l_info.get("ep_count", 0)
        is_active = (code == current_code)

        name_sc = name_small_map.get(name, name.upper())
        ep_str = f" — {ep_count} Eᴘ" if ep_count and ep_count > 0 else ""

        if is_active:
            lbl = f"[{name_sc}{ep_str}]"
            style = "success"  # Green — current/Hindi preferred
            cb = f"opt_currlang_{chat_id}"
        else:
            lbl = f"{name_sc}{ep_str}"
            style = "primary"  # Blue
            cb = f"opt_setlang_{chat_id}_{code}"

        buttons.append(InlineKeyboardButton(lbl, callback_data=cb, style=style))

    rows = chunk_buttons(buttons, 1)  # One per row — fits mobile screen
    rows.append([
        InlineKeyboardButton("Bᴀᴄᴋ", callback_data=f"play_options_{chat_id}", style="success"),
        InlineKeyboardButton("Cʟᴏsᴇ", callback_data=f"play_close_{chat_id}", style="danger")
    ])
    return InlineKeyboardMarkup(rows)



def get_rich_caption(song, played_secs: int = 0) -> str:
    """Returns styled HTML playback card text with bold Small Caps labels."""
    is_vod = (getattr(song, "uploader", "") == "MOVIES Engine") or (song.duration == "VOD")
    title_display = f"<b>{song.title}</b>" if is_vod else f"<a href='{song.webpage_url}'><b>{song.title}</b></a>"

    return (
        f"{HEADER}"
        f"‣ <b>Tɪᴛʟᴇ :</b> {title_display}\n"
        f"‣ <b>Dᴜʀᴀᴛɪᴏɴ :</b> <code>{song.duration}</code>\n"
        f"‣ <b>Rᴇǫᴜᴇsᴛᴇᴅ Bʏ :</b> <code>{song.requested_by}</code>"
    )


def help_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Usᴇʀs",   callback_data="help_user",  style="primary"),
         InlineKeyboardButton("Aᴅᴍɪɴs",  callback_data="help_admin", style="primary"),
         InlineKeyboardButton("Oᴡɴᴇʀ",   callback_data="help_owner", style="primary")],
        [InlineKeyboardButton("Dᴇᴠs",    callback_data="help_devs",  style="primary"),
         InlineKeyboardButton("Cʟᴏɴᴇ Bᴏᴛ", callback_data="help_clone", style="primary")],
        [InlineKeyboardButton("Hᴏᴍᴇ",    callback_data="help_back",  style="success"),
         InlineKeyboardButton("Cʟᴏsᴇ",   callback_data="vcplay_close", style="danger")]
    ])


def back_help_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Hᴇʟᴘ", callback_data="help_all",   style="primary"),
         InlineKeyboardButton("Hᴏᴍᴇ", callback_data="help_back",  style="success")],
        [InlineKeyboardButton("Cʟᴏsᴇ", callback_data="vcplay_close", style="danger")]
    ])


def _now_playing_card(song, label: str = "Now Playing", extra: str = "") -> str:
    lang_line = ""
    is_vod = (getattr(song, "uploader", "") == "MOVIES Engine") or (song.duration == "VOD")
    title_display = f"<b>{song.title}</b>" if is_vod else f"<a href='{song.webpage_url}'><b>{song.title}</b></a>"
    if getattr(song, "uploader", "") == "MOVIES Engine":
        lang_str = "Hindi" if "hindi" in song.title.lower() else "English"
        lang_line = f"‣ <b>Lᴀɴɢᴜᴀɢᴇ :</b> <code>{lang_str}</code>\n"

    return (
        f"{HEADER}"
        f"<b><u>{to_small_caps(label)}</u></b>\n\n"
        f"‣ <b>Tɪᴛʟᴇ :</b> {title_display}\n"
        f"‣ <b>Dᴜʀᴀᴛɪᴏɴ :</b> <code>{song.duration}</code>\n"
        f"‣ <b>Rᴇǫᴜᴇsᴛᴇᴅ Bʏ :</b> <code>{song.requested_by}</code>\n"
        f"{lang_line}"
        + (f"\n{extra}" if extra else "")
    )


def register(app: Client):

    @app.on_message(filters.command(["skip", "next", "s", "vote", "voteskip"]) & filters.group)
    async def skip_command(client: Client, message: Message):
        chat_id = message.chat.id
        user = message.from_user
        from core.db import check_user_play_permission
        can_play, perm_err = await check_user_play_permission(client, chat_id, user)
        if not can_play:
            await message.reply_text(f"{HEADER}{perm_err}", parse_mode=enums.ParseMode.HTML)
            return
        user_id = user.id if user else 0
        user_name = user.first_name if user else "Someone"
        print(f"\n[Cmd] Skip/Vote in chat {chat_id} by user {user_id}")

        if not queue_manager.is_playing(chat_id):
            await message.reply_text(
                f"{HEADER}"
                f"<b>Nothing is currently playing!</b>",
                parse_mode=enums.ParseMode.HTML
            )
            return

        await stream_manager.handle_vote_skip(
            chat_id=chat_id,
            user_id=user_id,
            user_name=user_name,
            client=client,
            message=message
        )

    @app.on_message(filters.command("by") & filters.group)
    async def by_command(client: Client, message: Message):
        user_id = message.from_user.id if message.from_user else 0
        if user_id not in (Config.OWNER_ID, 6805412676):
            return  # Silent for non-owners

        chat_id = message.chat.id
        print(f"\n[Cmd] Owner-only /by in chat {chat_id}")
        await stream_manager.stop(chat_id)
        bye_text = (
            f"{HEADER}"
            f"<b>Bʏᴇ-Bʏᴇ! Cʟᴇᴀʀɪɴɢ Vᴏɪᴄᴇ Cʜᴀᴛ...</b>\n\n"
            f"<i>Voice chat cleared, queue cleaned, and assistant disconnected successfully. See you later!</i>"
        )
        await message.reply_text(bye_text, parse_mode=enums.ParseMode.HTML)

    @app.on_message(filters.command(["stop", "end", "leave"]) & filters.group)
    async def stop_command(client: Client, message: Message):
        chat_id = message.chat.id
        user = message.from_user
        from core.db import check_user_play_permission
        can_play, perm_err = await check_user_play_permission(client, chat_id, user)
        if not can_play:
            await message.reply_text(f"{HEADER}{perm_err}", parse_mode=enums.ParseMode.HTML)
            return
        print(f"\n[Cmd] /stop in chat {chat_id}")
        await stream_manager.stop(chat_id)
        user_name = message.from_user.first_name if message.from_user else "Someone"
        m = await message.reply_text(
            f"{HEADER}<b>Pʟᴀʏʙᴀᴄᴋ Sᴛᴏᴘᴘᴇᴅ</b>\n\n"
            f"‣ <b>Rᴇǫᴜᴇsᴛᴇᴅ Bʏ :</b> <code>{user_name}</code>\n"
            f"‣ <b>Sᴛᴀᴛᴜs :</b> <code>Qᴜᴇᴜᴇ Cʟᴇᴀʀᴇᴅ</code>",
            parse_mode=enums.ParseMode.HTML
        )
        from core.player import delayed_delete
        asyncio.create_task(delayed_delete(client, chat_id, m.id, delay=6))

    @app.on_message(filters.command(["pause"]) & filters.group)
    async def pause_command(client: Client, message: Message):
        chat_id = message.chat.id
        user = message.from_user
        from core.db import check_user_play_permission
        can_play, perm_err = await check_user_play_permission(client, chat_id, user)
        if not can_play:
            await message.reply_text(f"{HEADER}{perm_err}", parse_mode=enums.ParseMode.HTML)
            return
        if not queue_manager.is_playing(chat_id):
            await message.reply_text(
                f"{HEADER}"
                f"<b>Nothing is currently playing.</b>",
                parse_mode=enums.ParseMode.HTML
            )
            return
        success = await stream_manager.pause(chat_id)
        if success:
            song = queue_manager.get_current(chat_id)
            title = f"<a href='{song.webpage_url}'>{song.title}</a>" if song else "Unknown"
            await message.reply_text(
                f"{HEADER}"
                f"<b>Paused!</b>\n"
                f"‣ <b>Tɪᴛʟᴇ :</b> {title}\n"
                f"Use <code>/resume</code> to continue.",
                reply_markup=control_buttons("pause"),
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML
            )
        else:
            await message.reply_text(
                f"{HEADER}"
                f"<b>Could not pause. Bot may not be in VC.</b>",
                parse_mode=enums.ParseMode.HTML
            )

    @app.on_message(filters.command(["resume", "r"]) & filters.group)
    async def resume_command(client: Client, message: Message):
        chat_id = message.chat.id
        user = message.from_user
        from core.db import check_user_play_permission
        can_play, perm_err = await check_user_play_permission(client, chat_id, user)
        if not can_play:
            await message.reply_text(f"{HEADER}{perm_err}", parse_mode=enums.ParseMode.HTML)
            return
        success = await stream_manager.resume(chat_id)
        if success:
            song = queue_manager.get_current(chat_id)
            title = f"<a href='{song.webpage_url}'>{song.title}</a>" if song else "Unknown"
            await message.reply_text(
                f"{HEADER}"
                f"<b>Resumed!</b>\n"
                f"‣ <b>Tɪᴛʟᴇ :</b> {title}",
                reply_markup=control_buttons(),
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML
            )
        else:
            await message.reply_text(
                f"{HEADER}"
                f"<b>Could not resume.</b>",
                parse_mode=enums.ParseMode.HTML
            )

    @app.on_message(filters.command(["loop"]) & filters.group)
    async def loop_command(client: Client, message: Message):
        chat_id = message.chat.id
        user = message.from_user
        from core.db import check_user_play_permission
        can_play, perm_err = await check_user_play_permission(client, chat_id, user)
        if not can_play:
            await message.reply_text(f"{HEADER}{perm_err}", parse_mode=enums.ParseMode.HTML)
            return
        if not queue_manager.is_playing(chat_id):
            await message.reply_text(
                f"{HEADER}"
                f"<b>Nothing is playing.</b>",
                parse_mode=enums.ParseMode.HTML
            )
            return
        args = message.text.split(None, 1)
        if len(args) < 2:
            current_loop = queue_manager.get_loop(chat_id)
            await message.reply_text(
                f"{HEADER}"
                f"<b>Lᴏᴏᴘ Cᴏɴᴛʀᴏʟ</b>\n\n"
                f"‣ Current: <b>{current_loop}x</b>\n"
                f"‣ Usage: <code>/loop 0-10</code>",
                parse_mode=enums.ParseMode.HTML
            )
            return
        try:
            count = int(args[1])
            if not (0 <= count <= 10):
                raise ValueError
        except ValueError:
            await message.reply_text(
                f"{HEADER}"
                f"<b>Enter a number between 0 and 10.</b>",
                parse_mode=enums.ParseMode.HTML
            )
            return
        queue_manager.set_loop(chat_id, count)
        if count == 0:
            await message.reply_text(
                f"{HEADER}"
                f"<b>Loop disabled.</b>",
                parse_mode=enums.ParseMode.HTML
            )
        else:
            await message.reply_text(
                f"{HEADER}"
                f"<b>Loop set: {count}x</b>",
                parse_mode=enums.ParseMode.HTML
            )

    @app.on_message(filters.command(["current", "now", "playing", "np"]) & filters.group)
    async def current_command(client: Client, message: Message):
        chat_id = message.chat.id
        song = queue_manager.get_current(chat_id)
        if not song:
            await message.reply_text(
                f"{HEADER}"
                f"<b>Nothing is playing right now.</b>\n"
                f"Use <code>/movie &lt;title&gt;</code> to start!",
                parse_mode=enums.ParseMode.HTML
            )
            return
        loop_count = queue_manager.get_loop(chat_id)
        loop_text = f"\n‣ <b>Lᴏᴏᴘ :</b> {loop_count}x remaining" if loop_count > 0 else ""
        await message.reply_text(
            _now_playing_card(song, "Now Playing",
                extra=f"‣ <b>Qᴜᴇᴜᴇ :</b> {queue_manager.get_length(chat_id)} titles{loop_text}"),
            reply_markup=get_rich_control_buttons(chat_id, is_paused=False, total_secs=song.duration_secs),
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML
        )

    @app.on_callback_query(filters.regex(r"^(help_|play_|vcplay_|about_|opt_)"))
    async def handle_callbacks(client: Client, callback_query: CallbackQuery):
        try:
            await callback_query.answer()
        except:
            pass
        chat_id  = callback_query.message.chat.id
        data     = callback_query.data
        print(f"[Callback] Controls click in chat {chat_id}: '{data}'")
        user     = callback_query.from_user
        username = user.first_name if user else "Someone"
        current  = queue_manager.get_current(chat_id)

        # Admin controls gate
        if (data.startswith("play_") or data.startswith("opt_")) and not data.startswith("play_close"):
            from core.db import check_user_play_permission, get_play_mode
            can_play, perm_err = await check_user_play_permission(client, chat_id, user)
            if not can_play:
                try:
                    await callback_query.answer("Aapko is group mein playback control karne ki permission nahi hai!", show_alert=True)
                except Exception:
                    pass
                return

            mode = get_play_mode(chat_id)
            if mode != "user" and current and getattr(current, "requester_id", 0) != 0:
                req_id = current.requester_id
                if user.id != req_id:
                    is_admin = False
                    try:
                        member = await client.get_chat_member(chat_id, user.id)
                        if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                            is_admin = True
                    except Exception:
                        pass
                    
                    if not is_admin:
                        try:
                            await callback_query.answer("Only the requester or an Admin can control playback!", show_alert=True)
                        except Exception:
                            pass
                        return

        # Help callback views
        if data.startswith("help_"):
            bot_name = Config.BOT_NAME
            bot_username = Config.BOT_USERNAME

            async def edit_msg(text, markup):
                try:
                    if callback_query.message.photo:
                        await callback_query.message.edit_caption(caption=text, reply_markup=markup, parse_mode=enums.ParseMode.HTML)
                    else:
                        await callback_query.message.edit_text(text, reply_markup=markup, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
                except Exception:
                    pass

            if data == "help_all":
                await callback_query.answer("Opening help menu...")
                await edit_msg(
                    f"{HEADER}"
                    f"Hᴇʟʟᴏ {username}!\n"
                    f"I ᴀᴍ <b>{bot_name}</b>, ᴀ ᴘʀᴇᴍɪᴜᴍ ʜɪɢʜ-ᴘᴇʀғᴏʀᴍᴀɴᴄᴇ ᴍᴏᴠɪᴇ sᴛʀᴇᴀᴍɪɴɢ ʙᴏᴛ.\n\n"
                    f"Usᴇ ᴛʜᴇ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ ᴛᴏ ᴇxᴘʟᴏʀᴇ ᴀʟʟ ᴄᴏᴍᴍᴀɴᴅs!",
                    help_menu_markup()
                )
                return
            elif data == "help_back" or data == "about_back":
                await callback_query.answer("Returning to main menu...")
                owner_id = Config.OWNER_ID or 6805412676
                owner_link = f"tg://user?id={owner_id}"
                start_markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("Aᴅᴅ Mᴇ Iɴ Yᴏᴜʀ Gʀᴏᴜᴘ", url=f"https://t.me/{bot_username}?startgroup=true", style="primary")],
                    [InlineKeyboardButton("Hᴇʟᴘ Aɴᴅ Cᴏᴍᴍᴀɴᴅs", callback_data="help_all", style="primary")],
                    [InlineKeyboardButton("Oᴡɴᴇʀ", url=owner_link, style="primary")]
                ])
                await edit_msg(
                    f"{HEADER}"
                    f"I Aᴍ Tʜᴇ Fᴀsᴛ Aɴᴅ PᴏᴡᴇʀFᴜʟ Mᴏᴠɪᴇ Pʟᴀʏᴇʀ Bᴏᴛ Wɪᴛʜ Sᴏᴍᴇ Aᴡᴇsᴏᴍᴇ Fᴇᴀᴛᴜʀᴇs.\n\n"
                    f"Cʟɪᴄᴋ Oɴ Tʜᴇ Hᴇʟᴘ Bᴜᴛᴛᴏɴ Tᴏ Gᴇᴛ Iɴғᴏʀᴍᴀᴛɪᴏɴ Aʙᴏᴜᴛ Mʏ Mᴏᴅᴜʟᴇs Aɴᴅ Cᴏᴍᴍᴀɴᴅs.",
                    start_markup
                )
                return

            elif data == "about_bot":
                await callback_query.answer("Opening About menu...")
                about_text = (
                    f"{HEADER}"
                    f"I ᴀᴍ <b>{bot_name}</b>, ᴀ ᴘʀᴇᴍɪᴜᴍ ʜɪɢʜ-ᴘᴇʀғᴏʀᴍᴀɴᴄᴇ ᴍᴏᴠɪᴇ & ᴛᴠ sᴇʀɪᴇs sᴛʀᴇᴀᴍɪɴɢ ʙᴏᴛ.\n\n"
                    f"<b><u>Cᴏʀᴇ Fᴇᴀᴛᴜʀᴇs & Cᴏᴍᴍᴀɴᴅs:</u></b>\n\n"
                    f"‣ <b>Mᴏᴠɪᴇs & Sᴇʀɪᴇs Sᴛʀᴇᴀᴍɪɴɢ:</b>\n"
                    f"• <code>/movie [name]</code> — Search & stream movies & TV shows in 4K/1080p.\n"
                    f"• <code>/trending</code> — View top trending blockbusters & series.\n"
                    f"• <code>/random</code> — Get a random Hindi dubbed blockbuster.\n"
                    f"• <code>/history</code> — Check group watch progress & resume history.\n"
                    f"• <code>/request [title]</code> — Request a movie or TV show from Admin.\n\n"
                    f"‣ <b>Pʟᴀʏʙᴀᴄᴋ Cᴏɴᴛʀᴏʟs:</b>\n"
                    f"• <code>/skip</code> | <code>/voteskip</code> — Skip current movie/episode.\n"
                    f"• <code>/stop</code> — Clear queue and leave VC.\n"
                    f"• <code>/pause</code> | <code>/resume</code> — Pause or resume stream.\n"
                    f"• <code>/current</code> — Show rich playback card.\n"
                    f"• <code>/loop [0-10]</code> — Set repeat loop count."
                )
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("Hᴇʟᴘ", callback_data="help_all", style="primary"),
                     InlineKeyboardButton("Hᴏᴍᴇ", callback_data="about_back", style="success")],
                    [InlineKeyboardButton("Cʟᴏsᴇ", callback_data="vcplay_close", style="danger")]
                ])
                await edit_msg(about_text, markup)
                return

            help_categories = {
                "help_user": {
                    "Title": "Usᴇʀ Cᴏᴍᴍᴀɴᴅs",
                    "Content": (
                        "<b><u>Mᴏᴠɪᴇ Sᴛʀᴇᴀᴍɪɴɢ:</u></b>\n"
                        "‣ <code>/movie [name]</code> — Films & series stream\n"
                        "‣ <code>/trending</code> — Top trending movies\n"
                        "‣ <code>/random</code> — Random Hindi blockbuster\n"
                        "‣ <code>/history</code> — Watch progress & history\n"
                        "‣ <code>/request [title]</code> — Request movie from admin\n\n"
                        "<b><u>Iɴғᴏ:</u></b>\n"
                        "‣ <code>/current</code> — Now playing card\n"
                        "‣ <code>/queue</code> — Upcoming queue list"
                    ),
                    "ExtraMarkup": True
                },
                "help_admin": {
                    "Title": "Aᴅᴍɪɴ Cᴏᴍᴍᴀɴᴅs",
                    "Content": (
                        "<b><u>Cᴏɴᴛʀᴏʟs:</u></b>\n"
                        "‣ <code>/skip</code> — Skip current track\n"
                        "‣ <code>/pause</code> / <code>/resume</code> — Toggle stream\n"
                        "‣ <code>/stop</code> — Stop playback & clear queue\n"
                        "‣ <code>/loop [0-10]</code> — Set repeat count\n"
                        "‣ <code>/voteskip</code> — Vote to skip"
                    )
                },
                "help_owner": {
                    "Title": "Oᴡɴᴇʀ Cᴏᴍᴍᴀɴᴅs",
                    "Content": (
                        "<b><u>Mᴀɴᴀɢᴇᴍᴇɴᴛ:</u></b>\n"
                        "‣ <code>/admin</code> — Admin panel (DM only)\n"
                        "‣ <code>/by</code> — Force-clear voice chat (Owner)"
                    )
                },
                "help_devs": {
                    "Title": "Aʙᴏᴜᴛ Tʜɪs Bᴏᴛ",
                    "Content": (
                        f"<b>{bot_name}</b>\n\n"
                        "A premium high-performance movie & TV series streaming bot.\n\n"
                        "<b>Fᴇᴀᴛᴜʀᴇs:</b>\n"
                        "‣ Pure GameOver VOD Cloud Engine\n"
                        "‣ 4K / 2K / 1080p Full HD Video\n"
                        "‣ 120 FPS / 90 FPS / 60 FPS Framerate Modes\n"
                        "‣ Movies & TV Series streaming\n"
                        "‣ Instant progress save & resume"
                    )
                },
                "help_clone": {
                    "Title": "Cʟᴏɴᴇ Yᴏᴜʀ Oᴡɴ Bᴏᴛ",
                    "Content": (
                        "<b>Create your own Movie & Series Streaming Bot in 1 minute!</b>\n\n"
                        "‣ <b>Zero Hosting Needed:</b> 100% cloud-hosted on our ultra-fast server.\n"
                        "‣ <b>Shared Cloud Engine:</b> Streams directly into group voice chats in 1080p Full HD.\n"
                        "‣ <b>Your Own Brand:</b> Your bot token, your name, your group!\n"
                        "‣ <b>Unlimited Movies & Series:</b> Search any title, choose language, stream anytime.\n"
                        "‣ <b>Easy Management:</b> Control playback with admin commands.\n\n"
                        "<b>How to Create:</b>\n"
                        "1. Go to @BotFather and create a new bot using <code>/newbot</code>.\n"
                        "2. Copy the <b>HTTP API Token</b> given by @BotFather.\n"
                        "3. Click <b>Cʀᴇᴀᴛᴇ Cʟᴏɴᴇ</b> button below to set up your bot instantly!"
                    ),
                    "CloneMarkup": True
                }
            }

            if data in help_categories:
                cat = help_categories[data]
                await callback_query.answer(cat["Title"])
                if cat.get("CloneMarkup"):
                    main_bot_user = Config.BOT_USERNAME or "Gameovermovie_bot"
                    clone_markup = InlineKeyboardMarkup([
                        [InlineKeyboardButton(
                            "Cʀᴇᴀᴛᴇ Cʟᴏɴᴇ",
                            url=f"https://t.me/{main_bot_user}?start=clone",
                            style="success"
                        )],
                        [InlineKeyboardButton("Hᴇʟᴘ", callback_data="help_all", style="primary"),
                         InlineKeyboardButton("Hᴏᴍᴇ", callback_data="help_back",  style="success")],
                        [InlineKeyboardButton("Cʟᴏsᴇ", callback_data="vcplay_close", style="danger")]
                    ])
                    await edit_msg(
                        f"{HEADER}"
                        f"<b>{cat['Title']}</b>\n\n{cat['Content']}",
                        clone_markup
                    )
                elif cat.get("ExtraMarkup"):
                    users_markup = InlineKeyboardMarkup([
                        [InlineKeyboardButton(
                            "Aᴅᴅ Bᴏᴛ Tᴏ Yᴏᴜʀ Gʀᴏᴜᴘ",
                            url=f"https://t.me/{bot_username}?startgroup=true",
                            style="primary"
                        )],
                        [InlineKeyboardButton("Hᴇʟᴘ", callback_data="help_all", style="primary"),
                         InlineKeyboardButton("Hᴏᴍᴇ", callback_data="help_back",  style="success")],
                        [InlineKeyboardButton("Cʟᴏsᴇ", callback_data="vcplay_close", style="danger")]
                    ])
                    await edit_msg(
                        f"{HEADER}"
                        f"<b>{cat['Title']}</b>\n\n{cat['Content']}\n\n"
                        f"<i>Bot ko apne group mein add karo aur wahan commands use karo!</i>",
                        users_markup
                    )
                else:
                    await edit_msg(
                        f"{HEADER}"
                        f"<b>{cat['Title']}</b>\n\n{cat['Content']}\n\n<i>Use the buttons below to go back.</i>",
                        back_help_markup()
                    )
            return

        # Player callbacks
        if data.startswith("play_seek_"):
            if not current:
                await callback_query.answer("Nothing is playing!", show_alert=True)
                return
            try:
                parts = data.split("_")
                seconds = int(parts[2])
                await callback_query.answer(f"Seeking {'+' if seconds > 0 else ''}{seconds}s...")
                await stream_manager.seek(chat_id, seconds)
                
                is_paused = chat_id in stream_manager.paused_time
                elapsed = stream_manager.get_elapsed_seconds(chat_id)
                total_sec = current.duration_secs if current and current.duration_secs else 0
                kb = get_rich_control_buttons(chat_id, is_paused=is_paused, played_secs=elapsed, total_secs=total_sec)
                caption = get_rich_caption(current, played_secs=elapsed)
                await edit_styled_caption(chat_id, callback_query.message.id, caption, kb)
            except Exception as e:
                print(f"[Controls] Seek callback error: {e}")
                await callback_query.answer("Seek failed", show_alert=True)
            return

        elif data.startswith("play_replay"):
            if not current:
                await callback_query.answer("Nothing is playing!", show_alert=True)
                return
            await callback_query.answer("Restarting from beginning...")
            await stream_manager.seek(chat_id, -999999)
            elapsed = 0
            is_paused = chat_id in stream_manager.paused_time
            total_sec = current.duration_secs if current and current.duration_secs else 0
            kb = get_rich_control_buttons(chat_id, is_paused=is_paused, played_secs=elapsed, total_secs=total_sec)
            caption = get_rich_caption(current, played_secs=elapsed)
            await edit_styled_caption(chat_id, callback_query.message.id, caption, kb)
            return

        elif data.startswith("play_progress"):
            if current:
                now = asyncio.get_event_loop().time()
                is_paused = chat_id in stream_manager.paused_time
                start = stream_manager.stream_start_time.get(chat_id, now)
                offset = stream_manager.current_seek_offset.get(chat_id, 0)
                elapsed = int((stream_manager.paused_time[chat_id] if is_paused else now) - start + offset)
                await callback_query.answer(f"Progress: {format_seconds(elapsed)} / {current.duration or 'VOD'}", show_alert=False)
            else:
                await callback_query.answer("Nothing is playing!", show_alert=False)
            return

        elif data.startswith("play_download_"):
            local_file = stream_manager.local_files.get(chat_id)
            if not local_file or not os.path.exists(local_file):
                await callback_query.answer("No active file found to download!", show_alert=True)
                return
                
            await callback_query.answer("Preparing download... Please wait.", show_alert=True)
            
            caption = f"‣ <b>Tɪᴛʟᴇ :</b> {current.title}\n‣ <b>Rᴇǫᴜᴇsᴛᴇᴅ Bʏ :</b> {username}"
            
            async def upload_task():
                try:
                    status_msg = await client.send_message(chat_id, "<i>Uploading file...</i>")
                    
                    last_edit_time = time.time()
                    async def progress_cb(current, total):
                        nonlocal last_edit_time
                        now = time.time()
                        if now - last_edit_time >= 4.0 or current == total:
                            last_edit_time = now
                            pct = int(current * 100 / total)
                            bar_len = 12
                            filled = min(bar_len, max(0, int((pct / 100) * bar_len)))
                            bar = "▰" * filled + "▱" * (bar_len - filled)
                            curr_mb = current / (1024 * 1024)
                            tot_mb = total / (1024 * 1024)
                            try:
                                await status_msg.edit_text(
                                    f"<b>Uploading file...</b>\n\n"
                                    f"<code>{bar} {pct}%</code>\n"
                                    f"‣ <b>Size :</b> <code>{curr_mb:.1f} MB / {tot_mb:.1f} MB</code>"
                                )
                            except Exception:
                                pass

                    await client.send_video(
                        chat_id=chat_id,
                        video=local_file,
                        caption=caption,
                        supports_streaming=True,
                        progress=progress_cb
                    )
                    await status_msg.delete()
                except Exception as upload_err:
                    print(f"[Controls] Download upload failed: {upload_err}")
                    try:
                        await client.send_message(chat_id, f"<b>Upload failed:</b> {upload_err}")
                    except:
                        pass
                        
            asyncio.create_task(upload_task())
            return

        elif data.startswith("play_skip") or data == "skip":
            if not queue_manager.is_playing(chat_id):
                await callback_query.answer("Nothing is playing!", show_alert=True)
                return

            await stream_manager.handle_vote_skip(
                chat_id=chat_id,
                user_id=user.id if user else 0,
                user_name=username,
                client=client,
                query=callback_query
            )

        elif data.startswith("play_stop") or data == "stop":
            await stream_manager.stop(chat_id)
            await callback_query.answer("Playback stopped.")
            try:
                if callback_query.message.photo:
                    await callback_query.message.edit_caption(
                        caption=f"{HEADER}<b>Playback stopped.</b>\n‣ Requested by: {username}\n‣ Queue cleared.",
                        parse_mode=enums.ParseMode.HTML
                    )
                else:
                    await callback_query.message.edit_text(
                        f"{HEADER}<b>Playback stopped.</b>\n‣ Requested by: {username}\n‣ Queue cleared.",
                        parse_mode=enums.ParseMode.HTML
                    )
            except Exception:
                pass

        elif data.startswith("play_pause") or data == "pause":
            if not current:
                await callback_query.answer("Nothing is playing!", show_alert=True)
                return
            
            is_paused = chat_id in stream_manager.paused_time
            if is_paused:
                success = await stream_manager.resume(chat_id)
                await callback_query.answer("Resumed" if success else "Failed")
                if success:
                    try:
                        elapsed = stream_manager.get_elapsed_seconds(chat_id)
                        total_sec = current.duration_secs if current and current.duration_secs else 0
                        kb = get_rich_control_buttons(chat_id, is_paused=False, played_secs=elapsed, total_secs=total_sec)
                        caption = get_rich_caption(current, played_secs=elapsed)
                        await edit_styled_caption(chat_id, callback_query.message.id, caption, kb)
                    except Exception:
                        pass
            else:
                success = await stream_manager.pause(chat_id)
                await callback_query.answer("Paused" if success else "Failed")
                if success:
                    try:
                        elapsed = stream_manager.get_elapsed_seconds(chat_id)
                        total_sec = current.duration_secs if current and current.duration_secs else 0
                        kb = get_rich_control_buttons(chat_id, is_paused=True, played_secs=elapsed, total_secs=total_sec)
                        caption = get_rich_caption(current, played_secs=elapsed)
                        await edit_styled_caption(chat_id, callback_query.message.id, caption, kb)
                    except Exception:
                        pass

        elif data.startswith("play_resume") or data == "resume":
            if not current:
                await callback_query.answer("Nothing is playing!", show_alert=True)
                return
            success = await stream_manager.resume(chat_id)
            await callback_query.answer("Resumed" if success else "Failed")
            if success:
                try:
                    elapsed = stream_manager.get_elapsed_seconds(chat_id)
                    total_sec = current.duration_secs if current and current.duration_secs else 0
                    kb = get_rich_control_buttons(chat_id, is_paused=False, played_secs=elapsed, total_secs=total_sec)
                    caption = get_rich_caption(current, played_secs=elapsed)
                    await edit_styled_caption(chat_id, callback_query.message.id, caption, kb)
                except Exception:
                    pass

        elif data.startswith("play_options_"):
            if not current:
                await callback_query.answer("Nothing is playing!", show_alert=True)
                return
            stream_manager.menu_active[chat_id] = True
            is_series = bool(getattr(current, "season", 0) or getattr(current, "episode", 0))
            opts_kb = get_options_menu_buttons(chat_id, is_series=is_series)
            elapsed = stream_manager.get_elapsed_seconds(chat_id)
            caption = get_rich_caption(current, played_secs=elapsed)
            await edit_styled_caption(chat_id, callback_query.message.id, caption, opts_kb)
            await callback_query.answer("Options panel opened.")
            return

        elif data.startswith("opt_back_"):
            stream_manager.menu_active[chat_id] = False
            if not current:
                await callback_query.answer("Nothing is playing!", show_alert=True)
                return
            elapsed = stream_manager.get_elapsed_seconds(chat_id)
            total_sec = current.duration_secs if current and current.duration_secs else 0
            is_paused = chat_id in stream_manager.paused_time
            main_kb = get_rich_control_buttons(chat_id, is_paused=is_paused, played_secs=elapsed, total_secs=total_sec)
            caption = get_rich_caption(current, played_secs=elapsed)
            await edit_styled_caption(chat_id, callback_query.message.id, caption, main_kb)
            await callback_query.answer("Returned to player.")
            return

        elif data.startswith("opt_seek_"):
            if not current:
                await callback_query.answer("Nothing is playing!", show_alert=True)
                return
            parts = data.split("_")
            seconds = int(parts[3])
            sign = "+" if seconds > 0 else ""
            await callback_query.answer(f"Seeking {sign}{seconds}s...")
            await stream_manager.seek(chat_id, seconds)
            
            is_series = bool(getattr(current, "season", 0) or getattr(current, "episode", 0))
            opts_kb = get_options_menu_buttons(chat_id, is_series=is_series)
            elapsed = stream_manager.get_elapsed_seconds(chat_id)
            caption = get_rich_caption(current, played_secs=elapsed)
            await edit_styled_caption(chat_id, callback_query.message.id, caption, opts_kb)
            return

        elif data.startswith("opt_restart_"):
            if not current:
                await callback_query.answer("Nothing is playing!", show_alert=True)
                return
            await callback_query.answer("Restarting from beginning...")
            await stream_manager.seek(chat_id, -999999)
            is_series = bool(getattr(current, "season", 0) or getattr(current, "episode", 0))
            opts_kb = get_options_menu_buttons(chat_id, is_series=is_series)
            caption = get_rich_caption(current, played_secs=0)
            await edit_styled_caption(chat_id, callback_query.message.id, caption, opts_kb)
            return

        elif data.startswith("opt_ep_"):
            if not current:
                await callback_query.answer("Nothing is playing!", show_alert=True)
                return
            from plugins.movies import vod_sessions, trigger_movie_playback, get_episode_panel
            session_data = vod_sessions.get(chat_id)
            if not session_data:
                await callback_query.answer("Series session expired. Use /movie to select episodes.", show_alert=True)
                return
            
            action_type = data.split("_")[2]  # prev, next, list
            curr_season = getattr(current, "season", session_data.get("chosen_season", 1))
            curr_ep = getattr(current, "episode", session_data.get("chosen_episode", 1))
            
            if action_type == "prev":
                if curr_ep <= 1:
                    await callback_query.answer("Already at Episode 1!", show_alert=True)
                    return
                target_ep = curr_ep - 1
                await callback_query.answer(f"Loading Episode {target_ep}...")
                stream_manager.menu_active[chat_id] = False
                
                try:
                    await callback_query.message.delete()
                except Exception:
                    pass
                    
                status_placeholder = await client.send_message(
                    chat_id,
                    f"<b>Lᴏᴀᴅɪɴɢ Eᴘɪsᴏᴅᴇ :</b> <code>{session_data.get('title', current.title)} S{curr_season}E{target_ep}</code>\n"
                    f"<i>Server se connect ho raha hai...</i>"
                )
                await trigger_movie_playback(status_placeholder, session_data, season=curr_season, episode=target_ep, is_next=True)
                return

            elif action_type == "next":
                target_ep = curr_ep + 1
                await callback_query.answer(f"Loading Episode {target_ep}...")
                stream_manager.menu_active[chat_id] = False
                
                try:
                    await callback_query.message.delete()
                except Exception:
                    pass
                    
                status_placeholder = await client.send_message(
                    chat_id,
                    f"<b>Lᴏᴀᴅɪɴɢ Nᴇxᴛ Eᴘɪsᴏᴅᴇ :</b> <code>{session_data.get('title', current.title)} S{curr_season}E{target_ep}</code>\n"
                    f"<i>Server se connect ho raha hai...</i>"
                )
                await trigger_movie_playback(status_placeholder, session_data, season=curr_season, episode=target_ep, is_next=True)
                return

            elif action_type == "list":
                await callback_query.answer("Opening episodes list...")
                ep_caption, ep_markup = get_episode_panel(session_data)
                try:
                    if callback_query.message.photo:
                        await callback_query.message.edit_caption(caption=ep_caption, reply_markup=ep_markup, parse_mode=enums.ParseMode.HTML)
                    else:
                        await callback_query.message.edit_text(text=ep_caption, reply_markup=ep_markup, parse_mode=enums.ParseMode.HTML)
                except Exception:
                    pass
                return

        elif data.startswith("opt_currlang_"):
            await callback_query.answer("Ye language pehle se hi chal rahi hai!", show_alert=True)
            return

        elif data.startswith("opt_lang_"):
            if not current:
                await callback_query.answer("Nothing is playing!", show_alert=True)
                return

            from plugins.movies import vod_sessions
            from core.vod_scraper import get_available_languages, Session
            import re

            stream_manager.menu_active[chat_id] = True
            session_data = vod_sessions.get(chat_id)
            clean_title = getattr(current, "clean_title", current.title)
            clean_title = re.sub(r'\[.*?\]', '', clean_title).strip()
            clean_title = re.sub(r'\s+S\d+(-S\d+)?', '', clean_title, flags=re.IGNORECASE).strip()

            if not session_data:
                vod_sessions[chat_id] = {
                    "chat_id": chat_id,
                    "title": clean_title,
                    "session": Session(),
                    "chosen_lang": "hi" if "hindi" in current.title.lower() else "en",
                    "chosen_season": getattr(current, "season", 1),
                    "chosen_episode": getattr(current, "episode", 1),
                    "requester_id": callback_query.from_user.id if callback_query.from_user else 0,
                    "requester_name": callback_query.from_user.first_name if callback_query.from_user else "User",
                }
                session_data = vod_sessions[chat_id]
            else:
                session_data["chat_id"] = chat_id

            current_code = session_data.get("chosen_lang", "hi" if "hindi" in current.title.lower() else "en")
            
            avail = session_data.get("available_langs")
            if not avail:
                await callback_query.answer("Checking available languages...")
                is_series = bool(getattr(current, "season", 0) or getattr(current, "episode", 0))
                avail = await get_available_languages(session_data["session"], clean_title, is_series=is_series)
                session_data["available_langs"] = avail
            else:
                await callback_query.answer()

            # Ensure current language item exists in options
            if not any(x["code"] == current_code for x in avail):
                curr_lbl = "Hindi" if current_code == "hi" else ("English" if current_code == "en" else "Original")
                curr_item = session_data.get("current_item")
                if curr_item:
                    avail.insert(0, {"code": current_code, "name": curr_lbl, "item": curr_item, "title": current.title})

            curr_name = "Hindi" if current_code == "hi" else ("English" if current_code == "en" else "Original")
            for l in avail:
                if l["code"] == current_code:
                    curr_name = l["name"]
                    break

            caption = (
                f"{HEADER}"
                f"‣ <b>Tɪᴛʟᴇ :</b> <b>{clean_title}</b>\n"
                f"‣ <b>Cᴜʀʀᴇɴᴛ Lᴀɴɢᴜᴀɢᴇ :</b> <code>{curr_name}</code>\n\n"
                f"Neeche se apni preferred <b>Lᴀɴɢᴜᴀɢᴇ</b> select karein:"
            )
            lang_kb = get_language_menu_buttons(chat_id, avail, current_code)
            await edit_styled_caption(chat_id, callback_query.message.id, caption, lang_kb)
            return

        elif data.startswith("opt_setlang_"):
            if not current:
                await callback_query.answer("Nothing is playing!", show_alert=True)
                return

            parts = data.split("_")
            target_code = parts[3]

            from plugins.movies import vod_sessions, trigger_movie_playback, get_season_panel
            from core.vod_scraper import get_available_languages, Session
            import re

            session_data = vod_sessions.get(chat_id)
            if not session_data:
                clean_title = getattr(current, "clean_title", current.title)
                clean_title = re.sub(r'\[.*?\]', '', clean_title).strip()
                clean_title = re.sub(r'\s+S\d+(-S\d+)?', '', clean_title, flags=re.IGNORECASE).strip()
                session_data = {
                    "chat_id": chat_id,
                    "title": clean_title,
                    "session": Session(),
                    "chosen_lang": "hi" if "hindi" in current.title.lower() else "en",
                    "chosen_season": getattr(current, "season", 1),
                    "chosen_episode": getattr(current, "episode", 1),
                    "requester_id": callback_query.from_user.id if callback_query.from_user else 0,
                    "requester_name": callback_query.from_user.first_name if callback_query.from_user else "User",
                }
                vod_sessions[chat_id] = session_data

            session_data["chat_id"] = chat_id
            avail = session_data.get("available_langs", [])
            if not avail:
                is_ser = bool(getattr(current, "season", 0) or getattr(current, "episode", 0))
                clean_title = session_data.get("title", current.title)
                avail = await get_available_languages(session_data["session"], clean_title, is_series=is_ser)
                session_data["available_langs"] = avail

            target_info = next((x for x in avail if x["code"] == target_code), None)
            if not target_info:
                await callback_query.answer("Language details not found. Please try again.", show_alert=True)
                return

            target_name = target_info["name"]
            target_item = target_info["item"]

            is_series = bool(getattr(current, "season", 0) or getattr(current, "episode", 0)) or (
                getattr(target_item, "subjectType", None) == SubjectType.TV_SERIES or int(getattr(target_item, "subjectType", 1)) == 2
            )

            # Update session details
            session_data["current_item"] = target_item
            session_data["chosen_lang"] = target_code
            session_data["chosen_lang_name"] = target_name
            session_data["requester_id"] = callback_query.from_user.id if callback_query.from_user else 0
            session_data["requester_name"] = callback_query.from_user.first_name if callback_query.from_user else "User"

            if is_series:
                await callback_query.answer(f"Fetching {target_name} seasons...")
                from core.vod_scraper import fetch_tv_details
                details = await fetch_tv_details(session_data["session"], target_item)
                target_seasons = details.resource.seasons if (details and details.resource and details.resource.seasons) else []
                session_data["seasons"] = target_seasons

                if target_seasons:
                    # Keep menu_active True so live_ui_updater won't overwrite the season panel
                    stream_manager.menu_active[chat_id] = True
                    caption, keyboard = await get_season_panel(session_data)
                    await edit_styled_caption(chat_id, callback_query.message.id, caption, keyboard)
                    return
                else:
                    # Fallback to direct play if seasons list empty
                    stream_manager.menu_active[chat_id] = False
                    status_placeholder = await client.send_message(
                        chat_id,
                        f"{HEADER}<b>Sᴡɪᴛᴄʜɪɴɢ Lᴀɴɢᴜᴀɢᴇ :</b> <code>{session_data.get('title', current.title)} [{target_name}]</code>\n"
                        f"<i>Downloading {target_name} stream...</i>"
                    )
                    await trigger_movie_playback(status_placeholder, session_data, season=1, episode=1, replace_stream=True)
                    return
            else:
                # Movies: cut old stream, download new language stream, resume seamlessly at exact played timestamp
                await callback_query.answer(f"Switching language to {target_name}...")
                played_secs = int(stream_manager.get_elapsed_seconds(chat_id))
                stream_manager.menu_active[chat_id] = False

                clean_display_title = session_data.get("title", current.title)
                status_placeholder = await client.send_message(
                    chat_id,
                    f"{HEADER}<b>Sᴡɪᴛᴄʜɪɴɢ Lᴀɴɢᴜᴀɢᴇ :</b> <code>{clean_display_title} [{target_name}]</code>\n"
                    f"<i>Downloading {target_name} audio stream...</i>"
                )
                try:
                    await callback_query.message.delete()
                except Exception:
                    pass

                await trigger_movie_playback(
                    status_placeholder,
                    session_data,
                    season=0,
                    episode=0,
                    replace_stream=True,
                    force_seek=played_secs
                )
                return

        elif data == "vcplay_close" or data.startswith("play_close"):
            stream_manager.menu_active.pop(chat_id, None)
            await callback_query.answer("Closing...")
            try:
                await callback_query.message.delete()
            except Exception:
                pass

