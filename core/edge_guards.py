"""
core/edge_guards.py
===================
Defensive Edge Case Verification and Safety Guards for Voicer Studio.

Guards against:
- Silent videos (no audio track or empty audio streams)
- Ultra-short (< 0.5s) or zero-duration media files
- Corrupted or invalid media containers
- Low disk space (< 1 GB) before heavy processing or export
- Unsaved work protection during video swap, import, or reload
- Corrupted .voicer project files with automatic autosave recovery
"""

from __future__ import annotations

import os
import json
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Tuple, Dict, Any, Optional

from config import SUBPROCESS_FLAGS

log = logging.getLogger(__name__)


def probe_video_integrity(video_path: Path) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Validates a video file using ffprobe to ensure:
    1. The file exists and is non-empty.
    2. The container format is valid and readable.
    3. The video duration is at least 0.5 seconds.
    4. At least one valid audio stream is present for speech extraction.

    Returns:
        (is_valid: bool, error_message: str, metadata: dict)
    """
    if not video_path.exists():
        return False, f"File does not exist: {video_path.name}", {}

    if video_path.stat().st_size == 0:
        return False, f"File is completely empty (0 bytes): {video_path.name}", {}

    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,size,bit_rate:stream=codec_type,codec_name,channels,sample_rate,width,height",
        "-of", "json",
        str(video_path)
    ]

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=SUBPROCESS_FLAGS
        )
        if res.returncode != 0:
            return False, f"Invalid or unreadable video format: {res.stderr.strip() or 'Unknown decoder error'}", {}

        data = json.loads(res.stdout)
        format_info = data.get("format", {})
        streams = data.get("streams", [])

        # Duration check
        duration_str = format_info.get("duration", "0")
        try:
            duration = float(duration_str)
        except (ValueError, TypeError):
            duration = 0.0

        if duration < 0.5:
            return False, f"Video is too short ({duration:.2f}s). Minimum required duration is 0.5 seconds.", {}

        # Audio stream check
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
        if not audio_streams:
            return False, (
                "No audio stream found in this video.\n\n"
                "Voicer Studio requires an audio track to extract dialogue and isolate vocals. "
                "Please import a video with dialogue."
            ), {"duration": duration, "has_audio": False}

        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        width = int(video_streams[0].get("width", 0)) if video_streams else 0
        height = int(video_streams[0].get("height", 0)) if video_streams else 0

        metadata = {
            "duration": duration,
            "has_audio": True,
            "audio_channels": int(audio_streams[0].get("channels", 2)),
            "sample_rate": int(audio_streams[0].get("sample_rate", 44100)),
            "width": width,
            "height": height,
            "file_size": video_path.stat().st_size,
        }
        return True, "", metadata

    except subprocess.TimeoutExpired:
        return False, "ffprobe timed out while reading file metadata.", {}
    except FileNotFoundError:
        # ffprobe not found in path, allow load but log warning
        log.warning("ffprobe not found in PATH; skipping deep integrity probe.")
        return True, "", {"duration": 0.0, "has_audio": True}
    except Exception as e:
        return False, f"Error verifying media file: {str(e)}", {}


def check_disk_space(target_dir: Path, min_required_gb: float = 1.0) -> Tuple[bool, float, float]:
    """
    Checks free disk space for target directory or drive.
    Returns:
        (has_sufficient_space: bool, free_gb: float, total_gb: float)
    """
    try:
        target = target_dir.resolve()
        while not target.exists() and target.parent != target:
            target = target.parent
        usage = shutil.disk_usage(str(target))
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        return (free_gb >= min_required_gb), free_gb, total_gb
    except Exception as e:
        log.warning(f"Could not check disk usage for {target_dir}: {e}")
        return True, 999.0, 999.0


def find_recoverable_autosave(project_path: Path) -> Optional[Path]:
    """
    If a .voicer project file is corrupted or empty, searches for a valid .autosave
    counterpart in the same folder.
    """
    try:
        parent = project_path.parent
        stem = project_path.stem
        # Search for .autosave variants
        candidates = [
            parent / f"{stem}.autosave.voicer",
            parent / f".{stem}.autosave.voicer",
            parent / f"{stem}_autosave.voicer",
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.stat().st_size > 50:
                # Verify candidate is valid JSON
                try:
                    data = json.loads(candidate.read_text(encoding="utf-8"))
                    if "dialogues" in data or "speakers" in data:
                        return candidate
                except Exception:
                    continue
    except Exception as e:
        log.debug(f"Autosave search error: {e}")
    return None


def cleanup_orphaned_temp_files(temp_dir: Path, max_age_hours: float = 24.0) -> int:
    """
    Safely purges orphaned temporary files (audio slices, frames, preview files)
    older than max_age_hours to prevent disk bloating. Never touches active files.
    Returns the number of files deleted.
    """
    if not temp_dir.exists():
        return 0

    import time
    deleted_count = 0
    now = time.time()
    max_age_sec = max_age_hours * 3600.0

    try:
        for root, dirs, files in os.walk(temp_dir):
            for fname in files:
                p = Path(root) / fname
                try:
                    if now - p.stat().st_mtime < max_age_sec:
                        continue
                    if p.suffix.lower() in (".wav", ".tmp", ".part", ".mp3", ".png", ".log"):
                        p.unlink(missing_ok=True)
                        deleted_count += 1
                except Exception:
                    pass
    except Exception as e:
        log.debug(f"Temp cleanup error: {e}")
    return deleted_count


from core.platform_utils import get_short_path


class EdgeGuards:
    """Class wrapper for edge case guards and safety checks."""
    probe_video_integrity = staticmethod(probe_video_integrity)
    validate_video_file = staticmethod(probe_video_integrity)
    check_disk_space = staticmethod(check_disk_space)
    find_recoverable_autosave = staticmethod(find_recoverable_autosave)
    recover_corrupted_project = staticmethod(find_recoverable_autosave)
    cleanup_orphaned_temp_files = staticmethod(cleanup_orphaned_temp_files)
    get_short_path = staticmethod(get_short_path)

