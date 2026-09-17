"""
core/pipeline.py
================
Main AI pipeline orchestrator.

Connects all core modules into a single async-aware pipeline
that emits Qt signals for GUI progress updates.

Architecture:
  PipelineWorker (QThread) runs in background
  Emits signals to MainWindow for progress, log, errors
  Supports step-level retry (skip completed steps)
  All intermediate results cached in PipelineState

  One-Click Mode:
    When auto_analyze=True, the pipeline starts automatically
    after video import. All steps run sequentially without user
    intervention.
"""

from __future__ import annotations

import logging
import time
import traceback
from pathlib import Path
from typing import Optional, Callable

from PySide6.QtCore import QThread, Signal, QObject

from config import (
    TEMP_DIR, TIMESTAMP_MODE_DEFAULT, VoiceSepMode,
    WHISPER_MODEL_DEFAULT, WHISPER_LANGUAGE_DEFAULT,
    PACK_BACKING_TRACK_NAME, AUDIO_EXPORT_FORMAT,
)
from core.models import (
    PipelineState, PipelineStep, PIPELINE_STEP_LABELS,
    PIPELINE_STEP_PROGRESS, DialogueItem, PackInfo,
)

log = logging.getLogger(__name__)


# ── Pipeline Signals ──────────────────────────────────────────────────────────

class PipelineSignals(QObject):
    """Qt signals emitted by PipelineWorker to the GUI."""
    step_started   = Signal(PipelineStep)          # step began
    step_completed = Signal(PipelineStep)          # step succeeded
    step_failed    = Signal(PipelineStep, str)     # step failed, error msg
    progress       = Signal(int)                   # 0-100 overall
    sub_progress   = Signal(int, int, str)         # current, total, detail_msg
    log_message    = Signal(str, str)              # message, level
    elapsed_time   = Signal(float)                 # seconds elapsed
    dialogues_ready= Signal()                      # state.dialogues populated
    pack_ready     = Signal(str)                   # pack output dir path
    finished       = Signal()                      # entire pipeline done
    cancelled      = Signal()                      # user cancelled


# ── Pipeline Worker ────────────────────────────────────────────────────────────

