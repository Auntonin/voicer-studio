"""
core/updater.py
===============
Voicer Studio Auto-Update and Self-Update Engine.

Features:
- Queries GitHub Releases API for latest tags, release notes, and assets.
- Robust semantic version parser (e.g., v1.1.0 vs 1.2.0).
- Asynchronous downloader with smooth byte-level progress, transfer speed, and ETA calculation.
- Safe Windows file-locking bypass: generates a detached stager batch script that waits for
  the running process to exit, unpacks/replaces the executable and bundle files,
  relaunches the new version, and cleans up temporary update files.
- Handles both standalone one-file executables and directory bundles (.zip).
- Development environment detection (notifies developers if running from source).
"""

from __future__ import annotations

import os
import sys
import re
import time
import json
import logging
import subprocess
import urllib.request
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from PySide6.QtCore import QThread, Signal

from config import APP_VERSION, GITHUB_REPO, GITHUB_RELEASES_API, TEMP_DIR

log = logging.getLogger(__name__)


@dataclass
class UpdateInfo:
    """Metadata describing an available application update."""
    version: str
    tag_name: str
    name: str
    body: str
    published_at: str
    html_url: str
    asset_name: str
    asset_url: str
    asset_size: int
    is_zip: bool


def parse_version(version_str: str) -> tuple[int, ...]:
    """
    Parses a version string like 'v1.2.3', '1.2.0-beta.1', or '2.0' into an integer tuple
    for safe semantic comparison.
    """
    if not version_str:
        return (0, 0, 0)
    
    # Strip leading 'v' or 'V' and any build metadata
    clean = version_str.strip().lstrip("vV")
    # Take only the base version before hyphen or plus
    base = re.split(r"[-+]", clean)[0]
    
    parts = []
    for token in base.split("."):
        token_clean = re.sub(r"[^\d]", "", token)
        if token_clean:
            parts.append(int(token_clean))
        else:
            break
            
    # Normalize to at least 3 segments (major, minor, patch)
    while len(parts) < 3:
        parts.append(0)
        
    return tuple(parts[:3])


def is_version_newer(remote_version: str, current_version: str = APP_VERSION) -> bool:
    """
    Returns True if remote_version is strictly newer than current_version.
    """
    remote_tuple = parse_version(remote_version)
    current_tuple = parse_version(current_version)
    return remote_tuple > current_tuple


def check_for_updates(
    current_version: str = APP_VERSION,
    repo: str = GITHUB_REPO,
    custom_url: Optional[str] = None,
    timeout: int = 10
) -> Tuple[bool, Optional[UpdateInfo], Optional[str]]:
    """
    Queries GitHub Releases API for the latest release.
    
    Returns:
        (has_update: bool, update_info: Optional[UpdateInfo], error_message: Optional[str])
    """
    url = custom_url or f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {
        "User-Agent": f"VoicerStudio/{current_version} (Windows; x64)",
        "Accept": "application/vnd.github.v3+json",
    }
    
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                return False, None, f"GitHub API responded with status {response.status}"
            raw_data = response.read().decode("utf-8")
            data = json.loads(raw_data)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, None, "No releases found on GitHub repository."
        elif e.code == 403:
            return False, None, "GitHub API rate limit exceeded. Please try again later."
        return False, None, f"HTTP Error {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return False, None, f"Network connection failed: {e.reason}"
    except Exception as e:
        return False, None, f"Update check failed: {str(e)}"

    tag_name = data.get("tag_name", "")
    release_name = data.get("name") or tag_name
    release_body = data.get("body") or ""
    published_at = data.get("published_at", "")
    html_url = data.get("html_url", f"https://github.com/{repo}/releases")
    
    # Strip 'v' to extract version string
    remote_version = tag_name.lstrip("vV")
    has_update = is_version_newer(remote_version, current_version)
    
    # Find best downloadable asset
    assets = data.get("assets", [])
    best_asset = None
    
    # Priority 1: .exe or .zip that matches VoicerStudio
    for asset in assets:
        name = asset.get("name", "").lower()
        if "voicer" in name and (name.endswith(".exe") or name.endswith(".zip")):
            best_asset = asset
            break
            
    # Priority 2: Any .zip or .exe asset
    if not best_asset:
        for asset in assets:
            name = asset.get("name", "").lower()
            if name.endswith(".zip") or name.endswith(".exe"):
                best_asset = asset
                break
                
    if best_asset:
        asset_name = best_asset.get("name", "update_package")
        asset_url = best_asset.get("browser_download_url", "")
        asset_size = best_asset.get("size", 0)
        is_zip = asset_name.lower().endswith(".zip")
    else:
        # Fallback to source zipball if no compiled assets attached
        asset_name = f"{tag_name}.zip"
        asset_url = data.get("zipball_url", "")
        asset_size = 0
        is_zip = True

    update_info = UpdateInfo(
        version=remote_version,
        tag_name=tag_name,
        name=release_name,
        body=release_body,
        published_at=published_at,
        html_url=html_url,
        asset_name=asset_name,
        asset_url=asset_url,
        asset_size=asset_size,
        is_zip=is_zip,
    )

    return has_update, update_info, None


