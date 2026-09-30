import sys
import unittest
import tempfile
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.frame_extractor import FrameExtractor
from core.models import PipelineState, DialogueItem, SpeakerInfo
from config import IMAGE_MIN_BRIGHTNESS, IMAGE_MOTION_BLUR_THRESHOLD


class TestFrameExtractor(unittest.TestCase):

    def test_is_good_frame_blur_and_brightness(self):
        extractor = FrameExtractor.__new__(FrameExtractor)
        extractor.cv2 = __import__("cv2")
        extractor.cap = None
        extractor.available = True

        # 1. Completely black image (brightness 0 < threshold)
        black_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        self.assertFalse(extractor.is_good_frame(black_frame))

        # 2. Uniform grey image (no edges / zero Laplacian variance -> blurry)
        flat_grey_frame = np.full((100, 100, 3), 128, dtype=np.uint8)
        self.assertFalse(extractor.is_good_frame(flat_grey_frame))

        # 3. High contrast textured image with sharp edges (high Laplacian variance, adequate brightness)
        sharp_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        sharp_frame[::4, :] = 255
        sharp_frame[:, ::4] = 200
        self.assertTrue(extractor.is_good_frame(sharp_frame))

    def test_detect_face_empty_or_no_face(self):
        extractor = FrameExtractor.__new__(FrameExtractor)
        extractor.cv2 = __import__("cv2")
        extractor.cap = None
        extractor.face_cascade = None
        extractor.available = True

        dummy_frame = np.full((100, 100, 3), 128, dtype=np.uint8)
        self.assertFalse(extractor.detect_face(dummy_frame))
        self.assertFalse(extractor.detect_face(None))

    def test_save_frame_valid_and_fallback(self):
        extractor = FrameExtractor.__new__(FrameExtractor)
        extractor.cv2 = __import__("cv2")
        extractor.cap = None
        extractor.available = True

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_path = Path(tmp_dir) / "frame.png"

            # 1. Valid frame saving
            frame = np.full((720, 1280, 3), 150, dtype=np.uint8)
            extractor.save_frame(frame, out_path)
            self.assertTrue(out_path.exists())
            self.assertGreater(out_path.stat().st_size, 0)

            # 2. Fallback saving (None frame) -> PIL dark grey 1280x720 (16:9) image
            fallback_path = Path(tmp_dir) / "fallback.png"
            extractor.save_frame(None, fallback_path)
            self.assertTrue(fallback_path.exists())
            self.assertGreater(fallback_path.stat().st_size, 0)

            # Check PIL image dimensions
            from PIL import Image
            with Image.open(fallback_path) as img:
                self.assertEqual(img.size, (1280, 720))

    def test_find_best_frame_selection(self):
        extractor = FrameExtractor.__new__(FrameExtractor)
        extractor.cv2 = __import__("cv2")
        extractor.cap = None
        extractor.available = True
        extractor.face_cascade = None
        extractor._frame_cache = {}

        # Mock extract_frame to return different frames
        sharp_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        sharp_frame[::2, :] = 255
        blurry_frame = np.full((100, 100, 3), 120, dtype=np.uint8)

        def mock_extract(ts):
            if abs(ts - 2.0) < 0.1:
                return sharp_frame
            return blurry_frame

        extractor.extract_frame = mock_extract

        best = extractor.find_best_frame(1.0, 3.0, num_candidates=3)
        self.assertIsNotNone(best)
        np.testing.assert_array_equal(best, sharp_frame)

    def test_extract_all_frames_dialogue_pipeline(self):
        extractor = FrameExtractor.__new__(FrameExtractor)
        extractor.cv2 = __import__("cv2")
        extractor.cap = None
        extractor.available = True
        extractor.face_cascade = None
        extractor._frame_cache = {}

        dummy_frame = np.full((720, 1280, 3), 140, dtype=np.uint8)
        extractor.find_best_frame = MagicMock(return_value=dummy_frame)

        state = PipelineState()
        state.speakers["SPEAKER_00"] = SpeakerInfo("SPEAKER_00", "ฮีโร่")
        item = DialogueItem(index=1, speaker_id="SPEAKER_00", start=1.0, end=3.0, caption="ลุยเลย!")
        state.dialogues = [item]

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir) / "pack_frames"
            extractor.extract_all_frames(state, out_dir)

            expected_file = out_dir / "001_ฮีโร่.png"
            self.assertTrue(expected_file.exists())
            self.assertEqual(item.image_path, expected_file)

    def test_release(self):
        extractor = FrameExtractor.__new__(FrameExtractor)
        extractor._frame_cache = {1.0: np.zeros((10, 10, 3))}
        extractor.cap = MagicMock()
        extractor.cap.isOpened.return_value = True

        extractor.release()
        self.assertEqual(len(extractor._frame_cache), 0)
        extractor.cap.release.assert_called_once()


if __name__ == "__main__":
    unittest.main()
