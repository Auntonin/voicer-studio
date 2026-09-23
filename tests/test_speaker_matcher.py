import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.models import PipelineState, SpeakerInfo, DialogueItem, UndoManager
from core.speaker_matcher import SpeakerMatcher
from core.diarization import SpeakerDiarizer


class TestSpeakerMatcher(unittest.TestCase):
    def test_speaker_info_voiceprint_serialization(self):
        spk = SpeakerInfo(
            speaker_id="SPEAKER_00",
            display_name="Sunraku",
            voiceprint_samples=["Sample 1", "Sample 2"],
            embedding=[0.1, 0.2, 0.3]
        )
        self.assertTrue(spk.has_voiceprint())
        d = spk.to_dict()
        self.assertEqual(d["speaker_id"], "SPEAKER_00")
        self.assertEqual(d["display_name"], "Sunraku")
        self.assertEqual(d["voiceprint_samples"], ["Sample 1", "Sample 2"])
        self.assertEqual(d["embedding"], [0.1, 0.2, 0.3])

        loaded = SpeakerInfo.from_dict(d)
        self.assertEqual(loaded.speaker_id, "SPEAKER_00")
        self.assertEqual(loaded.display_name, "Sunraku")
        self.assertEqual(loaded.voiceprint_samples, ["Sample 1", "Sample 2"])
        self.assertEqual(loaded.embedding, [0.1, 0.2, 0.3])
        self.assertTrue(loaded.has_voiceprint())

    def test_dialogue_item_confidence_serialization(self):
        item = DialogueItem(
            index=1,
            speaker_id="SPEAKER_00",
            start=1.0,
            end=3.0,
            caption="Test dialogue",
            speaker_confidence=0.885,
            needs_review=True
        )
        d = item.to_dict()
        self.assertEqual(d["speaker_confidence"], 0.885)
        self.assertTrue(d["needs_review"])

        loaded = DialogueItem.from_dict(d)
        self.assertEqual(loaded.speaker_confidence, 0.885)
        self.assertTrue(loaded.needs_review)

    def test_feature_vector_computation_normalized(self):
        # Generate 1 second of 440Hz test audio
        sr = 16000
        t = np.linspace(0, 1.0, sr, endpoint=False)
        seg = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

        vec = SpeakerMatcher.compute_feature_vector(seg, sr=sr)
        self.assertEqual(len(vec), 52)
        norm = float(np.linalg.norm(vec))
        self.assertAlmostEqual(norm, 1.0, places=4)

    def test_speaker_enrollment_and_matching(self):
        state = PipelineState()
        spk_a = SpeakerInfo(speaker_id="SPEAKER_00", display_name="Arthur")
        spk_b = SpeakerInfo(speaker_id="SPEAKER_01", display_name="Rei")
        state.speakers["SPEAKER_00"] = spk_a
        state.speakers["SPEAKER_01"] = spk_b

        # Create two distinct orthogonal-like normalized embeddings
        v_a = np.zeros(52, dtype=np.float32)
        v_a[0] = 1.0
        v_b = np.zeros(52, dtype=np.float32)
        v_b[1] = 1.0

        spk_a.embedding = v_a.tolist()
        spk_a.voiceprint_samples = ["Arthur Reference"]
        spk_b.embedding = v_b.tolist()
        spk_b.voiceprint_samples = ["Rei Reference"]

        self.assertTrue(SpeakerMatcher.has_enrolled_speakers(state))

        # Dialogue 1: audio matches Arthur perfectly
        item1 = DialogueItem(index=1, speaker_id="SPEAKER_UNKNOWN", start=0.0, end=2.0)
        # Dialogue 2: audio matches Rei perfectly
        item2 = DialogueItem(index=2, speaker_id="SPEAKER_UNKNOWN", start=2.5, end=4.5)
        # Dialogue 3: ambiguous audio (low similarity to both)
        item3 = DialogueItem(index=3, speaker_id="SPEAKER_UNKNOWN", start=5.0, end=7.0)

        state.dialogues = [item1, item2, item3]

        def mock_extract(audio_path, start, end):
            if start == 0.0:
                return v_a.copy()
            elif start == 2.5:
                return v_b.copy()
            else:
                # Orthogonal to both
                v_other = np.zeros(52, dtype=np.float32)
                v_other[10] = 1.0
                return v_other

        with patch.object(SpeakerMatcher, "extract_segment_features", side_effect=mock_extract):
            res = SpeakerMatcher.match_dialogues(state, Path("mock.wav"), confidence_threshold=0.60, margin_threshold=0.10)

        self.assertTrue(res["matched"])
        self.assertEqual(res["total"], 3)
        self.assertEqual(res["needs_review"], 1)

        # Check item 1 (Arthur)
        self.assertEqual(item1.speaker_id, "SPEAKER_00")
        self.assertAlmostEqual(item1.speaker_confidence, 1.0, places=2)
        self.assertFalse(item1.needs_review)

        # Check item 2 (Rei)
        self.assertEqual(item2.speaker_id, "SPEAKER_01")
        self.assertAlmostEqual(item2.speaker_confidence, 1.0, places=2)
        self.assertFalse(item2.needs_review)

        # Check item 3 (Low confidence -> flagged for review)
        self.assertTrue(item3.needs_review)
        self.assertLess(item3.speaker_confidence, 0.60)

    def test_diarize_routes_to_matcher_when_enrolled(self):
        state = PipelineState()
        spk = SpeakerInfo(speaker_id="SPEAKER_00", display_name="Hero", voiceprint_samples=["ref"], embedding=[0.5]*52)
        state.speakers["SPEAKER_00"] = spk

        diarizer = SpeakerDiarizer()
        with patch.object(SpeakerMatcher, "match_dialogues", return_value={"matched": True}) as mock_match:
            diarizer.diarize(Path("mock.wav"), state)
            mock_match.assert_called_once()

    def test_edge_cases_and_resilience(self):
        # 1. Feature computation on segment with NaNs and Infs
        nan_seg = np.array([np.nan, np.inf, -np.inf, 0.0, 0.5, -0.5] * 200, dtype=np.float32)
        vec = SpeakerMatcher.compute_feature_vector(nan_seg, sr=16000)
        self.assertFalse(np.any(np.isnan(vec)))
        self.assertFalse(np.any(np.isinf(vec)))

        # 2. Enrolling with empty speaker_id
        state = PipelineState()
        self.assertFalse(SpeakerMatcher.enroll_speaker_sample(state, "", Path("mock.wav"), 0.0, 1.0))

        # 3. Mismatched vector dimensions in enrolled speakers (e.g. 20-dim vs 52-dim)
        spk = state.get_speaker("SPEAKER_00")
        spk.embedding = [0.1] * 20
        spk.voiceprint_samples = ["Old 20-dim Sample"]
        state.dialogues = [DialogueItem(index=1, speaker_id="SPEAKER_UNKNOWN", start=0.0, end=1.0)]

        with patch.object(SpeakerMatcher, "extract_segment_features", return_value=np.zeros(52, dtype=np.float32)):
            res = SpeakerMatcher.match_dialogues(state, Path("mock.wav"))
            self.assertTrue(res["matched"])
            self.assertEqual(res["needs_review"], 1)

        # 4. Empty dialogues match
        state.dialogues.clear()
        res = SpeakerMatcher.match_dialogues(state, Path("mock.wav"))
        self.assertTrue(res["matched"])
        self.assertEqual(res["total"], 0)

        # 5. UndoManager pop_last
        mgr = UndoManager()
        self.assertIsNone(mgr.pop_last())
        mgr.push(state)
        self.assertEqual(len(mgr.undo_stack), 1)
        popped = mgr.pop_last()
        self.assertIsNotNone(popped)
        self.assertEqual(len(mgr.undo_stack), 0)


if __name__ == "__main__":
    unittest.main()