class UpdateDownloaderThread(QThread):
    """
    Background worker that downloads an update asset with real-time byte tracking,
    speed smoothing, and ETA estimation.
    """
    progress = Signal(int, int, float, float)  # downloaded_bytes, total_bytes, speed_bps, eta_seconds
    finished = Signal(Path, bool)               # downloaded_file_path, is_zip
    error = Signal(str)                        # error_message

    def __init__(self, update_info: UpdateInfo, save_dir: Optional[Path] = None):
        super().__init__()
        self.update_info = update_info
        self.save_dir = save_dir or (TEMP_DIR / "updates")
        self._is_cancelled = False

    def cancel(self):
        """Request download cancellation."""
        self._is_cancelled = True

    def run(self):
        self.save_dir.mkdir(parents=True, exist_ok=True)
        dest_path = self.save_dir / self.update_info.asset_name

        url = self.update_info.asset_url
        if not url:
            self.error.emit("No valid download URL provided for this release.")
            return

        headers = {
            "User-Agent": f"VoicerStudio/{APP_VERSION} (Windows; x64)",
            "Accept": "application/octet-stream",
        }
        req = urllib.request.Request(url, headers=headers)

        chunk_size = 64 * 1024  # 64 KB
        downloaded = 0
        total = self.update_info.asset_size
        start_time = time.time()
        last_update_time = start_time
        recent_bytes = 0
        speed_bps = 0.0

        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                content_len = response.headers.get("Content-Length")
                if content_len:
                    try:
                        total = int(content_len)
                    except ValueError:
                        pass

                with open(dest_path, "wb") as f:
                    while True:
                        if self._is_cancelled:
                            f.close()
                            if dest_path.exists():
                                try:
                                    dest_path.unlink()
                                except Exception:
                                    pass
                            self.error.emit("Download was cancelled.")
                            return

                        chunk = response.read(chunk_size)
                        if not chunk:
                            break

                        f.write(chunk)
                        chunk_len = len(chunk)
                        downloaded += chunk_len
                        recent_bytes += chunk_len

                        now = time.time()
                        dt = now - last_update_time
                        if dt >= 0.25:  # Update speed every 250ms
                            current_speed = recent_bytes / dt
                            if speed_bps <= 0:
                                speed_bps = current_speed
                            else:
                                speed_bps = 0.7 * speed_bps + 0.3 * current_speed
                            recent_bytes = 0
                            last_update_time = now

                            remaining_bytes = max(0, total - downloaded)
                            eta = remaining_bytes / speed_bps if speed_bps > 0 else 0.0
                            self.progress.emit(downloaded, total, speed_bps, eta)

            # Final 100% progress emit
            self.progress.emit(downloaded, total or downloaded, speed_bps, 0.0)
            self.finished.emit(dest_path, self.update_info.is_zip)

        except urllib.error.URLError as e:
            self.error.emit(f"Download connection failed: {e.reason}")
        except Exception as e:
            self.error.emit(f"Failed to download update: {str(e)}")


def get_current_app_path() -> Tuple[Path, bool]:
    """
    Detects whether the app is running as a compiled standalone executable
    or from source code (.py).
    
    Returns:
        (app_path: Path, is_frozen: bool)
    """
    is_frozen = getattr(sys, "frozen", False)
    if is_frozen:
        # Running as PyInstaller or packaged standalone binary
        return Path(sys.executable).resolve(), True
    else:
        # Running from source in project directory
        # If VoicerStudio.exe exists in root, use it as target
        root_dir = Path(__file__).resolve().parent.parent
        exe_path = root_dir / "VoicerStudio.exe"
        if exe_path.exists():
            return exe_path.resolve(), False
        return Path(sys.executable).resolve(), False


