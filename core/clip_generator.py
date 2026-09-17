import subprocess
import logging
from pathlib import Path
from core.models import PipelineState, DialogueItem
from config import AUDIO_EXPORT_BITRATE, AUDIO_SAMPLE_RATE

logger = logging.getLogger(__name__)

class ClipGenerator:
    def generate_clip(self, item: DialogueItem, source_audio: Path, output_dir: Path, speaker_safe_name: str) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{item.filename_base(speaker_safe_name)}.mp3"
        output_path = output_dir / filename
        
        duration = max(0.05, item.end - item.start)
        # Apply 5ms micro-fade in/out to prevent audio pops/clicks
        fade_out_st = max(0.0, duration - 0.005)
        afade_filter = f"afade=t=in:ss=0:d=0.005,afade=t=out:st={fade_out_st:.3f}:d=0.005"
        
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{item.start:.3f}",
            "-i", str(source_audio),
            "-t", f"{duration:.3f}",
            "-af", afade_filter,
            "-vn",
            "-c:a", "libmp3lame",
            "-b:a", AUDIO_EXPORT_BITRATE,
            "-ar", str(AUDIO_SAMPLE_RATE),
            str(output_path)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.error(f"FFmpeg error generating clip {item.index}: {res.stderr}")
            raise RuntimeError(f"FFmpeg failed to generate clip {item.index}: {res.stderr[:200]}")

        item.audio_path = output_path
        return output_path

    def generate_all_clips(self, state: PipelineState, source_audio: Path, output_dir: Path):
        logger.info(f"Generating clips in {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)
        audio = source_audio or state.work_audio_path
        for item in state.active_dialogues():
            try:
                speaker_safe_name = state.get_speaker_safe_name(item.speaker_id)
                self.generate_clip(item, audio, output_dir, speaker_safe_name)
            except Exception as e:
                logger.error(f"Failed to generate clip {item.index}: {e}")

    def regenerate_clip(self, item: DialogueItem, state: PipelineState, output_dir: Path):
        logger.info(f"Regenerating clip for item {item.index}")
        speaker_safe_name = state.get_speaker_safe_name(item.speaker_id)
        source_audio = state.separated_vocals_path if state.separated_vocals_path else state.work_audio_path
        self.generate_clip(item, source_audio, output_dir, speaker_safe_name)
