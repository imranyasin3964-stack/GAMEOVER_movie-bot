"""
GAMEOVER MOVIE HUB — Admin Panel Plugin
Interactive Admin Dashboard for owner.
Supports dynamic Broadcast management with toggles per group.
Music / streaming / cookies / API manager removed — Movie Hub only.

FIX: send_styled now uses the 'client' parameter passed by pyrogram handlers
     instead of importing from bot.py — avoids 'Client has not been started yet' error.
"""

import asyncio
import os
try:
    import psutil
except ImportError:
    psutil = None
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from config import Config
from core.db import is_sudo_user, get_broadcast_groups, set_group_broadcast_enabled, set_group_welcome_enabled, set_group_bot_active
from core.fonts import ADMIN_HEADER as ROYAL_HEADER

# In-memory admin state tracker
admin_states = {}


# ─── Local send_styled wrapper — calls bot.py's HTTP Bot API version for button colors ───
async def send_styled(client: Client, chat_id: int, text: str, markup=None, message_id: int = None):
    from bot import send_styled as bot_send_styled
    return await bot_send_styled(chat_id=chat_id, text=text, markup=markup, message_id=message_id)


async def get_cpu_usage() -> float:
    if not psutil:
        return 0.0
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, psutil.cpu_percent, 1)


# ─── Markup Builders ──────────────────────────────────────────────────────────

def get_admin_panel_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Bʀᴏᴀᴅᴄᴀsᴛ", callback_data="admin_bc_prompt", style="success"),
            InlineKeyboardButton("Bᴄ Gʀᴏᴜᴘs", callback_data="admin_groups|0", style="primary")
        ],
        [
            InlineKeyboardButton("Wᴇʟᴄᴏᴍᴇ Sᴇᴛᴛɪɴɢs", callback_data="admin_welcome_groups|0", style="primary"),
            InlineKeyboardButton("Bᴏᴛ Sᴛᴀᴛᴜs", callback_data="admin_status_groups|0", style="primary")
        ],
        [
            InlineKeyboardButton("Vɪᴅᴇᴏ Qᴜᴀʟɪᴛʏ & Fᴘs", callback_data="admin_quality_panel", style="primary"),
            InlineKeyboardButton("Mᴀɴᴀɢᴇ Vɪᴅᴇᴏs", callback_data="admin_manage_videos", style="primary")
        ],
        [
            InlineKeyboardButton("Aᴜᴛʜ Usᴇʀs", callback_data="admin_auth_panel", style="primary"),
            InlineKeyboardButton("Cʟᴏɴᴇ Bᴏᴛs", callback_data="admin_clones_panel|0", style="primary")
        ],
        [
            InlineKeyboardButton("Cʟᴏsᴇ", callback_data="admin_close", style="danger")
        ]
    ])


def get_quality_panel_markup() -> InlineKeyboardMarkup:
    from core.player import get_configured_video_parameters
    _, active_q, active_fps, _ = get_configured_video_parameters()

    q_4k_prefix = "[Active] " if active_q == "4K" else ""
    q_2k_prefix = "[Active] " if active_q == "2K" else ""
    q_1080_prefix = "[Active] " if active_q == "1080p" else ""
    q_720_prefix = "[Active] " if active_q == "720p" else ""
    q_480_prefix = "[Active] " if active_q == "480p" else ""

    fps_120_prefix = "[Active] " if active_fps == 120 else ""
    fps_90_prefix = "[Active] " if active_fps == 90 else ""
    fps_60_prefix = "[Active] " if active_fps == 60 else ""
    fps_30_prefix = "[Active] " if active_fps == 30 else ""

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"{q_4k_prefix}4K (2160p)", callback_data="admin_set_q_4K", style="success" if active_q == "4K" else "primary"),
            InlineKeyboardButton(f"{q_2k_prefix}2K (1440p)", callback_data="admin_set_q_2K", style="success" if active_q == "2K" else "primary"),
        ],
        [
            InlineKeyboardButton(f"{q_1080_prefix}1080p Full HD", callback_data="admin_set_q_1080p", style="success" if active_q == "1080p" else "primary"),
            InlineKeyboardButton(f"{q_720_prefix}720p HD", callback_data="admin_set_q_720p", style="success" if active_q == "720p" else "primary"),
            InlineKeyboardButton(f"{q_480_prefix}480p SD", callback_data="admin_set_q_480p", style="success" if active_q == "480p" else "primary"),
        ],
        [
            InlineKeyboardButton(f"{fps_120_prefix}120 FPS Mode", callback_data="admin_set_fps_120", style="success" if active_fps == 120 else "primary"),
            InlineKeyboardButton(f"{fps_90_prefix}90 FPS Mode", callback_data="admin_set_fps_90", style="success" if active_fps == 90 else "primary"),
        ],
        [
            InlineKeyboardButton(f"{fps_60_prefix}60 FPS Mode", callback_data="admin_set_fps_60", style="success" if active_fps == 60 else "primary"),
            InlineKeyboardButton(f"{fps_30_prefix}30 FPS Mode", callback_data="admin_set_fps_30", style="success" if active_fps == 30 else "primary"),
        ],
        [
            InlineKeyboardButton("Bᴀᴄᴋ Tᴏ Dᴀsʜʙᴏᴀʀᴅ", callback_data="admin_back", style="primary"),
            InlineKeyboardButton("Cʟᴏsᴇ", callback_data="admin_close", style="danger")
        ]
    ])


def get_groups_markup(groups: list, page: int) -> InlineKeyboardMarkup:
    per_page = 5
    start = page * per_page
    end = start + per_page
    page_groups = groups[start:end]

    buttons = []
    for g in page_groups:
        status_label = "[ON]" if g["enabled"] else "[OFF]"
        style = "success" if g["enabled"] else "danger"
        status_text = f"{status_label} {g['title']}"
        buttons.append([
            InlineKeyboardButton(status_text, callback_data=f"admin_toggle|{g['chat_id']}|{page}", style=style)
        ])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("Pʀᴇᴠ", callback_data=f"admin_groups|{page - 1}", style="success"))
    if end < len(groups):
        nav_buttons.append(InlineKeyboardButton("Nᴇxᴛ", callback_data=f"admin_groups|{page + 1}", style="success"))
    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([
        InlineKeyboardButton("Bᴀᴄᴋ", callback_data="admin_back", style="primary"),
        InlineKeyboardButton("Cʟᴏsᴇ", callback_data="admin_close", style="danger")
    ])
    return InlineKeyboardMarkup(buttons)


