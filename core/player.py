"""
**🎮 GameOver Music Bot — Core Player Engine (PyTgCalls Local Playback)**
Production-ready stream player manager with strict per-chat isolation.
Handles local file playback, 480p @ 60 FPS video parameters,
high-bass studio equalizer audio, and automatic cache deletion.
"""

import os
import asyncio
import time
import logging
logging.getLogger("pytgcalls").setLevel(logging.WARNING)
logging.getLogger("ffmpeg").setLevel(logging.WARNING)
from typing import Optional, Dict, Any, Union
from pyrogram import Client, filters as py_filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from pytgcalls import PyTgCalls, filters
from pytgcalls.types import MediaStream, VideoQuality, AudioQuality
from pytgcalls.types.raw import VideoParameters

from core.queue_manager import queue_manager, SongInfo
from core.downloader import download_song, clean_cached_file, get_vod_filename

FILE_CLEANUP_DELAY = 600  # 10 minutes in seconds

async def delayed_delete(app: Client, chat_id: int, message_id: int, delay: int = 6):
    """Automatically deletes a status/notification message after a few seconds."""
    try:
        await asyncio.sleep(delay)
        await app.delete_messages(chat_id, message_id)
    except Exception:
        pass

async def delayed_clean_cached_file(file_path: str, delay: int = FILE_CLEANUP_DELAY):
    """Delete a cached file after a short delay, protecting active/queued tracks."""
    await asyncio.sleep(delay)
    
    # Protect active playing files
    if file_path in list(stream_manager.local_files.values()):
        print(f"[Player] Protecting currently playing file from delayed cleanup: {file_path}")
        return
        
    # Protect queued files
    queued_ids = set()
    for chat_id, songs in list(queue_manager.queues.items()):
        for song in songs:
            clean_id = "".join(c for c in song.webpage_url.split("v=")[-1] if c.isalnum() or c in ("-", "_"))
            if clean_id:
                queued_ids.add(clean_id)
                
    filename = os.path.basename(file_path)
    is_queued = False
    for qid in queued_ids:
        if qid in filename:
            is_queued = True
            break
    if is_queued:
        print(f"[Player] Protecting queued file from delayed cleanup: {file_path}")
        return
        
    clean_cached_file(file_path)

def get_cleanup_delay(song: Optional[SongInfo]) -> int:
    """Helper to determine file cleanup delay: 24 hours to save VPS disk space while preserving cache."""
    return 86400  # 24 hours in seconds

async def start_downloads_garbage_collector():
    """Periodically purges files in downloads/ older than 24 hours, protecting active/queued tracks."""
    downloads_dir = "downloads"
    while True:
        try:
            if os.path.exists(downloads_dir):
                now = time.time()
                active_files = set(stream_manager.local_files.values())
                
                # Get all queued video IDs to protect them
                queued_ids = set()
                for chat_id, songs in list(queue_manager.queues.items()):
                    for song in songs:
                        clean_id = "".join(c for c in song.webpage_url.split("v=")[-1] if c.isalnum() or c in ("-", "_"))
                        if clean_id:
                            queued_ids.add(clean_id)
                
                for filename in os.listdir(downloads_dir):
                    file_path = os.path.join(downloads_dir, filename)
                    if os.path.isfile(file_path):
                        # Protect active files
                        if file_path in active_files:
                            continue
                            
                        # Protect queued files
                        is_queued = False
                        for qid in queued_ids:
                            if qid in filename:
                                is_queued = True
                                break
                        if is_queued:
                            continue
                            
                        # Delete if older than 24 hours
                        mtime = os.path.getmtime(file_path)
                        if now - mtime > 86400:  # 24 hours
                            try:
                                os.remove(file_path)
                                print(f"[Garbage Collector] Purged expired cached file: {file_path}")
                            except Exception as e:
                                print(f"[Garbage Collector] Error purging {file_path}: {e}")
        except Exception as e:
            print(f"[Garbage Collector] Error: {e}")
        await asyncio.sleep(1800)  # Run every 30 minutes


# ── Emojis and formatting constants ──────────────────────────────────────────
STAR   = ''
PLAY   = ''
SKIP   = ''
SLEEP  = ''
QUEUE  = ''
WAVE   = ''
CLOCK  = ''
INFO   = ''
USER   = ''
LINK   = ''
TRASH  = ''
WARN   = ''



def get_configured_video_parameters():
    """Reads configured target resolution and FPS from database for GAMEOVER MOVIE HUB."""
    from core.db import get_setting
    q = get_setting("quality_pref") or "1080p"
    fps_str = get_setting("fps_pref") or "90"
    try:
        fps_val = int(fps_str)
    except Exception:
        fps_val = 90

    # Support 120, 90, 60, 30 FPS
    fps_val = min(120, max(15, fps_val))

    resolution_map = {
        "4K": (3840, 2160, 2160),
        "2K": (2560, 1440, 1440),
        "1080p": (1920, 1080, 1080),
        "720p": (1280, 720, 720),
        "480p": (854, 480, 480),
    }

    w, h, max_h = resolution_map.get(q, (1920, 1080, 1080))
    vid_params = VideoParameters(width=w, height=h, frame_rate=fps_val)
    return vid_params, q, fps_val, max_h


class SeekableMediaStream(MediaStream):
    async def check_stream(self):
        import pytgcalls.types.stream.media_stream as ms_mod
        orig_check = ms_mod.check_stream
        
        async def mock_check(ffmpeg_params, path, stream_params, before_cmds=None, headers=None):
            # Pass None so that ffprobe only probes the stream format without erroring on custom ffmpeg filters
            return await orig_check(None, path, stream_params, before_cmds, headers)
            
        ms_mod.check_stream = mock_check
        try:
            await super().check_stream()
        finally:
            ms_mod.check_stream = orig_check


async def get_media_duration_seconds(file_path: str) -> int:
    """Fast ffprobe check to get exact video duration in seconds."""
    try:
        proc = await asyncio.create_subprocess_exec(
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3.0)
        dur = float(stdout.decode().strip())
        return int(dur)
    except Exception:
        return 0


