import logging
import math
from pathlib import Path
from typing import List, Tuple, Dict

from core.models import PipelineState, DialogueItem, SpeakerInfo
from config import (
    VAD_THRESHOLD,
    VAD_MIN_SPEECH_DURATION_MS,
    VAD_MIN_SILENCE_DURATION_MS,
    VAD_PADDING_MS,
    VAD_MERGE_GAP_MS
)

logger = logging.getLogger(__name__)

class VADDetector:
    def __init__(self):
        self.use_silero = False
        self._silero_model = None
        self._silero_utils = None
        try:
            import torch
            self.torch = torch
            self.use_silero = True
        except ImportError:
            logger.warning("torch not found, falling back to scipy energy VAD")

    def detect(self, audio_path: Path, state: PipelineState, config: Dict = None) -> List[Tuple[float, float]]:
        if config is None:
            config = {}
        threshold = config.get("threshold", VAD_THRESHOLD)
        min_speech_ms = config.get("min_speech_ms", VAD_MIN_SPEECH_DURATION_MS)
        min_silence_ms = config.get("min_silence_ms", VAD_MIN_SILENCE_DURATION_MS)
        padding_ms = config.get("padding_ms", VAD_PADDING_MS)
        merge_gap_ms = config.get("merge_gap_ms", VAD_MERGE_GAP_MS)

        segments = []
        if self.use_silero:
            try:
                segments = self._detect_silero(audio_path, threshold, min_speech_ms, min_silence_ms)
            except Exception as e:
                logger.warning(f"Silero VAD failed ({e}), falling back to Scipy energy VAD...")
                segments = self._detect_scipy(audio_path, threshold, min_speech_ms, min_silence_ms)
        else:
            segments = self._detect_scipy(audio_path, threshold, min_speech_ms, min_silence_ms)

        tot_dur = state.video_duration if state.video_duration > 0 else 999999.0
        segments = self._add_padding(segments, padding_ms, tot_dur)
        segments = self._merge_segments(segments, merge_gap_ms)
        
        state.dialogues.clear()
        speaker_id = "SPEAKER_UNKNOWN"
        if speaker_id not in state.speakers:
            state.speakers[speaker_id] = SpeakerInfo(speaker_id=speaker_id)
            
        for i, (start, end) in enumerate(segments, 1):
            item = DialogueItem(index=i, speaker_id=speaker_id, start=start, end=end)
            state.dialogues.append(item)
            
        logger.info(f"VAD detected {len(segments)} segments")
        return segments

    def _detect_silero(self, audio_path: Path, threshold: float, min_speech_ms: int, min_silence_ms: int):
        import torch
        
        logger.info("Using Silero VAD")
        if self._silero_model is None:
            model, utils = torch.hub.load(repo_or_dir='snakers4/silero-vad',
                                          model='silero_vad',
                                          force_reload=False,
                                          trust_repo=True)
            self._silero_model = model
            self._silero_utils = utils
            
        (get_speech_timestamps, save_audio, read_audio, VADIterator, collect_chunks) = self._silero_utils
        
        wav = read_audio(str(audio_path), sampling_rate=16000)
        speech_timestamps = get_speech_timestamps(
            wav, model, sampling_rate=16000, 
            threshold=threshold,
            min_speech_duration_ms=min_speech_ms,
            min_silence_duration_ms=min_silence_ms
        )
        
        return [(ts['start'] / 16000.0, ts['end'] / 16000.0) for ts in speech_timestamps]
        
    def _detect_scipy(self, audio_path: Path, threshold: float, min_speech_ms: int, min_silence_ms: int):
        import scipy.io.wavfile as wavfile
        import numpy as np
        
        logger.info("Using scipy fallback VAD")
        sr, data = wavfile.read(str(audio_path))
        if data.ndim > 1:
            data = data.mean(axis=1) # Mono
            
        chunk_ms = 50
        chunk_samples = int(sr * chunk_ms / 1000)
        if chunk_samples <= 0 or len(data) < chunk_samples:
            return []
            
        # normalize
        data = data.astype(np.float32)
        max_val = np.max(np.abs(data))
        if max_val > 0:
            data = data / max_val
        
        n_chunks = len(data) // chunk_samples
        if n_chunks == 0:
            return []
            
        rms = np.sqrt(np.mean(data[: n_chunks * chunk_samples].reshape(-1, chunk_samples)**2, axis=1))
        
        is_speech = rms > (threshold * 0.1)
        
        segments = []
        in_speech = False
        start_time = 0.0
        silence_start = 0.0
        
        for i, speech in enumerate(is_speech):
            t = i * chunk_ms / 1000.0
            if speech:
                if not in_speech:
                    in_speech = True
                    start_time = t
                silence_start = t + (chunk_ms / 1000.0)
            else:
                if in_speech:
                    if (t - silence_start) * 1000 >= min_silence_ms:
                        in_speech = False
                        end_time = silence_start
                        if (end_time - start_time) * 1000 >= min_speech_ms:
                            segments.append((start_time, end_time))
                    
        if in_speech:
            end_time = silence_start
            if (end_time - start_time) * 1000 >= min_speech_ms:
                segments.append((start_time, end_time))

        return segments

    def _merge_segments(self, segments: List[Tuple[float, float]], gap_ms: int) -> List[Tuple[float, float]]:
        if not segments: return []
        
        gap_sec = gap_ms / 1000.0
        merged = [segments[0]]
        
        for current in segments[1:]:
            prev = merged[-1]
            if current[0] - prev[1] <= gap_sec:
                merged[-1] = (prev[0], max(prev[1], current[1]))
            else:
                merged.append(current)
                
        return merged

    def _add_padding(self, segments: List[Tuple[float, float]], pad_ms: int, total_duration: float) -> List[Tuple[float, float]]:
        pad_sec = pad_ms / 1000.0
        padded = []
        for start, end in segments:
            n_start = max(0.0, start - pad_sec)
            n_end = min(total_duration, end + pad_sec)
            padded.append((n_start, max(n_start + 0.1, n_end)))
        return padded

