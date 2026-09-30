import sys
import unittest
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import PipelineState
from core.transcriber import Transcriber
from core.separator import VoiceSeparator
from core.device_manager import device_manager


class TestMemoryAndCancellation(unittest.TestCase):

    def test_transcriber_unload_model(self):
        transcriber = Transcriber(model_size="tiny", language="th")
        transcriber.available = True
        transcriber.model = "mock_model"

        transcriber.unload_model()
        self.assertIsNone(transcriber.model)
        self.assertFalse(transcriber.available)

    def test_device_manager_release_gpu_memory_safe(self):
        # Should execute safely across platforms without error
        device_manager.release_gpu_memory()

    def test_separator_cancel_check(self):
        separator = VoiceSeparator(mode="original")
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            dummy_audio = tmp_path / "dummy.wav"
            dummy_audio.write_bytes(b"dummy_wav_content")

            # Cancellation check that immediately returns True
            cancelled = True
            vocals, bg = separator.separate(dummy_audio, tmp_path, cancel_check=lambda: cancelled)
            self.assertEqual(vocals, dummy_audio)
            self.assertEqual(bg, dummy_audio)


if __name__ == "__main__":
    unittest.main()
