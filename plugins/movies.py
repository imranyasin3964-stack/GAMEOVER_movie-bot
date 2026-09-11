"""
MOVIES Engine — Video-On-Demand (VOD) Plugin
Provides interactive /movie search, season/episode choice, and buttonless auto-play.
Integrates our high-performance local caching & garbage collection engine.
"""

import os
import re
import time
import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from config import Config
from core.queue_manager import queue_manager, SongInfo
from core.player import (
    stream_manager, STAR, SKIP, QUEUE, CLOCK, LINK, USER, WARN, INFO, WAVE
)
from core.vod_scraper import (
    Session,
    search_vod,
    search_hindi_version,
    search_english_version,
    fetch_tv_details,
    resolve_stream_link,
    SubjectType,
)
from moviebox_api.v2.models import SearchResultsItem
from core.trending_manager import get_trending_list

# Global Video-On-Demand sessions tracker
vod_sessions: dict[int, dict] = {}

from core.fonts import HEADER, BULLET, to_small_caps
ROYAL_HEADER = HEADER


async def safe_edit(message, text, reply_markup=None):
    try:
        from core.player import edit_styled_text
        if hasattr(message, "chat"):
            chat_id = message.chat.id
            message_id = message.id
        elif isinstance(message, tuple):
            chat_id, message_id = message
        elif hasattr(message, "message") and hasattr(message.message, "chat"):
            chat_id = message.message.chat.id
            message_id = message.message.id
        else:
            return message
            
        await edit_styled_text(chat_id, message_id, text, reply_markup)
        return message
    except Exception as e:
        print(f"[safe_edit] Error: {e}")


def chunk_buttons(buttons, n):
    return [buttons[i:i + n] for i in range(0, len(buttons), n)]


def get_search_results_panel(session_data):
    query_text = session_data.get("base_query") or session_data.get("query", "")
    items = session_data.get("search_results", [])
    allowed_uid = session_data.get("requester_id", 0)
    
    caption_lines = [
        HEADER.strip(),
        "",
        f"‣ <b>Sᴇᴀʀᴄʜ Rᴇsᴜʟᴛs :</b> <code>{query_text}</code>",
        "<i>Neeche diye gaye number par click karke select karein:</i>",
        ""
    ]

    buttons = []
    for idx, itm in enumerate(items[:6], 1):
        is_ser = itm.subjectType == SubjectType.TV_SERIES or int(getattr(itm, "subjectType", 1)) == 2
        type_name = "Series" if is_ser else "Movie"
        
        t_lower = itm.title.lower()
        if "hindi" in t_lower:
            lang_badge = " <code>[HINDI]</code>"
            btn_tag = "[Hɪɴᴅɪ] "
        elif "english" in t_lower:
            lang_badge = " <code>[ENG]</code>"
            btn_tag = "[Eɴɢ] "
        else:
            lang_badge = ""
            btn_tag = f"[{'Sᴇʀɪᴇs' if is_ser else 'Mᴏᴠɪᴇ'}] "
        
        s_match = re.search(r'\bS\d+(-S\d+)?\b', itm.title, re.IGNORECASE)
        season_str = f" ({s_match.group(0).upper()})" if s_match else ""

        clean_name = re.sub(r'\[.*?\]', '', itm.title).strip()
        clean_name = re.sub(r'\s+S\d+(-S\d+)?', '', clean_name, flags=re.IGNORECASE).strip()
        clean_name = clean_name.title()
        
        caption_lines.append(f"<b>{idx}.</b> {clean_name}{lang_badge}{season_str} • <i>{type_name}</i>")
        
        if len(clean_name) > 14:
            btn_short = clean_name[:13].strip() + "…"
        else:
            btn_short = clean_name
        
        btn_label = f"{idx}. {btn_tag}{btn_short}"
        buttons.append([
            InlineKeyboardButton(
                btn_label,
                callback_data=f"VOD|select|{allowed_uid}|{itm.subjectId}",
                style="primary"
            )
        ])

    buttons.append([InlineKeyboardButton("Cʟᴏsᴇ", callback_data="vcplay_close", style="danger")])
    caption = "\n".join(caption_lines)
    return caption, InlineKeyboardMarkup(buttons)


async def get_season_panel(session_data):
    clean_title = session_data.get("title", "")
    allowed_uid = session_data.get("requester_id", 0)
    raw_seasons = session_data.get("seasons", [])
    seasons = sorted(raw_seasons, key=lambda s: getattr(s, "se", 0))
    
    lang_name = session_data.get("chosen_lang_name")
    if not lang_name:
        chosen_code = session_data.get("chosen_lang", "hi")
        if chosen_code == "hi" or "hindi" in getattr(session_data.get("current_item"), "title", "").lower():
            lang_name = "Hindi"
        elif chosen_code == "ja" or "japanese" in getattr(session_data.get("current_item"), "title", "").lower():
            lang_name = "Japanese"
        elif chosen_code == "en" or "english" in getattr(session_data.get("current_item"), "title", "").lower():
            lang_name = "English"
        else:
            lang_name = chosen_code.upper()
    display_title = f"{clean_title} [{lang_name}]"
    
    caption = (
        f"{HEADER}"
        f"‣ <b>Tɪᴛʟᴇ :</b> <b>{display_title}</b>\n"
        f"‣ <b>Tᴏᴛᴀʟ Sᴇᴀsᴏɴs :</b> <code>{len(seasons)}</code>\n\n"
        "Watch karne ke liye neeche se <b>Season</b> select karein:"
    )
    
    buttons = []
    for s in seasons:
        buttons.append(
            InlineKeyboardButton(f"Sᴇᴀsᴏɴ {s.se}", callback_data=f"VOD|season|{allowed_uid}|{s.se}", style="primary")
        )
        
    rows = chunk_buttons(buttons, 3)
    chat_id = session_data.get("chat_id", 0)
    back_row = []
    if session_data.get("search_results") and len(session_data.get("search_results", [])) > 1:
        back_row.append(InlineKeyboardButton("◀ Bᴀᴄᴋ", callback_data=f"VOD|back_to_results|{allowed_uid}", style="primary"))
    elif session_data.get("available_langs"):
        back_row.append(InlineKeyboardButton("◀ Bᴀᴄᴋ", callback_data=f"opt_lang_{chat_id}", style="primary"))
    back_row.append(InlineKeyboardButton("Cʟᴏsᴇ", callback_data="vcplay_close", style="danger"))
    rows.append(back_row)
    return caption, InlineKeyboardMarkup(rows)


