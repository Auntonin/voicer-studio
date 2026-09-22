"""
The Choice Voicer Dialogue Extractor
=====================================
Application-wide configuration and constants.
"""

import os
import sys
import subprocess
from pathlib import Path

# ── Process & Subsystem Flags ──────────────────────────────────────────────────
# On Windows GUI applications, subprocess calls pop up black command windows
# unless CREATE_NO_WINDOW is explicitly provided.
SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# ── App Metadata ───────────────────────────────────────────────────────────────
APP_NAME = "The Choice Voicer Dialogue Extractor"
APP_VERSION = "1.1.0"
APP_AUTHOR = "The Choice Voicer"
APP_LANGUAGE_DEFAULT = "en"
SUPPORTED_LANGUAGES = {"en": "English", "th": "ไทย (Thai)"}

# ── Update & Repository Settings ──────────────────────────────────────────────
GITHUB_REPO = "Auntonin/voicer-studio"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
UPDATE_CHECK_ON_STARTUP_DEFAULT = True

# ── Paths ──────────────────────────────────────────────────────────────────────
APP_DIR = Path(__file__).parent
MODELS_DIR = APP_DIR / "models"
ASSETS_DIR = APP_DIR / "assets"
TEMP_DIR = APP_DIR / ".temp"

# Ensure directories exist
MODELS_DIR.mkdir(exist_ok=True)
ASSETS_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)

# ── Settings File ──────────────────────────────────────────────────────────────
SETTINGS_FILE = APP_DIR / "settings.json"


def save_settings(settings: dict):
    """Saves application settings dictionary to settings.json atomically."""
    import json
    try:
        tmp_file = SETTINGS_FILE.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_file.replace(SETTINGS_FILE)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to save settings: {e}")


def load_settings() -> dict:
    """Loads application settings from settings.json, with fallback to empty dict."""
    import json
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

# ── Audio Defaults ─────────────────────────────────────────────────────────────
AUDIO_SAMPLE_RATE = 48000          # Hz — processing sample rate
AUDIO_CHANNELS = 2                 # Stereo
AUDIO_WORK_FORMAT = "wav"          # Internal processing format
AUDIO_EXPORT_FORMAT = "mp3"        # Final export format (The Choice Voicer)
AUDIO_EXPORT_CODEC = "libmp3lame"   # MP3 codec
AUDIO_EXPORT_BITRATE = "320k"      # 320 kbps high quality
AUDIO_MICRO_FADE_MS = 5            # 5ms micro-fade in/out to prevent audio clicks

# ── Image Defaults ─────────────────────────────────────────────────────────────
IMAGE_FORMAT = "png"
IMAGE_QUALITY = 95                 # Image quality (0-100)
IMAGE_MIN_BRIGHTNESS = 15          # Skip frames darker than this (0-255)
IMAGE_MOTION_BLUR_THRESHOLD = 100  # Laplacian variance threshold


# ── VAD Defaults ─────────────────────────────────────────────────────────────
# Tuned for game dubbing: pre-roll lead-in and post-roll lead-out so speech is centered
VAD_THRESHOLD = 0.3                # Tuned for game/anime dubbing: detect speech over BGM
VAD_MIN_SPEECH_DURATION_MS = 200   # Minimum speech duration to keep (shorter = more splits)
VAD_MIN_SILENCE_DURATION_MS = 200  # Silence gap that triggers a split (shorter = more clips)
VAD_PADDING_MS = 350               # 350ms (0.35s) lead-in and lead-out padding for dubbing breathing space
VAD_MERGE_GAP_MS = 120             # ONLY merge if gap < 120ms (breathing/pop sounds)

# Note: raise VAD_MERGE_GAP_MS in Settings if you want longer sentences per clip

# ── Diarization ────────────────────────────────────────────────────────────────
DIARIZATION_MODEL = "pyannote/speaker-diarization-3.1"
DIARIZATION_MAX_SPEAKERS = 8
DIARIZATION_MIN_SPEAKERS = 2


