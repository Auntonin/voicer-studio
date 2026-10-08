"""
core/updater.py
===============
Voicer Studio Auto-Update and Self-Update Engine.

Features:
- Queries GitHub Releases API for latest tags, release notes, and assets.
- Robust semantic version parser (e.g., v1.1.0 vs 1.2.0).
- Asynchronous downloader with smooth byte-level progress, transfer speed, and ETA calculation.
- Safe Windows file-locking bypass: launches a detached Python helper that waits for
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
import shutil
import hashlib
import logging
import subprocess
import tempfile
import urllib.request
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

try:
    from PySide6.QtCore import QThread, Signal
except ImportError:
    QThread = object
    Signal = lambda *args, **kwargs: None

from config import (
    APP_VERSION, GITHUB_REPO, GITHUB_RELEASES_API, TEMP_DIR,
    APP_DIR, SUBPROCESS_FLAGS
)

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
    sha256_url: str = ""


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
    Queries GitHub Releases API for the latest release on the main branch.
    
    Returns:
        (has_update: bool, update_info: Optional[UpdateInfo], error_message: Optional[str])
    """
    url = custom_url or f"https://api.github.com/repos/{repo}/releases/latest"
    import platform
    os_name = "macOS" if sys.platform == "darwin" else ("Linux" if sys.platform.startswith("linux") else "Windows")
    headers = {
        "User-Agent": f"VoicerStudio/{current_version} ({os_name}; {platform.machine()})",
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
    
    # Find best downloadable asset for current OS
    assets = data.get("assets", [])
    best_asset = None
    
    os_tag = "mac" if sys.platform == "darwin" else ("linux" if sys.platform.startswith("linux") else "win")
    
    # Native launchers need the complete runtime ZIP, not just a new launcher EXE.
    assets = sorted(assets, key=lambda asset: not asset.get('name', '').lower().endswith('.zip'))
    # Priority 1: VoicerStudio asset matching current OS tag
    for asset in assets:
        name = asset.get("name", "").lower()
        if "voicer" in name and os_tag in name and (name.endswith(".zip") or name.endswith(".exe")):
            best_asset = asset
            break
            
    # Only generic standalone packages may fall back; never cross OS boundaries.
    if not best_asset and getattr(sys, 'frozen', False):
        for asset in assets:
            name = asset.get("name", "").lower()
            if "voicer" in name and name.endswith(".exe") and sys.platform == 'win32':
                best_asset = asset
                break
                
    if best_asset:
        asset_name = best_asset.get("name", "update_package")
        asset_url = best_asset.get("browser_download_url", "")
        asset_size = best_asset.get("size", 0)
        is_zip = asset_name.lower().endswith(".zip")
    else:
        if has_update:
            return False, None, "The release has no supported update package. Download it from the release page instead."
        return False, None, None

    # The release must provide the matching checksum before offering installation.
    checksum_asset = next(
        (asset for asset in assets if asset.get("name", "") == f"{asset_name}.sha256"),
        None,
    )
    sha256_url = checksum_asset.get("browser_download_url", "") if checksum_asset else ""
    if has_update and not sha256_url:
        return False, None, 'The release update package is missing its SHA-256 checksum.'

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
        sha256_url=sha256_url,
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
        asset_path = Path(self.update_info.asset_name)
        if asset_path.name != self.update_info.asset_name or asset_path.suffix.lower() not in {".zip", ".exe"}:
            self.error.emit("Update package has an invalid filename.")
            return
        dest_path = self.save_dir / asset_path.name
        temp_path = dest_path.with_name(f".{dest_path.name}.part")

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
            expected_hash = None
            if not self.update_info.sha256_url:
                raise RuntimeError('Update package requires a SHA-256 checksum.')
            if self.update_info.sha256_url:
                try:
                    checksum_req = urllib.request.Request(self.update_info.sha256_url, headers=headers)
                    with urllib.request.urlopen(checksum_req, timeout=15) as checksum_response:
                        checksum_text = checksum_response.read(1024 * 1024).decode("utf-8", errors="replace")
                    checksum_match = re.search(r"\b([a-fA-F0-9]{64})\b", checksum_text)
                    if checksum_match:
                        expected_hash = checksum_match.group(1).lower()
                except Exception as ex:
                    raise RuntimeError(f'Could not load checksum file: {ex}') from ex
            if not expected_hash:
                raise RuntimeError('Release checksum file does not contain a valid SHA-256 hash.')

            with urllib.request.urlopen(req, timeout=15) as response:
                content_len = response.headers.get("Content-Length")
                if content_len:
                    try:
                        total = int(content_len)
                    except ValueError:
                        pass

                cancelled = False
                digest = hashlib.sha256()
                with open(temp_path, "wb") as f:
                    while True:
                        if self._is_cancelled:
                            cancelled = True
                            break

                        chunk = response.read(chunk_size)
                        if not chunk:
                            break

                        f.write(chunk)
                        digest.update(chunk)
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

                if cancelled:
                    temp_path.unlink(missing_ok=True)
                    self.error.emit("Download was cancelled.")
                    return

            if total and downloaded != total:
                raise RuntimeError(f"Update download is incomplete ({downloaded} of {total} bytes).")
            if expected_hash and digest.hexdigest().lower() != expected_hash:
                raise RuntimeError("Update integrity check failed (SHA-256 mismatch).")
            temp_path.replace(dest_path)

            # Final 100% progress emit
            self.progress.emit(downloaded, total or downloaded, speed_bps, 0.0)
            self.finished.emit(dest_path, self.update_info.is_zip)

        except urllib.error.URLError as e:
            log.exception('Update download connection failed', extra={'operation': 'update'})
            temp_path.unlink(missing_ok=True)
            self.error.emit(f"Download connection failed: {e.reason}")
        except Exception as e:
            temp_path.unlink(missing_ok=True)
            log.exception('Update download failed', extra={'operation': 'update'})
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


def _launch_update_helper(target_dir: Path, target_exe: Path, package: Optional[Path] = None, is_zip: bool = False):
    """Use the installed Python runtime, never cmd/batch or the custom app host."""
    candidates = [
        target_dir / '.venv' / 'Scripts' / 'pythonw.exe',
        target_dir / '.venv' / 'bin' / 'python',
        Path(getattr(sys, '_base_executable', sys.executable)),
        Path(sys.executable),
    ]
    interpreter = next((path for path in candidates if path.is_file() and path.name.lower().startswith('python')), None)
    if interpreter is None:
        raise RuntimeError('A Python runtime is required to install this update')
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    job = Path(tempfile.mkdtemp(prefix='voicer_update_', dir=TEMP_DIR))
    helper = job / 'installer.py'
    shutil.copy2(APP_DIR / 'scripts' / 'update_installer.py', helper)
    manifest = job / 'manifest.json'
    manifest.write_text(json.dumps({
        'pid': os.getpid(), 'target_dir': str(target_dir.resolve()),
        'target_exe': str(target_exe.resolve()), 'package': str(package.resolve()) if package else None,
        'is_zip': is_zip, 'restart': True,
    }, ensure_ascii=False), encoding='utf-8')
    kwargs = {'close_fds': True, 'cwd': str(target_dir)}
    if sys.platform == 'win32':
        kwargs['creationflags'] = SUBPROCESS_FLAGS | 0x00000200
    else:
        kwargs['start_new_session'] = True
    subprocess.Popen([str(interpreter), '-I', str(helper), str(manifest)], **kwargs)


def apply_update_and_restart(downloaded_file: Path, is_zip: bool, target_exe: Optional[Path] = None) -> Tuple[bool, str]:
    """Launch a detached Python installer; caller exits only after successful handoff."""
    if not downloaded_file.is_file():
        return False, f'Downloaded update file not found: {downloaded_file}'
    resolved_exe, _ = get_current_app_path()
    if target_exe:
        resolved_exe = target_exe.resolve()
    try:
        _launch_update_helper(resolved_exe.parent, resolved_exe, downloaded_file, is_zip)
        return True, 'Updater launched successfully.'
    except Exception as exc:
        log.error('Failed to launch updater: %s', exc, exc_info=True)
        return False, f'Failed to launch updater: {exc}'


def restart_application(target_app_dir: Optional[Path] = None):
    target_dir = target_app_dir or APP_DIR
    target_exe = target_dir / ('VoicerStudio.exe' if sys.platform == 'win32' else 'VoicerStudio')
    _launch_update_helper(target_dir, target_exe)
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app:
        app.quit()
    sys.exit(0)