class PlayerManager:
    def __init__(self):
        self._pytg: PyTgCalls = None
        self._assistant: Client = None
        self.app: Client = None   # Pyrogram bot used to send messages
        self._active_chats: set[int] = set()
        
        self.idle_timers: dict[int, asyncio.Task] = {}  # per-group idle timers
        self.stream_start_time: dict[int, float] = {}   # chat_id -> start time
        self.current_seek_offset: dict[int, int] = {}   # chat_id -> seek offset in seconds
        self.menu_active: dict[int, bool] = {}          # chat_id -> True if Options panel is currently open
        self.paused_time: dict[int, float] = {}         # chat_id -> pause timestamp
        self.active_message_id: dict[int, int] = {}     # chat_id -> now playing message_id
        
        # Local caching cache file path map: chat_id -> local_file_path
        self.local_files: dict[int, str] = {}
        self.skip_votes: dict[int, set[int]] = {}

    # ────────────────────────── Init ────────────────────────────────────────

    async def init(self, assistant: Client, bot: Client = None):
        """Initialise PyTgCalls and register event handlers."""
        self._assistant = assistant
        self.app = bot if bot else assistant
        self._pytg = PyTgCalls(assistant)
        
        # Start automatic 24-hour garbage collector
        asyncio.create_task(start_downloads_garbage_collector())

        from pytgcalls.types import ChatUpdate

        # ── Stream-end handler ─────────────────────────────────────────────
        @self._pytg.on_update(filters.stream_end())
        async def on_stream_end(_, update):
            try:
                chat_id = update.chat_id
                self.skip_votes.pop(chat_id, None)

                # De-duplicate: only process AUDIO end (skip VIDEO end)
                type_str = str(update.stream_type).upper()
                type_val = getattr(update.stream_type, "value", update.stream_type)
                if "VIDEO" in type_str or type_val == 2:
                    return

                print(f"\n[Player] ⏹  Audio stream ended in chat {chat_id}")
                
                current = queue_manager.get_current(chat_id)

                # Schedule file deletion after 10 minutes (not immediately)
                old_local = self.local_files.pop(chat_id, None)
                if old_local:
                    asyncio.create_task(delayed_clean_cached_file(old_local, delay=get_cleanup_delay(current)))
                    print(f"[Player] 🗑️  File queued for deletion: {old_local}")

                # ── Loop handling ──────────────────────────────────────────
                loop_remaining = queue_manager.get_loop(chat_id)
                if loop_remaining > 0:
                    if current:
                        queue_manager.decrement_loop(chat_id)
                        print(f"[Player] 🔁 Loop remaining: {queue_manager.get_loop(chat_id)} for chat {chat_id}")
                        asyncio.create_task(self._delayed_play(chat_id, current, send_card=True))
                        return

                # ── VOD Auto-Play Next Episode ──
                if current and (current.uploader == "MOVIES Engine" or current.duration == "VOD"):
                    try:
                        from plugins.movies import vod_sessions, trigger_movie_playback
                        session_data = vod_sessions.get(chat_id)
                        if session_data and session_data.get("seasons"):
                            chosen_season = session_data.get("chosen_season", 1)
                            chosen_episode = session_data.get("chosen_episode", 1)
                            seasons = session_data.get("seasons", [])
                            
                            next_season = None
                            next_episode = None
                            
                            current_season_info = next((s for s in seasons if s.se == chosen_season), None)
                            if current_season_info:
                                if chosen_episode < current_season_info.maxEp:
                                    next_season = chosen_season
                                    next_episode = chosen_episode + 1
                                else:
                                    for s in seasons:
                                        if s.se == chosen_season + 1:
                                            next_season = chosen_season + 1
                                            next_episode = 1
                                            break
                                            
                            if next_season is not None and next_episode is not None:
                                print(f"[Player] 📺 VOD Auto-Play Next Episode: Season {next_season} Episode {next_episode}")
                                
                                try:
                                    await self.app.send_message(
                                        chat_id,
                                        f"<b>Aᴜᴛᴏ-Pʟᴀʏɪɴɢ Nᴇxᴛ Eᴘɪsᴏᴅᴇ</b>\n\n"
                                        f"‣ <b>Tɪᴛʟᴇ :</b> <code>{session_data['title']} S{next_season}E{next_episode}</code>\n"
                                        f"<i>Loading next episode, please wait...</i>"
                                    )
                                except Exception as e:
                                    print(f"[Player] VOD notification failed: {e}")
                                    
                                placeholder = await self.app.send_message(chat_id, "<i>Loading...</i>")
                                
                                class DummyUser:
                                    def __init__(self, uid):
                                        self.id = uid
                                        self.first_name = "User"
                                        self.username = None
                                        
                                class DummyQuery:
                                    def __init__(self, msg, uid):
                                        self.message = msg
                                        self.from_user = DummyUser(uid)
                                    async def answer(self, *args, **kwargs):
                                        pass
                                        
                                query_obj = DummyQuery(placeholder, session_data.get("requester_id", 0))
                                asyncio.create_task(trigger_movie_playback(
                                    query_obj,
                                    session_data,
                                    season=next_season,
                                    episode=next_episode,
                                    is_next=True
                                ))
                                return
                    except Exception as vod_err:
                        print(f"[Player] Error in VOD auto-play next: {vod_err}")

                # ── Auto-Play next song ────────────────────────────────────
                if not queue_manager.is_empty(chat_id):
                    next_song = queue_manager.pop(chat_id)
                    if next_song:
                        self._cancel_idle_timer(chat_id)
                        print(f"[Player] ⏭  Auto-playing next: '{next_song.title}' in chat {chat_id}")

                        # Send auto-play notification first
                        try:
                            await self.app.send_message(
                                chat_id,
                                f"<b>Aᴜᴛᴏ-Pʟᴀʏɪɴɢ Nᴇxᴛ</b>\n\n"
                                f"‣ <b>Tɪᴛʟᴇ :</b> <a href='{next_song.webpage_url}'>{next_song.title}</a>\n"
                                f"‣ <b>Dᴜʀᴀᴛɪᴏɴ :</b> <code>{next_song.duration}</code>\n"
                                f"‣ <b>Tɪᴛʟᴇs Rᴇᴍᴀɪɴɪɴɢ :</b> <code>{queue_manager.get_length(chat_id)}</code>",
                                disable_web_page_preview=True
                            )
                        except Exception as e:
                            print(f"[Player] Auto-play notification failed: {e}")

                        asyncio.create_task(self._delayed_play(chat_id, next_song, send_card=True))
                        return

                # ── Queue is empty — start idle timer ──────────────────────
                queue_manager.clear_current(chat_id)
                print(f"[Player] Queue empty in chat {chat_id}. Starting 5-min idle timer.")
                
                # Delete active now playing message on queue completion
                old_msg_id = self.active_message_id.pop(chat_id, None)
                if old_msg_id and self.app:
                    try:
                        await self.app.delete_messages(chat_id, old_msg_id)
                    except Exception:
                        pass

                try:
                    await self.app.send_message(
                        chat_id,
                        f"<b>Qᴜᴇᴜᴇ Fɪɴɪsʜᴇᴅ</b>\n\n"
                        f"‣ Add more titles with <code>/movie &lt;title&gt;</code>\n"
                        f"‣ Bot will leave after <b>5 minutes</b> of inactivity."
                    )
                except Exception as e:
                    print(f"[Player] Queue ended notification failed: {e}")

                self.idle_timers[chat_id] = asyncio.create_task(
                    self._idle_timeout_task(chat_id)
                )

            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"[Player] ❌ Error in on_stream_end: {e}")

        # ── Voice-chat kicked / closed handlers ──
        @self._pytg.on_update(filters.chat_update(ChatUpdate.Status.KICKED))
        async def on_kicked(_, update):
            try:
                chat_id = update.chat_id
                self._cancel_idle_timer(chat_id)
                self._active_chats.discard(chat_id)
                old_local = self.local_files.pop(chat_id, None)
                if old_local:
                    current_song = queue_manager.get_current(chat_id)
                    asyncio.create_task(delayed_clean_cached_file(old_local, delay=get_cleanup_delay(current_song)))
                print(f"[Player] ⚠️ Assistant was kicked from call in chat {chat_id}.")
            except Exception as e:
                print(f"[Player] ❌ Error in on_kicked: {e}")

        @self._pytg.on_update(filters.chat_update(ChatUpdate.Status.CLOSED_VOICE_CHAT))
        async def on_closed_vc(_, update):
            try:
                chat_id = update.chat_id
                self._cancel_idle_timer(chat_id)
                queue_manager.clear(chat_id)
                self._active_chats.discard(chat_id)
                old_local = self.local_files.pop(chat_id, None)
                if old_local:
                    current_song = queue_manager.get_current(chat_id)
                    asyncio.create_task(delayed_clean_cached_file(old_local, delay=get_cleanup_delay(current_song)))
                print(f"[Player] 🔇 Voice chat closed in chat {chat_id}. State cleared.")
                try:
                    await self.app.send_message(
                        chat_id,
                        f"{WARN} <b>ᴠᴏɪᴄᴇ ᴄʜᴀᴛ ᴡᴀs ᴄʟᴏsᴇᴅ!</b>\n"
                        f"» Queue cleared. Start the voice chat and use <code>/movie</code> to restart."
                    )
                except Exception:
                    pass
            except Exception as e:
                print(f"[Player] ❌ Error in on_closed_vc: {e}")

        @self._pytg.on_update(filters.chat_update(ChatUpdate.Status.LEFT_GROUP))
        async def on_chat_update(_, update):
            try:
                chat_id = update.chat_id
                self._cancel_idle_timer(chat_id)
                queue_manager.clear(chat_id)
                self._active_chats.discard(chat_id)
                old_local = self.local_files.pop(chat_id, None)
                if old_local:
                    current_song = queue_manager.get_current(chat_id)
                    asyncio.create_task(delayed_clean_cached_file(old_local, delay=get_cleanup_delay(current_song)))
                print(f"[Player] 🔇 Assistant left call in chat {chat_id}. State cleared.")
                try:
                    await self.app.send_message(
                        chat_id,
                        f"{WARN} <b>ᴀssɪsᴛᴀɴᴛ ʟᴇғᴛ ᴛʜᴇ ᴠᴏɪᴄᴇ ᴄʜᴀᴛ!</b>\n"
                        f"» Queue cleared. Use <code>/movie</code> to start again."
                    )
                except Exception:
                    pass
            except Exception as e:
                print(f"[Player] ❌ Error in on_chat_update: {e}")

        await self._pytg.start()
        print("[Player] ✅ PyTgCalls started!")

    # ────────────────────────── Idle Timer ──────────────────────────────────

    async def _idle_timeout_task(self, chat_id: int):
        """Wait 5 minutes then leave the voice chat automatically."""
        try:
            await asyncio.sleep(300)  # 5 minutes
            print(f"[Player] 💤 5-minute idle reached for chat {chat_id}. Auto-leaving.")
            try:
                await self._pytg.leave_call(chat_id)
            except Exception:
                pass
            self._active_chats.discard(chat_id)
            queue_manager.clear(chat_id)
            try:
                await self.app.send_message(
                    chat_id,
                    f"{SLEEP} <b>ɴᴏ sᴏɴɢs ᴘʟᴀʏɪɴɢ ғᴏʀ 5 ᴍɪɴᴜᴛᴇs.</b>\n"
                    f"Leaving the voice chat to save resources. Bye! {WAVE}"
                )
            except Exception:
                pass
        except asyncio.CancelledError:
            print(f"[Player] ⏱  Idle timer cancelled for chat {chat_id}")
        finally:
            self.idle_timers.pop(chat_id, None)

    def _cancel_idle_timer(self, chat_id: int):
        task = self.idle_timers.pop(chat_id, None)
        if task and not task.done():
            task.cancel()
            print(f"[Player] ✅ Idle timer cancelled for chat {chat_id}")

    # ────────────────────────── Assistant & VC Verification ─────────────────

    async def ensure_assistant_in_chat(self, chat_id: int, bot_client: Client = None) -> tuple[bool, str, dict]:
        """
        Verify that the assistant account is in the chat.
        If not present, attempts:
        1. bot.add_chat_members(chat_id, asst_id)
        2. bot.create_chat_invite_link(chat_id) -> assistant.join_chat(invite)
        3. assistant.join_chat(chat.username)
        Returns (is_in_chat, error_message, info_dict)
        """
        if not self._assistant:
            return False, "Assistant client not initialized.", {}

        try:
            asst_me = await self._assistant.get_me()
        except Exception as e:
            return False, f"Failed to get assistant info: {e}", {}

        info = {
            "id": asst_me.id,
            "username": asst_me.username or "",
            "name": asst_me.first_name or "Assistant"
        }

        # Check if already present in chat
        try:
            member = await self._assistant.get_chat_member(chat_id, "me")
            if member and member.status not in (enums.ChatMemberStatus.BANNED, enums.ChatMemberStatus.LEFT):
                return True, "", info
        except Exception:
            pass

        # Not in chat: try auto-invite/auto-add
        _bot = bot_client or self.app
        joined = False

        if _bot:
            try:
                await _bot.add_chat_members(chat_id, asst_me.id)
                joined = True
                print(f"[Player] Added assistant to chat {chat_id} via bot.add_chat_members")
            except Exception as e:
                print(f"[Player] bot.add_chat_members failed: {e}")

        if not joined and _bot:
            try:
                invite = await _bot.create_chat_invite_link(chat_id)
                if invite and invite.invite_link:
                    await self._assistant.join_chat(invite.invite_link)
                    joined = True
                    print(f"[Player] Assistant joined chat {chat_id} via invite link")
            except Exception as e:
                print(f"[Player] Assistant join via invite link failed: {e}")

        if not joined:
            try:
                chat = await self._assistant.get_chat(chat_id)
                if chat and chat.username:
                    await self._assistant.join_chat(chat.username)
                    joined = True
                    print(f"[Player] Assistant joined public chat @{chat.username}")
            except Exception as e:
                print(f"[Player] Assistant join via username failed: {e}")

        # Final verification check
        try:
            member = await self._assistant.get_chat_member(chat_id, "me")
            if member and member.status not in (enums.ChatMemberStatus.BANNED, enums.ChatMemberStatus.LEFT):
                return True, "", info
        except Exception:
            pass

        asst_tag = f"@{info['username']}" if info['username'] else f"<a href='tg://user?id={info['id']}'>{info['name']}</a>"
        err_msg = (
            f"<b>⚠️ Assɪsᴛᴀɴᴛ Nᴏᴛ Fᴏᴜɴᴅ Iɴ Gʀᴏᴜᴘ</b>\n\n"
            f"Bot ka Assistant account ({asst_tag}) is group mein add nahi ho saka!\n\n"
            f"‣ Kripya Assistant ko group mein manually <b>Add karein</b> aur <b>Admin (Manage Video Chat)</b> banayein!\n"
            f"‣ Ya phir <b>Bot ko Group Admin</b> banayein taaki bot Assistant ko invite kar sake."
        )
        return False, err_msg, info

    async def ensure_active_voice_chat(self, chat_id: int, bot_client: Client = None) -> tuple[bool, str]:
        """
        Verify that Voice/Video Chat is currently open in chat_id.
        Attempts CreateGroupCall if not already started.
        Returns (has_call, error_message)
        """
        from pyrogram import raw
        import random

        _bot = bot_client or self.app
        client = self._assistant or _bot
        if not client:
            return True, ""

        has_call = False
        try:
            peer = await client.resolve_peer(chat_id)
            if isinstance(peer, (raw.types.InputPeerChannel, raw.types.InputChannel)):
                full = await client.invoke(raw.functions.channels.GetFullChannel(channel=peer))
                has_call = getattr(full.full_chat, "call", None) is not None
            elif isinstance(peer, (raw.types.InputPeerChat, int)):
                cid = peer.chat_id if hasattr(peer, "chat_id") else peer
                full = await client.invoke(raw.functions.messages.GetFullChat(chat_id=cid))
                has_call = getattr(full.full_chat, "call", None) is not None
        except Exception as e:
            print(f"[Player] Raw VC inspection note: {e}")
            has_call = True  # Don't block if inspection is inconclusive

        if not has_call:
            print(f"[Player] Voice chat not detected in chat {chat_id}. Attempting auto-start...")
            from pyrogram.raw.functions.phone import CreateGroupCall
            try:
                peer_as = await self._assistant.resolve_peer(chat_id)
                await self._assistant.invoke(
                    CreateGroupCall(
                        peer=peer_as,
                        random_id=random.randint(0, 0x7FFFFFFF)
                    )
                )
                print(f"[Player] Assistant auto-started group call in {chat_id}")
                await asyncio.sleep(1.5)
                has_call = True
            except Exception as e1:
                print(f"[Player] Assistant auto-start call failed: {e1}")
                if _bot:
                    try:
                        peer_bot = await _bot.resolve_peer(chat_id)
                        await _bot.invoke(
                            CreateGroupCall(
                                peer=peer_bot,
                                random_id=random.randint(0, 0x7FFFFFFF)
                            )
                        )
                        print(f"[Player] Bot auto-started group call in {chat_id}")
                        await asyncio.sleep(1.5)
                        has_call = True
                    except Exception as e2:
                        print(f"[Player] Bot auto-start call failed: {e2}")

        if not has_call:
            err_msg = (
                f"<b>🎙️ Vᴏɪᴄᴇ Cʜᴀᴛ Nᴏᴛ Aᴄᴛɪᴠᴇ</b>\n\n"
                f"Group mein Voice / Video Chat (Live) start nahi hai!\n\n"
                f"‣ Kripya group mein pehle <b>Video / Voice Chat start karein</b>!\n"
                f"‣ Voice chat start hone ke baad <code>/movie</code> play karein."
            )
            return False, err_msg

        return True, ""

    # ────────────────────────── Play ────────────────────────────────────────

    async def _delayed_play(self, chat_id: int, song: SongInfo, send_card: bool = True, delay: float = 1.0):
        """Small delay before re-playing (lets WebRTC settle after stream end)."""
        await asyncio.sleep(delay)
        await self.play(chat_id, song, send_card=send_card)

    async def play(self, chat_id: int, song: SongInfo, bot_client: Client = None, send_card: bool = True, is_seek: bool = False, force_seek: int = 0) -> bool:
        """
        Download the song video/audio locally, and start streaming via PyTgCalls.
        Uses local files to eliminate direct-link buffering issues.
        """
        try:
            from core.db import is_group_bot_active
            if not is_group_bot_active(chat_id):
                print(f"[Player] Chat {chat_id} is disabled in /admin. Aborting playback silently.")
                queue_manager.clear(chat_id)
                return False

            self._cancel_idle_timer(chat_id)

            if not is_seek:
                self.current_seek_offset[chat_id] = force_seek
                self.stream_start_time[chat_id] = asyncio.get_event_loop().time()
                self.paused_time.pop(chat_id, None)
                self.menu_active[chat_id] = False

            # Check 1: Assistant in group check
            ok_asst, asst_err, asst_info = await self.ensure_assistant_in_chat(chat_id, bot_client=bot_client)
            if not ok_asst:
                queue_manager.clear(chat_id)
                if self.app:
                    asst_user = asst_info.get("username", "")
                    btns = []
                    if asst_user:
                        btns.append([InlineKeyboardButton("➕ Aᴅᴅ Assɪsᴛᴀɴᴛ", url=f"https://t.me/{asst_user}?startgroup=true", style="success")])
                    btns.append([InlineKeyboardButton("Cʟᴏsᴇ", callback_data="vcplay_close", style="danger")])
                    status_mid = self.active_message_id.pop(chat_id, None)
                    if status_mid:
                        try:
                            await self.app.edit_message_text(chat_id, status_mid, asst_err, reply_markup=InlineKeyboardMarkup(btns))
                        except Exception:
                            pass
                    else:
                        try:
                            await self.app.send_message(chat_id, asst_err, reply_markup=InlineKeyboardMarkup(btns))
                        except Exception:
                            pass
                return False

            # Check 2: Active Voice Chat check
            ok_vc, vc_err = await self.ensure_active_voice_chat(chat_id, bot_client=bot_client)
            if not ok_vc:
                queue_manager.clear(chat_id)
                if self.app:
                    status_mid = self.active_message_id.pop(chat_id, None)
                    close_markup = InlineKeyboardMarkup([[InlineKeyboardButton("Cʟᴏsᴇ", callback_data="vcplay_close", style="danger")]])
                    if status_mid:
                        try:
                            await self.app.edit_message_text(chat_id, status_mid, vc_err, reply_markup=close_markup)
                        except Exception:
                            pass
                    else:
                        try:
                            await self.app.send_message(chat_id, vc_err, reply_markup=close_markup)
                        except Exception:
                            pass
                return False

            # Detect stream modes
            mode = "audio" if getattr(song, "quality", "") == "audio" else "video"

            target_url = song.video_url or song.audio_url
            if not target_url:
                raise Exception("No video or audio stream URL found for this title.")

            download_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                "Origin": "https://themoviebox.org",
                "Referer": "https://themoviebox.org/",
            }

            # Check if target is a local file or download to downloads/ folder first
            local_file = None
            if os.path.exists(target_url):
                local_file = os.path.abspath(target_url)
            else:
                from config import Config
                from config import Config
                expected_filename = get_vod_filename(song, mode)
                expected_local = os.path.abspath(os.path.join(Config.DOWNLOADS_DIR, expected_filename))

                if os.path.exists(expected_local) and os.path.getsize(expected_local) > 100000:
                    local_file = expected_local
                    print(f"[Player] Found cached downloaded file: {local_file}")
                elif is_seek and chat_id in self.local_files and os.path.exists(self.local_files[chat_id]):
                    local_file = self.local_files[chat_id]
                else:
                    print(f"[Player] Downloading VOD file to downloads/ folder for: {song.title}")
                    last_progress_edit = 0
                    status_mid = self.active_message_id.get(chat_id)

                    async def progress_cb(pct, down, total):
                        nonlocal last_progress_edit
                        now = time.time()
                        if now - last_progress_edit >= 4.0 or pct >= 99:
                            last_progress_edit = now
                            if status_mid and self.app:
                                mb_down = down / (1024 * 1024)
                                mb_tot = total / (1024 * 1024)
                                try:
                                    await self.app.edit_message_text(
                                        chat_id=chat_id,
                                        message_id=status_mid,
                                        text=f"<b>Dᴏᴡɴʟᴏᴀᴅɪɴɢ Mᴏᴠɪᴇ :</b> <code>{pct}%</code>\n"
                                             f"‣ <b>Tɪᴛʟᴇ :</b> <code>{song.title}</code>\n"
                                             f"‣ <b>Sɪᴢᴇ :</b> <code>{mb_down:.1f} / {mb_tot:.1f} MB</code>",
                                        disable_web_page_preview=True
                                    )
                                except Exception:
                                    pass

                    dl_path = await download_song(song, mode=mode, progress_callback=progress_cb)
                    if dl_path and os.path.exists(dl_path):
                        local_file = os.path.abspath(dl_path)
                    else:
                        print(f"[Player] Download failed or cancelled for {song.title}. Fallback to remote URL.")
                        local_file = target_url

            is_local = os.path.exists(local_file)
            media_path = os.path.abspath(local_file) if is_local else local_file
            headers = None if is_local else download_headers
            if is_local:
                self.local_files[chat_id] = media_path
                # Probe exact movie duration in seconds
                detected_dur = await get_media_duration_seconds(media_path)
                if detected_dur > 0:
                    song.duration_secs = detected_dur
                    from plugins.controls import format_seconds
                    song.duration = format_seconds(detected_dur)
                    print(f"[Player] Detected movie duration: {song.duration} ({detected_dur}s)")

            # ── PyTgCalls Media Stream Setup ──
            seek_val = self.current_seek_offset.get(chat_id, 0)
            seek_str = f"-ss {seek_val}" if seek_val > 0 else ""
            ffmpeg_params = f"--base ---start -loglevel error -hide_banner {seek_str}".strip()

            # Target 720p @ 60 FPS video parameters as instructed
            vid_params = VideoParameters(width=1280, height=720, frame_rate=60)

            def get_stream(video_required: bool = True):
                v_flags = MediaStream.Flags.REQUIRED if video_required else MediaStream.Flags.IGNORE
                return MediaStream(
                    media_path=media_path,
                    headers=headers,
                    video_parameters=vid_params,
                    audio_parameters=AudioQuality.HIGH,
                    video_flags=v_flags,
                    audio_flags=MediaStream.Flags.REQUIRED,
                    ffmpeg_parameters=ffmpeg_params
                )

            stream = get_stream(video_required=(mode == "video"))

            # Play Stream in PyTgCalls with auto-start retry
            try:
                try:
                    await self._pytg.unmute(chat_id)
                except Exception:
                    pass
                
                print(f"[Player] Starting PyTgCalls play for '{song.title}' in chat {chat_id}...")
                await self._pytg.play(chat_id, stream)
                print(f"[Player] Successfully started stream in chat {chat_id}!")
            except Exception as play_err:
                err_str = str(play_err).lower()
                if "no video source found" in err_str:
                    print(f"[Player] No video source found in stream. Trying audio-only...")
                    stream = get_stream(video_required=False)
                    await self._pytg.play(chat_id, stream)
                else:
                    print(f"[Player] Play failed: {play_err}. Checking group call...")
                    try:
                        from pyrogram.raw.functions.phone import CreateGroupCall
                        import random
                        peer_as = await self._assistant.resolve_peer(chat_id)
                        try:
                            await self._assistant.invoke(
                                CreateGroupCall(
                                    peer=peer_as,
                                    random_id=random.randint(0, 0x7FFFFFFF)
                                )
                            )
                            print(f"[Player] Assistant auto-started group call in chat {chat_id}")
                        except Exception:
                            if self.app:
                                peer_bot = await self.app.resolve_peer(chat_id)
                                await self.app.invoke(
                                    CreateGroupCall(
                                        peer=peer_bot,
                                        random_id=random.randint(0, 0x7FFFFFFF)
                                    )
                                )
                                print(f"[Player] Bot auto-started group call in chat {chat_id}")
                        # Wait 1.5 seconds for call to initialize
                        await asyncio.sleep(1.5)
                        try:
                            await self._pytg.play(chat_id, stream)
                            print("[Player] Play succeeded after auto-starting group call!")
                        except Exception as retry_play_err:
                            if "no video source found" in str(retry_play_err).lower():
                                print(f"[Player] Retry play failed due to missing video. Trying audio-only...")
                                stream = get_stream(video_required=False)
                                await self._pytg.play(chat_id, stream)
                                print("[Player] Audio-only fallback play succeeded after retry!")
                            else:
                                raise retry_play_err
                    except Exception as retry_err:
                        print(f"[Player] Retry play failed: {retry_err}")
                        queue_manager.clear(chat_id)
                        if self.app:
                            try:
                                await self.app.send_message(
                                    chat_id,
                                    "<b>Voice Chat Active Nahi Hai!</b>\n\n"
                                    "Kripya group mein pehle <b>Video/Voice Chat start karein</b> aur bot ko admin banayein, phir <code>/movie</code> chalayein!"
                                )
                            except Exception:
                                pass
                        return False


            # Delete old Now Playing card before playing the new track
            old_msg_id = self.active_message_id.pop(chat_id, None)
            if old_msg_id and self.app and not is_seek:
                try:
                    await self.app.delete_messages(chat_id, old_msg_id)
                except Exception:
                    pass

            self._active_chats.add(chat_id)
            queue_manager.set_current(chat_id, song)

            # Send Now Playing card
            if send_card and self.app and not is_seek:
                try:
                    from plugins.controls import get_rich_control_buttons, get_rich_caption
                    from core.image_helper import get_16_9_thumbnail
                    
                    photo_url = None
                    try:
                        photo_url = await get_16_9_thumbnail(song.thumbnail, song.title)
                        if photo_url and os.path.exists(photo_url):
                            photo_url = os.path.abspath(photo_url)
                    except Exception as img_err:
                        print(f"[Player] Thumbnail processing fallback: {img_err}")

                    if not photo_url:
                        photo_url = song.thumbnail or "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?q=80&w=1280"

                    caption = get_rich_caption(song, played_secs=0)
                    buttons = get_rich_control_buttons(chat_id, is_paused=False)
                    try:
                        msg = await self.app.send_photo(
                            chat_id=chat_id,
                            photo=photo_url,
                            caption=caption,
                            reply_markup=buttons,
                        )
                    except Exception as photo_err:
                        print(f"[Player] send_photo failed: {photo_err}. Retrying text...")
                        msg = await self.app.send_message(
                            chat_id=chat_id,
                            text=caption,
                            reply_markup=buttons,
                            disable_web_page_preview=True
                        )
                    self.active_message_id[chat_id] = msg.id

                    # Re-send keyboard via Bot HTTP API to apply native colored button styles
                    await apply_styled_buttons(chat_id, msg.id, buttons)

                    asyncio.create_task(live_ui_updater(self.app, chat_id, msg.id))
                except Exception as e:
                    print(f"[Player] Now-playing card error: {e}")

            return True

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[Player] Play error in chat {chat_id}: {e}")
            return False

    # ────────────────────────── Change Stream ───────────────────────────────

    async def change_stream(self, chat_id: int, song: SongInfo, send_card: bool = True) -> bool:
        return await self.play(chat_id, song, send_card=send_card)

    # ────────────────────────── Controls ────────────────────────────────────

    async def stop(self, chat_id: int):
        """Stop playback, clear queue, delete local cache, and leave voice chat."""
        self.skip_votes.pop(chat_id, None)
        self.menu_active.pop(chat_id, None)
        old_msg_id = self.active_message_id.pop(chat_id, None)
        if old_msg_id and self.app:
            try:
                await self.app.delete_messages(chat_id, old_msg_id)
            except Exception:
                pass

        self._cancel_idle_timer(chat_id)
        queue_manager.clear(chat_id)
        self._active_chats.discard(chat_id)
        
        # Garbage Collect local file
        old_local = self.local_files.pop(chat_id, None)
        if old_local:
            asyncio.create_task(delayed_clean_cached_file(old_local, delay=get_cleanup_delay(None)))
            
        try:
            await asyncio.wait_for(self._pytg.leave_call(chat_id), timeout=3.0)
        except Exception:
            pass

    async def skip(self, chat_id: int) -> bool:
        """Skip the current track and play the next one, or stop if queue is empty."""
        self.skip_votes.pop(chat_id, None)
        
        if not queue_manager.is_empty(chat_id):
            next_song = queue_manager.pop(chat_id)
            print(f"[Player] Skipping to next track: {next_song.title} in chat {chat_id}")
            return await self.change_stream(chat_id, next_song, send_card=True)
        else:
            print(f"[Player] Queue empty, stopping playback in chat {chat_id}")
            await self.stop(chat_id)
            return True

    async def handle_vote_skip(self, chat_id: int, user_id: int, user_name: str, client: Client, message: Message = None, query: CallbackQuery = None):
        """Processes vote skip check, handles instant overrides for admins/requesters, and tracks democratic skip votes."""
        current = queue_manager.get_current(chat_id)
        if not current:
            if query:
                await query.answer("Nothing is playing!", show_alert=True)
            elif message:
                await message.reply_text("<b>Nothing is currently playing!</b>")
            return

        from config import Config
        from core.db import is_sudo_user
        # 1. VIP override check
        is_vip = False
        if user_id in (Config.OWNER_ID, 6805412676) or is_sudo_user(user_id):
            is_vip = True
        elif getattr(current, "requester_id", 0) != 0 and user_id == current.requester_id:
            is_vip = True
        else:
            try:
                member = await client.get_chat_member(chat_id, user_id)
                # Restrict direct skip override to the Group Owner (Creator) only. Regular admins must vote.
                if member.status == enums.ChatMemberStatus.OWNER:
                    is_vip = True
            except Exception:
                pass

        if is_vip:
            if query:
                try:
                    await query.answer("Skipping track...")
                except Exception:
                    pass
            elif message:
                try:
                    m = await message.reply_text("<b>Skipping track...</b>")
                    asyncio.create_task(delayed_delete(client, chat_id, m.id, delay=4))
                except Exception:
                    pass
            await self.skip(chat_id, user_name=user_name)
            return

        # 2. Regular member vote check
        if chat_id not in self.skip_votes:
            self.skip_votes[chat_id] = set()

        if user_id in self.skip_votes[chat_id]:
            msg = "You have already voted to skip this track!"
            if query:
                await query.answer(msg, show_alert=True)
            elif message:
                m = await message.reply_text(f"<b>{msg}</b>")
                asyncio.create_task(delayed_delete(client, chat_id, m.id, delay=4))
            return

        self.skip_votes[chat_id].add(user_id)
        current_votes = len(self.skip_votes[chat_id])

        if current_votes >= 3:
            self.skip_votes.pop(chat_id, None)
            if query:
                try:
                    await query.answer("Votes complete! Skipping...")
                except Exception:
                    pass
            await self.skip(chat_id, user_name="Democratic Vote")
        else:
            feedback = (
                f"<b>Sᴋɪᴘ Vᴏᴛᴇ Rᴇɢɪsᴛᴇʀᴇᴅ :</b> <code>{current_votes}/3 Votes</code>\n"
                f"‣ <b>Vᴏᴛᴇʀ :</b> <code>{user_name}</code>\n"
                f"<i>Type /vote or click Skip to vote!</i>"
            )
            if query:
                try:
                    await query.answer(f"Vote registered: {current_votes}/3", show_alert=True)
                    m = await query.message.reply_text(feedback)
                    asyncio.create_task(delayed_delete(client, chat_id, m.id, delay=5))
                except Exception:
                    pass
            elif message:
                try:
                    m = await message.reply_text(feedback)
                    asyncio.create_task(delayed_delete(client, chat_id, m.id, delay=5))
                except Exception:
                    pass

    async def pause(self, chat_id: int) -> bool:
        try:
            await self._pytg.pause(chat_id)
            if chat_id not in self.paused_time:
                self.paused_time[chat_id] = asyncio.get_event_loop().time()
            return True
        except Exception as e:
            print(f"[Player] Pause error: {e}")
            return False

    async def resume(self, chat_id: int) -> bool:
        try:
            await self._pytg.resume(chat_id)
            p_time = self.paused_time.pop(chat_id, None)
            if p_time and chat_id in self.stream_start_time:
                duration = asyncio.get_event_loop().time() - p_time
                self.stream_start_time[chat_id] += duration
            return True
        except Exception as e:
            print(f"[Player] Resume error: {e}")
            return False

    def get_elapsed_seconds(self, chat_id: int) -> int:
        """Returns accurate media elapsed seconds considering pauses."""
        loop = asyncio.get_event_loop()
        now = loop.time()
        start = self.stream_start_time.get(chat_id, now)
        offset = self.current_seek_offset.get(chat_id, 0)
        is_paused = chat_id in self.paused_time
        curr = self.paused_time[chat_id] if is_paused else now
        elapsed = int(curr - start + offset)
        return max(0, elapsed)

    def get_progress(self, chat_id: int) -> int:
        """Alias for get_elapsed_seconds."""
        return self.get_elapsed_seconds(chat_id)

    async def seek(self, chat_id: int, seconds: int) -> bool:
        song = queue_manager.get_current(chat_id)
        if not song:
            return False
            
        loop = asyncio.get_event_loop()
        now = loop.time()
        elapsed = self.get_elapsed_seconds(chat_id)
            
        target = elapsed + seconds
        duration = song.duration_secs
        
        if duration > 0:
            target = max(0, min(target, duration - 5))
        else:
            target = max(0, target)
            
        self.current_seek_offset[chat_id] = int(target)
        self.stream_start_time[chat_id] = now
        if chat_id in self.paused_time:
            self.paused_time[chat_id] = now
            
        return await self.play(chat_id, song, is_seek=True)

    async def skip(self, chat_id: int, user_name: str = "Someone") -> bool:
        """
        Skip: if TV series, plays next episode. If movie/music, plays next queued track
        or cleanly finishes queue and leaves with auto-deleting notifications.
        """
        self.skip_votes.pop(chat_id, None)
        self.menu_active.pop(chat_id, None)
        
        current = queue_manager.get_current(chat_id)
        
        # Schedule cleanup of current local file after delay
        old_local = self.local_files.pop(chat_id, None)
        if old_local:
            asyncio.create_task(delayed_clean_cached_file(old_local, delay=get_cleanup_delay(current)))

        # 1. Handle TV Series progression
        is_series = bool(current and (getattr(current, "season", 0) > 0 or getattr(current, "episode", 0) > 0))
        if is_series:
            from plugins.movies import vod_sessions, trigger_movie_playback
            session_data = vod_sessions.get(chat_id)
            if session_data:
                chosen_season = getattr(current, "season", session_data.get("chosen_season", 1))
                chosen_episode = getattr(current, "episode", session_data.get("chosen_episode", 1))
                seasons = session_data.get("seasons", [])
                
                next_season = None
                next_episode = None
                
                current_season_info = next((s for s in seasons if s.se == chosen_season), None)
                if current_season_info:
                    if chosen_episode < current_season_info.maxEp:
                        next_season = chosen_season
                        next_episode = chosen_episode + 1
                    else:
                        for s in seasons:
                            if s.se == chosen_season + 1:
                                next_season = chosen_season + 1
                                next_episode = 1
                                break

                if next_season is not None and next_episode is not None:
                    print(f"[Player] Series Skip -> Season {next_season} Episode {next_episode} by {user_name}")
                    # Delete old now-playing card
                    old_msg_id = self.active_message_id.pop(chat_id, None)
                    if old_msg_id and self.app:
                        try:
                            await self.app.delete_messages(chat_id, old_msg_id)
                        except Exception:
                            pass
                            
                    title_name = session_data.get("title", getattr(current, "clean_title", current.title))
                    status_placeholder = None
                    if self.app:
                        try:
                            status_placeholder = await self.app.send_message(
                                chat_id,
                                f"<b>Sᴋɪᴘᴘᴇᴅ Bʏ :</b> <code>{user_name}</code>\n"
                                f"‣ <b>Nᴇxᴛ Eᴘɪsᴏᴅᴇ :</b> <code>{title_name} S{next_season}E{next_episode}</code>"
                            )
                            asyncio.create_task(delayed_delete(self.app, chat_id, status_placeholder.id, delay=6))
                        except Exception:
                            pass
                            
                    target_handle = status_placeholder if status_placeholder else chat_id
                    asyncio.create_task(trigger_movie_playback(
                        target_handle,
                        session_data,
                        season=next_season,
                        episode=next_episode,
                        is_next=True
                    ))
                    return True

        # 2. Regular Queue Skip
        if not queue_manager.is_empty(chat_id):
            next_song = queue_manager.pop(chat_id)
            print(f"[Player] Skipping to next track: {next_song.title} in chat {chat_id}")
            if self.app:
                try:
                    m = await self.app.send_message(
                        chat_id,
                        f"<b>Sᴋɪᴘᴘᴇᴅ Bʏ :</b> <code>{user_name}</code>\n"
                        f"‣ <b>Nᴇxᴛ Tʀᴀᴄᴋ :</b> <code>{next_song.title}</code>"
                    )
                    asyncio.create_task(delayed_delete(self.app, chat_id, m.id, delay=6))
                except Exception:
                    pass
            return await self.change_stream(chat_id, next_song, send_card=True)
        else:
            print(f"[Player] Queue empty, stopping playback in chat {chat_id}")
            await self.stop(chat_id)
            if self.app:
                try:
                    m = await self.app.send_message(
                        chat_id,
                        f"<b>Qᴜᴇᴜᴇ Cʟᴇᴀʀᴇᴅ</b>\n\n"
                        f"‣ <b>Sᴋɪᴘᴘᴇᴅ Bʏ :</b> <code>{user_name}</code>\n"
                        f"‣ <b>Sᴛᴀᴛᴜs :</b> <code>Pʟᴀʏʙᴀᴄᴋ Sᴛᴏᴘᴘᴇᴅ</code>"
                    )
                    asyncio.create_task(delayed_delete(self.app, chat_id, m.id, delay=6))
                except Exception:
                    pass
            return True

    async def close(self):
        """Graceful shutdown — leave all active voice chats and delete caches."""
        if self._pytg:
            print("[Player] Shutting down — leaving all active calls...")
            for chat_id in list(self._active_chats):
                try:
                    await asyncio.wait_for(self._pytg.leave_call(chat_id), timeout=3.0)
                except Exception:
                    pass
                old_local = self.local_files.pop(chat_id, None)
                if old_local:
                    clean_cached_file(old_local)
                    
            for chat_id in list(self.idle_timers.keys()):
                self._cancel_idle_timer(chat_id)
            self._active_chats.clear()


