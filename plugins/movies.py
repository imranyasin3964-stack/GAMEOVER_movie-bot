"""
MOVIES Engine — Video-On-Demand (VOD) Plugin
Provides interactive /movie search, season/episode choice, and buttonless auto-play.
Integrates our high-performance local caching & garbage collection engine.
"""

import os
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
        from bot import send_styled
        if hasattr(message, "chat"):
            chat_id = message.chat.id
            message_id = message.id
        elif isinstance(message, tuple):
            chat_id, message_id = message
        else:
            return message
            
        await send_styled(chat_id, text, markup=reply_markup, message_id=message_id)
    except Exception as e:
        print(f"[safe_edit] Error: {e}")


def chunk_buttons(buttons, n):
    return [buttons[i:i + n] for i in range(0, len(buttons), n)]


async def get_season_panel(session_data):
    title = session_data["title"]
    allowed_uid = session_data["requester_id"]
    seasons = session_data["seasons"]
    
    caption = (
        f"{HEADER}"
        f"<b>{title}</b> ke kul <code>{len(seasons)} seasons</code> hain.\n\n"
        "Watch karne ke liye <b>Season</b> select karein:"
    )
    
    buttons = []
    for s in seasons:
        style = "primary"
        buttons.append(
            InlineKeyboardButton(f"Sᴇᴀsᴏɴ {s.se}", callback_data=f"VOD|season|{allowed_uid}|{s.se}", style=style)
        )
        
    rows = chunk_buttons(buttons, 3)
    return caption, InlineKeyboardMarkup(rows)


def get_episode_panel(session_data):
    title = session_data["title"]
    allowed_uid = session_data["requester_id"]
    season_num = session_data["chosen_season"]
    seasons = session_data["seasons"]
    
    max_ep = 1
    for s in seasons:
        if s.se == season_num:
            max_ep = s.maxEp
            break
            
    caption = (
        f"{HEADER}"
        f"<b>{title} — Season {season_num}</b>\n\n"
        "Watch karne ke liye <b>Episode</b> select karein:"
    )
    
    buttons = []
    for ep in range(1, max_ep + 1):
        buttons.append(
            InlineKeyboardButton(f"Eᴘ {ep}", callback_data=f"VOD|episode|{allowed_uid}|{ep}", style="primary")
        )
        
    rows = chunk_buttons(buttons, 5)
    rows.append([InlineKeyboardButton("Bᴀᴄᴋ Tᴏ Sᴇᴀsᴏɴs", callback_data=f"VOD|back_to_seasons|{allowed_uid}", style="danger")])
    return caption, InlineKeyboardMarkup(rows)


async def select_vod_item(chat_id: int, item: SearchResultsItem, status_msg, user_id: int):
    session_data = vod_sessions.get(chat_id)
    if not session_data:
        return
        
    session_data["current_item"] = item
    session_data["chosen_lang"] = "hi" if "hindi" in item.title.lower() else "en"
    session_data["title"] = item.title.replace("[Hindi]", "").replace("[English]", "").replace("[english]","").replace("[Hindi]","").strip()
        
    is_series = session_data["current_item"].subjectType == SubjectType.TV_SERIES or int(getattr(session_data["current_item"], "subjectType", 1)) == 2
    
    if is_series:
        from core.vod_scraper import fetch_tv_details
        details = await fetch_tv_details(session_data["session"], session_data["current_item"])
        if details and details.resource and details.resource.seasons:
            session_data["seasons"] = details.resource.seasons
            caption, keyboard = await get_season_panel(session_data)
            await safe_edit(status_msg, caption, keyboard)
        else:
            is_series = False
            
    if not is_series:
        caption = (
            f"{HEADER}"
            f"‣ <b>Tɪᴛʟᴇ :</b> <code>{session_data['title']}</code>\n\n"
            f"Movie watch karne ke liye neeche click karein:"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Pʟᴀʏ Mᴏᴠɪᴇ", callback_data=f"VOD|play_movie|{user_id}", style="success")
            ]
        ])
        await safe_edit(status_msg, caption, keyboard)


