import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.models import PipelineState, DialogueItem
from core.separator import VoiceSeparator
from config import VoiceSepMode


class TestSeparator(unittest.TestCase):

    def test_separator_original_mode(self):
        separator = VoiceSeparator(mode=VoiceSepMode.ORIGINAL)
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            audio = tmp_path / "work.wav"
            audio.write_bytes(b"RIFF" + b"\x00" * 40)

            vocals, bg = separator.separate(audio, tmp_path)
            self.assertEqual(vocals, audio)
            self.assertEqual(bg, audio)

    def test_get_clip_audio_routing(self):
        separator = VoiceSeparator(mode=VoiceSepMode.ROFORMER)
        state = PipelineState()
        state.work_audio_path = Path("work.wav")
        state.separated_vocals_path = Path("vocals.wav")

        item = DialogueItem(index=1, speaker_id="SPEAKER_00", start=0.0, end=1.0)
        clip_audio = separator.get_clip_audio(item, state)
        self.assertEqual(clip_audio, Path("vocals.wav"))

        # In ORIGINAL mode, fallback to work_audio_path
        sep_orig = VoiceSeparator(mode=VoiceSepMode.ORIGINAL)
        clip_audio_orig = sep_orig.get_clip_audio(item, state)
        self.assertEqual(clip_audio_orig, Path("work.wav"))

    def test_separator_unavailable_fallback(self):
        separator = VoiceSeparator(mode=VoiceSepMode.ROFORMER)
        separator.available = False
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            audio = tmp_path / "audio.wav"
            audio.write_bytes(b"RIFF" + b"\x00" * 40)

            vocals, bg = separator.separate(audio, tmp_path)
            self.assertEqual(vocals, audio)
            self.assertEqual(bg, audio)


if __name__ == "__main__":
    unittest.main()