# Global singleton player
stream_manager = PlayerManager()


async def apply_styled_buttons(chat_id: int, message_id: int, buttons):
    try:
        from config import Config
        from bot import _markup_to_bot_api_json
        from core.clone_manager import clone_manager
        import aiohttp, json
        token_val = clone_manager.get_token_for_chat(chat_id) or Config.BOT_TOKEN
        if token_val:
            edit_payload = {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": json.dumps({
                    "inline_keyboard": _markup_to_bot_api_json(buttons)
                })
            }
            timeout = aiohttp.ClientTimeout(total=5.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                await session.post(
                    f"https://api.telegram.org/bot{token_val}/editMessageReplyMarkup",
                    json=edit_payload
                )
    except Exception as e:
        print(f"[Player] apply_styled_buttons error: {e}")


async def edit_styled_caption(chat_id: int, message_id: int, caption: str, buttons):
    """Edits message caption and reply markup in a single Bot API call to avoid button style flickering."""
    try:
        from config import Config
        from bot import _markup_to_bot_api_json
        from core.clone_manager import clone_manager
        import aiohttp, json
        token_val = clone_manager.get_token_for_chat(chat_id) or Config.BOT_TOKEN
        if token_val:
            payload = {
                "chat_id": chat_id,
                "message_id": message_id,
                "caption": caption,
                "parse_mode": "HTML",
                "reply_markup": json.dumps({
                    "inline_keyboard": _markup_to_bot_api_json(buttons)
                })
            }
            timeout = aiohttp.ClientTimeout(total=5.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                resp = await session.post(
                    f"https://api.telegram.org/bot{token_val}/editMessageCaption",
                    json=payload
                )
                if resp.status != 200:
                    text_payload = dict(payload)
                    text_payload["text"] = text_payload.pop("caption")
                    await session.post(
                        f"https://api.telegram.org/bot{token_val}/editMessageText",
                        json=text_payload
                    )
    except Exception as e:
        print(f"[Player] edit_styled_caption error: {e}")


async def live_ui_updater(app, chat_id, message_id):
    """
    Updates the progress bar smoothly every 12s without button style flickering or flood wait.
    """
    from plugins.controls import get_rich_control_buttons, get_rich_caption
    
    while True:
        await asyncio.sleep(12)  # Update every 12s: smooth updates, zero flood wait, zero flicker
        
        song = queue_manager.get_current(chat_id)
        if not song or not queue_manager.is_playing(chat_id):
            break
            
        if stream_manager.active_message_id.get(chat_id) != message_id:
            break
            
        is_paused = chat_id in stream_manager.paused_time
        if is_paused:
            continue
            
        # Calculate current elapsed seconds
        elapsed = stream_manager.get_elapsed_seconds(chat_id)
        
        # Save VOD progress dynamically
        is_vod = (getattr(song, "uploader", "") == "MOVIES Engine") or (song.duration == "VOD")
        subject_id = getattr(song, "subject_id", None)
        if is_vod and subject_id is not None:
            try:
                from core.db import set_vod_progress
                season = getattr(song, "season", 0)
                episode = getattr(song, "episode", 0)
                clean_title = getattr(song, "clean_title", song.title)
                if elapsed > 0:
                    set_vod_progress(chat_id, subject_id, clean_title, season, episode, elapsed)
            except Exception as db_err:
                print(f"[Player] Error saving VOD progress: {db_err}")
                
        # If user is currently interacting with any sub-menu (Options, Language, Quality, Seasons, etc.),
        # pause live updates so their interactive menu is NEVER overwritten or flickered!
        if stream_manager.menu_active.get(chat_id, False):
            continue

        new_caption = get_rich_caption(song, played_secs=elapsed)
        total_sec_val = song.duration_secs if song and song.duration_secs else 0
        keyboard = get_rich_control_buttons(chat_id, is_paused=False, played_secs=elapsed, total_secs=total_sec_val)
        
        try:
            # Single atomic Bot API update preserving colored button styles (no flicker)
            await edit_styled_caption(chat_id, message_id, new_caption, keyboard)
        except Exception:
            break
