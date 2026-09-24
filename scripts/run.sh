#!/usr/bin/env bash
# ============================================================
# Voicer Studio — macOS & Linux Application Launcher
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Ensure FFmpeg paths on macOS if available via Homebrew
if [ -x "/opt/homebrew/bin/ffmpeg" ]; then
    export PATH="/opt/homebrew/bin:$PATH"
elif [ -x "/usr/local/bin/ffmpeg" ]; then
    export PATH="/usr/local/bin:$PATH"
fi

# 1. Initialize settings.json if missing
if [ ! -f "settings.json" ] && [ -f "settings.example.json" ]; then
    cp "settings.example.json" "settings.json"
fi

# 2. Check virtual environment
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    exec python main.py "$@"
else
    echo "[INFO] Virtual environment not found. Running initial setup..."
    bash "$SCRIPT_DIR/setup.sh"
    source .venv/bin/activate
    exec python main.py "$@"
fi