# ── Transcription & Thai Dubbing Defaults ──────────────────────────────────────
WHISPER_MODEL_DEFAULT = "medium"
WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3"]
WHISPER_LANGUAGE_DEFAULT = "th"    # Default to Thai for dubbing
WHISPER_INITIAL_PROMPT_THAI = "บทสนทนาพากย์ไทย เสียงพากย์อนิเมะและเกม Thai and English dubbing dialogue"
WHISPER_SUPPORTED_LANGUAGES = {
    "th": "Thai (ภาษาไทย)",
    "auto": "Auto-detect / Dynamic (ตรวจจับอัตโนมัติแยกช่วง)",
    "ja": "Japanese (ภาษาญี่ปุ่น)",
    "en": "English (ภาษาอังกฤษ)",
    "zh": "Chinese (ภาษาจีน)",
    "ko": "Korean (ภาษาเกาหลี)",
    "es": "Spanish (ภาษาสเปน)",
    "fr": "French (ภาษาฝรั่งเศส)",
    "de": "German (ภาษาเยอรมัน)",
}

CLEAN_THAI_HALLUCINATIONS_DEFAULT = True
FORMAT_THAI_KEYWORDS_DEFAULT = True

# ── Voice Separation ───────────────────────────────────────────────────────────
class VoiceSepMode:
    ORIGINAL = "original"          # No separation, use source audio
    VOICE_ISOLATION = "isolate"    # Demucs vocals stem
    HIGH_QUALITY = "hq"            # Demucs htdemucs_6s
    ROFORMER = "roformer"          # SOTA BS-RoFormer via audio-separator

VOICE_SEP_MODE_DEFAULT = VoiceSepMode.ROFORMER
ROFORMER_MODEL_DEFAULT = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
DEMUCS_MODEL_HQ = "htdemucs_6s"
DEMUCS_MODEL_STANDARD = "htdemucs"

# ── Timestamp Mode ─────────────────────────────────────────────────────────────
class TimestampMode:
    START_ONLY = "start_only"          # [2.049]
    START_AND_END = "start_end"        # [2.049, 4.200]
    RELATIVE = "relative"             # [0.0] (relative to clip start)
    ABSOLUTE = "absolute"             # Same as START_ONLY

TIMESTAMP_MODE_DEFAULT = TimestampMode.START_ONLY

# ── Pack Defaults ──────────────────────────────────────────────────────────────
PACK_BACKING_TRACK_NAME = "_backing_track"
PACK_INFO_FILENAME = "_pack_info.ini"
PACK_DUB_VIDEO_FILENAME = "dub_video.ogv"
PACK_INCLUDE_DUB_VIDEO_DEFAULT = True

# Allowed characters in sanitized speaker/character names
FILENAME_ALLOWED_CHARS = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_"
)

# ── UI ────────────────────────────────────────────────────────────────────────
WINDOW_TITLE = APP_NAME
WINDOW_MIN_WIDTH = 1280
WINDOW_MIN_HEIGHT = 800

# Color palette (Minimal Adobe-like Dark Theme)
COLORS = {
    "bg_primary":     "#252525",   # Main window background
    "bg_secondary":   "#323232",   # Toolbars, tabs
    "bg_panel":       "#2d2d2d",   # Cards, inner panels
    "bg_input":       "#1e1e1e",   # Textboxes, lists
    "border":         "#424242",   # Soft borders
    "border_light":   "#555555",
    "accent":         "#1473E6",   # Adobe flat blue
    "accent_hover":   "#3A96FF",
    "accent_green":   "#22A05B",
    "accent_yellow":  "#D69B0C",
    "accent_red":     "#D03B2E",
    "text_primary":   "#E0E0E0",
    "text_secondary": "#999999",
    "text_muted":     "#777777",
    "timeline_seg":   "#1473E6",
    "timeline_bg":    "#1e1e1e",
}

# ── Unified Speaker Color Palette ─────────────────────────────────────────────
# 1:1 color synchronization across Timeline tracks, Speaker List, and Dialogue cards
SPEAKER_PALETTE = [
    "#2563EB",  # A1: Royal Studio Blue
    "#10B981",  # A2: Emerald Green
    "#F59E0B",  # A3: Warm Amber / Gold
    "#8B5CF6",  # A4: Studio Purple / Violet
    "#EF4444",  # A5: Coral Red / Crimson
    "#06B6D4",  # A6: Ocean Cyan / Teal
    "#EC4899",  # A7: Vivid Pink / Magenta
    "#84CC16",  # A8: Lime Green
    "#F97316",  # A9: Bright Tangerine Orange
    "#6366F1",  # A10: Deep Indigo
]

# ── Video Preview Proxy Defaults ──────────────────────────────────────────────
PREVIEW_PROXY_ENABLED = True
PREVIEW_PROXY_HEIGHT = 540          # 540p proxy (e.g. 960x540) for buttery-smooth scrubbing & playback
PREVIEW_PROXY_GOP = 15              # Short GOP (keyframe every 15 frames ~0.5s) for instant seeking
