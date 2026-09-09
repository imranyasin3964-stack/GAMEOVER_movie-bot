"""
GameOver Movie Hub — Clone Bot Plugin
Handles /clone, /clones, /deleteclone, and clone setup guides in PM.
"""

from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from config import Config
from core.fonts import HEADER, to_small_caps
from core.clone_manager import clone_manager, clone_states
from core.db import get_user_cloned_bots, delete_cloned_bot, is_global_auth_user, is_sudo_user


def get_clone_guide_text() -> str:
    return (
        f"{HEADER}"
        f"<b>Cʟᴏɴᴇ Yᴏᴜʀ Oᴡɴ Bᴏᴛ</b>\n\n"
        f"<i>Aap apna khud ka Full HD Movie & Music Player Bot bana sakte hain sirf 1 minute mein!</i>\n\n"
        f"‣ <b>100% Free Cloud Hosting:</b> Server aur high-bandwidth maintenance hamari taraf se.\n"
        f"‣ <b>Full HD Streaming:</b> Group voice chats mein bina kisi lag ke 1080p stream.\n"
        f"‣ <b>Apna Bot, Apna Brand:</b> Aapka bot token, aapka bot username, aur aapke group!\n"
        f"‣ <b>Unlimited Movies & Series:</b> Search any title, choose Hindi/English dub, play anytime.\n\n"
        f"<b><u>Bot Kaise Banayein (4 Simple Steps):</u></b>\n"
        f"1. Telegram par @BotFather open karein.\n"
        f"2. <code>/newbot</code> command bhejkar apna naya bot banayein.\n"
        f"3. @BotFather se milne wala <b>HTTP API Token</b> copy karein.\n"
        f"4. Yahan chat mein bhejhein: <code>/clone &lt;BOT_TOKEN&gt;</code>\n\n"
        f"<i>Example:</i> <code>/clone 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz</code>"
    )


def get_clone_guide_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "Cʀᴇᴀᴛᴇ Bᴏᴛ Nᴏᴡ (@BotFather)",
                url="https://t.me/BotFather",
                style="success"
            )
        ],
        [
            InlineKeyboardButton(
                "Mʏ Cʟᴏɴᴇᴅ Bᴏᴛs",
                callback_data="clone_my_list",
                style="primary"
            )
        ],
        [
            InlineKeyboardButton("Hᴏᴍᴇ", callback_data="help_back", style="primary"),
            InlineKeyboardButton("Cʟᴏsᴇ", callback_data="vcplay_close", style="danger")
        ]
    ])