class PipelineWorker(QThread):
    """
    Runs the full AI pipeline in a background QThread.

    Usage:
        worker = PipelineWorker(state, options)
        worker.signals.progress.connect(progress_bar.setValue)
        worker.signals.log_message.connect(log_panel.log)
        worker.start()
    """

    def __init__(self, state: PipelineState, options: dict, parent=None):
        super().__init__(parent)
        self.state = state
        self.options = options
        self.signals = PipelineSignals()
        self._cancelled = False
        self._output_dir: Optional[Path] = None
        self._start_time: float = 0.0
        self._fatal_steps = {
            PipelineStep.AUDIO_EXTRACT,
            PipelineStep.VAD,
            PipelineStep.CLIP_GENERATION,
            PipelineStep.PACK_BUILD,
        }

    def cancel(self):
        self._cancelled = True

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _log(self, msg: str, level: str = "info"):
        log.info(msg)
        self.signals.log_message.emit(msg, level)

    def _emit_elapsed(self):
        """Emit elapsed time since pipeline started."""
        if self._start_time > 0:
            self.signals.elapsed_time.emit(time.time() - self._start_time)

    def _begin_step(self, step: PipelineStep):
        self.state.current_step = step
        label = PIPELINE_STEP_LABELS.get(step, str(step))
        self._emit_elapsed()
        self._log(f"{label}", "info")
        self.signals.step_started.emit(step)
        pct = PIPELINE_STEP_PROGRESS.get(step, 0)
        self.signals.progress.emit(pct)

    def _complete_step(self, step: PipelineStep):
        self.state.step_completed[step] = True
        label = PIPELINE_STEP_LABELS.get(step, str(step))
        self._log(f"{label} — done", "ok")
        self.signals.step_completed.emit(step)

    def _fail_step(self, step: PipelineStep, err: str):
        self.state.step_errors[step] = err
        self._log(f"{PIPELINE_STEP_LABELS.get(step, str(step))} — FAILED: {err}", "error")
        self.signals.step_failed.emit(step, err)

    def _check_cancel(self) -> bool:
        if self._cancelled:
            self._log("Pipeline cancelled by user.", "warn")
            self.signals.cancelled.emit()
            return True
        return False

    def _skip_if_done(self, step: PipelineStep) -> bool:
        if self.state.is_step_done(step):
            self._log(f"Skipping {PIPELINE_STEP_LABELS.get(step, str(step))} (cached)", "info")
            return True
        return False

    # ── Pipeline Steps ────────────────────────────────────────────────────────

    def _step_audio_extract(self):
        step = PipelineStep.AUDIO_EXTRACT
        if self._skip_if_done(step):
            return
        self._begin_step(step)
        try:
            from core.audio_extractor import AudioExtractor
            extractor = AudioExtractor()
            work_wav = TEMP_DIR / f"{self.state.video_path.stem}_work.wav"
            extractor.fill_state(self.state, self.state.video_path, work_wav)
            self._complete_step(step)
        except Exception as e:
            self._fail_step(step, str(e))
            raise

    def _step_vad(self):
        step = PipelineStep.VAD
        if self._skip_if_done(step):
            return
        self._begin_step(step)
        try:
            from core.vad import VADDetector
            vad_config = {
                "threshold":     self.options.get("vad_threshold", 0.5),
                "padding_ms":    self.options.get("vad_padding_ms", 80),
                "min_speech_ms": self.options.get("vad_min_speech_ms", 200),
                "min_silence_ms":self.options.get("vad_min_silence_ms", 200),
                "merge_gap_ms":  self.options.get("vad_merge_gap_ms", 120),
            }
            detector = VADDetector()
            detector.detect(self.state.work_audio_path, self.state, vad_config)
            self._log(f"Detected {len(self.state.dialogues)} dialogue segments", "ok")
            self.signals.dialogues_ready.emit()
            self._complete_step(step)
        except Exception as e:
            self._fail_step(step, str(e))
            raise

    def _step_diarization(self):
        step = PipelineStep.DIARIZATION
        if self._skip_if_done(step):
            return
        self._begin_step(step)
        try:
            from core.diarization import SpeakerDiarizer
            diarizer = SpeakerDiarizer(
                hf_token=self.options.get("hf_token", ""),
                device=self.options.get("device", "auto"),
            )
            diarizer.diarize(self.state.work_audio_path, self.state)
            n_speakers = len(self.state.speakers)
            speaker_list = ", ".join(sorted(self.state.speakers.keys()))
            self._log(f"Found {n_speakers} speaker(s): {speaker_list}", "ok")
            self._complete_step(step)
        except Exception as e:
            self._fail_step(step, str(e))
            # Non-fatal: continue with single speaker
            self._log("Continuing without speaker diarization", "warn")

    def _step_transcription(self):
        step = PipelineStep.TRANSCRIPTION
        if self._skip_if_done(step):
            return
        self._begin_step(step)
        try:
            from core.transcriber import Transcriber
            transcriber = Transcriber(
                model_size=self.options.get("whisper_model", WHISPER_MODEL_DEFAULT),
                language=self.options.get("whisper_language", WHISPER_LANGUAGE_DEFAULT),
                initial_prompt=self.options.get("whisper_initial_prompt"),
            )
            self.signals.sub_progress.emit(0, 1, "กำลังโหลดโมเดล Whisper...")
            transcriber.load_model()

            use_whisper_seg = self.options.get("use_whisper_segmentation", True)

            if use_whisper_seg and transcriber.available:
                # ── Whisper-based segmentation (recommended for music-heavy audio) ──
                # Whisper transcribes the FULL audio and splits by natural sentence
                # boundaries — ignores background music, much better than VAD alone.
                self.signals.sub_progress.emit(0, 1,
                    "Whisper กำลังวิเคราะห์และแยกประโยค (อาจใช้เวลา 1-3 นาที)...")
                self._log("ใช้ Whisper segmentation เพื่อแยกประโยค (ดีกว่า VAD เมื่อมีเสียงดนตรี)", "info")

                def on_seg_progress(current, total_seg, detail):
                    self.signals.sub_progress.emit(current, max(current, 1), detail)
                    self.signals.dialogues_ready.emit()  # refresh table incrementally

                ok = transcriber.transcribe_and_segment(
                    self.state.work_audio_path,
                    self.state,
                    total_duration=self.state.video_duration,
                    progress_cb=on_seg_progress,
                )

                if ok:
                    n = len(self.state.active_dialogues())
                    self.signals.sub_progress.emit(n, n, f"แยกประโยคครบ {n} คลิป")
                    self._log(f"Whisper แยกได้ {n} ประโยค — พร้อมแยก Speaker", "ok")
                    self.signals.dialogues_ready.emit()
                    self._complete_step(step)
                    return
                else:
                    self._log("Whisper segmentation ล้มเหลว — ใช้ VAD segments แทน", "warn")

            # ── Fallback: transcribe existing VAD segments ──
            dialogues = self.state.active_dialogues()
            total = len(dialogues)
            self.signals.sub_progress.emit(0, total, "เตรียมโหลดเสียงเข้า RAM...")

            import numpy as np, subprocess as _sp, io
            from config import SUBPROCESS_FLAGS
            audio_data, sr = None, 16000
            try:
                import scipy.io.wavfile as wavfile
                res = _sp.run(
                    ["ffmpeg", "-y", "-i", str(self.state.work_audio_path),
                     "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"],
                    stdout=_sp.PIPE, stderr=_sp.DEVNULL, timeout=120,
                    creationflags=SUBPROCESS_FLAGS
                )
                if res.returncode == 0 and res.stdout:
                    sr, raw = wavfile.read(io.BytesIO(res.stdout))
                    audio_data = raw.astype(np.float32) / 32768.0
            except Exception as e:
                log.warning(f"Could not preload audio: {e}")

            for idx, item in enumerate(dialogues):
                if self._check_cancel():
                    return
                self.signals.sub_progress.emit(
                    idx + 1, total,
                    f"ถอดคำ [{idx+1}/{total}] ช่วง {item.format_start()}–{item.format_end()}"
                )
                text = transcriber.transcribe_segment(
                    self.state.work_audio_path, item.start, item.end,
                    audio_data=audio_data, sample_rate=sr
                )
                item.caption = text
                log.debug(f"Transcribed item {item.index}: {text[:40]}")

            self.signals.sub_progress.emit(total, total, f"ถอดคำครบ {total} คลิป")
            self._log(f"Transcribed {total} dialogue(s)", "ok")
            self._complete_step(step)
        except Exception as e:
            self._fail_step(step, str(e))
            self._log("Transcription failed — captions will be empty", "warn")


    def _step_voice_separation(self):
        step = PipelineStep.VOICE_SEPARATION
        if self._skip_if_done(step):
            return

        mode = self.options.get("voice_sep_mode", VoiceSepMode.ORIGINAL)
        if mode == VoiceSepMode.ORIGINAL:
            self._log("Voice separation: Original mode (skipping)", "info")
            self.state.separated_vocals_path = self.state.work_audio_path
            self.state.separated_bg_path = self.state.work_audio_path
            self.state.step_completed[step] = True
            return

        self._begin_step(step)
        try:
            from core.separator import VoiceSeparator
            sep = VoiceSeparator(mode=mode)
            sep_dir = TEMP_DIR / "separated"
            sep_dir.mkdir(exist_ok=True)
            self.signals.sub_progress.emit(0, 1, "กำลังรัน Demucs แยกเสียงพูดออกจากเพลง (อาจใช้เวลาหลายนาที)...")
            vocals, bg = sep.separate(self.state.work_audio_path, sep_dir)
            self.state.separated_vocals_path = vocals
            self.state.separated_bg_path = bg
            self.signals.sub_progress.emit(1, 1, "แยกเสียงเสร็จแล้ว")
            self._complete_step(step)
        except Exception as e:
            self._fail_step(step, str(e))
            self.state.separated_vocals_path = self.state.work_audio_path
            self.state.separated_bg_path = self.state.work_audio_path
            self._log("Falling back to original audio", "warn")

    def _step_clip_generation(self):
        step = PipelineStep.CLIP_GENERATION
        if self._skip_if_done(step):
            return
        self._begin_step(step)
        try:
            from core.clip_generator import ClipGenerator
            gen = ClipGenerator()

            pack_name = self._get_pack_name()
            out_dir = self._get_output_dir() / pack_name
            out_dir.mkdir(parents=True, exist_ok=True)
            self._output_dir = out_dir

            source_audio = self.state.separated_vocals_path or self.state.work_audio_path
            dialogues = self.state.active_dialogues()
            total = len(dialogues)

            for idx, item in enumerate(dialogues):
                if self._check_cancel():
                    return
                speaker_name = self.state.get_speaker_safe_name(item.speaker_id)
                self.signals.sub_progress.emit(
                    idx + 1, total,
                    f"ตัดคลิป [{idx+1}/{total}] {item.id_str}_{speaker_name} ({item.format_start()}–{item.format_end()})"
                )
                gen.generate_clip(item, source_audio, out_dir, speaker_name)

            self.signals.sub_progress.emit(total, total, f"ตัดคลิปครบ {total} คลิป")
            self._complete_step(step)
        except Exception as e:
            self._fail_step(step, str(e))
            raise

    def _step_frame_extraction(self):
        step = PipelineStep.FRAME_EXTRACTION
        if self._skip_if_done(step):
            return
        self._begin_step(step)
        from core.frame_extractor import FrameExtractor
        extractor = FrameExtractor(self.state.video_path)
        dialogues = self.state.active_dialogues()
        total = len(dialogues)
        quality = self.options.get("image_quality", 95)

        try:
            for idx, item in enumerate(dialogues):
                if self._check_cancel():
                    extractor.release()
                    return
                speaker_name = self.state.get_speaker_safe_name(item.speaker_id)
                self.signals.sub_progress.emit(
                    idx + 1, total,
                    f"แคปภาพ [{idx+1}/{total}] {item.id_str} ช่วง {item.format_start()}"
                )
                fname = f"{item.id_str}_{speaker_name}.png"
                out_path = self._output_dir / fname
                frame = extractor.find_best_frame(item.start, item.end)
                extractor.save_frame(frame, out_path, quality=quality)
                item.image_path = out_path

            extractor.release()
            self.signals.sub_progress.emit(total, total, f"แคปภาพครบ {total} เฟรม")
            self._complete_step(step)
        except Exception as e:
            log.error(f"Frame extraction failed ({e}) — generating placeholder images for all items")
            extractor.release()
            # Fallback for all items
            for item in dialogues:
                speaker_name = self.state.get_speaker_safe_name(item.speaker_id)
                fname = f"{item.id_str}_{speaker_name}.png"
                out_path = self._output_dir / fname
                extractor.save_frame(None, out_path, quality=quality)
                item.image_path = out_path
            self._log("Frame extraction failed — placeholder images generated", "warn")
            self.state.step_completed[step] = True
            self.signals.step_completed.emit(step)

    def _step_backing_track(self):
        step = PipelineStep.BACKING_TRACK
        if self._skip_if_done(step):
            return

        use_original = self.options.get("backing_track_original", False)
        self._begin_step(step)
        try:
            from core.separator import VoiceSeparator
            sep = VoiceSeparator(
                mode=self.options.get("voice_sep_mode", VoiceSepMode.ORIGINAL)
            )
            backing_path = self._output_dir / f"{PACK_BACKING_TRACK_NAME}.{AUDIO_EXPORT_FORMAT}"
            bitrate = self.options.get("audio_bitrate", "320k")
            if not bitrate or bitrate in ("192k", "256k"):
                bitrate = "320k"
            self.signals.sub_progress.emit(0, 1, f"กำลังเข้ารหัส backing track ({bitrate} MP3)...")
            sep.generate_backing_track(self.state, backing_path, bitrate=bitrate)
            self.state.pack_backing_track_path = backing_path
            self.signals.sub_progress.emit(1, 1, f"Backing track พร้อมแล้ว")
            self._log(f"Backing track saved: {backing_path.name} ({bitrate})", "ok")
            self._complete_step(step)
        except Exception as e:
            self._fail_step(step, str(e))
            self._log("Backing track generation failed", "warn")

    def _step_pack_build(self):
        step = PipelineStep.PACK_BUILD
        if self._skip_if_done(step):
            return
        self._begin_step(step)
        try:
            from core.pack_builder import PackBuilder
            builder = PackBuilder()
            dialogues = self.state.active_dialogues()
            total = len(dialogues)

            for idx, item in enumerate(dialogues):
                speaker_name = self.state.get_speaker_safe_name(item.speaker_id)
                txt_name = f"{item.id_str}_{speaker_name}.txt"
                txt_path = self._output_dir / txt_name

                all_speakers = [
                    self.state.get_speaker(sid).display_name
                    for sid in item.all_speakers
                    if sid in self.state.speakers
                ] or [speaker_name]

                content = builder.build_txt(
                    item,
                    self.state,
                    timestamp_mode=self.options.get("timestamp_mode", TIMESTAMP_MODE_DEFAULT),
                    speaker_display_names=all_speakers,
                )
                txt_path.write_text(content, encoding="utf-8")
                item.txt_path = txt_path
                self.signals.sub_progress.emit(
                    idx + 1, total,
                    f"สร้างไฟล์ [{idx+1}/{total}] {txt_name}"
                )

            # Write _pack_info.ini
            pack_info_content = builder.build_pack_info(self.state.pack_info)
            pack_info_path = self._output_dir / "_pack_info.ini"
            pack_info_path.write_text(pack_info_content, encoding="utf-8")

            # Copy/encode dub_video.ogv & dub_video.mp4
            if self.state.pack_info.include_dub_video and self.state.video_path:
                import shutil, subprocess
                dub_mp4 = self._output_dir / "dub_video.mp4"
                if not dub_mp4.exists() and self.state.video_path.resolve() != dub_mp4.resolve():
                    try:
                        shutil.copy2(self.state.video_path, dub_mp4)
                    except Exception:
                        pass

                dub_video_path = self._output_dir / "dub_video.ogv"
                if not dub_video_path.exists():
                    self.signals.sub_progress.emit(total, total, "กำลังสร้าง dub_video.ogv (คุณภาพสูงสุด)...")
                    if self.state.video_path.suffix.lower() == ".ogv":
                        shutil.copy2(self.state.video_path, dub_video_path)
                    else:
                        cmd = [
                            "ffmpeg", "-y", "-i", str(self.state.video_path),
                            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                            "-c:v", "libtheora", "-qscale:v", "10", "-b:v", "12M", "-maxrate", "16M", "-bufsize", "20M",
                            "-pix_fmt", "yuv420p", "-g", "15",
                            "-c:a", "libvorbis", "-qscale:a", "8",
                            str(dub_video_path)
                        ]
                        from config import SUBPROCESS_FLAGS
                        subprocess.run(cmd, capture_output=True, text=True, timeout=600, creationflags=SUBPROCESS_FLAGS)

            self.signals.sub_progress.emit(total, total, f"สร้างแพ็กครบ {total} ไฟล์")
            self._complete_step(step)
        except Exception as e:
            self._fail_step(step, str(e))
            raise

    def _resolve_output_dir(self) -> Path:
        if self._output_dir:
            return self._output_dir
        pack_name = self._get_pack_name()
        out_dir = self._get_output_dir() / pack_name
        out_dir.mkdir(parents=True, exist_ok=True)
        self._output_dir = out_dir
        return out_dir

    def _step_validation(self):
        step = PipelineStep.VALIDATION
        self._begin_step(step)
        try:
            from core.quality_checker import QualityChecker
            checker = QualityChecker()
            pack_dir = self._resolve_output_dir()
            results = checker.check_all(self.state, pack_dir)

            errors = [r for r in results if r.level == "error"]
            warns  = [r for r in results if r.level == "warn"]

            for r in results:
                self._log(r.message, r.level)

            if errors:
                self._log(f"{len(errors)} error(s) found — review before export", "warn")
            else:
                self._log(f"Validation passed ({len(warns)} warning(s))", "ok")

            self.state.step_completed[step] = True
            self.signals.step_completed.emit(step)
        except Exception as e:
            self._fail_step(step, str(e))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_pack_name(self) -> str:
        from core.pack_builder import PackBuilder
        return PackBuilder.sanitize_pack_name(self.state.pack_info.title or "Untitled_Pack")

    def _get_output_dir(self) -> Path:
        out = self.options.get("output_dir", "")
        if out:
            p = Path(out)
        else:
            p = self.state.video_path.parent / "output"
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ── Main run ──────────────────────────────────────────────────────────────

    @property
    def output_dir(self) -> Optional[Path]:
        """The resolved pack output directory (available after clip generation)."""
        return self._output_dir

    def run(self):
        """Execute the full pipeline sequentially."""
        self._start_time = time.time()
        self._log(f"Pipeline started for: {self.state.video_path.name}", "info")
        try:
            steps = [
                self._step_audio_extract,
                self._step_vad,
                self._step_transcription,
                self._step_diarization,
                self._step_voice_separation,
                self._step_clip_generation,
                self._step_frame_extraction,
                self._step_backing_track,
                self._step_pack_build,
                self._step_validation,
            ]
            for step_fn in steps:
                if self._check_cancel():
                    return
                step_fn()

            elapsed = time.time() - self._start_time
            self.state.current_step = PipelineStep.DONE
            self.signals.progress.emit(100)
            self._log(f"Pipeline complete in {elapsed:.1f}s — pack is ready to export.", "ok")
            if self._output_dir:
                self.signals.pack_ready.emit(str(self._output_dir))
            self.signals.finished.emit()

        except Exception as e:
            tb = traceback.format_exc()
            elapsed = time.time() - self._start_time
            self._log(f"Pipeline error after {elapsed:.1f}s: {e}", "error")
            self._log(tb, "error")
            self.state.current_step = PipelineStep.ERROR