def get_welcome_groups_markup(groups: list, page: int) -> InlineKeyboardMarkup:
    per_page = 5
    start = page * per_page
    end = start + per_page
    page_groups = groups[start:end]

    buttons = []
    for g in page_groups:
        welcome_active = g.get("welcome_enabled", 1)
        if welcome_active is None:
            welcome_active = 1
        status_label = "[ON]" if welcome_active else "[OFF]"
        style = "success" if welcome_active else "danger"
        status_text = f"{status_label} {g['title']}"
        buttons.append([
            InlineKeyboardButton(status_text, callback_data=f"admin_welcome_toggle|{g['chat_id']}|{page}", style=style)
        ])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("Pʀᴇᴠ", callback_data=f"admin_welcome_groups|{page - 1}", style="success"))
    if end < len(groups):
        nav_buttons.append(InlineKeyboardButton("Nᴇxᴛ", callback_data=f"admin_welcome_groups|{page + 1}", style="success"))
    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([
        InlineKeyboardButton("Bᴀᴄᴋ", callback_data="admin_back", style="primary"),
        InlineKeyboardButton("Cʟᴏsᴇ", callback_data="admin_close", style="danger")
    ])
    return InlineKeyboardMarkup(buttons)


def get_status_groups_markup(groups: list, page: int) -> InlineKeyboardMarkup:
    per_page = 5
    start = page * per_page
    end = start + per_page
    page_groups = groups[start:end]

    buttons = []
    for g in page_groups:
        bot_active = g.get("bot_active", 1)
        if bot_active is None:
            bot_active = 1
        status_label = "[ON]" if bot_active else "[OFF]"
        style = "success" if bot_active else "danger"
        status_text = f"{status_label} {g['title']}"
        buttons.append([
            InlineKeyboardButton(status_text, callback_data=f"admin_status_toggle|{g['chat_id']}|{page}", style=style)
        ])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("Pʀᴇᴠ", callback_data=f"admin_status_groups|{page - 1}", style="success"))
    if end < len(groups):
        nav_buttons.append(InlineKeyboardButton("Nᴇxᴛ", callback_data=f"admin_status_groups|{page + 1}", style="success"))
    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([
        InlineKeyboardButton("Bᴀᴄᴋ", callback_data="admin_back", style="primary"),
        InlineKeyboardButton("Cʟᴏsᴇ", callback_data="admin_close", style="danger")
    ])
    return InlineKeyboardMarkup(buttons)


def get_auth_panel_markup() -> InlineKeyboardMarkup:
    from core.db import get_global_auth_users
    users = get_global_auth_users()
    buttons = []
    for u in users[:10]:
        name = u.get("first_name") or f"User {u['user_id']}"
        if len(name) > 12:
            name = name[:11] + "…"
        buttons.append([
            InlineKeyboardButton(f"{name} ({u['user_id']})", callback_data="admin_noop", style="primary"),
            InlineKeyboardButton("❌ Rᴇᴍᴏᴠᴇ", callback_data=f"admin_del_auth_{u['user_id']}", style="danger")
        ])
    buttons.append([
        InlineKeyboardButton("➕ Aᴅᴅ Aᴜᴛʜ Usᴇʀ", callback_data="admin_add_auth_prompt", style="success")
    ])
    buttons.append([
        InlineKeyboardButton("Bᴀᴄᴋ Tᴏ Dᴀsʜʙᴏᴀʀᴅ", callback_data="admin_back", style="primary"),
        InlineKeyboardButton("Cʟᴏsᴇ", callback_data="admin_close", style="danger")
    ])
    return InlineKeyboardMarkup(buttons)


