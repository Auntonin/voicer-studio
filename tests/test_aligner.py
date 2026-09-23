import sys
import unittest
import tempfile
from pathlib import Path
import numpy as np
import scipy.io.wavfile as wavfile

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.models import PipelineState, DialogueItem
from core.aligner import ForcedAligner


class TestForcedAligner(unittest.TestCase):
    def setUp(self):
        self.sr = 16000
        # 4 seconds total: 0-1s silence, 1-3s speech tone, 3-4s silence
        self.duration = 4.0
        self.audio = np.zeros(int(self.sr * self.duration), dtype=np.float32)

        t_speech = np.linspace(0, 2.0, int(self.sr * 2.0), endpoint=False)
        speech_signal = (
            0.6 * np.sin(2 * np.pi * 300 * t_speech)
            + 0.3 * np.sin(2 * np.pi * 600 * t_speech)
            + 0.05 * np.random.randn(len(t_speech))
        ).astype(np.float32)

        start_idx = int(self.sr * 1.0)
        end_idx = start_idx + len(speech_signal)
        self.audio[start_idx:end_idx] = speech_signal

    def test_refine_boundary_acoustic_active_speech(self):
        # Coarse initial bounds: 0.85s to 3.15s (speech is 1.0s to 3.0s)
        coarse_start = 0.85
        coarse_end = 3.15

        new_start, new_end = ForcedAligner.refine_boundary_acoustic(
            self.audio, self.sr, coarse_start, coarse_end,
            search_win_s=0.25, threshold_ratio=0.04, pad_lead_s=0.08, pad_tail_s=0.10
        )

        # Onset is at 1.0s; with 80ms lead padding, new_start should be around 0.92s
        self.assertAlmostEqual(new_start, 0.92, delta=0.05)
        # Decay is at 3.0s; with 100ms tail padding, new_end should be around 3.10s
        self.assertAlmostEqual(new_end, 3.10, delta=0.05)
        self.assertLess(new_start, new_end)

    def test_refine_boundary_acoustic_silence(self):
        # In a silent region, boundaries should remain unchanged
        silent_audio = np.zeros(int(self.sr * 3.0), dtype=np.float32)
        start, end = ForcedAligner.refine_boundary_acoustic(
            silent_audio, self.sr, 1.0, 2.0
        )
        self.assertEqual(start, 1.0)
        self.assertEqual(end, 2.0)

    def test_refine_boundary_acoustic_short_audio(self):
        # Audio shorter than 80ms should return original boundaries
        short_audio = np.zeros(int(self.sr * 0.05), dtype=np.float32)
        start, end = ForcedAligner.refine_boundary_acoustic(
            short_audio, self.sr, 0.01, 0.04
        )
        self.assertEqual(start, 0.01)
        self.assertEqual(end, 0.04)

    def test_edge_cases_empty_and_nan(self):
        # None or empty audio
        s, e = ForcedAligner.refine_boundary_acoustic(np.array([], dtype=np.float32), 16000, 1.0, 2.0)
        self.assertEqual((s, e), (1.0, 2.0))

        # Zero sample rate
        s, e = ForcedAligner.refine_boundary_acoustic(self.audio, 0, 1.0, 2.0)
        self.assertEqual((s, e), (1.0, 2.0))

        # Inverted or zero duration
        s, e = ForcedAligner.refine_boundary_acoustic(self.audio, self.sr, 2.5, 1.0)
        self.assertEqual((s, e), (2.5, 1.0))
        s, e = ForcedAligner.refine_boundary_acoustic(self.audio, self.sr, 1.0, 1.02)
        self.assertEqual((s, e), (1.0, 1.02))

        # Audio containing NaN or Inf
        nan_audio = self.audio.copy()
        nan_audio[int(1.5 * self.sr):int(1.6 * self.sr)] = np.nan
        s, e = ForcedAligner.refine_boundary_acoustic(nan_audio, self.sr, 0.85, 3.15)
        self.assertIsInstance(s, float)
        self.assertIsInstance(e, float)

    def test_neighbor_clamping_prevents_overlap(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wav_path = Path(tmp_dir) / "test_adjacent.wav"
            scaled = (self.audio * 32767).astype(np.int16)
            wavfile.write(str(wav_path), self.sr, scaled)

            state = PipelineState()
            item1 = DialogueItem(index=1, speaker_id="SPEAKER_00", start=1.0, end=1.9, caption="Part 1")
            item2 = DialogueItem(index=2, speaker_id="SPEAKER_01", start=2.0, end=3.0, caption="Part 2")
            state.dialogues.extend([item1, item2])

            res = ForcedAligner.align_all(state, wav_path)
            self.assertEqual(res["total"], 2)
            # Item 1 end must not overlap item 2 start
            self.assertLessEqual(item1.end, item2.start)

    def test_load_audio_mono_16k_stereo_and_empty(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            # 1. Stereo file
            stereo_path = Path(tmp_dir) / "stereo.wav"
            stereo_data = np.stack([self.audio, self.audio], axis=-1)
            scaled = (stereo_data * 32767).astype(np.int16)
            wavfile.write(str(stereo_path), self.sr, scaled)

            loaded, sr = ForcedAligner.load_audio_mono_16k(stereo_path)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.ndim, 1)
            self.assertEqual(sr, 16000)

            # 2. Empty WAV file
            empty_path = Path(tmp_dir) / "empty.wav"
            wavfile.write(str(empty_path), self.sr, np.array([], dtype=np.int16))
            loaded_empty, _ = ForcedAligner.load_audio_mono_16k(empty_path)
            self.assertIsNone(loaded_empty)

            # 3. Nonexistent file
            loaded_none, _ = ForcedAligner.load_audio_mono_16k(Path(tmp_dir) / "nonexistent.wav")
            self.assertIsNone(loaded_none)

    def test_align_clip_and_align_all(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            wav_path = Path(tmp_dir) / "test_audio.wav"
            scaled = (self.audio * 32767).astype(np.int16)
            wavfile.write(str(wav_path), self.sr, scaled)

            state = PipelineState()
            item = DialogueItem(
                index=1,
                speaker_id="SPEAKER_00",
                start=0.85,
                end=3.15,
                caption="Testing alignment"
            )
            state.dialogues.append(item)

            # Test single clip alignment
            adjusted = ForcedAligner.align_clip(item, wav_path)
            self.assertTrue(adjusted)
            self.assertAlmostEqual(item.start, 0.92, delta=0.05)
            self.assertAlmostEqual(item.end, 3.10, delta=0.05)

            # Reset item for align_all test
            item.start = 0.85
            item.end = 3.15
            res = ForcedAligner.align_all(state, wav_path)
            self.assertEqual(res["total"], 1)
            self.assertEqual(res["adjusted"], 1)
            self.assertGreater(res["avg_shift_ms"], 0.0)


if __name__ == "__main__":
    unittest.main()
