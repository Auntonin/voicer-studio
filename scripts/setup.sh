#!/usr/bin/env bash
# ============================================================
# The Choice Voicer Dialogue Extractor — macOS & Linux Setup
# ============================================================
# Automatically configures Python virtual environment (.venv),
# installs hardware-accelerated AI libraries (Metal MPS / CUDA / CPU),
# and verifies FFmpeg.
# ============================================================

set -e

# Change directory to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "============================================================"
echo "  Voicer Studio — Cross-Platform Setup (macOS / Linux)"
echo "============================================================"
echo ""

# ── 1. Detect Operating System & Architecture ────────────────
OS="$(uname -s)"
ARCH="$(uname -m)"
echo "[1/6] Operating System: $OS ($ARCH)"

# ── 2. Check Python ──────────────────────────────────────────
echo "[2/6] Checking Python installation..."
PYTHON_BIN=""
for cmd in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        VER="$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)"
        MAJOR="$(echo "$VER" | cut -d'.' -f1)"
        MINOR="$(echo "$VER" | cut -d'.' -f2)"
        if [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 10 ]; then
            PYTHON_BIN="$cmd"
            echo "      Found compatible Python: $cmd (v$VER)"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "[ERROR] Python 3.10 or higher is required."
    if [ "$OS" = "Darwin" ]; then
        echo "        On macOS with Homebrew: brew install python@3.11"
    else
        echo "        On Ubuntu/Debian: sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
    fi
    exit 1
fi

# ── 3. Check FFmpeg ──────────────────────────────────────────
echo "[3/6] Checking FFmpeg multimedia backend..."
if ! command -v ffmpeg >/dev/null 2>&1; then
    # Check well-known locations
    if [ -x "/opt/homebrew/bin/ffmpeg" ]; then
        export PATH="/opt/homebrew/bin:$PATH"
    elif [ -x "/usr/local/bin/ffmpeg" ]; then
        export PATH="/usr/local/bin:$PATH"
    fi
fi

if command -v ffmpeg >/dev/null 2>&1; then
    FFMPEG_VER="$(ffmpeg -version 2>/dev/null | head -n1)"
    echo "      Found FFmpeg: $FFMPEG_VER"
else
    echo "[WARNING] FFmpeg is not currently installed in PATH."
    if [ "$OS" = "Darwin" ]; then
        echo "          Installing via Homebrew..."
        if command -v brew >/dev/null 2>&1; then
            brew install ffmpeg || true
        else
            echo "          Please install Homebrew and run: brew install ffmpeg"
        fi
    elif [ "$OS" = "Linux" ]; then
        echo "          Install FFmpeg via package manager:"
        echo "          - Debian/Ubuntu: sudo apt install -y ffmpeg"
        echo "          - Fedora:        sudo dnf install -y ffmpeg"
        echo "          - Arch Linux:    sudo pacman -S ffmpeg"
    fi
fi

# ── 4. Virtual Environment Setup ────────────────────────────
echo "[4/6] Configuring virtual environment (.venv)..."
if [ ! -d ".venv" ] || [ ! -f ".venv/bin/python" ]; then
    echo "      Creating virtual environment with $PYTHON_BIN..."
    "$PYTHON_BIN" -m venv .venv
else
    echo "      Using existing .venv"
fi

source .venv/bin/activate
pip install --upgrade pip setuptools wheel >/dev/null 2>&1

# ── 5. Install PyTorch with Hardware Acceleration ───────────
echo "[5/6] Installing dependencies and deep learning runtimes..."
if [ "$OS" = "Darwin" ]; then
    echo "      macOS detected — Configuring Apple Silicon Metal (MPS) / Accelerate..."
    pip install torch torchvision torchaudio
elif [ "$OS" = "Linux" ]; then
    if command -v nvidia-smi >/dev/null 2>&1; then
        echo "      NVIDIA GPU detected on Linux — Configuring CUDA 12.1 runtime..."
        pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
    else
        echo "      Standard Linux CPU compute runtime..."
        pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
    fi
fi

# Install application requirements
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
fi

# ── 6. Ensure Settings File ─────────────────────────────────
echo "[6/6] Finalizing configuration..."
if [ ! -f "settings.json" ] && [ -f "settings.example.json" ]; then
    cp "settings.example.json" "settings.json"
    echo "      Created settings.json from template."
fi

echo ""
echo "============================================================"
echo "  Voicer Studio Setup Complete!"
echo "  To launch the studio: ./scripts/run.sh"
echo "============================================================"