def get_clones_panel_markup(page: int = 0) -> InlineKeyboardMarkup:
    from core.db import get_all_cloned_bots
    clones = get_all_cloned_bots(status=None)
    page_size = 5
    total_pages = max(1, (len(clones) + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * page_size
    current_clones = clones[start_idx:start_idx + page_size]
    
    buttons = []
    for c in current_clones:
        u_name = c.get("bot_username") or str(c["bot_id"])
        o_id = c.get("owner_id", 0)
        buttons.append([
            InlineKeyboardButton(f"@{u_name} (Owner: {o_id})", callback_data="admin_noop", style="primary"),
            InlineKeyboardButton("🗑️ Dᴇʟᴇᴛᴇ", callback_data=f"admin_del_clone_{c['bot_id']}", style="danger")
        ])
        
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("◀ Pʀᴇᴠ", callback_data=f"admin_clones_panel|{page-1}", style="primary"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Nᴇxᴛ ▶", callback_data=f"admin_clones_panel|{page+1}", style="primary"))
    if nav_row:
        buttons.append(nav_row)
        
    buttons.append([
        InlineKeyboardButton("Bᴀᴄᴋ Tᴏ Dᴀsʜʙᴏᴀʀᴅ", callback_data="admin_back", style="primary"),
        InlineKeyboardButton("Cʟᴏsᴇ", callback_data="admin_close", style="danger")
    ])
    return InlineKeyboardMarkup(buttons)


def get_playmode_panel(chat_id: int, current_mode: str) -> tuple[str, InlineKeyboardMarkup]:
    from core.fonts import HEADER
    mode_name_map = {
        "user": "Usᴇʀ Mᴏᴅᴇ (Everyone)",
        "admin": "Aᴅᴍɪɴ Mᴏᴅᴇ (Admins Only)",
        "auth": "Aᴜᴛʜ Mᴏᴅᴇ (Authorized Only)"
    }
    mode_display = mode_name_map.get(current_mode, "Usᴇʀ Mᴏᴅᴇ (Everyone)")

    caption = (
        f"{HEADER}"
        f"‣ <b>Pʟᴀʏ Mᴏᴅᴇ Sᴇᴛᴛɪɴɢs</b>\n"
        f"‣ <b>Cᴜʀʀᴇɴᴛ Mᴏᴅᴇ :</b> <code>{mode_display}</code>\n\n"
        f"<i>Neeche se is group ka play mode select karein:</i>\n\n"
        f"• <b>Usᴇʀ Mᴏᴅᴇ :</b> Har koi movie search aur play kar sakta hai.\n"
        f"• <b>Aᴅᴍɪɴ Mᴏᴅᴇ :</b> Sirf group admins movie play kar sakte hain.\n"
        f"• <b>Aᴜᴛʜ Mᴏᴅᴇ :</b> Sirf authorized users aur admins movie play kar sakte hain."
    )

    is_u = (current_mode == "user")
    is_adm = (current_mode == "admin")
    is_ath = (current_mode == "auth")

    buttons = [
        [
            InlineKeyboardButton(
                f"{'[Active] ' if is_u else ''}Usᴇʀ Mᴏᴅᴇ (Everyone)",
                callback_data=f"set_pm_user_{chat_id}",
                style="success" if is_u else "primary"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'[Active] ' if is_adm else ''}Aᴅᴍɪɴ Mᴏᴅᴇ (Admins Only)",
                callback_data=f"set_pm_admin_{chat_id}",
                style="success" if is_adm else "primary"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'[Active] ' if is_ath else ''}Aᴜᴛʜ Mᴏᴅᴇ (Authorized Only)",
                callback_data=f"set_pm_auth_{chat_id}",
                style="success" if is_ath else "primary"
            )
        ],
        [
            InlineKeyboardButton("Cʟᴏsᴇ", callback_data=f"close_pm_{chat_id}", style="danger")
        ]
    ]
    return caption, InlineKeyboardMarkup(buttons)


def register(app: Client):

    def is_admin_filter(_, __, message: Message) -> bool:
        user_id = message.from_user.id if message.from_user else 0
        return user_id in (Config.OWNER_ID, 6805412676) or is_sudo_user(user_id)

    # ─── /admin command ────────────────────────────────────────────────────────
    @app.on_message(filters.command("admin") & filters.private & filters.create(is_admin_filter))
    async def admin_panel(client: Client, message: Message):
        admin_states.pop(message.from_user.id, None)
        cpu_usage = await get_cpu_usage()
        ram_usage = psutil.virtual_memory().percent if psutil else "N/A"
        await send_styled(
            client=client,
            chat_id=message.chat.id,
            text=(
                f"{ROYAL_HEADER}"
                f"Welcome to the Movie Hub control dashboard, Owner.\n\n"
                f"‣ <b>System Status:</b>\n"
                f"• CPU Usage: <code>{cpu_usage}%</code>\n"
                f"• RAM Usage: <code>{ram_usage}%</code>\n\n"
                f"‣ <b>Quick Guide:</b>\n"
                f"• <b>Bʀᴏᴀᴅᴄᴀsᴛ</b>: Send announcement to all groups.\n"
                f"• <b>Bᴄ Gʀᴏᴜᴘs</b>: Toggle group broadcast targets ([ON] = receive, [OFF] = skip).\n"
                f"• <b>Wᴇʟᴄᴏᴍᴇ Sᴇᴛᴛɪɴɢs</b>: Toggle welcome cards per group.\n"
                f"• <b>Bᴏᴛ Sᴛᴀᴛᴜs</b>: Toggle bot per group.\n\n"
                f"Select an operation below:"
            ),
            markup=get_admin_panel_markup()
        )

    # ─── Welcome/Start video upload ───────────────────────────────────────────
    @app.on_message(filters.video & filters.private & filters.create(is_admin_filter))
    async def admin_video_upload(client: Client, message: Message):
        uid = message.from_user.id if message.from_user else 0
        state = admin_states.get(uid)
        if state not in ("waiting_for_start_video", "waiting_for_welcome_video"):
            return
        file_id = message.video.file_id
        key = "start_video_file_id" if state == "waiting_for_start_video" else "welcome_video_file_id"
        label = "Start Video" if state == "waiting_for_start_video" else "Welcome Video"
        custom_key = "start_video_custom" if state == "waiting_for_start_video" else "welcome_video_custom"
        from core.db import set_setting
        set_setting(key, file_id)
        set_setting(custom_key, "true")
        admin_states.pop(uid, None)
        await send_styled(
            client=client,
            chat_id=message.chat.id,
            text=(
                f"{ROYAL_HEADER}"
                f"<b>{label} Updated!</b>\n\n"
                f"Naya video successfully save ho gaya hai."
            ),
            markup=get_admin_panel_markup()
        )

    # ─── Broadcast text interceptor ───────────────────────────────────────────
    @app.on_message(filters.text & filters.private & filters.create(is_admin_filter))
    async def admin_text_interceptor(client: Client, message: Message):
        uid = message.from_user.id if message.from_user else 0
        state = admin_states.get(uid)

        if state == "waiting_for_auth_user_id":
            admin_states.pop(uid, None)
            text = message.text.strip()
            target_uid = None
            target_username = ""
            target_first_name = ""
            try:
                if text.isdigit():
                    target_uid = int(text)
                else:
                    u_obj = await client.get_users(text)
                    if u_obj:
                        target_uid = u_obj.id
                        target_username = u_obj.username or ""
                        target_first_name = u_obj.first_name or ""
            except Exception:
                pass

            if not target_uid:
                await send_styled(
                    client=client,
                    chat_id=message.chat.id,
                    text=f"{ROYAL_HEADER}<b>Invalid User ID ya Username!</b>\nKripya valid numeric User ID ya @username bhejein.",
                    markup=get_auth_panel_markup()
                )
                return

            from core.db import add_global_auth_user
            add_global_auth_user(target_uid, target_username, target_first_name, added_by=uid)
            await send_styled(
                client=client,
                chat_id=message.chat.id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"✅ <b>Usᴇʀ Aᴜᴛʜᴏʀɪᴢᴇᴅ!</b>\n\n"
                    f"‣ <b>User ID:</b> <code>{target_uid}</code>\n"
                    f"‣ <b>Username:</b> @{target_username or 'N/A'}\n\n"
                    f"<i>Yeh user ab globally authorized hai.</i>"
                ),
                markup=get_auth_panel_markup()
            )
            return

        if state != "waiting_for_broadcast":
            return
        admin_states.pop(uid, None)

        groups = get_broadcast_groups()
        enabled_groups = [g for g in groups if g.get("enabled", 1)]

        if not enabled_groups:
            await send_styled(
                client=client,
                chat_id=message.chat.id,
                text=f"{ROYAL_HEADER}<b>Koi broadcast group nahi mila!</b>",
                markup=get_admin_panel_markup()
            )
            return

        status_msg = await message.reply_text(
            f"{ROYAL_HEADER}<b>Broadcasting...</b>\n<i>0 / {len(enabled_groups)} groups</i>",
            parse_mode=enums.ParseMode.HTML
        )

        success = 0
        failed = 0
        for i, g in enumerate(enabled_groups):
            try:
                await client.send_message(g["chat_id"], message.text, parse_mode=enums.ParseMode.HTML)
                success += 1
            except Exception as e:
                print(f"[Broadcast] Failed for {g['chat_id']}: {e}")
                failed += 1
            if (i + 1) % 5 == 0:
                try:
                    await status_msg.edit_text(
                        f"{ROYAL_HEADER}<b>Broadcasting...</b>\n<i>{i+1} / {len(enabled_groups)} groups</i>",
                        parse_mode=enums.ParseMode.HTML
                    )
                except:
                    pass
            await asyncio.sleep(0.3)

        await send_styled(
            client=client,
            chat_id=message.chat.id,
            text=(
                f"{ROYAL_HEADER}"
                f"<b>Bʀᴏᴀᴅᴄᴀsᴛ Cᴏᴍᴘʟᴇᴛᴇᴅ!</b>\n\n"
                f"‣ Sent: <code>{success}</code>\n"
                f"‣ Failed: <code>{failed}</code>"
            ),
            markup=get_admin_panel_markup(),
            message_id=status_msg.id
        )

    # ─── Admin callback handler ───────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^admin_"))
    async def admin_callback(client: Client, query: CallbackQuery):
        user_id = query.from_user.id if query.from_user else 0
        if user_id not in (Config.OWNER_ID, 6805412676) and not is_sudo_user(user_id):
            await query.answer("Access Denied!", show_alert=True)
            return

        data = query.data
        chat_id = query.message.chat.id

        if data == "admin_close":
            admin_states.pop(user_id, None)
            await query.answer("Closing...")
            await query.message.delete()
            return

        elif data == "admin_back":
            admin_states.pop(user_id, None)
            await query.answer("Back...")
            cpu_usage = await get_cpu_usage()
            ram_usage = psutil.virtual_memory().percent if psutil else "N/A"
            await send_styled(
                client=client,
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"Welcome to the Movie Hub control dashboard, Owner.\n\n"
                    f"‣ <b>System Status:</b>\n"
                    f"• CPU Usage: <code>{cpu_usage}%</code>\n"
                    f"• RAM Usage: <code>{ram_usage}%</code>\n\n"
                    f"Select an operation below:"
                ),
                markup=get_admin_panel_markup(),
                message_id=query.message.id
            )

        elif data == "admin_bc_prompt":
            await query.answer("Broadcast mode activated!")
            admin_states[user_id] = "waiting_for_broadcast"
            await send_styled(
                client=client,
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"<b>Bʀᴏᴀᴅᴄᴀsᴛ Mᴏᴅᴇ Aᴄᴛɪᴠᴇ!</b>\n\n"
                    f"Ab aap jo bhi text message bhejenge,\nwoh saare enabled groups mein broadcast ho jayega.\n\n"
                    f"<i>Cancel karne ke liye /admin dobara type karein.</i>"
                ),
                message_id=query.message.id
            )

        elif data.startswith("admin_groups|"):
            page = int(data.split("|")[1])
            groups = get_broadcast_groups()
            if not groups:
                await query.answer("No groups found!", show_alert=True)
                return
            await query.answer()
            await send_styled(
                client=client,
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"<b>Bʀᴏᴀᴅᴄᴀsᴛ Gʀᴏᴜᴘs</b> — Page {page + 1}\n\n"
                    f"Total: <code>{len(groups)}</code> groups\n"
                    f"[ON] = Broadcast enabled | [OFF] = Skipped\n\n"
                    f"<i>Group par click karo toggle karne ke liye:</i>"
                ),
                markup=get_groups_markup(groups, page),
                message_id=query.message.id
            )

        elif data.startswith("admin_toggle|"):
            parts = data.split("|")
            toggle_chat_id = int(parts[1])
            page = int(parts[2])
            groups = get_broadcast_groups()
            group = next((g for g in groups if g["chat_id"] == toggle_chat_id), None)
            if not group:
                await query.answer("Group not found!", show_alert=True)
                return
            new_state = not bool(group.get("enabled", 1))
            set_group_broadcast_enabled(toggle_chat_id, new_state)
            await query.answer(f"{'Enabled [ON]' if new_state else 'Disabled [OFF]'}")
            groups = get_broadcast_groups()
            await send_styled(
                client=client,
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"<b>Bʀᴏᴀᴅᴄᴀsᴛ Gʀᴏᴜᴘs</b> — Page {page + 1}\n\n"
                    f"Total: <code>{len(groups)}</code> groups\n"
                    f"[ON] = Broadcast enabled | [OFF] = Skipped"
                ),
                markup=get_groups_markup(groups, page),
                message_id=query.message.id
            )

        elif data.startswith("admin_welcome_groups|"):
            page = int(data.split("|")[1])
            groups = get_broadcast_groups()
            if not groups:
                await query.answer("No groups found!", show_alert=True)
                return
            await query.answer()
            await send_styled(
                client=client,
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"<b>Wᴇʟᴄᴏᴍᴇ Sᴇᴛᴛɪɴɢs</b> — Page {page + 1}\n\n"
                    f"[ON] = Welcome enabled | [OFF] = Welcome disabled\n\n"
                    f"<i>Group par click karo toggle karne ke liye:</i>"
                ),
                markup=get_welcome_groups_markup(groups, page),
                message_id=query.message.id
            )

        elif data.startswith("admin_welcome_toggle|"):
            parts = data.split("|")
            toggle_chat_id = int(parts[1])
            page = int(parts[2])
            groups = get_broadcast_groups()
            group = next((g for g in groups if g["chat_id"] == toggle_chat_id), None)
            if not group:
                await query.answer("Group not found!", show_alert=True)
                return
            current = group.get("welcome_enabled", 1)
            if current is None:
                current = 1
            new_state = not bool(current)
            set_group_welcome_enabled(toggle_chat_id, new_state)
            await query.answer(f"Welcome {'Enabled [ON]' if new_state else 'Disabled [OFF]'}")
            groups = get_broadcast_groups()
            await send_styled(
                client=client,
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"<b>Wᴇʟᴄᴏᴍᴇ Sᴇᴛᴛɪɴɢs</b> — Page {page + 1}\n\n"
                    f"[ON] = Welcome enabled | [OFF] = Welcome disabled"
                ),
                markup=get_welcome_groups_markup(groups, page),
                message_id=query.message.id
            )

        elif data.startswith("admin_status_groups|"):
            page = int(data.split("|")[1])
            groups = get_broadcast_groups()
            if not groups:
                await query.answer("No groups found!", show_alert=True)
                return
            await query.answer()
            await send_styled(
                client=client,
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"<b>Bᴏᴛ Sᴛᴀᴛᴜs</b> — Page {page + 1}\n\n"
                    f"[ON] = Bot active | [OFF] = Bot disabled\n\n"
                    f"<i>Group par click karo toggle karne ke liye:</i>"
                ),
                markup=get_status_groups_markup(groups, page),
                message_id=query.message.id
            )

        elif data.startswith("admin_status_toggle|"):
            parts = data.split("|")
            toggle_chat_id = int(parts[1])
            page = int(parts[2])
            groups = get_broadcast_groups()
            group = next((g for g in groups if g["chat_id"] == toggle_chat_id), None)
            if not group:
                await query.answer("Group not found!", show_alert=True)
                return
            bot_active = group.get("bot_active", 1)
            if bot_active is None:
                bot_active = 1
            new_state = not bool(bot_active)
            set_group_bot_active(toggle_chat_id, new_state)
            await query.answer(f"Bot {'Active [ON]' if new_state else 'Disabled [OFF]'}")
            groups = get_broadcast_groups()
            await send_styled(
                client=client,
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"<b>Bᴏᴛ Sᴛᴀᴛᴜs</b> — Page {page + 1}\n\n"
                    f"[ON] = Bot active | [OFF] = Bot disabled"
                ),
                markup=get_status_groups_markup(groups, page),
                message_id=query.message.id
            )

        elif data == "admin_quality_panel":
            await query.answer("Quality & FPS Manager")
            from core.player import get_configured_video_parameters
            _, active_q, active_fps, _ = get_configured_video_parameters()
            await send_styled(
                client=client,
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"<b>Vɪᴅᴇᴏ Qᴜᴀʟɪᴛʏ & Fᴘs Mᴀɴᴀɢᴇʀ</b>\n\n"
                    f"Current Active Stream Target:\n"
                    f"‣ <b>Target Quality:</b> <code>{active_q}</code>\n"
                    f"‣ <b>Framerate Mode:</b> <code>{active_fps} FPS</code>\n\n"
                    f"<i>Select your preferred resolution or framerate below. All Telegram video streams will extract using these quality settings!</i>"
                ),
                markup=get_quality_panel_markup(),
                message_id=query.message.id
            )

        elif data.startswith("admin_set_q_"):
            new_q = data.replace("admin_set_q_", "")
            from core.db import set_setting
            set_setting("quality_pref", new_q)
            await query.answer(f"Quality updated to {new_q}!", show_alert=True)
            from core.player import get_configured_video_parameters
            _, active_q, active_fps, _ = get_configured_video_parameters()
            await send_styled(
                client=client,
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"<b>Vɪᴅᴇᴏ Qᴜᴀʟɪᴛʏ & Fᴘs Mᴀɴᴀɢᴇʀ</b>\n\n"
                    f"Current Active Stream Target:\n"
                    f"‣ <b>Target Quality:</b> <code>{active_q}</code>\n"
                    f"‣ <b>Framerate Mode:</b> <code>{active_fps} FPS</code>\n\n"
                    f"<i>Select your preferred resolution or framerate below. All Telegram video streams will extract using these quality settings!</i>"
                ),
                markup=get_quality_panel_markup(),
                message_id=query.message.id
            )

        elif data.startswith("admin_set_fps_"):
            new_fps = data.replace("admin_set_fps_", "")
            from core.db import set_setting
            set_setting("fps_pref", new_fps)
            await query.answer(f"FPS mode updated to {new_fps} FPS!", show_alert=True)
            from core.player import get_configured_video_parameters
            _, active_q, active_fps, _ = get_configured_video_parameters()
            await send_styled(
                client=client,
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"<b>Vɪᴅᴇᴏ Qᴜᴀʟɪᴛʏ & Fᴘs Mᴀɴᴀɢᴇʀ</b>\n\n"
                    f"Current Active Stream Target:\n"
                    f"‣ <b>Target Quality:</b> <code>{active_q}</code>\n"
                    f"‣ <b>Framerate Mode:</b> <code>{active_fps} FPS</code>\n\n"
                    f"<i>Select your preferred resolution or framerate below. All Telegram video streams will extract using these quality settings!</i>"
                ),
                markup=get_quality_panel_markup(),
                message_id=query.message.id
            )

        elif data == "admin_manage_videos":
            await query.answer("Video Manager")
            admin_states[user_id] = None
            await send_styled(
                client=client,
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"<b>Vɪᴅᴇᴏ Mᴀɴᴀɢᴇʀ</b>\n\n"
                    f"Videos update karne ke liye neeche button dabao, phir video send karo:\n\n"
                    f"‣ <b>Start Video:</b> /start command par jo video aata hai\n"
                    f"‣ <b>Welcome Video:</b> Naye member aane par jo video aata hai"
                ),
                markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Uᴘᴅᴀᴛᴇ Sᴛᴀʀᴛ Vɪᴅᴇᴏ", callback_data="admin_set_start_video", style="primary")],
                    [InlineKeyboardButton("Uᴘᴅᴀᴛᴇ Wᴇʟᴄᴏᴍᴇ Vɪᴅᴇᴏ", callback_data="admin_set_welcome_video", style="primary")],
                    [
                        InlineKeyboardButton("Bᴀᴄᴋ", callback_data="admin_back", style="primary"),
                        InlineKeyboardButton("Cʟᴏsᴇ", callback_data="admin_close", style="danger")
                    ]
                ]),
                message_id=query.message.id
            )

        elif data == "admin_set_start_video":
            admin_states[user_id] = "waiting_for_start_video"
            await query.answer("Send new start video!")
            await send_styled(
                client=client,
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"<b>Sᴛᴀʀᴛ Vɪᴅᴇᴏ Uᴘᴅᴀᴛᴇ Mᴏᴅᴇ</b>\n\n"
                    f"Ab aap jo video bhejenge woh /start ka naya video ban jayega.\n\n"
                    f"<i>Cancel ke liye /admin type karein.</i>"
                ),
                message_id=query.message.id
            )

        elif data == "admin_set_welcome_video":
            admin_states[user_id] = "waiting_for_welcome_video"
            await query.answer("Send new welcome video!")
            await send_styled(
                client=client,
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"<b>Wᴇʟᴄᴏᴍᴇ Vɪᴅᴇᴏ Uᴘᴅᴀᴛᴇ Mᴏᴅᴇ</b>\n\n"
                    f"Ab aap jo video bhejenge woh naye members ke liye naya welcome video ban jayega.\n\n"
                    f"<i>Cancel ke liye /admin type karein.</i>"
                ),
                message_id=query.message.id
            )

        elif data == "admin_auth_panel":
            await query.answer("Authorized Users")
            admin_states[user_id] = None
            from core.db import get_global_auth_users
            users = get_global_auth_users()
            caption = (
                f"{ROYAL_HEADER}"
                f"<b>Aᴜᴛʜᴏʀɪᴢᴇᴅ Usᴇʀs Mᴀɴᴀɢᴇʀ</b>\n\n"
                f"Total Authorized Users: <code>{len(users)}</code>\n\n"
                f"<i>Yeh users bot ko control kar sakte hain aur playback manage kar sakte hain bina group admin bane.</i>\n\n"
                f"<i>Naya user add karne ke liye 'Add Auth User' button dabayein ya <code>/auth &lt;id&gt;</code> use karein.</i>"
            )
            await send_styled(
                client=client,
                chat_id=chat_id,
                text=caption,
                markup=get_auth_panel_markup(),
                message_id=query.message.id
            )

        elif data == "admin_add_auth_prompt":
            admin_states[user_id] = "waiting_for_auth_user_id"
            await query.answer("Send User ID or Username")
            await send_styled(
                client=client,
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"<b>Aᴅᴅ Aᴜᴛʜ Usᴇʀ Mᴏᴅᴇ</b>\n\n"
                    f"Kripya us user ka <b>Telegram User ID</b> ya <b>@username</b> chat mein bhejein.\n\n"
                    f"<i>Cancel karne ke liye /admin type karein.</i>"
                ),
                message_id=query.message.id
            )

        elif data.startswith("admin_del_auth_"):
            target_uid = int(data.replace("admin_del_auth_", ""))
            from core.db import remove_global_auth_user
            remove_global_auth_user(target_uid)
            await query.answer(f"Removed User {target_uid} from Auth!", show_alert=True)
            await send_styled(
                client=client,
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"<b>Aᴜᴛʜᴏʀɪᴢᴇᴅ Usᴇʀs Mᴀɴᴀɢᴇʀ</b>\n\n"
                    f"User <code>{target_uid}</code> ko remove kar diya gaya hai."
                ),
                markup=get_auth_panel_markup(),
                message_id=query.message.id
            )

        elif data.startswith("admin_clones_panel"):
            parts = data.split("|")
            page = int(parts[1]) if len(parts) > 1 else 0
            await query.answer("Clone Bots Manager")
            admin_states[user_id] = None
            from core.db import get_all_cloned_bots
            clones = get_all_cloned_bots(status=None)
            caption = (
                f"{ROYAL_HEADER}"
                f"<b>Cʟᴏɴᴇ Bᴏᴛs Mᴀɴᴀɢᴇʀ</b>\n\n"
                f"Total Cloned Bots: <code>{len(clones)}</code>\n\n"
                f"<i>Yeh bots hamare shared engine se live stream kar rahe hain.</i>\n\n"
                f"<i>Kisi bot ko band karne ke liye 'Delete' button click karein.</i>"
            )
            await send_styled(
                client=client,
                chat_id=chat_id,
                text=caption,
                markup=get_clones_panel_markup(page),
                message_id=query.message.id
            )

        elif data.startswith("admin_del_clone_"):
            bot_id_to_del = int(data.replace("admin_del_clone_", ""))
            from core.clone_manager import clone_manager
            await clone_manager.delete_clone(bot_id_to_del)
            await query.answer("Clone bot stopped and deleted!", show_alert=True)
            await send_styled(
                client=client,
                chat_id=chat_id,
                text=(
                    f"{ROYAL_HEADER}"
                    f"<b>Cʟᴏɴᴇ Bᴏᴛs Mᴀɴᴀɢᴇʀ</b>\n\n"
                    f"Bot ID <code>{bot_id_to_del}</code> ko stop aur delete kar diya gaya hai."
                ),
                markup=get_clones_panel_markup(0),
                message_id=query.message.id
            )

        elif data == "admin_noop":
            await query.answer()

    @app.on_callback_query(filters.regex(r"^REQ\|"))
    async def request_action_callback(client: Client, query: CallbackQuery):
        user_id = query.from_user.id if query.from_user else 0
        if user_id not in (Config.OWNER_ID, 6805412676) and not is_sudo_user(user_id):
            await query.answer("Access Denied!", show_alert=True)
            return
            
        parts = query.data.split("|")
        action = parts[1]
        req_id = int(parts[2])
        
        try:
            await query.answer()
        except:
            pass
            
        from core.db import get_movie_request, update_request_status, delete_movie_request
        req = get_movie_request(req_id)
        if not req:
            await query.answer("Request details not found (already deleted).", show_alert=True)
            await query.message.delete()
            return
            
        if action == "add":
            # Update status in db
            update_request_status(req_id, "Completed")
            
            # Edit Owner's message to reflect completed status
            alert_caption = (
                f"{ROYAL_HEADER}"
                f"<b>Mᴏᴠɪᴇ Rᴇǫᴜᴇsᴛ Aᴅᴅᴇᴅ</b>\n\n"
                f"‣ <b>Movie:</b> <code>{req['movie_name']}</code>\n"
                f"‣ <b>User:</b> {req['first_name']} (@{req['username'] or 'N/A'}) [ID: <code>{req['user_id']}</code>]\n"
                f"‣ <b>Chat:</b> {req['chat_title']} [ID: <code>{req['chat_id']}</code>]\n"
                f"‣ <b>Status:</b> Completed / Added"
            )
            await send_styled(client=client, chat_id=query.message.chat.id, text=alert_caption, message_id=query.message.id)
            
            # Send notification to the chat where the request originated!
            notify_text = (
                f"{ROYAL_HEADER}"
                f"<b>Rᴇǫᴜᴇsᴛ Cᴏᴍᴘʟᴇᴛᴇᴅ!</b>\n\n"
                f"Aapki requested movie <b>{req['movie_name']}</b> ab platform par available hai!\n\n"
                f"Play karne ke liye abhi click karein:\n"
                f"<code>/movie {req['movie_name']}</code>"
            )
            try:
                await client.send_message(chat_id=req["chat_id"], text=notify_text, parse_mode=enums.ParseMode.HTML)
            except Exception as notify_err:
                print(f"[Admin Plugin] Failed to send notification to chat {req['chat_id']}: {notify_err}")
                
        elif action == "reject":
            # Delete request from db
            delete_movie_request(req_id)
            
            # Edit Owner's message to reflect deleted status
            alert_caption = (
                f"{ROYAL_HEADER}"
                f"<b>Mᴏᴠɪᴇ Rᴇǫᴜᴇsᴛ Dᴇʟᴇᴛᴇᴅ</b>\n\n"
                f"‣ <b>Movie:</b> <code>{req['movie_name']}</code>\n"
                f"‣ <b>User:</b> {req['first_name']} (@{req['username'] or 'N/A'})\n"
                f"‣ <b>Status:</b> Rejected / Deleted"
            )
            await send_styled(client=client, chat_id=query.message.chat.id, text=alert_caption, message_id=query.message.id)

    # ─── /auth, /unauth, /authusers, and /playmode commands ──────────────────
    @app.on_message(filters.command(["auth", "authorize"]))
    async def auth_cmd_handler(client: Client, message: Message):
        chat_id = message.chat.id
        sender = message.from_user
        sender_id = sender.id if sender else 0
        is_priv = message.chat.type == enums.ChatType.PRIVATE

        if is_priv:
            if sender_id not in (Config.OWNER_ID, 6805412676) and not is_sudo_user(sender_id):
                return
        else:
            from core.db import is_group_admin
            admin_ok = await is_group_admin(client, chat_id, sender_id)
            if not admin_ok:
                await message.reply_text(
                    f"{ROYAL_HEADER}<b>Sirf Group Admins kisi user ko authorize kar sakte hain!</b>",
                    parse_mode=enums.ParseMode.HTML
                )
                return

        target_uid = None
        target_name = ""
        target_username = ""

        if message.reply_to_message and message.reply_to_message.from_user:
            u = message.reply_to_message.from_user
            target_uid = u.id
            target_name = u.first_name or ""
            target_username = u.username or ""
        elif len(message.command) > 1:
            raw = message.command[1].strip()
            if raw.isdigit():
                target_uid = int(raw)
            else:
                if raw.startswith("@"):
                    raw = raw[1:]
                try:
                    u = await client.get_users(raw)
                    if u:
                        target_uid = u.id
                        target_name = u.first_name or ""
                        target_username = u.username or ""
                except Exception:
                    pass

        if not target_uid:
            await message.reply_text(
                f"{ROYAL_HEADER}"
                f"<b>Usage:</b> Kisi user ke message par reply karke <code>/auth</code> likhein ya <code>/auth @username</code> use karein.",
                parse_mode=enums.ParseMode.HTML
            )
            return

        uname_str = f" (@{target_username})" if target_username else ""

        if is_priv:
            from core.db import add_global_auth_user
            add_global_auth_user(target_uid, target_username, target_name, added_by=sender_id)
            await message.reply_text(
                f"{ROYAL_HEADER}"
                f"✅ <b>Usᴇʀ Gʟᴏʙᴀʟʟʏ Aᴜᴛʜᴏʀɪᴢᴇᴅ!</b>\n\n"
                f"‣ <b>User ID:</b> <code>{target_uid}</code>\n"
                f"‣ <b>Name:</b> {target_name or 'User'}{uname_str}\n\n"
                f"<i>Yeh user ab globally authorized hai.</i>",
                parse_mode=enums.ParseMode.HTML
            )
        else:
            from core.db import add_auth_user
            add_auth_user(
                chat_id=chat_id,
                user_id=target_uid,
                username=target_username,
                first_name=target_name,
                added_by=sender_id
            )
            await message.reply_text(
                f"{ROYAL_HEADER}"
                f"✅ <b>Usᴇʀ Aᴜᴛʜᴏʀɪᴢᴇᴅ Sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n"
                f"‣ <b>Nᴀᴍᴇ :</b> <b>{target_name or 'User'}</b>{uname_str}\n"
                f"‣ <b>Usᴇʀ ID :</b> <code>{target_uid}</code>\n"
                f"‣ <b>Aᴅᴅᴇᴅ Bʏ :</b> {sender.first_name if sender else 'Admin'}\n\n"
                f"<i>Yeh user ab is group mein movie search aur playback controls use kar sakta hai.</i>",
                parse_mode=enums.ParseMode.HTML
            )

    @app.on_message(filters.command(["unauth", "deauth"]))
    async def unauth_cmd_handler(client: Client, message: Message):
        chat_id = message.chat.id
        sender = message.from_user
        sender_id = sender.id if sender else 0
        is_priv = message.chat.type == enums.ChatType.PRIVATE

        if is_priv:
            if sender_id not in (Config.OWNER_ID, 6805412676) and not is_sudo_user(sender_id):
                return
        else:
            from core.db import is_group_admin
            admin_ok = await is_group_admin(client, chat_id, sender_id)
            if not admin_ok:
                await message.reply_text(
                    f"{ROYAL_HEADER}<b>Sirf Group Admins kisi user ko unauthorize kar sakte hain!</b>",
                    parse_mode=enums.ParseMode.HTML
                )
                return

        target_uid = None
        if message.reply_to_message and message.reply_to_message.from_user:
            target_uid = message.reply_to_message.from_user.id
        elif len(message.command) > 1:
            raw = message.command[1].strip()
            if raw.isdigit():
                target_uid = int(raw)
            else:
                if raw.startswith("@"):
                    raw = raw[1:]
                try:
                    u = await client.get_users(raw)
                    if u:
                        target_uid = u.id
                except Exception:
                    pass

        if not target_uid:
            await message.reply_text(
                f"{ROYAL_HEADER}"
                f"<b>Usage:</b> Kisi user ke message par reply karke <code>/unauth</code> likhein ya <code>/unauth @username</code> use karein.",
                parse_mode=enums.ParseMode.HTML
            )
            return

        if is_priv:
            from core.db import remove_global_auth_user
            remove_global_auth_user(target_uid)
            await message.reply_text(
                f"{ROYAL_HEADER}"
                f"❌ <b>Usᴇʀ Gʟᴏʙᴀʟʟʏ Uɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ!</b>\n\n"
                f"‣ <b>User ID:</b> <code>{target_uid}</code>\n"
                f"<i>Is user se global authorization permissions hata di gayi hain.</i>",
                parse_mode=enums.ParseMode.HTML
            )
        else:
            from core.db import remove_auth_user
            remove_auth_user(chat_id, target_uid)
            await message.reply_text(
                f"{ROYAL_HEADER}"
                f"❌ <b>Usᴇʀ Uɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ!</b>\n\n"
                f"‣ <b>User ID:</b> <code>{target_uid}</code>\n"
                f"<i>Is user se is group ki authorization permissions hata di gayi hain.</i>",
                parse_mode=enums.ParseMode.HTML
            )

    @app.on_message(filters.command(["authusers", "authlist"]) & filters.group)
    async def authusers_cmd_handler(client: Client, message: Message):
        chat_id = message.chat.id
        from core.db import get_auth_users
        users = get_auth_users(chat_id)
        if not users:
            await message.reply_text(
                f"{ROYAL_HEADER}"
                f"<b>Is group mein koi authorized user nahi hai.</b>\n\n"
                f"Naya user add karne ke liye kisi user ke message par reply karke <code>/auth</code> likhein.",
                parse_mode=enums.ParseMode.HTML
            )
            return

        lines = [
            f"{ROYAL_HEADER}",
            f"<b>Aᴜᴛʜᴏʀɪᴢᴇᴅ Usᴇʀs Lɪsᴛ</b>\n",
            f"Total: <code>{len(users)}</code> users\n"
        ]
        for idx, u in enumerate(users, 1):
            name = u.get("first_name") or "User"
            uname = f" (@{u['username']})" if u.get("username") else ""
            lines.append(f"{idx}. <b>{name}</b>{uname} [<code>{u['user_id']}</code>]")

        await message.reply_text("\n".join(lines), parse_mode=enums.ParseMode.HTML)

    @app.on_message(filters.command(["playmode", "mode"]) & filters.group)
    async def playmode_cmd_handler(client: Client, message: Message):
        chat_id = message.chat.id
        sender = message.from_user
        sender_id = sender.id if sender else 0

        from core.db import is_group_admin, get_play_mode, set_play_mode
        admin_ok = await is_group_admin(client, chat_id, sender_id)
        if not admin_ok:
            await message.reply_text(
                f"{ROYAL_HEADER}<b>Sirf Group Admins play mode change kar sakte hain!</b>",
                parse_mode=enums.ParseMode.HTML
            )
            return

        if len(message.command) > 1:
            target = message.command[1].lower().strip()
            if target in ("user", "everyone", "all"):
                set_play_mode(chat_id, "user")
                await message.reply_text(
                    f"{ROYAL_HEADER}✅ Play mode <b>Usᴇʀ Mᴏᴅᴇ (Everyone)</b> set kar diya gaya hai!\n\nAb group ka har member movie search aur play kar sakta hai.",
                    parse_mode=enums.ParseMode.HTML
                )
                return
            elif target in ("admin", "admins"):
                set_play_mode(chat_id, "admin")
                await message.reply_text(
                    f"{ROYAL_HEADER}✅ Play mode <b>Aᴅᴍɪɴ Mᴏᴅᴇ</b> set kar diya gaya hai!\n\nAb sirf group admins movie play aur controls use kar sakte hain.",
                    parse_mode=enums.ParseMode.HTML
                )
                return
            elif target in ("auth", "authorized"):
                set_play_mode(chat_id, "auth")
                await message.reply_text(
                    f"{ROYAL_HEADER}✅ Play mode <b>Aᴜᴛʜ Mᴏᴅᴇ</b> set kar diya gaya hai!\n\nAb sirf authorized users aur admins movie play aur controls use kar sakte hain.",
                    parse_mode=enums.ParseMode.HTML
                )
                return

        curr_mode = get_play_mode(chat_id)
        caption, markup = get_playmode_panel(chat_id, curr_mode)
        await send_styled(client=client, chat_id=chat_id, text=caption, markup=markup)

    @app.on_callback_query(filters.regex(r"^(set_pm_|close_pm_)"))
    async def playmode_callback_handler(client: Client, query: CallbackQuery):
        chat_id = query.message.chat.id
        data = query.data
        user = query.from_user
        user_id = user.id if user else 0

        from core.db import is_group_admin, get_play_mode, set_play_mode
        admin_ok = await is_group_admin(client, chat_id, user_id)
        if not admin_ok:
            await query.answer("Sirf Group Admins play mode change kar sakte hain!", show_alert=True)
            return

        if data.startswith("close_pm_"):
            try:
                await query.message.delete()
            except Exception:
                pass
            return

        if data.startswith("set_pm_"):
            parts = data.split("_")
            new_mode = parts[2]
            target_chat_id = int(parts[3])
            set_play_mode(target_chat_id, new_mode)

            mode_labels = {
                "user": "User Mode (Everyone)",
                "admin": "Admin Mode (Admins Only)",
                "auth": "Auth Mode (Authorized Only)"
            }
            await query.answer(f"Play mode updated to {mode_labels.get(new_mode, new_mode)}!", show_alert=True)

            caption, markup = get_playmode_panel(target_chat_id, new_mode)
            await send_styled(client=client, chat_id=target_chat_id, text=caption, markup=markup, message_id=query.message.id)
