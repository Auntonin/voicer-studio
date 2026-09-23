"""
core/speaker_matcher.py
=======================
Closed-set speaker enrollment and voiceprint matching.

Allows enrolling 1-N reference voice samples per character and attributing
dialogue clips using cosine similarity against enrolled character voiceprints,
with confidence scoring and human-in-the-loop flagging.
"""

from __future__ import annotations

import io
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np

from core.models import PipelineState, SpeakerInfo, DialogueItem

logger = logging.getLogger(__name__)


class SpeakerMatcher:
    """
    Manages character voiceprint enrollment and closed-set speaker attribution.
    """

    @staticmethod
    def compute_feature_vector(seg: np.ndarray, sr: int = 16000) -> np.ndarray:
        """
        Extracts and L2-normalizes the 52-dimensional vocal acoustic feature vector.
        """
        from core.diarization import SpeakerDiarizer
        diarizer = SpeakerDiarizer()
        raw_feats = np.array(diarizer._compute_segment_features(seg, sr), dtype=np.float32)
        raw_feats = np.nan_to_num(raw_feats, nan=0.0, posinf=0.0, neginf=0.0)
        norm = np.linalg.norm(raw_feats)
        if norm > 1e-6:
            raw_feats = raw_feats / norm
        return raw_feats

    @classmethod
    def extract_segment_features(cls, audio_path: Path, start: float, end: float) -> Optional[np.ndarray]:
        """
        Extract normalized feature vector for a specific time range in an audio file.
        """
        try:
            import scipy.io.wavfile as wavfile
            from config import SUBPROCESS_FLAGS

            dur = max(0.05, end - start)
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{start:.3f}",
                "-i", str(audio_path),
                "-t", f"{dur:.3f}",
                "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"
            ]
            res = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=30, creationflags=SUBPROCESS_FLAGS
            )
            if res.returncode != 0 or not res.stdout:
                return None

            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                sr, raw = wavfile.read(io.BytesIO(res.stdout))
            if len(raw) == 0:
                return None
            if raw.ndim > 1:
                raw = raw[:, 0]
            audio = raw.astype(np.float32)
            if len(audio) < int(0.05 * sr):
                return None
            max_val = np.max(np.abs(audio))
            if max_val > 0:
                audio /= max_val
            return cls.compute_feature_vector(audio, sr)
        except Exception as e:
            logger.warning(f"Failed to extract segment features ({start:.2f}-{end:.2f}): {e}")
            return None

    @classmethod
    def enroll_speaker_sample(
        cls,
        state: PipelineState,
        speaker_id: str,
        audio_path: Path,
        start: float,
        end: float,
        sample_name: Optional[str] = None
    ) -> bool:
        """
        Enrolls a clean reference voice sample for a character.
        Updates the character's centroid voiceprint embedding.
        """
        if not speaker_id:
            return False
        spk = state.get_speaker(speaker_id)
        vec = cls.extract_segment_features(audio_path, start, end)
        if vec is None:
            return False

        if not sample_name:
            sample_name = f"Sample_{len(spk.voiceprint_samples) + 1} ({start:.1f}s–{end:.1f}s)"

        spk.voiceprint_samples.append(sample_name)

        if spk.embedding is None or len(spk.embedding) == 0 or len(spk.embedding) != len(vec):
            spk.embedding = vec.tolist()
        else:
            old_vec = np.array(spk.embedding, dtype=np.float32)
            n = len(spk.voiceprint_samples) - 1
            # Running centroid average
            new_vec = (old_vec * n + vec) / (n + 1)
            new_vec = np.nan_to_num(new_vec, nan=0.0, posinf=0.0, neginf=0.0)
            norm = np.linalg.norm(new_vec)
            if norm > 1e-6:
                new_vec = new_vec / norm
            spk.embedding = new_vec.tolist()

        logger.info(
            f"Enrolled sample '{sample_name}' for speaker {speaker_id} ({spk.display_name}). "
            f"Total samples: {len(spk.voiceprint_samples)}"
        )
        return True

    @classmethod
    def remove_voiceprint(cls, state: PipelineState, speaker_id: str) -> None:
        """Clears all enrolled samples and embedding for a speaker."""
        if speaker_id in state.speakers:
            spk = state.speakers[speaker_id]
            spk.voiceprint_samples.clear()
            spk.embedding = None

    @staticmethod
    def has_enrolled_speakers(state: PipelineState) -> bool:
        """Returns True if at least one speaker in state has an enrolled voiceprint."""
        return any(spk.has_voiceprint() for spk in state.speakers.values())

    @classmethod
    def match_dialogues(
        cls,
        state: PipelineState,
        audio_path: Path,
        confidence_threshold: float = 0.60,
        margin_threshold: float = 0.08
    ) -> Dict[str, Any]:
        """
        Attributes all active dialogue items to enrolled characters using cosine similarity.
        Flags items with low confidence or narrow top-1 vs top-2 margins for human review.
        """
        enrolled_speakers = {}
        for sid, spk in state.speakers.items():
            if spk.has_voiceprint():
                arr = np.array(spk.embedding, dtype=np.float32)
                arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
                norm = np.linalg.norm(arr)
                if norm > 1e-6:
                    enrolled_speakers[sid] = arr / norm

        if not enrolled_speakers:
            return {"matched": False, "reason": "No enrolled character voiceprints"}

        dialogues = state.active_dialogues()
        if not dialogues:
            return {"matched": True, "total": 0, "needs_review": 0}

        # Preload full audio for fast batch feature extraction
        import scipy.io.wavfile as wavfile
        from config import SUBPROCESS_FLAGS

        full_audio = None
        sr = 16000
        try:
            res = subprocess.run(
                ["ffmpeg", "-y", "-i", str(audio_path),
                 "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120,
                creationflags=SUBPROCESS_FLAGS
            )
            if res.returncode == 0 and res.stdout:
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    sr, raw = wavfile.read(io.BytesIO(res.stdout))
                if len(raw) > 0:
                    if raw.ndim > 1:
                        raw = raw[:, 0]
                    full_audio = raw.astype(np.float32)
                    m = np.max(np.abs(full_audio))
                    if m > 0:
                        full_audio /= m
        except Exception as e:
            logger.warning(f"Could not preload audio in memory for speaker matching: {e}")

        total_matched = 0
        needs_review_count = 0

        for item in dialogues:
            vec = None
            if full_audio is not None:
                s = max(0, int(item.start * sr))
                e = min(len(full_audio), int(item.end * sr))
                seg = full_audio[s:e]
                if len(seg) >= int(0.05 * sr):
                    vec = cls.compute_feature_vector(seg, sr)
            if vec is None:
                vec = cls.extract_segment_features(audio_path, item.start, item.end)

            if vec is None:
                item.speaker_confidence = 0.0
                item.needs_review = True
                needs_review_count += 1
                continue

            # Compute cosine similarities with all enrolled characters
            scores: List[Tuple[str, float]] = []
            for sid, spk_vec in enrolled_speakers.items():
                if spk_vec.shape != vec.shape:
                    continue
                sim = float(np.dot(vec, spk_vec))
                if not np.isfinite(sim):
                    sim = 0.0
                sim = max(0.0, min(1.0, sim))
                scores.append((sid, sim))

            if not scores:
                item.speaker_confidence = 0.0
                item.needs_review = True
                needs_review_count += 1
                continue

            scores.sort(key=lambda x: x[1], reverse=True)

            top1_id, top1_sim = scores[0]
            top2_sim = scores[1][1] if len(scores) > 1 else 0.0

            item.speaker_id = top1_id
            item.speaker_confidence = round(top1_sim, 3)

            margin = top1_sim - top2_sim
            if top1_sim < confidence_threshold or (len(scores) > 1 and margin < margin_threshold):
                item.needs_review = True
                needs_review_count += 1
            else:
                item.needs_review = False

            total_matched += 1

        logger.info(
            f"Speaker matching finished: {total_matched} clips matched against "
            f"{len(enrolled_speakers)} enrolled characters ({needs_review_count} clips flagged for review)"
        )
        return {
            "matched": True,
            "total": total_matched,
            "needs_review": needs_review_count,
            "confident": total_matched - needs_review_count
        }