def get_episode_panel(session_data):
    clean_title = session_data.get("title", "")
    allowed_uid = session_data.get("requester_id", 0)
    season_num = session_data.get("chosen_season", 1)
    seasons = session_data.get("seasons", [])
    
    lang_name = session_data.get("chosen_lang_name")
    if not lang_name:
        chosen_code = session_data.get("chosen_lang", "hi")
        if chosen_code == "hi" or "hindi" in getattr(session_data.get("current_item"), "title", "").lower():
            lang_name = "Hindi"
        elif chosen_code == "ja" or "japanese" in getattr(session_data.get("current_item"), "title", "").lower():
            lang_name = "Japanese"
        elif chosen_code == "en" or "english" in getattr(session_data.get("current_item"), "title", "").lower():
            lang_name = "English"
        else:
            lang_name = chosen_code.upper()
    display_title = f"{clean_title} [{lang_name}]"
    
    max_ep = 1
    for s in seasons:
        if s.se == season_num:
            max_ep = s.maxEp
            break
            
    caption = (
        f"{HEADER}"
        f"‣ <b>Tɪᴛʟᴇ :</b> <b>{display_title}</b>\n"
        f"‣ <b>Sᴇᴀsᴏɴ :</b> <code>{season_num}</code> (Total Episodes: <code>{max_ep}</code>)\n\n"
        "Watch karne ke liye neeche se <b>Episode</b> select karein:"
    )
    
    buttons = []
    for ep in range(1, max_ep + 1):
        buttons.append(
            InlineKeyboardButton(f"Eᴘ {ep}", callback_data=f"VOD|episode|{allowed_uid}|{ep}", style="primary")
        )
        
    rows = chunk_buttons(buttons, 5)
    rows.append([
        InlineKeyboardButton("◀ Bᴀᴄᴋ Tᴏ Sᴇᴀsᴏɴs", callback_data=f"VOD|back_to_seasons|{allowed_uid}", style="primary"),
        InlineKeyboardButton("Cʟᴏsᴇ", callback_data="vcplay_close", style="danger")
    ])
    return caption, InlineKeyboardMarkup(rows)


def get_language_panel(session_data: dict) -> tuple:
    """
    Render language selection panel with episode counts.
    Same small-caps font, no emojis, clean single-column button boxes.
    Format:
      ‣ Tɪᴛʟᴇ : Bleach

      Lᴀɴɢᴜᴀɢᴇ Sᴇʟᴇᴄᴛ Kᴀʀᴇɪɴ
      Neeche se apni pasand ki language select karein:

      [ Hɪɴᴅɪ — 56 Eᴘ ]   (Green)
      [ Eɴɢʟɪsʜ — 300 Eᴘ ] (Blue)
      [ Jᴀᴘᴀɴᴇsᴇ — 80 Eᴘ ] (Blue)
      [ Cʟᴏsᴇ ]           (Red)
    """
    clean_title = session_data.get("title", "")
    allowed_uid = session_data.get("requester_id", 0)
    available_langs = session_data.get("available_langs", [])

    caption = (
        f"{HEADER}"
        f"‣ <b>Tɪᴛʟᴇ :</b> <b>{clean_title}</b>\n\n"
        f"<b>Lᴀɴɢᴜᴀɢᴇ Sᴇʟᴇᴄᴛ Kᴀʀᴇɪɴ</b>\n"
        f"<i>Neeche se apni pasand ki language select karein:</i>"
    )

    buttons = []
    for lang_info in available_langs:
        code = lang_info.get("code", "en")
        name = lang_info.get("name", "Unknown")
        ep_count = lang_info.get("ep_count", 0)
        subject_id = getattr(lang_info.get("item"), "subjectId", "")

        name_small = {
            "Hindi": "Hɪɴᴅɪ",
            "English": "Eɴɢʟɪsʜ",
            "Japanese": "Jᴀᴘᴀɴᴇsᴇ",
            "Korean": "Kᴏʀᴇᴀɴ",
            "Spanish": "Sᴘᴀɴɪsʜ",
            "Russian": "Rᴜssɪᴀɴ",
            "Tamil": "Tᴀᴍɪʟ",
            "Telugu": "Tᴇʟᴜɢᴜ",
            "Original": "Oʀɪɢɪɴᴀʟ",
        }.get(name, name.upper())

        ep_str = f" — {ep_count} Eᴘ" if ep_count and ep_count > 0 else ""
        btn_label = f"{name_small}{ep_str}"
        btn_style = "success" if code == "hi" else "primary"

        buttons.append([
            InlineKeyboardButton(
                btn_label,
                callback_data=f"VODLANG|{code}|{subject_id}|{allowed_uid}",
                style=btn_style
            )
        ])

    buttons.append([InlineKeyboardButton("Cʟᴏsᴇ", callback_data="vcplay_close", style="danger")])
    return caption, InlineKeyboardMarkup(buttons)


async def select_vod_item(chat_id: int, item: SearchResultsItem, status_msg, user_id: int):
    session_data = vod_sessions.get(chat_id)
    if not session_data:
        return
        
    session_data["current_item"] = item
    session_data["chosen_lang"] = "hi" if "hindi" in item.title.lower() else "en"
    clean_title = re.sub(r'\[.*?\]', '', item.title).strip()
    clean_title = re.sub(r'\s+S\d+(-S\d+)?', '', clean_title, flags=re.IGNORECASE).strip()
    clean_title = clean_title.title()
    session_data["title"] = clean_title
        
    is_series = session_data["current_item"].subjectType == SubjectType.TV_SERIES or int(getattr(session_data["current_item"], "subjectType", 1)) == 2
    
    # Check if multiple languages are available for this series
    if not session_data.get("available_langs"):
        try:
            from core.vod_scraper import get_available_languages
            available_langs = await get_available_languages(
                session_data["session"],
                clean_title,
                is_series=is_series,
                existing_items=session_data.get("search_results")
            )
            if available_langs and len(available_langs) > 1:
                session_data["available_langs"] = available_langs
                caption, keyboard = get_language_panel(session_data)
                await safe_edit(status_msg, caption, keyboard)
                return
            elif available_langs and len(available_langs) == 1:
                session_data["available_langs"] = available_langs
                if available_langs[0].get("seasons"):
                    session_data["seasons"] = available_langs[0]["seasons"]
        except Exception as e:
            print(f"[MOVIES Engine] select_vod_item lang detect note: {e}")

    if is_series:
        if session_data.get("seasons"):
            caption, keyboard = await get_season_panel(session_data)
            await safe_edit(status_msg, caption, keyboard)
            return

        await safe_edit(
            status_msg,
            f"{HEADER}‣ <b>Tɪᴛʟᴇ :</b> <b>{clean_title}</b>\n\n<i>Lᴏᴀᴅɪɴɢ Sᴇᴀsᴏɴs, ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ...</i>"
        )
        try:
            from core.vod_scraper import fetch_tv_details
            details = await fetch_tv_details(session_data["session"], session_data["current_item"])
            if details and details.resource and details.resource.seasons:
                session_data["seasons"] = sorted(details.resource.seasons, key=lambda s: getattr(s, 'se', 0))
                caption, keyboard = await get_season_panel(session_data)
                await safe_edit(status_msg, caption, keyboard)
                return
            else:
                print(f"[MOVIES Engine] No seasons found in tv_details for {clean_title}")
                await safe_edit(
                    status_msg,
                    f"{HEADER}‣ <b>Tɪᴛʟᴇ :</b> <b>{clean_title}</b>\n\n<b>Notice :</b> <i>Is series ke seasons load nahi ho sake. Kripya doosra option select karein.</i>",
                    InlineKeyboardMarkup([[InlineKeyboardButton("◀ Bᴀᴄᴋ Tᴏ Rᴇsᴜʟᴛs", callback_data=f"VOD|back_to_results|{user_id}", style="primary")]])
                )
                return
        except Exception as e:
            print(f"[MOVIES Engine] Error fetching TV details: {e}")
            await safe_edit(
                status_msg,
                f"{HEADER}‣ <b>Tɪᴛʟᴇ :</b> <b>{clean_title}</b>\n\n<b>Error :</b> <code>{e}</code>",
                InlineKeyboardMarkup([[InlineKeyboardButton("◀ Bᴀᴄᴋ Tᴏ Rᴇsᴜʟᴛs", callback_data=f"VOD|back_to_results|{user_id}", style="primary")]])
            )
            return

    # Direct movie playback without redundant intermediate screen
    await trigger_movie_playback(status_msg, session_data, season=0, episode=0)


