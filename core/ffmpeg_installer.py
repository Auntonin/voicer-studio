"""
core/ffmpeg_installer.py
========================
Automated FFmpeg Dependency Detector & First-Time Self-Installer for Voicer Studio.

Behavior:
1. First Check: Checks if FFmpeg is present in system PATH or local app directory.
2. If Present: Returns True immediately with 0 ms overhead (no re-installation).
3. If Missing (First Run):
   - Attempts silent Winget installation (`winget install Gyan.FFmpeg`).
   - Fallback: Auto-downloads pre-built standalone FFmpeg binaries to `tools/ffmpeg/bin/`.
   - Dynamically adds the local bin folder to `os.environ["PATH"]` so all media pipelines
     (AudioExtractor, ClipGenerator, VoiceSeparator, ProxyGenerator) work seamlessly without rebooting.
"""

from __future__ import annotations

import os
import sys
import shutil
import logging
import zipfile
import urllib.request
import subprocess
from pathlib import Path
from typing import Optional, Callable

log = logging.getLogger(__name__)

# Canonical local tools directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_TOOLS_DIR = PROJECT_ROOT / "runtime" / "bin"
LOCAL_TOOLS_DIR = PROJECT_ROOT / "tools" / "ffmpeg" / "bin"
APPDATA_TOOLS_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "VoicerStudio" / "tools" / "ffmpeg" / "bin"


def get_ffmpeg_executable() -> Optional[Path]:
    """
    Checks if ffmpeg is available in system PATH or local application directories.
    Returns Path to ffmpeg.exe if found, else None.
    """
    # 1. Check local project runtime/bin dir
    runtime_exe = RUNTIME_TOOLS_DIR / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    if runtime_exe.exists():
        _ensure_in_path(RUNTIME_TOOLS_DIR)
        return runtime_exe

    # 2. Check local project tools dir
    local_exe = LOCAL_TOOLS_DIR / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    if local_exe.exists():
        _ensure_in_path(LOCAL_TOOLS_DIR)
        return local_exe

    # 3. Check AppData tools dir
    appdata_exe = APPDATA_TOOLS_DIR / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    if appdata_exe.exists():
        _ensure_in_path(APPDATA_TOOLS_DIR)
        return appdata_exe

    # 4. Check system PATH via shutil.which
    sys_path_exe = shutil.which("ffmpeg")
    if sys_path_exe:
        return Path(sys_path_exe)

    return None


def _ensure_in_path(bin_dir: Path):
    """Prepends bin_dir to os.environ['PATH'] if not already present."""
    bin_str = str(bin_dir)
    paths = os.environ.get("PATH", "").split(os.pathsep)
    if bin_str not in paths:
        os.environ["PATH"] = bin_str + os.pathsep + os.environ.get("PATH", "")
        log.info(f"Added local FFmpeg directory to runtime PATH: {bin_str}")


def is_ffmpeg_available() -> bool:
    """
    Fast non-blocking verification of FFmpeg availability.
    Returns True if FFmpeg runs successfully.
    """
    exe = get_ffmpeg_executable()
    if not exe:
        return False

    try:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        res = subprocess.run(
            [str(exe), "-version"],
            capture_output=True,
            timeout=3,
            creationflags=flags
        )
        return res.returncode == 0
    except Exception as e:
        log.debug(f"FFmpeg check failed: {e}")
        return False


def ensure_ffmpeg(progress_cb: Optional[Callable[[int, str], None]] = None) -> bool:
    """
    Guarantees FFmpeg availability for Voicer Studio.

    - If FFmpeg is already installed: Returns True instantly (0ms work).
    - If missing on first run: Auto-installs via Winget or downloads standalone zip to local dir.
    """
    if is_ffmpeg_available():
        log.info("FFmpeg verification passed (already installed).")
        return True

    log.warning("FFmpeg not found in PATH or local directory. Initiating first-time automated setup...")
    if progress_cb:
        progress_cb(30, "FFmpeg missing — Starting first-time automated setup...")

    # ── Strategy 1: Windows Winget Auto-Install ───────────────────────────────
    if sys.platform == "win32" and shutil.which("winget"):
        try:
            if progress_cb:
                progress_cb(40, "Installing FFmpeg via Windows Package Manager (winget)...")
            log.info("Attempting winget install Gyan.FFmpeg...")
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            res = subprocess.run(
                [
                    "winget", "install", "Gyan.FFmpeg",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                    "--silent"
                ],
                capture_output=True, text=True, timeout=300,
                creationflags=flags
            )
            if res.returncode == 0:
                # Refresh PATH environment variable after Winget install
                _refresh_system_path()
                if is_ffmpeg_available():
                    log.info("Winget FFmpeg installation completed successfully!")
                    if progress_cb:
                        progress_cb(100, "FFmpeg installed successfully via Winget!")
                    return True
        except Exception as e:
            log.warning(f"Winget auto-installation failed: {e}")

    # ── Strategy 2: Standalone Download & Extraction to App Tools Folder ─────
    if progress_cb:
        progress_cb(50, "Downloading standalone FFmpeg package...")

    target_bin_dir = LOCAL_TOOLS_DIR
    try:
        target_bin_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        target_bin_dir = APPDATA_TOOLS_DIR
        target_bin_dir.mkdir(parents=True, exist_ok=True)

    # Official Gyan FFmpeg Release Essentials Zip URL
    download_url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    zip_path = target_bin_dir.parent / "ffmpeg-essentials.zip"

    try:
        log.info(f"Downloading FFmpeg standalone zip from {download_url} to {zip_path}")
        req = urllib.request.Request(
            download_url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) VoicerStudio/1.1.0"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp, open(zip_path, "wb") as out_f:
            total_size = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 512 * 1024
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out_f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0 and progress_cb:
                    pct = 50 + int((downloaded / total_size) * 35)
                    progress_cb(pct, f"Downloading FFmpeg binaries ({downloaded // (1024*1024)}MB / {total_size // (1024*1024)}MB)...")

        if progress_cb:
            progress_cb(88, "Extracting FFmpeg executables...")
        log.info("Extracting FFmpeg executables from zip...")

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            for member in zip_ref.namelist():
                if member.endswith("ffmpeg.exe") or member.endswith("ffprobe.exe") or member.endswith("ffmpeg") or member.endswith("ffprobe"):
                    filename = os.path.basename(member)
                    if filename:
                        target_file = target_bin_dir / filename
                        with zip_ref.open(member) as source, open(target_file, "wb") as target:
                            shutil.copyfileobj(source, target)
                        if sys.platform != "win32":
                            os.chmod(target_file, 0o755)

        # Cleanup zip file
        if zip_path.exists():
            zip_path.unlink(missing_ok=True)

        _ensure_in_path(target_bin_dir)

        if is_ffmpeg_available():
            log.info(f"Standalone FFmpeg auto-installation complete: {target_bin_dir}")
            if progress_cb:
                progress_cb(100, "FFmpeg installed successfully!")
            return True

    except Exception as e:
        log.error(f"Failed standalone FFmpeg download/extraction: {e}")
        if zip_path.exists():
            try:
                zip_path.unlink(missing_ok=True)
            except Exception:
                pass

    return is_ffmpeg_available()


def _refresh_system_path():
    """Refreshes os.environ['PATH'] from Windows registry after Winget installs."""
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment") as key:
                sys_path, _ = winreg.QueryValueEx(key, "Path")
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
                user_path, _ = winreg.QueryValueEx(key, "Path")
            full_path = user_path + os.pathsep + sys_path
            os.environ["PATH"] = full_path
        except Exception:
            pass