async def show_loading_animation(chat_id: int, base_text: str) -> tuple:
    """Creates a message and animates loading dots for smooth, responsive UX."""
    from bot import send_styled
    msg_data = await send_styled(
        chat_id=chat_id,
        text=f"{HEADER}<b>{base_text}</b>"
    )
    msg_id = msg_data.get("result", {}).get("message_id")
    msg_tuple = (chat_id, msg_id)
    
    # Run a quick 1.5-second dots animation
    for i in range(1, 4):
        await asyncio.sleep(0.4)
        dots = "." * i
        await safe_edit(msg_tuple, f"{HEADER}<b>{base_text}{dots}</b>")
        
    return msg_tuple


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

        query = " ".join(message.command[1:])
        print(f"[MOVIES Engine] Search request: '{query}' by user {user_id}")

        status_msg = await show_loading_animation(chat_id, "Searching")

        try:
            items = await search_vod(query, language="hi")
            if not items:
                await safe_edit(
                    status_msg,
                    f"{HEADER}"
                    f"<b>Humein '{query}' ke naam se koi movie ya series nahi mili!</b>\n"
                    "Please spelling check karein aur dobara try karein."
                )
                return

            session = Session()
            top_item = items[0]
            clean_title = top_item.title.replace("[Hindi]", "").replace("[English]", "").replace("[english]","").replace("[Hindi]","").strip()

            vod_sessions[chat_id] = {
                "query": query,
                "requester_id": user_id,
                "requester_name": user.first_name if user and user.first_name else (f"@{user.username}" if user and user.username else str(user_id)),
                "search_results": items,
                "session": session,
                "seasons": [],
                "chosen_season": 1,
                "chosen_episode": 1,
                "current_item": top_item,
                "chosen_lang": "hi" if "hindi" in top_item.title.lower() else "en",
                "title": clean_title
            }
            session_data = vod_sessions[chat_id]

            # If top item is clearly the target or only 1 item returned, auto-proceed
            if len(items) == 1 or query.lower() in top_item.title.lower():
                is_series = top_item.subjectType == SubjectType.TV_SERIES or int(getattr(top_item, "subjectType", 1)) == 2
                if is_series:
                    await select_vod_item(chat_id, top_item, status_msg, user_id)
                else:
                    await trigger_movie_playback(status_msg, session_data, season=0, episode=0)
                return

            # Multiple search results — render interactive selection panel
            caption = (
                f"{HEADER}"
                f"<b>Sᴇᴀʀᴄʜ Rᴇsᴜʟᴛs ғᴏʀ:</b> <code>{query}</code>\n\n"
                f"Neeche se apni preferred movie ya series select karein:"
            )
            buttons = []
            for itm in items[:6]:
                is_ser = itm.subjectType == SubjectType.TV_SERIES or int(getattr(itm, "subjectType", 1)) == 2
                type_label = "[Series]" if is_ser else "[Movie]"
                clean_item_t = itm.title.replace("[Hindi]", "").replace("[English]", "").replace("[english]","").replace("[Hindi]","").strip()
                short_t = (clean_item_t[:30] + "...") if len(clean_item_t) > 30 else clean_item_t
                buttons.append([
                    InlineKeyboardButton(f"{type_label} {short_t}", callback_data=f"VOD|select|{user_id}|{itm.subjectId}", style="primary")
                ])
            buttons.append([InlineKeyboardButton("Cʟᴏsᴇ", callback_data="vcplay_close", style="danger")])
            await safe_edit(status_msg, caption, InlineKeyboardMarkup(buttons))

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
        except:
            pass
            
        if len(parts) < 4:
            return
            
        lang = parts[1]
        movie_query = parts[2]
        allowed_uid = int(parts[3])
        
        requester_id = query.from_user.id if query.from_user else 0
        if allowed_uid != 0 and requester_id != allowed_uid:
            await query.answer("Sirf wahi click kar sakta hai jisne search start kiya tha!", show_alert=True)
            return
            
        await safe_edit(query.message, f"{HEADER}<b>Searching for {lang.upper()} version...</b>\n<i>Please wait...</i>")
        
        try:
            items = await search_vod(movie_query, language=lang)
            if not items:
                await safe_edit(query.message, f"{HEADER}<b>Humein is query ka koi {lang.upper()} version nahi mila!</b>")
                return
                
            session = Session()
            vod_sessions[chat_id] = {
                "query": movie_query,
                "requester_id": allowed_uid,
                "requester_name": query.from_user.first_name if query.from_user and query.from_user.first_name else str(allowed_uid),
                "search_results": items,
                "session": session,
                "seasons": [],
                "chosen_season": 1,
                "chosen_episode": 1,
                "current_item": items[0],
                "chosen_lang": lang,
                "title": items[0].title.replace("[Hindi]", "").replace("[English]", "").replace("[english]","").replace("[Hindi]","").strip()
            }
            session_data = vod_sessions[chat_id]
            current_item = items[0]
            is_series = current_item.subjectType == SubjectType.TV_SERIES or int(getattr(current_item, "subjectType", 1)) == 2
            
            if is_series:
                await select_vod_item(chat_id, current_item, query.message, allowed_uid)
            else:
                await trigger_movie_playback(query, session_data, season=0, episode=0)
        except Exception as e:
            print(f"[MOVIES Engine] Callback lang error: {e}")
            await safe_edit(query.message, f"{HEADER}<b>Error:</b> <code>{str(e)}</code>")

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
            subject_id = int(parts[3])
            items = session_data.get("search_results", [])
            item = next((x for x in items if x.subjectId == subject_id), None)
            if not item:
                await query.answer("Movie details not found. Search again.", show_alert=True)
                return
            await select_vod_item(chat_id, item, query.message, allowed_uid)

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
            await trigger_movie_playback(query, session_data, season=session_data["chosen_season"], episode=ep_num)

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