async def show_loading_animation(chat_id: int, base_text: str, client=None) -> tuple:
    """Sends a fast loading message using pyrogram native client for instant response."""
    try:
        # Try pyrogram native first — fastest
        from bot import bot as _bot_client
        _client = client or _bot_client
        sent = await _client.send_message(
            chat_id=chat_id,
            text=f"{HEADER}<b>{base_text}...</b>",
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True
        )
        return (chat_id, sent.id)
    except Exception as e:
        print(f"[show_loading_animation] pyrogram failed: {e}, trying aiohttp...")
        try:
            from bot import send_styled
            msg_data = await send_styled(
                chat_id=chat_id,
                text=f"{HEADER}<b>{base_text}...</b>"
            )
            msg_id = msg_data.get("result", {}).get("message_id")
            return (chat_id, msg_id)
        except Exception as e2:
            print(f"[show_loading_animation] aiohttp also failed: {e2}")
            return (chat_id, None)



async def get_trending_movies_panel(allowed_uid: int) -> tuple:
    items = await get_trending_list("trending_movies")
    caption = (
        f"{HEADER}"
        f"<b>Tᴏᴘ Tʀᴇɴᴅɪɴɢ Mᴏᴠɪᴇs</b>\n"
        f"<i>Tap on a command to copy and search:</i>\n\n"
    )
    
    if not items:
        caption += "<i>No trending movies found.</i>"
    else:
        for idx, item in enumerate(items, 1):
            h_tag = " [Hindi Dubbed]" if item["has_hindi"] else ""
            caption += (
                f"{idx}. <b>{item['title']}</b> ({item['release_date']}) - Rating: {item['rating']}{h_tag}\n"
                f"   ‣ <code>/movie {item['title']}</code>\n\n"
            )
            
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Sʜᴏᴡ Sᴇʀɪᴇs", callback_data=f"VOD|trend_series|{allowed_uid}", style="primary"),
            InlineKeyboardButton("Hɪɴᴅɪ Oɴʟʏ", callback_data=f"VOD|trend_hindi|{allowed_uid}", style="success")
        ],
        [
            InlineKeyboardButton("Cʟᴏsᴇ", callback_data=f"VOD|trend_close|{allowed_uid}", style="danger")
        ]
    ])
    return caption, keyboard


async def get_trending_series_panel(allowed_uid: int) -> tuple:
    items = await get_trending_list("trending_series")
    caption = (
        f"{HEADER}"
        f"<b>Tᴏᴘ Tʀᴇɴᴅɪɴɢ Sᴇʀɪᴇs</b>\n"
        f"<i>Tap on a command to copy and search:</i>\n\n"
    )
    
    if not items:
        caption += "<i>No trending series found.</i>"
    else:
        for idx, item in enumerate(items, 1):
            h_tag = " [Hindi Dubbed]" if item["has_hindi"] else ""
            caption += (
                f"{idx}. <b>{item['title']}</b> ({item['release_date']}) - Rating: {item['rating']}{h_tag}\n"
                f"   ‣ <code>/movie {item['title']}</code>\n\n"
            )
            
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Sʜᴏᴡ Mᴏᴠɪᴇs", callback_data=f"VOD|trend_movies|{allowed_uid}", style="primary"),
            InlineKeyboardButton("Hɪɴᴅɪ Oɴʟʏ", callback_data=f"VOD|trend_hindi|{allowed_uid}", style="success")
        ],
        [
            InlineKeyboardButton("Cʟᴏsᴇ", callback_data=f"VOD|trend_close|{allowed_uid}", style="danger")
        ]
    ])
    return caption, keyboard


async def get_trending_hindi_panel(allowed_uid: int) -> tuple:
    movies = await get_trending_list("trending_movies")
    series = await get_trending_list("trending_series")
    
    hindi_items = []
    for m in movies:
        if m["has_hindi"]:
            hindi_items.append((m, "Movie"))
    for s in series:
        if s["has_hindi"]:
            hindi_items.append((s, "Series"))
            
    caption = (
        f"{HEADER}"
        f"<b>Hɪɴᴅɪ Dᴜʙʙᴇᴅ Tʀᴇɴᴅɪɴɢ</b>\n"
        f"<i>Tap on a command to copy and search:</i>\n\n"
    )
    
    if not hindi_items:
        caption += "<i>No Hindi dubbed trending titles found.</i>"
    else:
        for idx, (item, type_lbl) in enumerate(hindi_items, 1):
            caption += (
                f"{idx}. [{type_lbl}] <b>{item['title']}</b> ({item['release_date']}) - Rating: {item['rating']}\n"
                f"   ‣ <code>/movie {item['title']}</code>\n\n"
            )
            
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Sʜᴏᴡ Mᴏᴠɪᴇs", callback_data=f"VOD|trend_movies|{allowed_uid}", style="primary"),
            InlineKeyboardButton("Sʜᴏᴡ Sᴇʀɪᴇs", callback_data=f"VOD|trend_series|{allowed_uid}", style="primary")
        ],
        [
            InlineKeyboardButton("Cʟᴏsᴇ", callback_data=f"VOD|trend_close|{allowed_uid}", style="danger")
        ]
    ])
    return caption, keyboard