def generate_updater_batch(
    downloaded_file: Path,
    is_zip: bool,
    target_app_dir: Path,
    target_exe: Path,
    current_pid: int
) -> Path:
    """
    Generates a robust Windows batch script (.bat) that:
    1. Waits for the current Voicer Studio process (PID) to fully exit so file locks release.
    2. Backs up the previous executable / files.
    3. Replaces old files with the newly downloaded version (unzipping or direct copy).
    4. Relaunches the updated Voicer Studio executable.
    5. Cleans up downloaded archives and self-deletes.
    """
    updater_bat_path = downloaded_file.parent / "voicer_updater_run.bat"
    
    # Safe Windows batch script with UTF-8 encoding
    bat_content = f"""@echo off
chcp 65001 >nul
title Voicer Studio Updater
echo ======================================================================
echo               Voicer Studio — Updating Application...
echo ======================================================================
echo.

set "PID={current_pid}"
set "SOURCE_FILE={str(downloaded_file)}"
set "TARGET_DIR={str(target_app_dir)}"
set "TARGET_EXE={str(target_exe)}"
set "IS_ZIP={'1' if is_zip else '0'}"

echo [1/4] Waiting for Voicer Studio (PID %PID%) to close...
set RETRIES=0
:WAIT_PID
tasklist /FI "PID eq %PID%" 2>NUL | find /I "%PID%" >NUL
if not errorlevel 1 (
    set /a RETRIES+=1
    if %RETRIES% GEQ 25 (
        echo [INFO] Terminating process %PID% gracefully...
        taskkill /F /PID %PID% >nul 2>&1
    )
    timeout /t 1 /nobreak >nul
    goto WAIT_PID
)

:: Wait for VoicerStudio launcher process to also release locks
set RETRIES_EXE=0
:WAIT_EXE
tasklist /FI "IMAGENAME eq VoicerStudio.exe" 2>NUL | find /I "VoicerStudio.exe" >NUL
if not errorlevel 1 (
    set /a RETRIES_EXE+=1
    if %RETRIES_EXE% GEQ 10 (
        taskkill /F /IM VoicerStudio.exe >nul 2>&1
    )
    timeout /t 1 /nobreak >nul
    goto WAIT_EXE
)

echo [2/4] Processes closed. Releasing Windows file handles...
timeout /t 1 /nobreak >nul

echo [3/4] Installing updated files...
if "%IS_ZIP%"=="1" (
    echo [INFO] Extracting update archive into %TARGET_DIR%...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "$ErrorActionPreference = 'Stop'; try {{ $src = $env:SOURCE_FILE; $dst = $env:TARGET_DIR; $temp = Join-Path $env:TEMP ('voicer_upd_' + [System.Guid]::NewGuid().ToString('N')); Expand-Archive -LiteralPath $src -DestinationPath $temp -Force; $items = Get-ChildItem -Path $temp; if ($items.Count -eq 1 -and $items[0].PSIsContainer) {{ Copy-Item -Path (Join-Path $items[0].FullName '*') -Destination $dst -Recurse -Force }} else {{ Copy-Item -Path (Join-Path $temp '*') -Destination $dst -Recurse -Force }}; Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue; exit 0 }} catch {{ Write-Error $_; exit 1 }}"
) else (
    echo [INFO] Updating executable: %TARGET_EXE%...
    if exist "%TARGET_EXE%" (
        copy /y "%TARGET_EXE%" "%TARGET_EXE%.bak" >nul 2>&1
    )
    copy /y "%SOURCE_FILE%" "%TARGET_EXE%" >nul
)

if errorlevel 1 (
    echo.
    echo ======================================================================
    echo [ERROR] Update installation failed! 
    echo If access was denied, please run the application as Administrator.
    echo ======================================================================
    pause
    exit /b 1
)

echo.
echo [4/4] Update applied successfully! Relaunching Voicer Studio...
timeout /t 1 /nobreak >nul
start "" "%TARGET_EXE%"

:: Clean up downloaded update package
if exist "%SOURCE_FILE%" (
    del /f /q "%SOURCE_FILE%" >nul 2>&1
)

echo Done.
:: Self-delete updater batch script
(goto) 2>nul & del "%~f0"
"""
    updater_bat_path.write_text(bat_content, encoding="utf-8")
    return updater_bat_path


def apply_update_and_restart(
    downloaded_file: Path,
    is_zip: bool,
    target_exe: Optional[Path] = None
) -> Tuple[bool, str]:
    """
    Prepares and launches the detached background updater script and signals the
    caller to exit the application.
    
    Returns:
        (success: bool, message: str)
    """
    if not downloaded_file.exists():
        return False, f"Downloaded update file not found: {downloaded_file}"

    resolved_exe, is_frozen = get_current_app_path()
    if target_exe:
        resolved_exe = target_exe.resolve()

    target_app_dir = resolved_exe.parent
    current_pid = os.getpid()

    try:
        bat_file = generate_updater_batch(
            downloaded_file=downloaded_file,
            is_zip=is_zip,
            target_app_dir=target_app_dir,
            target_exe=resolved_exe,
            current_pid=current_pid
        )

        # Launch detached process with high-level flags on Windows
        # DETACHED_PROCESS (0x00000008) + CREATE_NEW_PROCESS_GROUP (0x00000200)
        detached_flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0
        
        subprocess.Popen(
            ["cmd.exe", "/c", str(bat_file)],
            creationflags=detached_flags,
            close_fds=True,
            cwd=str(target_app_dir)
        )
        return True, "Updater launched successfully."
    except Exception as e:
        log.error(f"Failed to launch updater: {e}", exc_info=True)
        return False, f"Failed to launch updater stager: {str(e)}"
