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

logger = logging.getLogger(__name__)


class SpeakerDiarizer:
    def __init__(self, hf_token: str = '', device: str = 'auto'):
        self.hf_token = hf_token
        self.device = 'cuda' if device == 'auto' else device
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
                logger.warning("pyannote.audio not installed. Using energy clustering fallback.")
            except Exception as e:
                logger.warning(f"Error loading pyannote: {e}. Using energy clustering fallback.")

    # ── Public API ─────────────────────────────────────────────────────────────

    def diarize(self, audio_path: Path, state: PipelineState) -> None:
        if self.available and self.pipeline:
            self._pyannote_diarize(audio_path, state)
        else:
            logger.info("Using energy+spectral clustering for speaker separation (no HF token).")
            self._cluster_diarize(audio_path, state)

    def reassign_speaker(self, state: PipelineState, old_id: str, new_display_name: str):
        if old_id in state.speakers:
            state.speakers[old_id].display_name = new_display_name

    # ── Pyannote (requires HF token) ───────────────────────────────────────────

    def _pyannote_diarize(self, audio_path: Path, state: PipelineState) -> None:
        try:
            logger.info("Running pyannote diarization")
            diarization = self.pipeline(str(audio_path))

            segments: List[Tuple[float, float, str]] = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                segments.append((turn.start, turn.end, speaker))

            mapping = self._match_segments(segments, state.active_dialogues())

            unique_speakers = set()
            for i, item in enumerate(state.active_dialogues()):
                speaker = mapping.get(i, "SPEAKER_00")
                item.speaker_id = speaker
                unique_speakers.add(speaker)

            for spk in unique_speakers:
                if spk not in state.speakers:
                    state.speakers[spk] = SpeakerInfo(speaker_id=spk)

            logger.info(f"Pyannote found {len(unique_speakers)} speakers")
        except Exception as e:
            logger.error(f"Pyannote runtime error: {e}, falling back to clustering.")
            self._cluster_diarize(audio_path, state)

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

    # ── Energy + Spectral Clustering Fallback ──────────────────────────────────

    def _cluster_diarize(self, audio_path: Path, state: PipelineState) -> None:
        """
        Offline speaker separation using audio features + k-means clustering.
        Works without any API key or GPU.

        Features per segment:
          - Mean log energy
          - Energy variance (dynamic range proxy)
          - Spectral centroid mean (brightness / vocal register)
          - Spectral centroid variance
          - Zero-crossing rate (voiced vs unvoiced proxy)
        """
        dialogues = state.active_dialogues()
        if not dialogues:
            return

        try:
            features = self._extract_features(audio_path, dialogues)
            if features is None or len(features) == 0:
                self._assign_single_speaker(state)
                return

            n_speakers = self._estimate_speaker_count(features, max_speakers=6)
            labels = self._kmeans(features, n_speakers)

            # Assign speaker IDs
            unique_labels = sorted(set(labels))
            speaker_map = {lbl: f"SPEAKER_{i:02d}" for i, lbl in enumerate(unique_labels)}

            unique_ids = set()
            for i, item in enumerate(dialogues):
                spk_id = speaker_map.get(labels[i], "SPEAKER_00")
                item.speaker_id = spk_id
                unique_ids.add(spk_id)

            # Register speakers in state
            state.speakers = {}  # reset; keep only detected speakers
            for spk_id in sorted(unique_ids):
                state.speakers[spk_id] = SpeakerInfo(speaker_id=spk_id)

            logger.info(f"Clustering diarization: detected {len(unique_ids)} speaker(s): {sorted(unique_ids)}")

        except Exception as e:
            logger.error(f"Clustering diarization failed: {e}")
            self._assign_single_speaker(state)

    def _extract_features(self, audio_path: Path, dialogues: List[DialogueItem]) -> Optional[list]:
        """Load WAV and extract feature vectors for each dialogue segment."""
        try:
            import numpy as np
            import subprocess
            import io

            # Load full audio as 16kHz mono float32 via ffmpeg pipe
            res = subprocess.run(
                ["ffmpeg", "-y", "-i", str(audio_path),
                 "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120
            )
            if res.returncode != 0 or not res.stdout:
                return None

            import scipy.io.wavfile as wavfile
            sr, raw = wavfile.read(io.BytesIO(res.stdout))
            audio = raw.astype(np.float32)
            if np.max(np.abs(audio)) > 0:
                audio /= np.max(np.abs(audio))

            features = []
            for item in dialogues:
                s = int(item.start * sr)
                e = int(item.end * sr)
                seg = audio[s:e]
                if len(seg) < 100:
                    features.append([0.0, 0.0, 0.0, 0.0, 0.0])
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
        import numpy as np

        # 1. Energy features
        energy = seg ** 2
        mean_log_energy = float(np.log1p(np.mean(energy) * 1000))
        energy_var = float(np.var(energy) * 1000)

        # 2. Spectral centroid (brightness proxy)
        frame_size = min(512, len(seg))
        n_frames = max(1, len(seg) // frame_size)
        centroids = []
        for f in range(n_frames):
            frame = seg[f * frame_size:(f + 1) * frame_size]
            spectrum = np.abs(np.fft.rfft(frame * np.hanning(len(frame))))
            freqs = np.fft.rfftfreq(len(frame), 1 / sr)
            total = np.sum(spectrum)
            centroid = float(np.sum(freqs * spectrum) / total) if total > 0 else 0.0
            centroids.append(centroid)
        sc_mean = float(np.mean(centroids))
        sc_var = float(np.var(centroids))

        # 3. Zero-crossing rate (voiced/unvoiced proxy)
        zcr = float(np.mean(np.abs(np.diff(np.sign(seg)))) / 2)

        return [mean_log_energy, energy_var, sc_mean / 8000.0, sc_var / 1e7, zcr]

    def _estimate_speaker_count(self, features: list, max_speakers: int = 6) -> int:
        """Estimate optimal k using silhouette-like gap heuristic."""
        try:
            import numpy as np
            X = np.array(features, dtype=np.float32)
            n = len(X)
            if n < 4:
                return min(n, 2)

            best_k = 2
            best_score = -1.0

            for k in range(2, min(max_speakers + 1, n)):
                labels = self._kmeans(features, k)
                score = self._silhouette_approx(X, labels, k)
                if score > best_score:
                    best_score = score
                    best_k = k

            logger.info(f"Auto-detected {best_k} speaker(s) (silhouette={best_score:.3f})")
            return best_k

        except Exception:
            return 2

    def _silhouette_approx(self, X: "np.ndarray", labels: list, k: int) -> float:
        """Fast approximate silhouette score."""
        import numpy as np
        scores = []
        label_arr = np.array(labels)
        for i in range(len(X)):
            same = X[label_arr == labels[i]]
            if len(same) > 1:
                a = np.mean(np.linalg.norm(same - X[i], axis=1))
            else:
                a = 0.0
            b_vals = []
            for c in range(k):
                if c == labels[i]:
                    continue
                other = X[label_arr == c]
                if len(other) > 0:
                    b_vals.append(np.mean(np.linalg.norm(other - X[i], axis=1)))
            b = min(b_vals) if b_vals else 0.0
            denom = max(a, b)
            scores.append((b - a) / denom if denom > 0 else 0.0)
        return float(sum(scores) / len(scores)) if scores else 0.0

    def _kmeans(self, features: list, k: int, max_iter: int = 50) -> list:
        """Simple k-means clustering (no sklearn needed)."""
        import numpy as np
        X = np.array(features, dtype=np.float32)
        n = len(X)
        if n == 0:
            return []
        k = min(k, n)

        # Normalise features
        std = X.std(axis=0)
        std[std == 0] = 1.0
        X = (X - X.mean(axis=0)) / std

        # K-means++ initialisation
        rng = np.random.RandomState(42)
        centers = [X[rng.randint(n)]]
        for _ in range(k - 1):
            dists = np.array([min(np.linalg.norm(x - c) ** 2 for c in centers) for x in X])
            probs = dists / dists.sum()
            centers.append(X[rng.choice(n, p=probs)])
        centers = np.array(centers)

        labels = np.zeros(n, dtype=int)
        for _ in range(max_iter):
            dists = np.linalg.norm(X[:, None] - centers[None, :], axis=2)
            new_labels = np.argmin(dists, axis=1)
            if np.all(new_labels == labels):
                break
            labels = new_labels
            for c in range(k):
                if np.any(labels == c):
                    centers[c] = X[labels == c].mean(axis=0)

        return labels.tolist()

    def _assign_single_speaker(self, state: PipelineState) -> None:
        """Last-resort: assign everything to SPEAKER_00."""
        spk = "SPEAKER_00"
        for item in state.active_dialogues():
            item.speaker_id = spk
        state.speakers[spk] = SpeakerInfo(speaker_id=spk)
        logger.warning("Using single-speaker assignment (feature extraction failed).")