def register(app: Client):

    @app.on_message(filters.command(["trending", "latest"]) & filters.group)
    async def trending_command(client: Client, message: Message):
        chat_id = message.chat.id
        from core.db import is_group_bot_active
        if not is_group_bot_active(chat_id):
            return
        user = message.from_user
        user_id = user.id if user else 0
        print(f"[MOVIES Engine] Trending command triggered by user {user_id} in chat {chat_id}")
        status_msg = await show_loading_animation(chat_id, "Fetching Trending List")
        try:
            caption, keyboard = await get_trending_movies_panel(user_id)
            await safe_edit(status_msg, caption, keyboard)
        except Exception as e:
            print(f"[MOVIES Engine] Trending command error: {e}")
            await safe_edit(status_msg, f"{HEADER}<b>Error:</b> <code>{str(e)}</code>")

    @app.on_message(filters.command("random") & filters.group)
    async def random_command(client: Client, message: Message):
        chat_id = message.chat.id
        from core.db import is_group_bot_active
        if not is_group_bot_active(chat_id):
            return
        user = message.from_user
        user_id = user.id if user else 0
        print(f"[MOVIES Engine] Random command triggered by user {user_id} in chat {chat_id}")
        status_msg = await show_loading_animation(chat_id, "Shuffling movie database")
        try:
            from core.random_manager import get_random_hindi_title
            res = await get_random_hindi_title()
            if not res:
                await safe_edit(status_msg, f"{HEADER}<b>Humein koi random movie nahi mili! Please dobara try karein.</b>")
                return
            vod_sessions[chat_id] = {
                "query": res["title"],
                "requester_id": user_id,
                "requester_name": user.first_name if user and user.first_name else str(user_id),
                "search_results": [res["item"]],
                "session": res["session"],
                "seasons": [],
                "chosen_season": 1,
                "chosen_episode": 1,
                "current_item": res["item"],
                "chosen_lang": "hi",
                "title": res["title"]
            }
            m_type = "Series" if res["is_series"] else "Movie"
            caption = (
                f"{HEADER}"
                f"<b>Sᴜʀᴘʀɪsᴇ Vɪᴅᴇᴏ Fᴏʀ Yᴏᴜ!</b>\n"
                f"<i>Aapke liye ek random blockbuster select ki gayi hai:</i>\n\n"
                f"‣ <b>Tɪᴛʟᴇ :</b> <b>{res['title']}</b> ({res['year']}) - Rating: {res['rating']}\n"
                f"‣ <b>Tʏᴘᴇ :</b> {m_type}\n"
                f"‣ <b>Lᴀɴɢᴜᴀɢᴇ :</b> Hindi Dubbed\n\n"
                f"<i>Neeche play button click karke video chat mein instant stream chalu karein:</i>"
            )
            if res["is_series"]:
                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("Sᴇʟᴇᴄᴛ Sᴇᴀsᴏɴ", callback_data=f"VOD|select|{user_id}|{res['item'].subjectId}", style="success"),
                        InlineKeyboardButton("Cʟᴏsᴇ", callback_data=f"VOD|trend_close|{user_id}", style="danger")
                    ]
                ])
            else:
                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("Pʟᴀʏ Mᴏᴠɪᴇ", callback_data=f"VOD|play_movie|{user_id}", style="success"),
                        InlineKeyboardButton("Cʟᴏsᴇ", callback_data=f"VOD|trend_close|{user_id}", style="danger")
                    ]
                ])
            await safe_edit(status_msg, caption, keyboard)
        except Exception as e:
            print(f"[MOVIES Engine] Random command error: {e}")
            await safe_edit(status_msg, f"{HEADER}<b>Error:</b> <code>{str(e)}</code>")

    @app.on_message(filters.command("history") & filters.group)
    async def history_command(client: Client, message: Message):
        chat_id = message.chat.id
        from core.db import is_group_bot_active
        if not is_group_bot_active(chat_id):
            return
        user = message.from_user
        user_id = user.id if user else 0
        print(f"[MOVIES Engine] History command triggered by user {user_id} in chat {chat_id}")
        status_msg = await show_loading_animation(chat_id, "Fetching watch history")
        try:
            from core.db import get_chat_vod_history
            items = get_chat_vod_history(chat_id)
            caption = (
                f"{HEADER}"
                f"<b>Pʟᴀʏʙᴀᴄᴋ Hɪsᴛᴏʀʏ</b>\n"
                f"<i>Aapki chat ki recent movies aur saved progress ki list:</i>\n\n"
            )
            if not items:
                caption += "<i>Is chat ki abhi koi watch history nahi mili.</i>"
            else:
                def format_time(secs: int) -> str:
                    h = secs // 3600
                    m = (secs % 3600) // 60
                    s = secs % 60
                    return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

                for idx, item in enumerate(items, 1):
                    time_str = format_time(item["progress_seconds"])
                    suffix = f" S{item['season']}E{item['episode']}" if item["season"] > 0 else ""
                    caption += (
                        f"{idx}. <b>{item['title']}{suffix}</b>\n"
                        f"   ‣ <b>Position:</b> <code>{time_str}</code>\n"
                        f"   ‣ <code>/movie {item['title']}</code>\n\n"
                    )
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Cʟᴏsᴇ", callback_data=f"VOD|trend_close|{user_id}", style="danger")
                ]
            ])
            await safe_edit(status_msg, caption, keyboard)
        except Exception as e:
            print(f"[MOVIES Engine] History command error: {e}")
            await safe_edit(status_msg, f"{HEADER}<b>Error:</b> <code>{str(e)}</code>")

    @app.on_message(filters.command("request") & filters.group)
    async def request_command(client: Client, message: Message):
        chat_id = message.chat.id
        from core.db import is_group_bot_active
        if not is_group_bot_active(chat_id):
            return
        user = message.from_user
        user_id = user.id if user else 0
        if len(message.command) < 2:
            await message.reply_text(
                f"{HEADER}"
                "<b>Aapne movie ya series ka naam nahi likha!</b>\n"
                "Example: `/request The Boys Season 4`",
                parse_mode=enums.ParseMode.HTML
            )
            return
        movie_name = " ".join(message.command[1:])
        chat_title = message.chat.title if message.chat.title else "Private Message"
        try:
            from core.db import add_movie_request
            req_id = add_movie_request(
                user_id=user_id,
                username=user.username if user and user.username else "",
                first_name=user.first_name if user and user.first_name else "",
                chat_id=chat_id,
                chat_title=chat_title,
                movie_name=movie_name
            )
            owner_id = Config.OWNER_ID or 6805412676
            alert_caption = (
                f"{HEADER}"
                f"<b>Nᴇᴡ Mᴏᴠɪᴇ Rᴇǫᴜᴇsᴛ</b>\n"
                f"<i>User ne ek movie request ki hai:</i>\n\n"
                f"‣ <b>Tɪᴛʟᴇ :</b> <b>{movie_name}</b>\n"
                f"‣ <b>Usᴇʀ :</b> {user.first_name} (@{user.username or 'N/A'}) [ID: <code>{user_id}</code>]\n"
                f"‣ <b>Cʜᴀᴛ :</b> {chat_title} [ID: <code>{chat_id}</code>]\n"
                f"‣ <b>Rᴇǫᴜᴇsᴛ ID :</b> <code>#{req_id}</code>"
            )
            alert_keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Aᴅᴅᴇᴅ / Cᴏᴍᴘʟᴇᴛᴇᴅ", callback_data=f"REQ|add|{req_id}", style="success"),
                    InlineKeyboardButton("Rᴇᴊᴇᴄᴛ / Dᴇʟᴇᴛᴇ", callback_data=f"REQ|reject|{req_id}", style="danger")
                ]
            ])
            try:
                from bot import send_styled
                await send_styled(chat_id=owner_id, text=alert_caption, markup=alert_keyboard)
            except Exception as pm_err:
                print(f"[Movies Engine] Failed to alert owner in PM: {pm_err}")
                
            await message.reply_text(
                f"{HEADER}"
                f"<b>Rᴇǫᴜᴇsᴛ Sᴜʙᴍɪᴛᴛᴇᴅ!</b>\n\n"
                f"Aapki request <code>{movie_name}</code> humare record mein save ho gayi hai aur admin ko send kar di gayi hai!",
                parse_mode=enums.ParseMode.HTML
            )
        except Exception as e:
            print(f"[MOVIES Engine] Request command error: {e}")
            await message.reply_text(f"{HEADER}<b>Error:</b> <code>{str(e)}</code>")

    @app.on_message(filters.command(["movie", "vod"]) & filters.group)
    async def movie_command(client: Client, message: Message):
        chat_id = message.chat.id
        from core.db import is_group_bot_active
        if not is_group_bot_active(chat_id):
            return
        user = message.from_user
        user_id = user.id if user else 0

        if len(message.command) < 2:
            caption = (
                f"{HEADER}"
                "<b>Mᴏᴠɪᴇ Sᴇᴀʀᴄʜ Pᴀɴᴇʟ</b>\n\n"
                "Aapne movie ya series ka naam nahi likha. Movie play karne ke liye <code>/movie Name</code> type karein.\n\n"
                "Ya fir niche diye button par click karke <b>Tʀᴇɴᴅɪɴɢ & Lᴀᴛᴇsᴛ Mᴏᴠɪᴇs</b> check karein:"
            )
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Tʀᴇɴᴅɪɴɢ Mᴏᴠɪᴇs & Sᴇʀɪᴇs", callback_data=f"VOD|trend_movies|{user_id}", style="success")
                ]
            ])
            from bot import send_styled
            await send_styled(chat_id=chat_id, text=caption, markup=keyboard)
            return

        raw_query = " ".join(message.command[1:]).strip()
        print(f"[MOVIES Engine] Search request: '{raw_query}' by user {user_id}")

        status_msg = await show_loading_animation(chat_id, "Sᴇᴀʀᴄʜɪɴɢ", client=client)

        try:
            import re, difflib
            from core.vod_scraper import normalize_search_query
            
            is_hindi_query = bool(re.search(r'\b(hindi|dubbed|dub)\b', raw_query, re.IGNORECASE))
            base_query = re.sub(r'\b(hindi|dubbed|dub|eng|english)\b', '', raw_query, flags=re.IGNORECASE).strip()
            base_query = re.sub(r'\s+', ' ', base_query).strip()
            if not base_query:
                base_query = raw_query

            # Always search with Hindi preference by default
            items = await search_vod(raw_query, language="hi")
            if not items:
                await safe_edit(
                    status_msg,
                    f"{HEADER}"
                    f"<b>Humein '{raw_query}' ke naam se koi movie ya series nahi mili!</b>\n"
                    "Please spelling check karein aur dobara try karein."
                )
                return

            session = Session()

            # === HINDI PRIORITY FIX ===
            # Hindi items pehle sort karo — agar Hindi available hai toh wahi top pe
            hindi_items = [it for it in items if "hindi" in it.title.lower()]
            non_hindi_items = [it for it in items if "hindi" not in it.title.lower()]
            items_sorted = hindi_items + non_hindi_items
            top_item = items_sorted[0]

            clean_title = re.sub(r'\[.*?\]', '', top_item.title).strip()
            clean_title = re.sub(r'\s+S\d+(-S\d+)?', '', clean_title, flags=re.IGNORECASE).strip()
            clean_title = clean_title.title()

            vod_sessions[chat_id] = {
                "chat_id": chat_id,
                "query": raw_query,
                "base_query": base_query,
                "requester_id": user_id,
                "requester_name": user.first_name if user and user.first_name else (f"@{user.username}" if user and user.username else str(user_id)),
                "search_results": items_sorted,
                "session": session,
                "seasons": [],
                "chosen_season": 1,
                "chosen_episode": 1,
                "current_item": top_item,
                "chosen_lang": "hi" if "hindi" in top_item.title.lower() else "en",
                "chosen_lang_name": "Hindi" if "hindi" in top_item.title.lower() else None,
                "title": clean_title
            }
            session_data = vod_sessions[chat_id]

            # Auto-proceed determination
            is_series = top_item.subjectType == SubjectType.TV_SERIES or int(getattr(top_item, "subjectType", 1)) == 2
            top_clean = re.sub(r'\[.*?\]', '', top_item.title).strip()
            top_clean = re.sub(r'\s+S\d+(-S\d+)?', '', top_clean, flags=re.IGNORECASE).strip()

            base_norm = normalize_search_query(base_query).replace("-", " ").strip().lower()
            top_norm = normalize_search_query(top_clean).replace("-", " ").strip().lower()

            sim_score = difflib.SequenceMatcher(None, base_norm, top_norm).ratio()
            is_match = (base_norm == top_norm) or (base_norm in top_norm) or (top_norm in base_norm) or (sim_score >= 0.55)

            # Auto-proceed: agar match mila ya sirf ek result hai
            should_auto_proceed = (len(items_sorted) == 1) or is_match

            if should_auto_proceed:
                # Detect all available languages in parallel
                try:
                    from core.vod_scraper import get_available_languages
                    available_langs = await get_available_languages(
                        session,
                        clean_title,
                        is_series=is_series,
                        existing_items=items_sorted
                    )
                    if available_langs and len(available_langs) > 1:
                        session_data["available_langs"] = available_langs
                        caption, keyboard = get_language_panel(session_data)
                        await safe_edit(status_msg, caption, keyboard)
                        return
                    elif available_langs and len(available_langs) == 1:
                        session_data["available_langs"] = available_langs
                        first_l = available_langs[0]
                        session_data["current_item"] = first_l["item"]
                        session_data["chosen_lang"] = first_l["code"]
                        session_data["chosen_lang_name"] = first_l["name"]
                        if first_l.get("seasons"):
                            session_data["seasons"] = first_l["seasons"]
                except Exception as lang_err:
                    print(f"[MOVIES Engine] Lang detection err: {lang_err}")

                if is_series:
                    await select_vod_item(chat_id, session_data["current_item"], status_msg, user_id)
                else:
                    await trigger_movie_playback(status_msg, session_data, season=0, episode=0)
                return

            # Multiple search results — render clean mobile-optimized selection panel
            caption, keyboard = get_search_results_panel(session_data)
            await safe_edit(status_msg, caption, keyboard)

        except Exception as e:
            print(f"[MOVIES Engine] Error in /movie command: {e}")
            await safe_edit(
                status_msg,
                f"{HEADER}"
                f"<b>Kuch error aaya hai:</b> <code>{str(e)}</code>"
            )

    @app.on_callback_query(filters.regex(r"^VODLANG_PLAY\|"))
    async def vodlang_play_callback(client: Client, query: CallbackQuery):
        chat_id = query.message.chat.id
        parts = query.data.split("|")
        allowed_uid = int(parts[1])
        
        try:
            await query.answer()
        except:
            pass
            
        requester_id = query.from_user.id if query.from_user else 0
        if allowed_uid != 0 and requester_id != allowed_uid:
            await query.answer("Sirf wahi click kar sakta hai jisne search start kiya tha!", show_alert=True)
            return
            
        session_data = vod_sessions.get(chat_id)
        if not session_data:
            await safe_edit(query.message, f"{HEADER}<b>Error: Session expired. Search again.</b>")
            return
            
        current_item = session_data["current_item"]
        is_series = current_item.subjectType == SubjectType.TV_SERIES or int(getattr(current_item, "subjectType", 1)) == 2
        
        if is_series:
            await select_vod_item(chat_id, current_item, query.message, allowed_uid)
        else:
            await trigger_movie_playback(query, session_data, season=0, episode=0)

    @app.on_callback_query(filters.regex(r"^VODLANG\|"))
    async def vodlang_callback(client: Client, query: CallbackQuery):
        chat_id = query.message.chat.id
        data = query.data
        parts = data.split("|")
        
        try:
            await query.answer()
        except Exception:
            pass
            
        if len(parts) < 4:
            return
            
        lang = parts[1]
        target_subject_id = str(parts[2])
        allowed_uid = int(parts[3])
        
        requester_id = query.from_user.id if query.from_user else 0
        if allowed_uid != 0 and requester_id != allowed_uid:
            await query.answer("Sirf wahi click kar sakta hai jisne search start kiya tha!", show_alert=True)
            return
            
        session_data = vod_sessions.get(chat_id)
        if not session_data:
            await safe_edit(query.message, f"{HEADER}<b>Session expired. Please search again with /movie.</b>")
            return

        available_langs = session_data.get("available_langs", [])
        matched_lang = next((l for l in available_langs if str(getattr(l.get("item"), "subjectId", "")) == target_subject_id or l.get("code") == lang), None)

        if matched_lang and matched_lang.get("item"):
            item = matched_lang["item"]
            session_data["current_item"] = item
            session_data["chosen_lang"] = lang
            session_data["chosen_lang_name"] = matched_lang.get("name", lang.upper())

            clean_title = re.sub(r'\[.*?\]', '', item.title).strip()
            clean_title = re.sub(r'\s+S\d+(-S\d+)?', '', clean_title, flags=re.IGNORECASE).strip()
            clean_title = clean_title.title()
            session_data["title"] = clean_title

            # Use pre-fetched seasons if available for instant load
            cached_seasons = matched_lang.get("seasons", [])
            if cached_seasons:
                session_data["seasons"] = cached_seasons

            is_series = item.subjectType == SubjectType.TV_SERIES or int(getattr(item, "subjectType", 1)) == 2
            if is_series:
                if session_data.get("seasons"):
                    caption, keyboard = await get_season_panel(session_data)
                    await safe_edit(query.message, caption, keyboard)
                else:
                    await select_vod_item(chat_id, item, query.message, allowed_uid)
            else:
                await trigger_movie_playback(query, session_data, season=0, episode=0)
            return

        # Fallback if not found in pre-fetched list
        try:
            items = await search_vod(session_data.get("query", ""), language=lang)
            if items:
                await select_vod_item(chat_id, items[0], query.message, allowed_uid)
            else:
                await safe_edit(query.message, f"{HEADER}<b>Humein is version ka data nahi mila.</b>")
        except Exception as e:
            print(f"[MOVIES Engine] Callback lang fallback error: {e}")

    @app.on_callback_query(filters.regex(r"^VOD\|"))
    async def vod_callback(client: Client, query: CallbackQuery):
        chat_id = query.message.chat.id
        from core.db import is_group_bot_active
        if not is_group_bot_active(chat_id):
            await query.answer("Bot is currently disabled in this group by Admin.", show_alert=True)
            return
        data = query.data
        parts = data.split("|")
        print(f"[MOVIES Engine DEBUG] Received callback: data='{data}', chat_id={chat_id}")
        
        try:
            await query.answer()
        except Exception as q_ans_err:
            print(f"[MOVIES Engine DEBUG] query.answer() failed: {q_ans_err}")
            
        if len(parts) < 3:
            print(f"[MOVIES Engine DEBUG] parts length too small: {len(parts)}")
            return

        action = parts[1]
        try:
            allowed_uid = int(parts[2])
        except Exception as val_err:
            print(f"[MOVIES Engine DEBUG] Parse allowed_uid failed: {val_err}")
            return
            
        requester_id = query.from_user.id if query.from_user else 0
        print(f"[MOVIES Engine DEBUG] action={action}, allowed_uid={allowed_uid}, requester_id={requester_id}")

        if allowed_uid != 0 and requester_id != allowed_uid:
            is_adm = False
            try:
                from config import Config
                from plugins.admin import is_sudo_user
                if requester_id in (Config.OWNER_ID, 6805412676) or is_sudo_user(requester_id):
                    is_adm = True
                else:
                    member = await client.get_chat_member(chat_id, requester_id)
                    if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                        is_adm = True
            except Exception:
                pass
            if not is_adm:
                print(f"[MOVIES Engine DEBUG] Access denied: requester_id {requester_id} != allowed_uid {allowed_uid}")
                await query.answer("Sirf wahi click kar sakta hai jisne search start kiya tha!", show_alert=True)
                return

        # Handle trending actions first (they don't require VOD search session data)
        if action == "trend_movies":
            caption, keyboard = await get_trending_movies_panel(allowed_uid)
            await safe_edit(query.message, caption, keyboard)
            return

        elif action == "trend_series":
            caption, keyboard = await get_trending_series_panel(allowed_uid)
            await safe_edit(query.message, caption, keyboard)
            return

        elif action == "trend_hindi":
            caption, keyboard = await get_trending_hindi_panel(allowed_uid)
            await safe_edit(query.message, caption, keyboard)
            return

        elif action == "trend_close":
            try:
                await query.message.delete()
            except Exception:
                pass
            return

        session_data = vod_sessions.get(chat_id)
        if not session_data:
            await safe_edit(query.message, f"{HEADER}<b>Error: Session expired. Please search again.</b>")
            return

        if action == "select":
            target_subject_id = str(parts[3])
            items = session_data.get("search_results", [])
            item = next((x for x in items if str(getattr(x, "subjectId", "")) == target_subject_id), None)
            if not item:
                print(f"[MOVIES Engine DEBUG] Subject ID {target_subject_id} not found in search_results: {[getattr(x, 'subjectId', None) for x in items]}")
                await safe_edit(
                    query.message,
                    f"{HEADER}<b>Movie details not found. Please search again.</b>"
                )
                return
            await select_vod_item(chat_id, item, query.message, allowed_uid)

        elif action == "back_to_results":
            if not session_data.get("search_results"):
                await safe_edit(query.message, f"{HEADER}<b>Session expired. Please search again with /movie.</b>")
                return
            caption, keyboard = get_search_results_panel(session_data)
            await safe_edit(query.message, caption, keyboard)

        elif action == "play_movie":
            await trigger_movie_playback(query, session_data, season=0, episode=0)

        elif action == "season":
            season_num = int(parts[3])
            session_data["chosen_season"] = season_num
            await query.answer(f"Selected Season {season_num}")
            
            caption, keyboard = get_episode_panel(session_data)
            await safe_edit(query.message, caption, keyboard)

        elif action == "episode":
            ep_num = int(parts[3])
            session_data["chosen_episode"] = ep_num
            stream_manager.menu_active[chat_id] = False
            await trigger_movie_playback(query, session_data, season=session_data["chosen_season"], episode=ep_num, replace_stream=True)

        elif action == "back_to_seasons":
            await query.answer("Returning...")
            caption, keyboard = await get_season_panel(session_data)
            await safe_edit(query.message, caption, keyboard)


    @app.on_callback_query(filters.regex(r"^VODNEXT\|"))
    async def vod_next_callback(client: Client, query: CallbackQuery):
        try:
            await query.answer()
        except:
            pass
        chat_id = query.message.chat.id
        data = query.data
        parts = data.split("|")
        
        if len(parts) < 4:
            return
            
        target_chat_id = int(parts[1])
        next_season = int(parts[2])
        next_episode = int(parts[3])
        
        session_data = vod_sessions.get(chat_id)
        if not session_data:
            await query.answer("Session expired. Search again.", show_alert=True)
            return
            
        allowed_uid = session_data.get("requester_id", 0)
        requester_id = query.from_user.id if query.from_user else 0
        if requester_id != allowed_uid:
            await query.answer("Only the requester can load the next episode!", show_alert=True)
            return
            
        await trigger_movie_playback(query, session_data, season=next_season, episode=next_episode, is_next=True)

    @app.on_callback_query(filters.regex(r"^VODRESUME\|"))
    async def vod_resume_callback(client: Client, query: CallbackQuery):
        chat_id = query.message.chat.id
        data = query.data
        parts = data.split("|")
        
        try:
            await query.answer()
        except:
            pass
            
        if len(parts) < 5:
            return
            
        allowed_uid = int(parts[1])
        season = int(parts[2])
        episode = int(parts[3])
        progress = int(parts[4])
        
        requester_id = query.from_user.id if query.from_user else 0
        if allowed_uid != 0 and requester_id != allowed_uid:
            try:
                member = await client.get_chat_member(chat_id, requester_id)
                if member.status not in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                    await query.answer("Sirf wahi click kar sakta hai jisne search start kiya tha!", show_alert=True)
                    return
            except Exception:
                await query.answer("Sirf wahi click kar sakta hai jisne search start kiya tha!", show_alert=True)
                return
                
        session_data = vod_sessions.get(chat_id)
        if not session_data:
            await safe_edit(query.message, f"{HEADER}<b>Session expired. Please search again.</b>")
            return
            
        await trigger_movie_playback(query, session_data, season=season, episode=episode, force_seek=progress)

    @app.on_callback_query(filters.regex(r"^VODSTARTOVER\|"))
    async def vod_startover_callback(client: Client, query: CallbackQuery):
        chat_id = query.message.chat.id
        data = query.data
        parts = data.split("|")
        
        try:
            await query.answer()
        except:
            pass
            
        if len(parts) < 4:
            return
            
        allowed_uid = int(parts[1])
        season = int(parts[2])
        episode = int(parts[3])
        
        requester_id = query.from_user.id if query.from_user else 0
        if allowed_uid != 0 and requester_id != allowed_uid:
            try:
                member = await client.get_chat_member(chat_id, requester_id)
                if member.status not in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                    await query.answer("Sirf wahi click kar sakta hai jisne search start kiya tha!", show_alert=True)
                    return
            except Exception:
                await query.answer("Sirf wahi click kar sakta hai jisne search start kiya tha!", show_alert=True)
                return
                
        session_data = vod_sessions.get(chat_id)
        if not session_data:
            await safe_edit(query.message, f"{HEADER}<b>Session expired. Please search again.</b>")
            return
            
        # Clear progress from db
        from core.db import clear_vod_progress
        subject_id = int(session_data["current_item"].subjectId)
        clear_vod_progress(chat_id, subject_id, season, episode)
        
        await trigger_movie_playback(query, session_data, season=season, episode=episode, force_seek=0)


