"""
core/proxy_generator.py
========================
High-speed proxy video generator for buttery-smooth timeline scrubbing & preview.
Generates lightweight 540p H.264 proxy with short keyframe interval (GOP=15).
Uses multi-vendor hardware acceleration (NVENC, AMF, QSV, VideoToolbox, VA-API) with automatic libx264 ultrafast fallback.
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

        from core.device_manager import device_manager
        encoder, _ = device_manager.get_ffmpeg_hwaccel_encoder()
        logger.info(f"Generating preview proxy (height={target_height}, encoder={encoder}) for {video_path.name}")

        vf_filter = f"scale=-2:{target_height}"
        gop_str = str(PREVIEW_PROXY_GOP)

        if encoder != "libx264":
            if encoder == "h264_nvenc":
                enc_args = ["-vf", vf_filter, "-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ll", "-cq", "28"]
            elif encoder == "h264_amf":
                enc_args = ["-vf", vf_filter, "-c:v", "h264_amf", "-quality", "speed", "-usage", "transcoding"]
            elif encoder == "h264_qsv":
                enc_args = ["-vf", vf_filter, "-c:v", "h264_qsv", "-preset", "veryfast"]
            elif encoder == "h264_videotoolbox":
                enc_args = ["-vf", vf_filter, "-c:v", "h264_videotoolbox", "-b:v", "3000k"]
            else:
                enc_args = ["-vf", vf_filter, "-c:v", encoder]

            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                *enc_args,
                "-g", gop_str,
                "-c:a", "aac",
                "-ac", "2",
                "-ar", "44100",
                "-b:a", "192k",
                "-movflags", "+faststart",
                str(temp_proxy)
            ]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=120, creationflags=SUBPROCESS_FLAGS)
                if res.returncode == 0 and temp_proxy.exists() and temp_proxy.stat().st_size > 1024:
                    temp_proxy.replace(proxy_path)
                    logger.info(f"{encoder.upper()} Proxy successfully generated: {proxy_path}")
                    return proxy_path
                else:
                    logger.warning(f"{encoder} proxy generation failed (code {res.returncode}), falling back to CPU...")
            except Exception as e:
                logger.warning(f"{encoder} proxy error ({e}), falling back to CPU...")

        # Fallback to libx264 ultrafast with all CPU threads
        cmd_cpu = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", vf_filter,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "26",
            "-threads", "0",
            "-g", gop_str,
            "-c:a", "aac",
            "-ac", "2",
            "-ar", "44100",
            "-b:a", "192k",
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

    def __init__(self, video_path: Path, target_height: int = PREVIEW_PROXY_HEIGHT, force: bool = False, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.target_height = target_height
        self.force = force

    def run(self):
        try:
            proxy_path = ProxyGenerator.generate_proxy(self.video_path, self.target_height, force=self.force)
            self.proxy_ready.emit(str(proxy_path))
        except Exception as e:
            logger.error(f"Background proxy worker failed: {e}", exc_info=True)
            self.proxy_failed.emit(str(e))
