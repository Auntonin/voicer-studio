import subprocess
import json
import logging
from pathlib import Path

from config import TEMP_DIR
from core.models import PipelineState

logger = logging.getLogger(__name__)

class AudioExtractor:
    def extract_audio(self, video_path: Path, output_path: Path) -> Path:
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")
        logger.info(f"Extracting audio from {video_path} to {output_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vn", "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "2",
            "-threads", "0",
            str(output_path)
        ]
        from config import SUBPROCESS_FLAGS
        file_mb = (video_path.stat().st_size / (1024 * 1024)) if video_path.exists() else 0
        timeout_sec = max(600, int(file_mb * 0.5) + 300)
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec, creationflags=SUBPROCESS_FLAGS)
        except FileNotFoundError:
            raise RuntimeError("ffmpeg not found. Please install ffmpeg.")
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"ffmpeg audio extraction timed out after {timeout_sec}s.")
        if res.returncode != 0:
            logger.error(f"FFmpeg extract_audio failed: {res.stderr}")
            raise RuntimeError(f"FFmpeg audio extraction failed: {res.stderr[:200]}")
        return output_path

    def probe_video(self, video_path: Path) -> dict:
        if not video_path.exists():
            return {"duration": 0.0, "width": 0, "height": 0, "fps": 0.0, "audio_tracks": 0}
            
        logger.info(f"Probing video: {video_path}")
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", str(video_path)
        ]
        from config import SUBPROCESS_FLAGS
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60, creationflags=SUBPROCESS_FLAGS)
        except FileNotFoundError:
            logger.error("ffprobe not found.")
            return {"duration": 0.0, "width": 0, "height": 0, "fps": 0.0, "audio_tracks": 0}
        except subprocess.TimeoutExpired:
            logger.error("ffprobe timed out.")
            return {"duration": 0.0, "width": 0, "height": 0, "fps": 0.0, "audio_tracks": 0}
        if res.returncode != 0:
            logger.error(f"FFprobe failed: {res.stderr}")
            return {"duration": 0.0, "width": 0, "height": 0, "fps": 0.0, "audio_tracks": 0}

        try:
            data = json.loads(res.stdout)
        except Exception as e:
            logger.error(f"Failed to parse ffprobe json output: {e}")
            return {"duration": 0.0, "width": 0, "height": 0, "fps": 0.0, "audio_tracks": 0}

        duration_raw = data.get("format", {}).get("duration", 0.0)
        duration = float(duration_raw) if duration_raw is not None else 0.0
        
        info = {
            "duration": duration,
            "width": 0,
            "height": 0,
            "fps": 0.0,
            "audio_tracks": 0
        }
        
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video" and info["width"] == 0:
                info["width"] = int(stream.get("width", 0))
                info["height"] = int(stream.get("height", 0))
                fps_str = stream.get("r_frame_rate", "0/1")
                try:
                    num, den = map(int, fps_str.split("/"))
                    info["fps"] = num / den if den != 0 else 0.0
                except:
                    pass
                if info["duration"] == 0.0 and "duration" in stream:
                    try:
                        info["duration"] = float(stream["duration"])
                    except:
                        pass
            elif stream.get("codec_type") == "audio":
                info["audio_tracks"] += 1
                if info["duration"] == 0.0 and "duration" in stream:
                    try:
                        info["duration"] = float(stream["duration"])
                    except:
                        pass
                
        return info

    def fill_state(self, state: PipelineState, video_path: Path, output_path: Path = None):
        logger.info("Filling state with video info and extracting audio...")
        info = self.probe_video(video_path)
        state.video_path = video_path
        state.video_duration = info["duration"]
        state.video_width = info["width"]
        state.video_height = info["height"]
        state.video_fps = info["fps"]
        state.video_audio_tracks = info["audio_tracks"]

        if output_path is None:
            output_path = TEMP_DIR / f"{video_path.stem}_work.wav"
        self.extract_audio(video_path, output_path)
        state.work_audio_path = output_path