# ── Export Worker ─────────────────────────────────────────────────────────────

class ExportWorker(QThread):
    """
    Exports the pack directory as a ZIP file in background.
    """
    progress  = Signal(int)
    log_msg   = Signal(str, str)
    finished  = Signal(str)   # zip path
    error     = Signal(str)

    def __init__(self, pack_dir: Path, zip_path: Path, parent=None):
        super().__init__(parent)
        self.pack_dir = pack_dir
        self.zip_path = zip_path

    def run(self):
        try:
            from core.pack_builder import PackBuilder
            self.log_msg.emit("Creating ZIP archive…", "info")
            self.progress.emit(10)
            PackBuilder.export_zip(self.pack_dir, self.zip_path)
            self.progress.emit(100)
            self.log_msg.emit(f"Exported: {self.zip_path}", "ok")
            self.finished.emit(str(self.zip_path))
        except Exception as e:
            self.error.emit(str(e))


# ── Convenience factory ───────────────────────────────────────────────────────

def build_options_from_settings(settings: dict) -> dict:
    """Convert settings.json dict to pipeline options dict."""
    from config import WHISPER_INITIAL_PROMPT_THAI
    return {
        "hf_token":                  settings.get("hf_token", ""),
        "whisper_model":             settings.get("whisper_model", WHISPER_MODEL_DEFAULT),
        "whisper_language":          settings.get("whisper_language", "th"),
        "whisper_initial_prompt":    settings.get("whisper_initial_prompt", WHISPER_INITIAL_PROMPT_THAI),
        "use_whisper_segmentation":  settings.get("use_whisper_segmentation", True),
        "voice_sep_mode":            settings.get("voice_sep_mode", VoiceSepMode.ORIGINAL),
        "timestamp_mode":            settings.get("timestamp_mode", TIMESTAMP_MODE_DEFAULT),
        "vad_threshold":             settings.get("vad_threshold", 0.5),
        "vad_padding_ms":            settings.get("vad_padding_ms", 80),
        "vad_merge_gap_ms":          settings.get("vad_merge_gap_ms", 120),
        "include_dub_video":         settings.get("include_dub_video", True),
        "output_dir":                settings.get("output_dir", ""),
        "audio_bitrate":             settings.get("audio_bitrate", "256k"),
        "image_quality":             settings.get("image_quality", 95),
        "backing_track_original":    settings.get("backing_track_original", False),
        "device":                    "auto",
    }

