import os
import logging
import subprocess
import numpy as np
from pathlib import Path
from config import TEMP_DIR, WHISPER_INITIAL_PROMPT_THAI
from core.models import PipelineState
from core.text_cleaner import ThaiTextCleaner

logger = logging.getLogger(__name__)

class Transcriber:
    def __init__(self, model_size='medium', language='th', device='auto', initial_prompt: str = None):
        self.model_size = model_size
        self.language = None if (language in (None, "auto", "None", "")) else language
        self.device = device
        self.initial_prompt = initial_prompt if initial_prompt is not None else (WHISPER_INITIAL_PROMPT_THAI if self.language == 'th' else None)
        self.available = False
        self.model = None

    def load_model(self):
        try:
            from faster_whisper import WhisperModel
            from core.device_manager import device_manager
            
            dev_info = device_manager.get_optimal_device(self.device)
            whisper_kwargs = device_manager.get_whisper_kwargs(dev_info)
            concurrency = device_manager.get_optimal_concurrency_config()
            
            logger.info(f"Loading faster-whisper model '{self.model_size}' on {dev_info.name} ({whisper_kwargs})")
            try:
                self.model = WhisperModel(self.model_size, **whisper_kwargs)
            except Exception as e:
                logger.warning(f"Failed loading Whisper on {dev_info.name} ({e}), releasing memory and falling back to CPU INT8 ({concurrency.whisper_threads} threads)...")
                device_manager.release_gpu_memory()
                self.model = WhisperModel(self.model_size, device="cpu", compute_type="int8", cpu_threads=concurrency.whisper_threads)
                
            self.available = True
        except ImportError:
            logger.warning("faster-whisper not installed. Transcription disabled.")
            self.available = False
        except Exception as e:
            logger.error(f"Failed to load WhisperModel: {e}")
            self.available = False

    def transcribe_segment(self, audio_path: Path, start: float, end: float, audio_data: np.ndarray = None, sample_rate: int = 16000) -> str:
        if not self.available or not self.model:
            return ""
            
        raw_text = ""
        transcribed_ok = False
        
        # Build transcribe kwargs with precision settings
        transcribe_kwargs = {
            "language": self.language,
            "beam_size": 5,
            "vad_filter": True,
            "vad_parameters": dict(
                threshold=0.2,
                min_speech_duration_ms=100,
                min_silence_duration_ms=150,
                speech_pad_ms=200
            ),
            "condition_on_previous_text": False,
            "word_timestamps": True,
        }
        if self.language is None:
            transcribe_kwargs["multilingual"] = True
        if self.initial_prompt:
            transcribe_kwargs["initial_prompt"] = self.initial_prompt

        if audio_data is not None and len(audio_data) > 0:
            try:
                s_idx = int(start * sample_rate)
                e_idx = int(end * sample_rate)
                segment_audio = audio_data[s_idx:e_idx]
                if len(segment_audio) > 0:
                    segments, _ = self.model.transcribe(segment_audio, **transcribe_kwargs)
                    raw_text = " ".join([segment.text.strip() for segment in segments]).strip()
                    transcribed_ok = True
            except Exception as e:
                logger.warning(f"In-memory transcription failed ({e}), falling back to temp wav file...")
                transcribed_ok = False

        if not transcribed_ok:
            import uuid, os
            temp_wav = TEMP_DIR / f"temp_transcribe_{os.getpid()}_{uuid.uuid4().hex[:8]}.wav"
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{start:.3f}",
                "-i", str(audio_path),
                "-t", f"{max(0.05, end - start):.3f}",
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                str(temp_wav)
            ]
            try:
                from config import SUBPROCESS_FLAGS
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, creationflags=SUBPROCESS_FLAGS)
                segments, _ = self.model.transcribe(str(temp_wav), **transcribe_kwargs)
                raw_text = " ".join([segment.text.strip() for segment in segments]).strip()
            except Exception as e2:
                logger.error(f"Error transcribing segment: {e2}")
                return ""
            finally:
                if temp_wav.exists():
                    temp_wav.unlink(missing_ok=True)

        # Apply ThaiTextCleaner post-processing if language is Thai or contains Thai characters
        if self.language == 'th' or (self.language is None and any('\u0e00' <= c <= '\u0e7f' for c in raw_text)):
            cleaned_text = ThaiTextCleaner.process_transcript(
                raw_text,
                language=self.language or "th",
                clean_hallucinations=True,
                format_keywords=True
            )
            return cleaned_text
        return raw_text.strip()

    def transcribe_all(self, state: PipelineState, work_audio_path: Path):
        if not self.available:
            logger.warning("Transcriber not available. Filling empty captions.")
            for item in state.active_dialogues():
                item.caption = ""
            return

        logger.info(f"Transcribing all active dialogues (Language={self.language or 'auto'})")

        # Load full audio into memory at 16kHz float32 mono for fast slicing
        audio_data = None
        sr = 16000
        try:
            import scipy.io.wavfile as wavfile
            from config import SUBPROCESS_FLAGS
            res = subprocess.run([
                "ffmpeg", "-y", "-i", str(work_audio_path),
                "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"
            ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120, creationflags=SUBPROCESS_FLAGS)
            if res.returncode == 0 and len(res.stdout) > 0:
                import io
                sr, raw_data = wavfile.read(io.BytesIO(res.stdout))
                audio_data = raw_data.astype(np.float32) / 32768.0
        except Exception as e:
            logger.warning(f"Could not load full audio into memory for fast transcription: {e}")

        for item in state.active_dialogues():
            text = self.transcribe_segment(work_audio_path, item.start, item.end, audio_data=audio_data, sample_rate=sr)
            item.caption = text
            logger.debug(f"Transcribed item {item.index}: {text}")

    def transcribe_and_segment(self, work_audio_path: Path, state: PipelineState,
                                total_duration: float = 0.0,
                                progress_cb=None) -> bool:
        """
        PRIMARY SEGMENTER for music-heavy audio.

        Uses Whisper's own segment timestamps instead of VAD to split dialogue.
        Each Whisper segment = one DialogueItem. Much more reliable than energy VAD
        when background music fills the silent gaps between speakers.

        Returns True if segmentation succeeded, False if fallback needed.
        """
        if not self.available or not self.model:
            return False

        logger.info(f"Whisper-based segmentation: transcribing full audio for segment timestamps (Language={self.language or 'auto-dynamic'})...")

        kwargs = {
            "language": self.language,
            "beam_size": 5,
            "vad_filter": True,
            "vad_parameters": dict(
                threshold=0.2,
                min_speech_duration_ms=100,
                min_silence_duration_ms=150,
                speech_pad_ms=200
            ),
            "condition_on_previous_text": False,
            "word_timestamps": True,
        }
        if self.language is None:
            kwargs["multilingual"] = True
        if self.initial_prompt:
            kwargs["initial_prompt"] = self.initial_prompt

        try:
            segments_gen, info = self.model.transcribe(str(work_audio_path), **kwargs)

            from core.models import DialogueItem, SpeakerInfo
            new_dialogues = []
            idx = 1

            for seg in segments_gen:
                start = max(0.0, seg.start)
                end = seg.end

                # Word-level timestamp refinement to eliminate trailing silence
                if hasattr(seg, "words") and seg.words:
                    valid_words = [
                        w for w in seg.words
                        if getattr(w, "start", None) is not None and getattr(w, "end", None) is not None
                    ]
                    if valid_words:
                        w_start = valid_words[0].start
                        w_end = valid_words[-1].end
                        # 100ms lead-in padding and 120ms lead-out padding for natural speech boundaries
                        refined_start = max(0.0, w_start - 0.10)
                        refined_end = w_end + 0.12
                        if refined_end > refined_start:
                            start = refined_start
                            end = min(end, refined_end) if refined_end < end else refined_end
                if total_duration > 0:
                    end = min(end, total_duration)
                duration = end - start

                # Skip inverted, zero-length, very short, or likely hallucinated segments
                if end <= start or duration < 0.15:
                    continue

                raw_text = seg.text.strip()
                if not raw_text:
                    continue

                # Clean Thai text if language is Thai or contains Thai characters
                if self.language == "th" or any('\u0e00' <= c <= '\u0e7f' for c in raw_text):
                    raw_text = ThaiTextCleaner.process_transcript(
                        raw_text, language="th",
                        clean_hallucinations=True,
                        format_keywords=True
                    )

                item = DialogueItem(
                    index=idx,
                    speaker_id="SPEAKER_UNKNOWN",
                    start=round(start, 3),
                    end=round(end, 3),
                    caption=raw_text,
                )
                new_dialogues.append(item)

                if progress_cb:
                    progress_cb(idx, -1, f"Segment [{idx}] {start:.1f}s–{end:.1f}s: {raw_text[:30]}...")
                idx += 1

            if not new_dialogues:
                logger.warning("Whisper segmentation returned no segments.")
                return False

            # Replace state dialogues with Whisper-segmented ones
            state.dialogues = new_dialogues
            if "SPEAKER_UNKNOWN" not in state.speakers:
                state.speakers["SPEAKER_UNKNOWN"] = SpeakerInfo(speaker_id="SPEAKER_UNKNOWN")

            logger.info(f"Whisper segmentation: {len(new_dialogues)} segments detected "
                        f"(language detected: {info.language})")
            return True

        except Exception as e:
            logger.error(f"Whisper segmentation failed: {e}")
            return False
