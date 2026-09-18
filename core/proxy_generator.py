"""
core/proxy_generator.py
========================
High-speed proxy video generator for buttery-smooth timeline scrubbing & preview.
Generates lightweight 540p H.264 proxy with short keyframe interval (GOP=15).
Uses NVENC hardware acceleration when available, with automatic libx264 ultrafast fallback.
"""

import subprocess
import logging
from pathlib import Path
from typing import Optional, Callable
from PySide6.QtCore import QThread, Signal

from config import TEMP_DIR, SUBPROCESS_FLAGS, PREVIEW_PROXY_HEIGHT, PREVIEW_PROXY_GOP

logger = logging.getLogger(__name__)

PROXIES_DIR = TEMP_DIR / "proxies"
PROXIES_DIR.mkdir(parents=True, exist_ok=True)

_NVENC_AVAILABLE: Optional[bool] = None


def check_nvenc_available() -> bool:
    global _NVENC_AVAILABLE
    if _NVENC_AVAILABLE is not None:
        return _NVENC_AVAILABLE
    try:
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=0.1:size=320x240:rate=30",
            "-c:v", "h264_nvenc", "-f", "null", "-"
        ]
        res = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            creationflags=SUBPROCESS_FLAGS
        )
        _NVENC_AVAILABLE = (res.returncode == 0)
    except Exception:
        _NVENC_AVAILABLE = False
    return _NVENC_AVAILABLE


class ProxyGenerator:
    """Manages lightweight video proxy creation, caching, and retrieval."""

    @staticmethod
    def get_proxy_path(video_path: Path, target_height: int = PREVIEW_PROXY_HEIGHT) -> Path:
        """Returns the canonical deterministic cache path for a video's proxy."""
        try:
            st = video_path.stat()
            cache_key = f"{st.st_size}_{int(st.st_mtime)}"
        except Exception:
            cache_key = "default"
        clean_stem = "".join(c for c in video_path.stem if c.isalnum() or c in ("-", "_"))
        return PROXIES_DIR / f"{clean_stem}_{cache_key}_{target_height}p.mp4"

    get_default_proxy_path = get_proxy_path

    @classmethod
    def is_proxy_ready(cls, video_path: Path, target_height: int = PREVIEW_PROXY_HEIGHT) -> bool:
        proxy = cls.get_proxy_path(video_path, target_height)
        return proxy.exists() and proxy.stat().st_size > 1024

    @classmethod
    def generate_proxy(
        cls,
        video_path: Path,
        target_height: int = PREVIEW_PROXY_HEIGHT,
        force: bool = False
    ) -> Path:
        """
        Creates a fast-seeking proxy video with short keyframe interval (GOP=15).
        Returns the path to the proxy video file.
        """
        video_path = Path(video_path).resolve()
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        proxy_path = cls.get_proxy_path(video_path, target_height)
        if not force and proxy_path.exists() and proxy_path.stat().st_size > 1024:
            logger.info(f"Using cached preview proxy: {proxy_path}")
            return proxy_path

        temp_proxy = proxy_path.with_suffix(".tmp.mp4")
        if temp_proxy.exists():
            temp_proxy.unlink(missing_ok=True)

        use_nvenc = check_nvenc_available()
        logger.info(f"Generating preview proxy (height={target_height}, nvenc={use_nvenc}) for {video_path.name}")

        vf_filter = f"scale=-2:{target_height}"
        gop_str = str(PREVIEW_PROXY_GOP)

        if use_nvenc:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-vf", vf_filter,
                "-c:v", "h264_nvenc",
                "-preset", "p1",
                "-tune", "ll",
                "-cq", "28",
                "-g", gop_str,
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                str(temp_proxy)
            ]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=120, creationflags=SUBPROCESS_FLAGS)
                if res.returncode == 0 and temp_proxy.exists() and temp_proxy.stat().st_size > 1024:
                    temp_proxy.replace(proxy_path)
                    logger.info(f"NVENC Proxy successfully generated: {proxy_path}")
                    return proxy_path
                else:
                    logger.warning(f"NVENC proxy generation failed (code {res.returncode}), falling back to CPU...")
            except Exception as e:
                logger.warning(f"NVENC proxy error ({e}), falling back to CPU...")

        # Fallback to libx264 ultrafast
        cmd_cpu = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", vf_filter,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "26",
            "-g", gop_str,
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            str(temp_proxy)
        ]
        res_cpu = subprocess.run(cmd_cpu, capture_output=True, text=True, timeout=180, creationflags=SUBPROCESS_FLAGS)
        if res_cpu.returncode != 0 or not temp_proxy.exists() or temp_proxy.stat().st_size <= 1024:
            err = res_cpu.stderr[-400:] if res_cpu.stderr else "Unknown error"
            raise RuntimeError(f"FFmpeg CPU proxy generation failed: {err}")

        temp_proxy.replace(proxy_path)
        logger.info(f"CPU Proxy successfully generated: {proxy_path}")
        return proxy_path


class ProxyWorker(QThread):
    """Background worker thread for non-blocking proxy video generation."""
    proxy_ready = Signal(str)      # Emits str path to proxy video
    proxy_failed = Signal(str)     # Emits error message

    def __init__(self, video_path: Path, target_height: int = PREVIEW_PROXY_HEIGHT, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.target_height = target_height

    def run(self):
        try:
            proxy_path = ProxyGenerator.generate_proxy(self.video_path, self.target_height)
            self.proxy_ready.emit(str(proxy_path))
        except Exception as e:
            logger.error(f"Background proxy worker failed: {e}", exc_info=True)
            self.proxy_failed.emit(str(e))
