"""
GameOver Movie Hub — Pure VOD Stream Downloader
Fast, reliable direct VOD downloader for MovieBox streams with 0% YouTube junk.
"""

import os
import time
import asyncio
import aiohttp
import socket
from typing import Optional, Callable, Awaitable
from core.queue_manager import SongInfo

socket.setdefaulttimeout(30.0)
from config import Config

DOWNLOADS_DIR = Config.DOWNLOADS_DIR
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


async def download_file(
    url: str,
    dest_path: str,
    progress_callback: Optional[Callable[[int, int, int], Awaitable[None]]] = None,
    headers: Optional[dict] = None
) -> bool:
    """Asynchronously download a MovieBox VOD URL to a file with progress updates."""
    loop = asyncio.get_running_loop()
    if not headers:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://themoviebox.org",
            "Referer": "https://themoviebox.org/",
        }
    else:
        headers = dict(headers)

    if os.path.exists(dest_path):
        try:
            os.remove(dest_path)
        except Exception:
            pass

    max_retries = 3
    total_size = 0

    start_time = time.time()
    last_update_time = time.time()
    last_console_time = 0

    timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=60)
    for attempt in range(1, max_retries + 1):
        connector = aiohttp.TCPConnector(ssl=False)
        try:
            existing_bytes = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0

            if existing_bytes > 0:
                headers["Range"] = f"bytes={existing_bytes}-"
                file_mode = "ab"
                print(f"[Downloader] Resuming VOD download from byte {existing_bytes} (Attempt {attempt}/{max_retries})...")
            else:
                headers.pop("Range", None)
                file_mode = "wb"
                if attempt > 1 and os.path.exists(dest_path):
                    try:
                        os.remove(dest_path)
                    except Exception:
                        pass
                print(f"[Downloader] Starting VOD download (Attempt {attempt}/{max_retries})...")

            async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
                async with session.get(url, timeout=timeout, allow_redirects=True) as response:
                    if response.status not in (200, 206):
                        if response.status == 416:
                            return True
                        print(f"[Downloader] Bad status code {response.status} for URL: {url[:60]}")
                        raise Exception(f"HTTP Status {response.status}")

                    if existing_bytes == 0:
                        total_size = int(response.headers.get('content-length', 0))
                    else:
                        content_range = response.headers.get('Content-Range', '')
                        if '/' in content_range:
                            try:
                                total_size = int(content_range.split('/')[-1])
                            except Exception:
                                pass
                        if not total_size:
                            partial_length = int(response.headers.get('content-length', 0))
                            total_size = existing_bytes + partial_length

                    total_size_mb = total_size / (1024 * 1024)
                    downloaded = existing_bytes

                    with open(dest_path, file_mode) as f:
                        async for chunk in response.content.iter_chunked(256 * 1024):
                            await loop.run_in_executor(None, f.write, chunk)
                            downloaded += len(chunk)

                            now = time.time()
                            elapsed = now - start_time
                            speed_bps = downloaded / elapsed if elapsed > 0 else 0
                            speed_mb = speed_bps / (1024 * 1024)
                            downloaded_mb = downloaded / (1024 * 1024)

                            if speed_bps > 0 and total_size > 0:
                                remaining_bytes = total_size - downloaded
                                seconds_left = max(0, int(remaining_bytes / speed_bps))
                                time_left_str = f"{seconds_left}s"
                            else:
                                time_left_str = "calculating..."

                            if now - last_console_time >= 0.5 or downloaded == total_size:
                                percent = int((downloaded / total_size) * 100) if total_size > 0 else 0
                                print(f"[Console Downloader] -> {percent}% | {downloaded_mb:.2f}/{total_size_mb:.2f} MB | Speed: {speed_mb:.2f} MB/s | ETA: {time_left_str}  ", end="\r", flush=True)
                                last_console_time = now

                            if progress_callback:
                                percent = int((downloaded / total_size) * 100) if total_size > 0 else 0
                                if now - last_update_time >= 2.0 or (total_size > 0 and percent >= 99):
                                    await progress_callback(percent, downloaded, total_size)
                                    last_update_time = now

                    if total_size > 0 and downloaded < total_size:
                        raise Exception(f"Downloaded bytes {downloaded} is less than total expected {total_size}")

                    if downloaded < 100000:
                        raise Exception(f"Downloaded file size too small ({downloaded} bytes).")

                    print()
                    if progress_callback:
                        await progress_callback(100, downloaded, total_size)
                    return True

        except Exception as e:
            print(f"\n[Downloader] Attempt {attempt} failed: {e}")
            if attempt == max_retries:
                break
            await asyncio.sleep(2)

    print(f"[Downloader] VOD download failed after {max_retries} attempts.")
    if os.path.exists(dest_path):
        try:
            os.remove(dest_path)
        except Exception:
            pass
    return False


async def download_song(
    song: SongInfo,
    mode: str = "video",
    progress_callback: Optional[Callable[[int, int, int], Awaitable[None]]] = None
) -> Optional[str]:
    """Downloads MovieBox VOD stream locally and returns local file path."""
    clean_id = "".join(c for c in song.title if c.isalnum() or c in ("-", "_"))[:30]
    if not clean_id:
        clean_id = str(abs(hash(song.title)))

    output_filename = f"{clean_id}_{mode}.mp4"
    output_path = os.path.join(DOWNLOADS_DIR, output_filename)

    if os.path.exists(output_path):
        size = os.path.getsize(output_path)
        if size > 100000:
            print(f"[Downloader] File already downloaded and valid: {output_path} ({size / (1024*1024):.2f} MB)")
            if progress_callback:
                try:
                    await progress_callback(100, size, size)
                except Exception:
                    pass
            return output_path
        else:
            try:
                os.remove(output_path)
            except Exception:
                pass

    download_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://themoviebox.org",
        "Referer": "https://themoviebox.org/",
        "Sec-Fetch-Dest": "video",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "cross-site"
    }

    target_url = song.video_url or song.audio_url
    if not target_url:
        print(f"[Downloader] No stream URL provided for {song.title}")
        return None

    print(f"[Downloader] Downloading VOD stream for: {song.title}")
    ok = await download_file(target_url, output_path, progress_callback, headers=download_headers)
    if ok:
        return output_path
    return None


def clean_cached_file(file_path: Optional[str]):
    """Removes downloaded file from filesystem."""
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
            print(f"[Downloader] Deleted local cached file: {file_path}")
        except Exception as e:
            print(f"[Downloader] Error deleting file {file_path}: {e}")
