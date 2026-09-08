# GᴀᴍᴇOᴠᴇʀ Mᴏᴠɪᴇ Hᴜʙ

A high-performance Telegram Video-On-Demand (VOD) streaming bot built with Pyrofork, PyTgCalls, and MovieBox API integration. Streams movies and TV series directly inside Telegram Group Voice/Video Chats with modern zero-emoji UI and dynamic player controls.

---

## Features

- **MovieBox VOD Engine:** Search and stream thousands of movies and TV series in HD with multi-language support (Hindi Dubbed & English).
- **Interactive Player Controls:** Play, Pause, Replay, Skip, Stop, and real-time seek bar.
- **Auto-Play Episodes:** Seamlessly plays consecutive episodes in a series.
- **Smart Resume:** Remembers playback position so users can resume where they left off.
- **Admin & Broadcast Dashboard:** Manage active groups, video quality (4K, 1080p, 720p), framerate (30, 60, 120 FPS), and broadcast messages.

---

## Deployment Guide (Ubuntu 24.04 LTS / 22.04 LTS VPS)

### 1. System Packages Installation

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git ffmpeg curl screen
```

### 2. Clone Repository

```bash
git clone https://github.com/imranyasin3964-stack/GAMEOVER_movie-bot.git
cd GAMEOVER_movie-bot
```

### 3. Virtual Environment Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configuration (`.env`)

Create your `.env` configuration:

```bash
cp .env.example .env
nano .env
```

Fill in your Telegram credentials:

```env
API_ID=your_api_id
API_HASH=your_api_hash
TOKEN=your_bot_token
STRING3=your_pyrogram_string_session
OWNER_ID=your_telegram_user_id
```

### 5. Running the Bot

#### Option A: Using Screen (Simple Background Process)

```bash
screen -S moviebot
source venv/bin/activate
python3 bot.py
```

*Press `Ctrl + A` then `D` to detach the screen. To reattach, run `screen -r moviebot`.*

#### Option B: Using Systemd Service (Auto-Restart on Reboot)

```bash
sudo nano /etc/systemd/system/moviebot.service
```

Paste the following service configuration:

```ini
[Unit]
Description=GameOver Movie Hub Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/GAMEOVER_movie-bot
ExecStart=/root/GAMEOVER_movie-bot/venv/bin/python3 bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable moviebot
sudo systemctl start moviebot
sudo systemctl status moviebot
```

---

## Commands

- `/movie <name>` - Search and stream a movie or TV series
- `/admin` - Open Admin Management Dashboard (Owner only)
- `/start` - Start the bot in private chat
