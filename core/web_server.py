"""
GameOver Movie Hub — 24/7 Web Server & Keep-Alive Dashboard
Listens on port 7860 (Hugging Face default) or $PORT.
Provides an HTML status dashboard, /health & /ping endpoints,
and a self-ping task to prevent Hugging Face Spaces from idling/sleeping.
"""

import os
import time
import asyncio
import psutil
from aiohttp import web
from config import Config

_START_TIME = time.time()


async def handle_home(request):
    uptime_sec = int(time.time() - _START_TIME)
    hours = uptime_sec // 3600
    mins = (uptime_sec % 3600) // 60
    secs = uptime_sec % 60
    uptime_str = f"{hours}h {mins}m {secs}s"

    try:
        cpu_usage = psutil.cpu_percent(interval=None)
        ram_mb = psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        cpu_usage = 0.0
        ram_mb = 0.0

    try:
        from core.player import stream_manager
        active_streams = len(stream_manager.active_calls) if hasattr(stream_manager, "active_calls") else 0
    except Exception:
        active_streams = 0

    port_val = os.getenv("PORT", "7860")
    bot_user = f"@{Config.BOT_USERNAME}" if Config.BOT_USERNAME else "@Gameovermovie_bot"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GᴀᴍᴇOᴠᴇʀ Mᴏᴠɪᴇ Hᴜʙ — Status</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; font-family: 'Outfit', sans-serif; }}
        body {{ background: #07090e; color: #e2e8f0; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }}
        .card {{ background: rgba(18, 24, 38, 0.85); backdrop-filter: blur(20px); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 28px; padding: 42px 36px; max-width: 520px; width: 100%; box-shadow: 0 25px 60px rgba(0,0,0,0.65); text-align: center; }}
        .badge {{ display: inline-flex; align-items: center; gap: 8px; background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.4); color: #10b981; padding: 7px 18px; border-radius: 50px; font-weight: 600; font-size: 0.88rem; margin-bottom: 24px; letter-spacing: 0.5px; }}
        .dot {{ width: 10px; height: 10px; background: #10b981; border-radius: 50%; box-shadow: 0 0 14px #10b981; animation: pulse 1.8s infinite; }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; transform: scale(1); }} 50% {{ opacity: 0.4; transform: scale(1.25); }} }}
        h1 {{ font-size: 1.9rem; font-weight: 700; color: #ffffff; margin-bottom: 6px; letter-spacing: -0.5px; }}
        p.subtitle {{ color: #94a3b8; font-size: 0.95rem; margin-bottom: 28px; }}
        .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; margin-bottom: 24px; }}
        .stat {{ background: rgba(10, 14, 23, 0.75); border: 1px solid rgba(255, 255, 255, 0.05); padding: 16px; border-radius: 16px; text-align: left; }}
        .stat-label {{ color: #64748b; font-size: 0.72rem; text-transform: uppercase; font-weight: 600; letter-spacing: 0.6px; margin-bottom: 4px; }}
        .stat-value {{ color: #f8fafc; font-size: 1.15rem; font-weight: 700; }}
        .full {{ grid-column: span 2; }}
        .footer {{ font-size: 0.8rem; color: #475569; margin-top: 16px; }}
        a {{ color: #38bdf8; text-decoration: none; font-weight: 600; }}
        a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="badge"><div class="dot"></div> 24/7 SERVER ONLINE</div>
        <h1>GᴀᴍᴇOᴠᴇʀ Mᴏᴠɪᴇ Hᴜʙ</h1>
        <p class="subtitle">Telegram Group Video & Movie Stream Engine</p>
        <div class="grid">
            <div class="stat"><div class="stat-label">Bot Handle</div><div class="stat-value"><a href="https://t.me/{bot_user.replace('@', '')}" target="_blank">{bot_user}</a></div></div>
            <div class="stat"><div class="stat-label">System Uptime</div><div class="stat-value">{uptime_str}</div></div>
            <div class="stat"><div class="stat-label">Active Streams</div><div class="stat-value">{active_streams} Calls</div></div>
            <div class="stat"><div class="stat-label">VOD Engine</div><div class="stat-value" style="color: #38bdf8; font-size: 0.95rem;">MovieBox API</div></div>
            <div class="stat"><div class="stat-label">CPU Load</div><div class="stat-value">{cpu_usage}%</div></div>
            <div class="stat"><div class="stat-label">RAM Usage</div><div class="stat-value">{ram_mb:.1f} MB</div></div>
        </div>
        <div class="footer">Hugging Face Space Keep-Alive Active • Port {port_val}</div>
    </div>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


async def handle_health(request):
    uptime_sec = int(time.time() - _START_TIME)
    try:
        from core.player import stream_manager
        active_streams = len(stream_manager.active_calls) if hasattr(stream_manager, "active_calls") else 0
    except Exception:
        active_streams = 0

    return web.json_response({
        "status": "online",
        "service": "GameOver Movie Hub",
        "uptime": uptime_sec,
        "bot": Config.BOT_USERNAME or "Gameovermovie_bot",
        "active_streams": active_streams
    })


async def handle_diag(request):
    """Diagnostic endpoint to inspect mirror status codes directly from cloud container."""
    sid = request.query.get("sid", "1552116708968747152")
    dpath = request.query.get("dpath", "72-hours-hindi-iHfXJ35IEQ1")
    se = int(request.query.get("se", "0"))
    ep = int(request.query.get("ep", "0"))

    import httpx
    from moviebox_api.v2 import Session
    from core.domain_manager import get_domain

    domain = get_domain()
    hosts = ["h5.aoneroom.com", "fmoviesunblocked.net", "sflix.film", "movieboxhd.net", domain]
    results = {}

    session = Session()
    auth_ok = False
    try:
        await session.ensure_cookies_are_assigned()
        auth_ok = True
    except Exception as e:
        results["auth_error"] = str(e)

    for bad_key in ["Origin", "origin"]:
        if bad_key in session._client.headers:
            del session._client.headers[bad_key]

    for host in hosts:
        url = f"https://{host}/wefeed-h5-bff/web/subject/play"
        params = {"subjectId": sid, "se": se, "ep": ep}
        headers = {
            "Referer": f"https://{host}/movies/{dpath}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "X-Forwarded-For": "103.255.4.1",
            "Client-IP": "103.255.4.1",
            "X-Real-IP": "103.255.4.1",
            "X-Client-Info": '{"timezone":"Africa/Nairobi"}',
        }
        # Try with session client
        try:
            r = await session._client.get(url, params=params, headers=headers, timeout=4.0)
            results[f"{host}_session"] = {
                "status": r.status_code,
                "content_type": r.headers.get("content-type"),
                "body": r.text[:200]
            }
        except Exception as e:
            results[f"{host}_session"] = {"error": str(e)}

        # Try with raw httpx client
        try:
            async with httpx.AsyncClient(timeout=4.0) as raw_client:
                r2 = await raw_client.get(url, params=params, headers=headers)
                results[f"{host}_raw"] = {
                    "status": r2.status_code,
                    "content_type": r2.headers.get("content-type"),
                    "body": r2.text[:200]
                }
        except Exception as e:
            results[f"{host}_raw"] = {"error": str(e)}

    # Check outgoing IP
    out_ip = {}
    try:
        async with httpx.AsyncClient(timeout=3.0) as ipc:
            rip = await ipc.get("https://api.ipify.org?format=json")
            out_ip = rip.json()
    except Exception as eip:
        out_ip = {"error": str(eip)}
    results["outgoing_ip"] = out_ip

    # Test downloading from CDN directly
    test_stream_url = "https://bcdnxw.hakunaymatata.com/resource/b95385b7a7b55d3565b078916bf71361.mp4?sign=cc218e329be6130ebc4b2b1a740ab8fa&t=1788879806"
    cdn_tests = {}

    # Test 1: Python subprocess curl -I
    import subprocess
    try:
        cp = subprocess.run(["curl", "-I", "-s", test_stream_url], capture_output=True, text=True, timeout=5)
        cdn_tests["curl_I_default"] = cp.stdout[:300] or cp.stderr[:200]
    except Exception as ec:
        cdn_tests["curl_I_default"] = str(ec)

    # Test 2: curl with http2 vs http1.1
    try:
        cp2 = subprocess.run(["curl", "--http2", "-I", "-s", test_stream_url], capture_output=True, text=True, timeout=5)
        cdn_tests["curl_http2"] = cp2.stdout[:300] or cp2.stderr[:200]
    except Exception as ec2:
        cdn_tests["curl_http2"] = str(ec2)

    # Test 3: curl without headers vs with browser headers
    try:
        cp3 = subprocess.run(["curl", "-r", "0-1000", "-s", "-o", "/dev/null", "-w", "%{http_code}", test_stream_url], capture_output=True, text=True, timeout=5)
        cdn_tests["curl_range_http_code"] = cp3.stdout
    except Exception as ec3:
        cdn_tests["curl_range_http_code"] = str(ec3)

    # Test 4: httpx with and without headers
    try:
        async with httpx.AsyncClient(timeout=5.0) as htc:
            rh1 = await htc.get(test_stream_url, headers={"Range": "bytes=0-1000"})
            cdn_tests["httpx_plain"] = {"status": rh1.status_code, "headers": dict(rh1.headers)}
    except Exception as eh1:
        cdn_tests["httpx_plain"] = str(eh1)

    results["cdn_tests"] = cdn_tests
    return web.json_response({"auth_ok": auth_ok, "results": results})


async def start_web_server():
    """Starts the 24/7 web server and self-ping background task."""
    try:
        app = web.Application()
        app.router.add_get("/", handle_home)
        app.router.add_get("/health", handle_health)
        app.router.add_get("/ping", handle_health)
        app.router.add_get("/diag", handle_diag)

        runner = web.AppRunner(app)
        await runner.setup()
        port = int(os.getenv("PORT", "7860"))
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        print(f"[WebServer]  24/7 Dashboard running on http://0.0.0.0:{port}")

        # Self-ping task to prevent cloud/container sleep
        async def _self_ping_loop():
            await asyncio.sleep(20)
            import aiohttp
            ping_url = f"http://127.0.0.1:{port}/health"
            while True:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(ping_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                            pass
                except Exception:
                    pass
                await asyncio.sleep(240)  # Ping every 4 minutes

        asyncio.create_task(_self_ping_loop())
        return runner
    except Exception as e:
        print(f"[WebServer]  Server start note: {e}")
        return None
