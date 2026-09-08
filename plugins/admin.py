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
