#!/bin/bash
set -e

echo "=========================================="
echo "   GameOver Movie Hub — VPS Auto Installer"
echo "=========================================="

echo "[1/4] Updating Ubuntu packages..."
sudo apt update -y
sudo apt install -y python3 python3-pip python3-venv git ffmpeg curl screen

echo "[2/4] Setting up Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

echo "[3/4] Installing Python requirements..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "[4/4] Checking .env configuration..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "⚠️  .env file created from .env.example!"
    echo "👉 Please edit .env with your credentials: nano .env"
else
    echo "✅ .env file found."
fi

echo ""
echo "=========================================="
echo "Installation complete!"
echo ""
echo "To start the Telegram Bot:"
echo "  screen -S moviebot"
echo "  source venv/bin/activate"
echo "  python3 bot.py"
echo ""
echo "To start the Public REST API Server:"
echo "  screen -S movieapi"
echo "  source venv/bin/activate"
echo "  python3 api.py"
echo "=========================================="