def register(app: Client):

    # ── /clone command ────────────────────────────────────────────────────────
    @app.on_message(filters.command("clone") & filters.private)
    async def clone_command(client: Client, message: Message):
        user = message.from_user
        user_id = user.id if user else 0
        user_name = user.first_name if user and user.first_name else "User"

        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            clone_states[user_id] = "WAITING_FOR_TOKEN"
            await message.reply_text(
                get_clone_guide_text() + "\n\n<b>Ab apna Bot Token chat mein send karein:</b>",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=get_clone_guide_markup(),
                disable_web_page_preview=True
            )
            return

        bot_token = args[1].strip()
        await _process_token_submission(client, message, user_id, user_name, bot_token)

    # ── Token text interceptor for in-memory state ─────────────────────────────
    @app.on_message(filters.text & filters.private & ~filters.command(["start", "help", "clone", "clones", "deleteclone", "admin"]))
    async def clone_text_interceptor(client: Client, message: Message):
        user = message.from_user
        user_id = user.id if user else 0
        user_name = user.first_name if user and user.first_name else "User"

        if clone_states.get(user_id) == "WAITING_FOR_TOKEN":
            clone_states.pop(user_id, None)
            bot_token = message.text.strip()
            await _process_token_submission(client, message, user_id, user_name, bot_token)

    # ── /clones command ───────────────────────────────────────────────────────
    @app.on_message(filters.command("clones") & filters.private)
    async def list_clones_command(client: Client, message: Message):
        user_id = message.from_user.id if message.from_user else 0
        await _send_my_clones_panel(client, message.chat.id, user_id, reply_to_id=message.id)

    # ── /deleteclone command ──────────────────────────────────────────────────
    @app.on_message(filters.command("deleteclone") & filters.private)
    async def delete_clone_command(client: Client, message: Message):
        user_id = message.from_user.id if message.from_user else 0
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.reply_text(
                f"{HEADER}"
                f"<b>Usage:</b> <code>/deleteclone &lt;bot_id&gt;</code>\n"
                f"Aap apne bot ka ID dekhne ke liye <code>/clones</code> use karein.",
                parse_mode=enums.ParseMode.HTML
            )
            return
            
        try:
            target_bot_id = int(args[1].strip())
        except ValueError:
            await message.reply_text(f"{HEADER}<b>Invalid Bot ID!</b>", parse_mode=enums.ParseMode.HTML)
            return

        # Ensure user owns this bot, or is sudo/owner
        is_owner = (user_id in (Config.OWNER_ID, 6805412676)) or is_sudo_user(user_id)
        user_clones = get_user_cloned_bots(user_id)
        owned_ids = [c["bot_id"] for c in user_clones]

        if not is_owner and target_bot_id not in owned_ids:
            await message.reply_text(f"{HEADER}<b>Aap sirf apna banaya hua clone delete kar sakte hain!</b>", parse_mode=enums.ParseMode.HTML)
            return

        await clone_manager.delete_clone(target_bot_id)
        await message.reply_text(
            f"{HEADER}"
            f"✅ <b>Cʟᴏɴᴇ Bᴏᴛ Dᴇʟᴇᴛᴇᴅ!</b>\n\n"
            f"Bot ID <code>{target_bot_id}</code> ko successfully stop aur database se delete kar diya gaya hai.",
            parse_mode=enums.ParseMode.HTML
        )

    # ── Clone Callbacks ───────────────────────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^clone_"))
    async def clone_callbacks(client: Client, query: CallbackQuery):
        user_id = query.from_user.id if query.from_user else 0
        data = query.data

        if data == "clone_start":
            await query.answer()
            from bot import send_styled
            await send_styled(
                chat_id=query.message.chat.id,
                text=get_clone_guide_text(),
                markup=get_clone_guide_markup(),
                message_id=query.message.id
            )

        elif data == "clone_my_list":
            await query.answer()
            await _send_my_clones_panel(client, query.message.chat.id, user_id, message_id=query.message.id)

        elif data.startswith("clone_del_"):
            target_bot_id = int(data.replace("clone_del_", ""))
            is_owner = (user_id in (Config.OWNER_ID, 6805412676)) or is_sudo_user(user_id)
            user_clones = get_user_cloned_bots(user_id)
            owned_ids = [c["bot_id"] for c in user_clones]

            if not is_owner and target_bot_id not in owned_ids:
                await query.answer("Aap sirf apna bot delete kar sakte hain!", show_alert=True)
                return

            await clone_manager.delete_clone(target_bot_id)
            await query.answer("Clone bot stopped and deleted!", show_alert=True)
            await _send_my_clones_panel(client, query.message.chat.id, user_id, message_id=query.message.id)


