import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.vad import VADDetector
from core.models import PipelineState


class TestVAD(unittest.TestCase):
    def setUp(self):
        self.vad = VADDetector()

    def test_merge_segments_micro_pauses(self):
        # Two speech segments with a 80ms gap (< 120ms gap) should be merged
        segments = [(1.0, 2.0), (2.080, 3.5)]
        merged = self.vad._merge_segments(segments, gap_ms=120, min_speech_ms=150)
        self.assertEqual(len(merged), 1)
        self.assertAlmostEqual(merged[0][0], 1.0, places=3)
        self.assertAlmostEqual(merged[0][1], 3.5, places=3)

    def test_merge_segments_distinct_pauses(self):
        # Two speech segments with a 500ms gap (> 120ms gap) should remain distinct
        segments = [(1.0, 2.0), (2.5, 4.0)]
        merged = self.vad._merge_segments(segments, gap_ms=120, min_speech_ms=150)
        self.assertEqual(len(merged), 2)
        self.assertAlmostEqual(merged[0][0], 1.0, places=3)
        self.assertAlmostEqual(merged[0][1], 2.0, places=3)
        self.assertAlmostEqual(merged[1][0], 2.5, places=3)
        self.assertAlmostEqual(merged[1][1], 4.0, places=3)

    def test_merge_micro_fragment_bridging(self):
        # A tiny fragment (70ms) close to a preceding word (150ms gap) is bridged
        segments = [(1.0, 2.5), (2.65, 2.72)]
        merged = self.vad._merge_segments(segments, gap_ms=120, min_speech_ms=150)
        self.assertEqual(len(merged), 1)
        self.assertAlmostEqual(merged[0][0], 1.0, places=3)
        self.assertAlmostEqual(merged[0][1], 2.72, places=3)

    def test_isolated_micro_noise_rejection(self):
        # An isolated 50ms spike surrounded by wide silence should be filtered out
        segments = [(10.0, 10.05)]
        merged = self.vad._merge_segments(segments, gap_ms=120, min_speech_ms=150)
        self.assertEqual(len(merged), 0)

    def test_smart_padding_lead_in_lead_out(self):
        # Single isolated segment with 350ms pad
        segments = [(2.0, 4.0)]
        padded = self.vad._apply_smart_padding(segments, pad_ms=350, total_duration=10.0)
        self.assertEqual(len(padded), 1)
        self.assertAlmostEqual(padded[0][0], 1.650, places=3)
        self.assertAlmostEqual(padded[0][1], 4.350, places=3)

    def test_smart_padding_collision_clamping(self):
        # Two segments 200ms apart with 350ms pad (total required 700ms > 200ms)
        # Midpoint is at 2.0 + 0.1 = 2.10
        segments = [(1.0, 2.0), (2.2, 3.5)]
        padded = self.vad._apply_smart_padding(segments, pad_ms=350, total_duration=10.0)
        self.assertEqual(len(padded), 2)
        # Left boundary of first segment
        self.assertAlmostEqual(padded[0][0], 0.650, places=3)
        # Right boundary of first segment clamped at midpoint 2.100
        self.assertAlmostEqual(padded[0][1], 2.100, places=3)
        # Left boundary of second segment clamped at midpoint 2.100
        self.assertAlmostEqual(padded[1][0], 2.100, places=3)
        # Right boundary of second segment
        self.assertAlmostEqual(padded[1][1], 3.850, places=3)

    def test_smart_padding_bounds_and_zero_clamping(self):
        # Segment starting at 0.1s should not go below 0.0s
        segments = [(0.1, 1.0)]
        padded = self.vad._apply_smart_padding(segments, pad_ms=350, total_duration=2.0)
        self.assertEqual(padded[0][0], 0.0)
        self.assertAlmostEqual(padded[0][1], 1.350, places=3)


if __name__ == "__main__":
    unittest.main()
