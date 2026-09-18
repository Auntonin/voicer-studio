"""
core/diarization.py
====================
Speaker diarization — assigns speaker IDs to each dialogue segment.

Priority:
  1. pyannote/speaker-diarization-3.1 (requires HF token + GPU) — most accurate
  2. Energy + spectral clustering fallback (numpy/scipy only) — works offline,
     detects multiple speakers using pitch/energy feature clustering

Fallback design:
  - Extracts per-segment features: mean energy, spectral centroid, pitch proxy
  - k-means clustering on features to group segments by speaker
  - Auto-detects number of speakers (2..N) using silhouette scoring
  - Labels speakers SPEAKER_00, SPEAKER_01, ... consistently
"""

import logging
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.models import PipelineState, SpeakerInfo, DialogueItem
from config import DIARIZATION_MAX_SPEAKERS, DIARIZATION_MIN_SPEAKERS

logger = logging.getLogger(__name__)


class SpeakerDiarizer:
    def __init__(
        self,
        hf_token: str = '',
        device: str = 'auto',
        min_speakers: int = DIARIZATION_MIN_SPEAKERS,
        max_speakers: int = DIARIZATION_MAX_SPEAKERS
    ):
        self.hf_token = hf_token
        self.device = 'cuda' if device == 'auto' else device
        self.min_speakers = min_speakers
        self.max_speakers = max_speakers
        self.available = False
        self.pipeline = None

        if self.hf_token:
            try:
                from pyannote.audio import Pipeline
                import torch

                logger.info("Loading pyannote diarization pipeline")
                try:
                    self.pipeline = Pipeline.from_pretrained(
                        "pyannote/speaker-diarization-3.1",
                        use_auth_token=self.hf_token
                    )
                except TypeError:
                    self.pipeline = Pipeline.from_pretrained(
                        "pyannote/speaker-diarization-3.1",
                        token=self.hf_token
                    )

                if self.device == 'cuda' and torch.cuda.is_available() and self.pipeline:
                    self.pipeline.to(torch.device("cuda"))
                self.available = self.pipeline is not None
            except ImportError:
                logger.warning("pyannote.audio not installed. Using acoustic clustering fallback.")
            except Exception as e:
                logger.warning(f"Error loading pyannote: {e}. Using acoustic clustering fallback.")

    # ── Public API ─────────────────────────────────────────────────────────────

    def diarize(
        self,
        audio_path: Path,
        state: PipelineState,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None
    ) -> None:
        min_spk = min_speakers or self.min_speakers
        max_spk = max_speakers or self.max_speakers
        if self.available and self.pipeline:
            self._pyannote_diarize(audio_path, state, min_spk, max_spk)
        else:
            logger.info("Using advanced acoustic clustering for speaker separation (no HF token).")
            self._cluster_diarize(audio_path, state, min_spk, max_spk)

    def reassign_speaker(self, state: PipelineState, old_id: str, new_display_name: str):
        if old_id in state.speakers:
            state.speakers[old_id].display_name = new_display_name

    # ── Pyannote (requires HF token) ───────────────────────────────────────────

    def _pyannote_diarize(self, audio_path: Path, state: PipelineState, min_speakers: int, max_speakers: int) -> None:
        try:
            logger.info(f"Running pyannote diarization (min={min_speakers}, max={max_speakers})")
            try:
                diarization = self.pipeline(str(audio_path), min_speakers=min_speakers, max_speakers=max_speakers)
            except (TypeError, Exception):
                diarization = self.pipeline(str(audio_path))

            segments: List[Tuple[float, float, str]] = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                segments.append((turn.start, turn.end, speaker))

            mapping = self._match_segments(segments, state.active_dialogues())

            # Chronological mapping so first speaker is SPEAKER_00
            unique_in_order = []
            for i, item in enumerate(state.active_dialogues()):
                raw_spk = mapping.get(i, "SPEAKER_00")
                if raw_spk not in unique_in_order:
                    unique_in_order.append(raw_spk)

            spk_remap = {raw: f"SPEAKER_{idx:02d}" for idx, raw in enumerate(unique_in_order)}

            state.speakers = {}
            for i, item in enumerate(state.active_dialogues()):
                final_spk = spk_remap.get(mapping.get(i, "SPEAKER_00"), "SPEAKER_00")
                item.speaker_id = final_spk
                if final_spk not in state.speakers:
                    state.speakers[final_spk] = SpeakerInfo(speaker_id=final_spk)

            logger.info(f"Pyannote identified {len(state.speakers)} speakers: {list(state.speakers.keys())}")
        except Exception as e:
            logger.error(f"Pyannote runtime error: {e}, falling back to clustering.")
            self._cluster_diarize(audio_path, state, min_speakers, max_speakers)

    def _match_segments(self, diarization_output: List, dialogues: List[DialogueItem]) -> Dict[int, str]:
        mapping: Dict[int, str] = {}
        for i, item in enumerate(dialogues):
            best_speaker = "SPEAKER_00"
            max_overlap = 0.0
            for d_start, d_end, speaker in diarization_output:
                overlap = max(0.0, min(item.end, d_end) - max(item.start, d_start))
                if overlap > max_overlap:
                    max_overlap = overlap
                    best_speaker = speaker
            mapping[i] = best_speaker
        return mapping

    # ── Advanced Acoustic Clustering Fallback ──────────────────────────────────

    def _cluster_diarize(self, audio_path: Path, state: PipelineState, min_speakers: int = 2, max_speakers: int = 8) -> None:
        """
        Offline speaker separation using vocal tract timbre (MFCCs),
        fundamental pitch (F0), and spectral contrast with Agglomerative Clustering.
        Works offline without HF token or GPU.
        """
        dialogues = state.active_dialogues()
        if not dialogues:
            return

        try:
            features = self._extract_features(audio_path, dialogues)
            if features is None or len(features) == 0:
                self._assign_single_speaker(state)
                return

            labels = self._cluster_features(features, min_speakers=min_speakers, max_speakers=max_speakers)

            # Map clusters in chronological order of appearance (SPEAKER_00, SPEAKER_01, ...)
            ordered_map = {}
            for lbl in labels:
                if lbl not in ordered_map:
                    ordered_map[lbl] = f"SPEAKER_{len(ordered_map):02d}"

            state.speakers = {}
            for i, item in enumerate(dialogues):
                spk_id = ordered_map.get(labels[i], "SPEAKER_00")
                item.speaker_id = spk_id
                if spk_id not in state.speakers:
                    state.speakers[spk_id] = SpeakerInfo(speaker_id=spk_id)

            logger.info(f"Acoustic clustering: separated into {len(state.speakers)} speaker(s): {list(state.speakers.keys())}")

        except Exception as e:
            logger.error(f"Acoustic clustering diarization failed: {e}", exc_info=True)
            self._assign_single_speaker(state)

    def _extract_features(self, audio_path: Path, dialogues: List[DialogueItem]) -> Optional[list]:
        """Load WAV and extract 52-dimensional vocal acoustic feature vectors for each dialogue segment."""
        try:
            import numpy as np
            import subprocess
            import io

            from config import SUBPROCESS_FLAGS
            res = subprocess.run(
                ["ffmpeg", "-y", "-i", str(audio_path),
                 "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120,
                creationflags=SUBPROCESS_FLAGS
            )
            if res.returncode != 0 or not res.stdout:
                return None

            import scipy.io.wavfile as wavfile
            sr, raw = wavfile.read(io.BytesIO(res.stdout))
            audio = raw.astype(np.float32)
            max_val = np.max(np.abs(audio))
            if max_val > 0:
                audio /= max_val

            features = []
            for item in dialogues:
                s = max(0, int(item.start * sr))
                e = min(len(audio), int(item.end * sr))
                seg = audio[s:e]
                if len(seg) < int(0.05 * sr):
                    features.append(np.zeros(52, dtype=np.float32).tolist())
                    continue
                features.append(self._compute_segment_features(seg, sr))

            return features

        except FileNotFoundError:
            logger.warning("FFmpeg not found; cannot extract audio features for clustering.")
            return None
        except Exception as e:
            logger.warning(f"Feature extraction failed: {e}")
            return None

    def _compute_segment_features(self, seg: "np.ndarray", sr: int) -> List[float]:
        """
        Extract rich vocal characteristics:
        - 20 MFCC means (vocal tract formants & timbre)
        - 20 MFCC stds (spectral dynamics)
        - Pitch / F0 features (median, std, voicing ratio via librosa.yin)
        - Spectral contrast (7 bands mean)
        - Spectral centroid (mean & std)
        """
        import numpy as np

        try:
            import librosa

            # 1. MFCCs (20 mean, 20 std = 40 features)
            n_fft = min(1024, len(seg))
            hop_length = n_fft // 2
            mfcc = librosa.feature.mfcc(y=seg, sr=sr, n_mfcc=20, n_fft=n_fft, hop_length=hop_length)
            mfcc_mean = np.mean(mfcc, axis=1)
            mfcc_std = np.std(mfcc, axis=1)

            # 2. Fundamental Frequency F0 (pitch median, pitch std, voicing ratio)
            try:
                # Yin pitch estimator (detects human vocal fundamental pitch between 65Hz and 450Hz)
                f0 = librosa.yin(seg, fmin=65, fmax=450, sr=sr, frame_length=n_fft, hop_length=hop_length)
                voiced = f0[(f0 >= 65) & (f0 <= 450)]
                f0_med = float(np.median(voiced)) if len(voiced) > 0 else 0.0
                f0_std = float(np.std(voiced)) if len(voiced) > 0 else 0.0
                v_ratio = float(len(voiced) / max(1, len(f0)))
            except Exception:
                f0_med, f0_std, v_ratio = 0.0, 0.0, 0.0

            # 3. Spectral Contrast (7 bands mean)
            try:
                contrast = librosa.feature.spectral_contrast(y=seg, sr=sr, n_bands=6, n_fft=n_fft, hop_length=hop_length)
                contrast_mean = np.mean(contrast, axis=1)
            except Exception:
                contrast_mean = np.zeros(7, dtype=np.float32)

            # 4. Spectral Centroid (mean & std)
            sc = librosa.feature.spectral_centroid(y=seg, sr=sr, n_fft=n_fft, hop_length=hop_length)
            sc_mean = float(np.mean(sc))
            sc_std = float(np.std(sc))

            feats = np.hstack([
                mfcc_mean,
                mfcc_std,
                [f0_med, f0_std, v_ratio],
                contrast_mean,
                [sc_mean, sc_std]
            ])
            return feats.astype(np.float32).tolist()

        except Exception:
            return self._compute_numpy_fallback_features(seg, sr)

    def _compute_numpy_fallback_features(self, seg: "np.ndarray", sr: int) -> List[float]:
        import numpy as np
        energy = seg ** 2
        mean_log_energy = float(np.log1p(np.mean(energy) * 1000))
        energy_var = float(np.var(energy) * 1000)
        zcr = float(np.mean(np.abs(np.diff(np.sign(seg)))) / 2)
        vec = np.zeros(52, dtype=np.float32)
        vec[0] = mean_log_energy
        vec[1] = energy_var
        vec[2] = zcr
        return vec.tolist()

    def _cluster_features(self, features: list, min_speakers: int = 2, max_speakers: int = 8) -> list:
        """
        Performs Agglomerative Hierarchical Clustering using Cosine Distance and Silhouette Scoring.
        """
        import numpy as np
        from sklearn.preprocessing import StandardScaler
        from sklearn.cluster import AgglomerativeClustering
        from sklearn.metrics import silhouette_score

        X = np.array(features, dtype=np.float32)
        n = len(X)
        if n == 0:
            return []
        if n == 1:
            return [0]
        if n == 2:
            norm0 = np.linalg.norm(X[0])
            norm1 = np.linalg.norm(X[1])
            if norm0 > 0 and norm1 > 0:
                cos_sim = np.dot(X[0], X[1]) / (norm0 * norm1)
            else:
                cos_sim = 1.0
            return [0, 1] if cos_sim < 0.75 else [0, 0]

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        max_k = min(max_speakers, n - 1)
        min_k = min(min_speakers, max_k)

        best_k = min_k
        best_score = -2.0
        best_labels = None

        for k in range(min_k, max_k + 1):
            try:
                clusterer = AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average")
                labels = clusterer.fit_predict(X_scaled)
                score = silhouette_score(X_scaled, labels, metric="cosine")
                logger.debug(f"AHC k={k}: silhouette={score:.3f}")
                if score > best_score:
                    best_score = score
                    best_k = k
                    best_labels = labels
            except Exception as err:
                logger.debug(f"Clustering with k={k} skipped: {err}")
                continue

        if best_labels is None:
            best_labels = np.zeros(n, dtype=int)
        else:
            logger.info(f"Optimal speaker clusters: {best_k} (silhouette={best_score:.3f})")

        return best_labels.tolist()

    def _assign_single_speaker(self, state: PipelineState) -> None:
        """Last-resort: assign everything to SPEAKER_00."""
        spk = "SPEAKER_00"
        for item in state.active_dialogues():
            item.speaker_id = spk
        state.speakers = {spk: SpeakerInfo(speaker_id=spk)}
        logger.warning("Using single-speaker assignment (feature extraction failed).")