async def trigger_movie_playback(msg_or_query, session_data: dict, season: int = 0, episode: int = 0, is_next: bool = False, force_seek: int = -1):
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
    if force_seek == -1 and not is_next:
        from core.db import get_vod_progress
        saved_progress = get_vod_progress(chat_id, subject_id, season, episode)
        if saved_progress and saved_progress > 10:
            from plugins.controls import format_seconds
            pos_str = format_seconds(saved_progress)
            
            allowed_uid = session_data.get("requester_id", 0)
            lang = session_data.get("chosen_lang", "en")
            lang_tag = "[Hindi]" if lang == "hi" else ""
            title_suffix = f" S{season}E{episode}" if season > 0 else ""
            display_title = f"{session_data['title']}{title_suffix} {lang_tag}"
            
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

    await safe_edit(message, f"{HEADER}<b>Fetching Movie...</b>\n<i>Server se connection kiya ja raha hai...</i>")
    
    try:
        # Resolve stream link directly from current selected item
        result = await resolve_stream_link(
            session_data["session"],
            current_item,
            season=season,
            episode=episode,
            quality="720"
        )
        
        lang = session_data["chosen_lang"]
        lang_tag = "[Hindi]" if lang == "hi" else ""
        title_suffix = f" S{season}E{episode}" if is_series else ""
        display_title = f"{session_data['title']}{title_suffix} {lang_tag}"
        
        song = SongInfo(
            title=display_title,
            video_url=result["url"],
            audio_url=result["url"],
            thumbnail=str(current_item.cover.url) if (current_item.cover and current_item.cover.url) else "",
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
        
        # Check if already playing - Queue if needed
        is_playing = queue_manager.is_playing(chat_id)
        if is_playing and not is_next:
            start_time = time.time()
            last_edit_time = [0.0]
            last_pct = [-1]
            async def progress_cb(pct, downloaded, total_size):
                now = time.time()
                if now - last_edit_time[0] >= 3.5 or (pct - last_pct[0] >= 10 and pct > 0) or pct == 100:
                    last_edit_time[0] = now
                    last_pct[0] = pct
                    elapsed = time.time() - start_time
                    if elapsed == 0:
                        elapsed = 0.01
                    speed_bps = downloaded / elapsed
                    speed_mb = speed_bps / (1024 * 1024)
                    downloaded_mb = downloaded / (1024 * 1024)
                    
                    if total_size > 0:
                        total_size_mb = total_size / (1024 * 1024)
                        remaining_bytes = total_size - downloaded
                        seconds_left = max(0, int(remaining_bytes / speed_bps)) if speed_bps > 0 else 0
                        time_left_str = f"{seconds_left}s"
                        filled = int(pct / 10)
                        bar = "■" * filled + "□" * (10 - filled)
                        progress_str = f"<code>[{bar}] {pct}%</code>"
                        size_str = f"‣ <b>Sɪᴢᴇ :</b> <code>{downloaded_mb:.1f} MB / {total_size_mb:.1f} MB</code>"
                    else:
                        time_left_str = "calculating..."
                        progress_str = "<code>[DOWNLOADING...]</code>"
                        size_str = f"‣ <b>Sɪᴢᴇ :</b> <code>{downloaded_mb:.1f} MB / calculating...</code>"
                        
                    try:
                        await safe_edit(
                            message,
                            f"{HEADER}"
                            f"<b>Pʀᴏᴄᴇssɪɴɢ Mᴇᴅɪᴀ (Qᴜᴇᴜᴇ)...</b>\n\n"
                            f"‣ <b>Tɪᴛʟᴇ :</b> <code>{song.title}</code>\n"
                            f"{progress_str}\n"
                            f"{size_str}\n"
                            f"‣ <b>Sᴘᴇᴇᴅ :</b> <code>{speed_mb:.1f} MB/s</code>\n"
                            f"‣ <b>Rᴇᴍᴀɪɴɪɴɢ :</b> <code>{time_left_str}</code>"
                        )
                    except Exception:
                        pass

            from core.downloader import download_song
            local_file = await download_song(song, mode="video", progress_callback=progress_cb)
            if not local_file:
                await safe_edit(
                    message,
                    f"{HEADER}<b>Error: Failed to download track cache.</b>"
                )
                return
                
            stream_manager.local_files[chat_id] = local_file
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
        force_seek = session_data.get("force_seek", 0)
        success = await stream_manager.play(chat_id, song, send_card=True, force_seek=force_seek)
        if success:
            try:
                if hasattr(msg_or_query, "message"):
                    await msg_or_query.message.delete()
                elif hasattr(msg_or_query, "delete"):
                    await msg_or_query.delete()
                elif isinstance(msg_or_query, tuple) and stream_manager._app:
                    await stream_manager._app.delete_messages(msg_or_query[0], msg_or_query[1])
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