async def trigger_movie_playback(msg_or_query, session_data: dict, season: int = 0, episode: int = 0, is_next: bool = False, force_seek: int = -1, replace_stream: bool = False):
    if hasattr(msg_or_query, "message"):
        message = msg_or_query.message
        chat_id = message.chat.id
    else:
        message = msg_or_query
        if hasattr(message, "chat"):
            chat_id = message.chat.id
        elif isinstance(message, tuple):
            chat_id = message[0]

    current_item = session_data["current_item"]
    is_series = current_item.subjectType == SubjectType.TV_SERIES or int(getattr(current_item, "subjectType", 1)) == 2
    subject_id = int(current_item.subjectId)

    # ── VOD Playback Resume Gate ──
    if force_seek == -1 and not is_next and not replace_stream:
        from core.db import get_vod_progress
        saved_progress = get_vod_progress(chat_id, subject_id, season, episode)
        if saved_progress and saved_progress > 10:
            from plugins.controls import format_seconds
            pos_str = format_seconds(saved_progress)
            
            allowed_uid = session_data.get("requester_id", 0)
            lang = session_data.get("chosen_lang", "en")
            lang_name = session_data.get("chosen_lang_name")
            if not lang_name:
                is_hi = (lang == "hi") or ("hindi" in getattr(current_item, "title", "").lower())
                lang_name = "Hindi" if is_hi else "English"
            lang_tag = f" [{lang_name}]"
            title_suffix = f" S{season}E{episode}" if season > 0 else ""
            display_title = f"{session_data.get('title', '').strip()}{title_suffix}{lang_tag}".strip()
            
            caption = (
                f"{HEADER}"
                f"<b>Sᴀᴠᴇᴅ Pʀᴏɢʀᴇss Fᴏᴜɴᴅ</b>\n\n"
                f"‣ <b>Tɪᴛʟᴇ :</b> <code>{display_title}</code>\n"
                f"‣ <b>Sᴀᴠᴇᴅ Pᴏsɪᴛɪᴏɴ :</b> <code>{pos_str}</code>\n\n"
                f"Kya aap wahan se <b>Resume</b> karna chahte hain ya shuru se <b>Start Over</b>?"
            )
            
            # Setup Inline Buttons with green/red styling (success/danger)
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Rᴇsᴜᴍᴇ Pʟᴀʏ", callback_data=f"VODRESUME|{allowed_uid}|{season}|{episode}|{saved_progress}", style="success"),
                    InlineKeyboardButton("Sᴛᴀʀᴛ Oᴠᴇʀ", callback_data=f"VODSTARTOVER|{allowed_uid}|{season}|{episode}", style="danger")
                ],
                [
                    InlineKeyboardButton("Cʟᴏsᴇ", callback_data="vcplay_close", style="danger")
                ]
            ])
            
            if hasattr(msg_or_query, "message"):
                await safe_edit(msg_or_query.message, caption, reply_markup=keyboard)
            else:
                await safe_edit(msg_or_query, caption, reply_markup=keyboard)
            return

    # If force_seek is >= 0, we use it, otherwise use 0
    seek_offset = force_seek if force_seek >= 0 else 0
    session_data["force_seek"] = seek_offset

    # ── Voice Chat & Assistant Pre-Flight Check Before Fetching Stream ──
    from core.player import stream_manager
    ok_asst, asst_err, asst_info = await stream_manager.ensure_assistant_in_chat(chat_id, bot_client=stream_manager.app)
    if not ok_asst:
        asst_user = asst_info.get("username", "")
        btns = []
        if asst_user:
            btns.append([InlineKeyboardButton("➕ Aᴅᴅ Assɪsᴛᴀɴᴛ", url=f"https://t.me/{asst_user}?startgroup=true", style="success")])
        btns.append([InlineKeyboardButton("Cʟᴏsᴇ", callback_data="vcplay_close", style="danger")])
        await safe_edit(message, asst_err, reply_markup=InlineKeyboardMarkup(btns))
        return

    ok_vc, vc_err = await stream_manager.ensure_active_voice_chat(chat_id, bot_client=stream_manager.app)
    if not ok_vc:
        vc_markup = InlineKeyboardMarkup([[InlineKeyboardButton("Cʟᴏsᴇ", callback_data="vcplay_close", style="danger")]])
        await safe_edit(message, vc_err, reply_markup=vc_markup)
        return

    label = "Eᴘɪsᴏᴅᴇ" if is_series else "Mᴏᴠɪᴇ"
    await safe_edit(message, f"{HEADER}<b>Fᴇᴛᴄʜɪɴɢ {label}...</b>\n<i>Server se stream fetch ki ja rahi hai...</i>")
    
    try:
        # Resolve stream link directly from current selected item
        result = await resolve_stream_link(
            session_data["session"],
            current_item,
            season=season,
            episode=episode,
            quality="720"
        )
        
        lang = session_data.get("chosen_lang", "en")
        lang_name = session_data.get("chosen_lang_name")
        if not lang_name:
            if lang == "hi" or "hindi" in getattr(current_item, "title", "").lower():
                lang_name = "Hindi"
            elif lang == "ja" or "japanese" in getattr(current_item, "title", "").lower():
                lang_name = "Japanese"
            elif lang == "en" or "english" in getattr(current_item, "title", "").lower():
                lang_name = "English"
            else:
                lang_name = lang.upper()
        lang_tag = f" [{lang_name}]"
        title_suffix = f" S{season}E{episode}" if is_series else ""
        display_title = f"{session_data.get('title', '').strip()}{title_suffix}{lang_tag}".strip()
        
        # Safely extract cover image URL
        thumb_url = ""
        cov_obj = getattr(current_item, "cover", None)
        if cov_obj:
            if hasattr(cov_obj, "url") and cov_obj.url:
                thumb_url = str(cov_obj.url)
            elif isinstance(cov_obj, dict):
                thumb_url = str(cov_obj.get("url", ""))
            elif isinstance(cov_obj, str):
                thumb_url = cov_obj

        song = SongInfo(
            title=display_title,
            video_url=result["url"],
            audio_url=result["url"],
            thumbnail=thumb_url,
            duration="VOD",
            duration_secs=0,
            webpage_url=result["url"],
            uploader="MOVIES Engine",
            requested_by=session_data.get("requester_name", "Someone"),
            quality="720",
            requester_id=session_data.get("requester_id", 0)
        )
        song.subject_id = subject_id
        song.season = season
        song.episode = episode
        song.clean_title = session_data.get("title", song.title)
        
        # Check if already playing - Queue if needed (skip if replacing active stream or next episode)
        is_playing = queue_manager.is_playing(chat_id)
        if is_playing and not is_next and not replace_stream:
            pos = queue_manager.add(chat_id, song)
            from plugins.controls import control_buttons
            await safe_edit(
                message,
                f"{HEADER}"
                f"<b><u>Uᴘᴄᴏᴍɪɴɢ Vᴏᴅ Tʀᴀᴄᴋ: #{pos}</u></b>\n\n"
                f"‣ <b>Tɪᴛʟᴇ :</b> <code>{song.title}</code>\n"
                f"‣ <b>Dᴜʀᴀᴛɪᴏɴ :</b> {song.duration}\n"
                f"‣ <b>Rᴇǫᴜᴇsᴛᴇᴅ Bʏ :</b> {song.requested_by}",
                reply_markup=control_buttons()
            )
            return


        if is_series:
            session_data["chosen_season"] = season
            session_data["chosen_episode"] = episode

        if hasattr(msg_or_query, "message"):
            stream_manager.active_message_id[chat_id] = msg_or_query.message.id
        elif isinstance(msg_or_query, tuple):
            stream_manager.active_message_id[chat_id] = msg_or_query[1]
        elif hasattr(msg_or_query, "id"):
            stream_manager.active_message_id[chat_id] = msg_or_query.id
        force_seek = session_data.get("force_seek", 0)
        success = await stream_manager.play(chat_id, song, send_card=True, force_seek=force_seek)
        if success:
            try:
                if hasattr(msg_or_query, "message"):
                    await msg_or_query.message.delete()
                elif hasattr(msg_or_query, "delete"):
                    await msg_or_query.delete()
                elif isinstance(msg_or_query, tuple) and stream_manager.app:
                    await stream_manager.app.delete_messages(msg_or_query[0], msg_or_query[1])
            except Exception:
                pass
        else:
            queue_manager.clear(chat_id)
            await safe_edit(
                message,
                f"{HEADER}"
                f"<b>Stream start karne mein error aaya!</b>\n\nEnsure group voice chat is active."
            )
            
    except Exception as e:
        queue_manager.clear(chat_id)
        print(f"[MOVIES Engine] Playback error: {e}")
        await safe_edit(message, f"{HEADER}<b>Error resolving stream:</b> {str(e)}")
