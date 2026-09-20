"""
core/platform_utils.py
======================
Cross-platform operating system abstraction layer for Voicer Studio.
Provides unified interfaces for:
- Platform identification (Windows, macOS, Linux)
- System file manager integration (open folder, reveal file in Explorer/Finder/File Manager)
- Keyboard shortcut formatting (translates Ctrl/Alt to ⌘/⌥ on macOS)
- System typography and font family discovery
- Standard application data and cache directories
- Windows 8.3 short-path fallback for Unicode compatibility with C/C++ libraries
"""

from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path
from typing import Optional

# ── Platform Detection ────────────────────────────────────────────────────────
IS_WINDOWS: bool = (sys.platform == "win32")
IS_MACOS: bool = (sys.platform == "darwin")
IS_LINUX: bool = (sys.platform.startswith("linux"))

# Windows Subprocess Flag (hide CMD popup)
SUBPROCESS_FLAGS: int = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0


def is_windows() -> bool:
    return IS_WINDOWS


def is_macos() -> bool:
    return IS_MACOS


def is_linux() -> bool:
    return IS_LINUX


# ── File Manager Integration ──────────────────────────────────────────────────

def open_in_file_manager(folder_path: Path | str) -> bool:
    """
    Opens the target directory in the OS default file manager:
    - Windows: os.startfile
    - macOS: open
    - Linux: xdg-open
    """
    path = Path(folder_path).resolve()
    if not path.exists():
        return False

    try:
        if IS_WINDOWS:
            os.startfile(str(path))
            return True
        elif IS_MACOS:
            res = subprocess.run(["open", str(path)], creationflags=SUBPROCESS_FLAGS)
            return res.returncode == 0
        else:
            res = subprocess.run(["xdg-open", str(path)], creationflags=SUBPROCESS_FLAGS)
            return res.returncode == 0
    except Exception:
        return False


def reveal_in_file_manager(file_path: Path | str) -> bool:
    """
    Highlights/selects the specified file in the OS file manager:
    - Windows: explorer /select,<file>
    - macOS: open -R <file>
    - Linux: xdg-open <folder>
    """
    path = Path(file_path).resolve()
    if not path.exists():
        return False

    try:
        if IS_WINDOWS:
            # Note: Windows Explorer requires exact path without forward slashes
            win_path = str(path).replace("/", "\\")
            subprocess.run(["explorer", f"/select,{win_path}"], creationflags=SUBPROCESS_FLAGS)
            return True
        elif IS_MACOS:
            res = subprocess.run(["open", "-R", str(path)], creationflags=SUBPROCESS_FLAGS)
            return res.returncode == 0
        else:
            res = subprocess.run(["xdg-open", str(path.parent)], creationflags=SUBPROCESS_FLAGS)
            return res.returncode == 0
    except Exception:
        return False


# ── Keyboard Shortcut Formatting ──────────────────────────────────────────────

def format_shortcut(shortcut_str: str) -> str:
    """
    Adapts shortcut strings according to the current operating system.
    On macOS:
        'Ctrl+Z'        -> '⌘Z'
        'Ctrl + Wheel'  -> '⌘ + Wheel'
        'Ctrl+Alt+S'    -> '⌘⌥S'
        'Alt + Drag'    -> '⌥ + Drag'
        'Delete'        -> '⌫ Delete'
    On Windows/Linux:
        Returns standard Ctrl / Alt notation.
    """
    if not shortcut_str:
        return ""

    if not IS_MACOS:
        return shortcut_str

    formatted = shortcut_str
    # Replace combinations with Mac standard symbols
    formatted = formatted.replace("Ctrl + ", "⌘ + ")
    formatted = formatted.replace("Ctrl+", "⌘")
    formatted = formatted.replace("Ctrl", "⌘")
    formatted = formatted.replace("Alt + ", "⌥ + ")
    formatted = formatted.replace("Alt+", "⌥")
    formatted = formatted.replace("Alt", "⌥")
    formatted = formatted.replace("Shift + ", "⇧ + ")
    formatted = formatted.replace("Shift+", "⇧")
    formatted = formatted.replace("Shift", "⇧")
    formatted = formatted.replace("Backspace", "⌫")
    return formatted


# ── System Typography ─────────────────────────────────────────────────────────

def get_default_font_family() -> str:
    """Returns the primary recommended UI font family for the current OS."""
    if IS_WINDOWS:
        return "Segoe UI"
    elif IS_MACOS:
        return ".AppleSystemUIFont"
    else:
        return "Ubuntu"


def get_thai_font_family() -> str:
    """Returns the primary recommended Thai font family for the current OS."""
    if IS_WINDOWS:
        return "Leelawadee UI"
    elif IS_MACOS:
        return "Thonburi"
    else:
        return "Noto Sans Thai"


# ── Standard Directories ──────────────────────────────────────────────────────

def get_appdata_dir() -> Path:
    """
    Returns the standard writable user data directory for Voicer Studio:
    - Windows: %APPDATA%/VoicerStudio
    - macOS: ~/Library/Application Support/VoicerStudio
    - Linux: ~/.config/voicer-studio
    """
    if IS_WINDOWS:
        base = os.environ.get("APPDATA")
        if base:
            p = Path(base) / "VoicerStudio"
        else:
            p = Path.home() / "AppData" / "Roaming" / "VoicerStudio"
    elif IS_MACOS:
        p = Path.home() / "Library" / "Application Support" / "VoicerStudio"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        if xdg:
            p = Path(xdg) / "voicer-studio"
        else:
            p = Path.home() / ".config" / "voicer-studio"

    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Fallback to home or current directory if system directory is restricted
        p = Path.home() / ".voicer_studio"
        p.mkdir(parents=True, exist_ok=True)
    return p


def get_crash_log_path() -> Path:
    """Returns the absolute path to crash.log in the user data directory."""
    return get_appdata_dir() / "crash.log"


# ── Windows 8.3 Short Path Fallback ───────────────────────────────────────────

def get_short_path(path: Path | str) -> str:
    """
    Returns the Windows 8.3 short ASCII path (e.g. C:\\1234~1\\VIDEO~1.MP4).
    This guarantees that C/C++ libraries (like OpenCV VideoCapture or legacy DLLs)
    can reliably open files even when the path contains Thai, Asian, or accented Unicode characters.
    On macOS and Linux, returns str(path) unchanged since POSIX handles UTF-8 natively.
    """
    p_str = str(path)
    if not IS_WINDOWS:
        return p_str

    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(500)
        res = ctypes.windll.kernel32.GetShortPathNameW(p_str, buf, 500)
        if res > 0 and buf.value:
            return buf.value
    except Exception:
        pass
    return p_str


class PlatformUtils:
    """Unified cross-platform helper singleton."""
    is_windows = staticmethod(is_windows)
    is_macos = staticmethod(is_macos)
    is_linux = staticmethod(is_linux)
    open_in_file_manager = staticmethod(open_in_file_manager)
    reveal_in_file_manager = staticmethod(reveal_in_file_manager)
    format_shortcut = staticmethod(format_shortcut)
    get_default_font_family = staticmethod(get_default_font_family)
    get_thai_font_family = staticmethod(get_thai_font_family)
    get_appdata_dir = staticmethod(get_appdata_dir)
    get_crash_log_path = staticmethod(get_crash_log_path)
    get_short_path = staticmethod(get_short_path)


platform_utils = PlatformUtils()
