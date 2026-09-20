import os
import subprocess
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Callable
from core.models import PipelineState, DialogueItem
from config import AUDIO_EXPORT_BITRATE, AUDIO_SAMPLE_RATE

logger = logging.getLogger(__name__)

class ClipGenerator:
    def generate_clip(self, item: DialogueItem, source_audio: Path, output_dir: Path, speaker_safe_name: str) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{item.filename_base(speaker_safe_name)}.mp3"
        output_path = output_dir / filename
        
        duration = max(0.05, item.end - item.start)
        # Apply 15ms micro-fade in/out to prevent audio pops/clicks at clip boundaries
        fade_ms = 0.015
        fade_out_st = max(0.0, duration - fade_ms)
        afade_filter = f"afade=t=in:ss=0:d={fade_ms:.3f},afade=t=out:st={fade_out_st:.3f}:d={fade_ms:.3f}"
        
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
            "-threads", "1",
            str(output_path)
        ]
        from config import SUBPROCESS_FLAGS
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30, creationflags=SUBPROCESS_FLAGS)
        except subprocess.TimeoutExpired:
            logger.error(f"FFmpeg timed out generating clip {item.index}")
            raise RuntimeError(f"FFmpeg timed out generating clip {item.index}")

        if res.returncode != 0:
            logger.error(f"FFmpeg error generating clip {item.index}: {res.stderr}")
            raise RuntimeError(f"FFmpeg failed to generate clip {item.index}: {res.stderr[:200]}")

        item.audio_path = output_path
        return output_path

    def generate_all_clips(
        self,
        state: PipelineState,
        source_audio: Path,
        output_dir: Path,
        progress_cb: Optional[Callable[[int, int, DialogueItem], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        max_workers: Optional[int] = None,
    ):
        logger.info(f"Generating clips in parallel in {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)
        audio = source_audio or state.work_audio_path
        dialogues = state.active_dialogues()
        total = len(dialogues)
        if total == 0:
            return

        if max_workers is not None:
            workers = max_workers
        else:
            from core.device_manager import device_manager
            workers = device_manager.get_optimal_concurrency_config().clip_workers

        def _task(item: DialogueItem):
            if cancel_check and cancel_check():
                return item, False
            speaker_safe_name = state.get_speaker_safe_name(item.speaker_id)
            self.generate_clip(item, audio, output_dir, speaker_safe_name)
            return item, True

        completed_count = 0
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_item = {executor.submit(_task, item): item for item in dialogues}
            for future in as_completed(future_to_item):
                if cancel_check and cancel_check():
                    try:
                        executor.shutdown(wait=False, cancel_futures=True)
                    except TypeError:
                        executor.shutdown(wait=False)
                    break
                try:
                    item, ok = future.result()
                    completed_count += 1
                    if ok and progress_cb:
                        progress_cb(completed_count, total, item)
                except Exception as e:
                    logger.error(f"Failed to generate clip: {e}")

    def regenerate_clip(self, item: DialogueItem, state: PipelineState, output_dir: Path):
        logger.info(f"Regenerating clip for item {item.index}")
        speaker_safe_name = state.get_speaker_safe_name(item.speaker_id)
        source_audio = state.separated_vocals_path if state.separated_vocals_path else state.work_audio_path
        self.generate_clip(item, source_audio, output_dir, speaker_safe_name)