async def _process_token_submission(client: Client, message: Message, user_id: int, user_name: str, bot_token: str):
    """Validates and provisions a new clone bot instance."""
    if ":" not in bot_token or len(bot_token) < 20:
        await message.reply_text(
            f"{HEADER}"
            f"<b>Invalid Bot Token Format!</b>\n\n"
            f"Token ka format is tarah hota hai: <code>123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ</code>\n"
            f"Kripya @BotFather se exact token copy karke bhejein.",
            parse_mode=enums.ParseMode.HTML
        )
        return

    status_msg = await message.reply_text(
        f"{HEADER}"
        f"<b>Validating bot token with Telegram...</b>\n<i>Please wait 2 seconds...</i>",
        parse_mode=enums.ParseMode.HTML
    )

    success, reply_text, bot_data = await clone_manager.create_clone(bot_token, user_id, user_name)

    if not success:
        await status_msg.edit_text(
            f"{HEADER}<b>Error :</b> {reply_text}",
            parse_mode=enums.ParseMode.HTML
        )
        return

    bot_username = bot_data.get("bot_username", "")
    bot_id = bot_data.get("bot_id", 0)

    congrats_text = (
        f"{HEADER}"
        f"🎉 <b>Bᴀᴅʜᴀɪ Hᴏ! Aᴀᴘᴋᴀ Cʟᴏɴᴇ Bᴏᴛ Lɪᴠᴇ Hᴏ Gᴀʏᴀ Hᴀɪ!</b>\n\n"
        f"‣ <b>Bᴏᴛ :</b> @{bot_username}\n"
        f"‣ <b>Bᴏᴛ ID :</b> <code>{bot_id}</code>\n"
        f"‣ <b>Oᴡɴᴇʀ :</b> <code>{user_name}</code> (<code>{user_id}</code>)\n\n"
        f"<i>Aapka bot ab bilkul active hai! Apne bot ko groups mein add karein aur /movie ya /vod commands use karein.</i>"
    )

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "Oᴘᴇɴ Yᴏᴜʀ Bᴏᴛ",
                url=f"https://t.me/{bot_username}",
                style="success"
            )
        ],
        [
            InlineKeyboardButton(
                "Aᴅᴅ Yᴏᴜʀ Bᴏᴛ Tᴏ Gʀᴏᴜᴘ",
                url=f"https://t.me/{bot_username}?startgroup=true",
                style="primary"
            )
        ],
        [
            InlineKeyboardButton("Cʟᴏsᴇ", callback_data="vcplay_close", style="danger")
        ]
    ])

    from bot import send_styled
    await send_styled(
        chat_id=message.chat.id,
        text=congrats_text,
        markup=markup,
        message_id=status_msg.id
    )


async def _send_my_clones_panel(client: Client, chat_id: int, user_id: int, message_id: int = None, reply_to_id: int = None):
    """Sends the user's active cloned bots list with management buttons."""
    user_clones = get_user_cloned_bots(user_id)
    if not user_clones:
        text = (
            f"{HEADER}"
            f"<b>Aapka abhi koi Cloned Bot active nahi hai.</b>\n\n"
            f"Naya bot create karne ke liye <code>/clone</code> type karein!"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Cʀᴇᴀᴛᴇ Cʟᴏɴᴇ Bᴏᴛ", callback_data="clone_start", style="success")],
            [InlineKeyboardButton("Cʟᴏsᴇ", callback_data="vcplay_close", style="danger")]
        ])
    else:
        text = (
            f"{HEADER}"
            f"<b>Yᴏᴜʀ Cʟᴏɴᴇᴅ Bᴏᴛs :</b> (Total: <code>{len(user_clones)}</code>)\n\n"
            f"<i>Neeche diye gaye buttons se apne bot ko open karein ya delete karein:</i>\n\n"
        )
        buttons = []
        for idx, c in enumerate(user_clones, 1):
            u_name = c.get("bot_username", "bot")
            b_id = c["bot_id"]
            text += f"<b>{idx}.</b> @{u_name} (ID: <code>{b_id}</code>)\n"
            buttons.append([
                InlineKeyboardButton(f"Oᴘᴇɴ @{u_name}", url=f"https://t.me/{u_name}", style="primary"),
                InlineKeyboardButton("🗑️ Dᴇʟᴇᴛᴇ", callback_data=f"clone_del_{b_id}", style="danger")
            ])
        buttons.append([
            InlineKeyboardButton("➕ Cʀᴇᴀᴛᴇ Aɴᴏᴛʜᴇʀ Cʟᴏɴᴇ", callback_data="clone_start", style="success")
        ])
        buttons.append([
            InlineKeyboardButton("Hᴏᴍᴇ", callback_data="help_back", style="primary"),
            InlineKeyboardButton("Cʟᴏsᴇ", callback_data="vcplay_close", style="danger")
        ])
        markup = InlineKeyboardMarkup(buttons)

    from bot import send_styled
    if message_id:
        await send_styled(chat_id=chat_id, text=text, markup=markup, message_id=message_id)
    else:
        await send_styled(chat_id=chat_id, text=text, markup=markup)
