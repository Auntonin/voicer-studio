import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.transcriber import Transcriber
from core.text_cleaner import ThaiTextCleaner
from config import WHISPER_SUPPORTED_LANGUAGES, WHISPER_INITIAL_PROMPT_THAI


class TestTranscriberLanguage(unittest.TestCase):
    def test_transcriber_init_languages(self):
        # Explicit Thai
        t_th = Transcriber(language="th")
        self.assertEqual(t_th.language, "th")
        self.assertEqual(t_th.initial_prompt, WHISPER_INITIAL_PROMPT_THAI)

        # Auto-detect / Dynamic
        t_auto = Transcriber(language="auto")
        self.assertIsNone(t_auto.language)
        self.assertIsNone(t_auto.initial_prompt)

        t_none = Transcriber(language=None)
        self.assertIsNone(t_none.language)

        # Explicit Japanese
        t_ja = Transcriber(language="ja")
        self.assertEqual(t_ja.language, "ja")
        self.assertIsNone(t_ja.initial_prompt)

    def test_supported_languages_config(self):
        self.assertIn("th", WHISPER_SUPPORTED_LANGUAGES)
        self.assertIn("auto", WHISPER_SUPPORTED_LANGUAGES)
        self.assertIn("ja", WHISPER_SUPPORTED_LANGUAGES)
        self.assertIn("en", WHISPER_SUPPORTED_LANGUAGES)

    def test_thai_text_cleaner_mixed_content(self):
        thai_text = "ขอบคุณครับ ขอบคุณครับ ขอบคุณครับ"
        cleaned = ThaiTextCleaner.process_transcript(thai_text, language="th")
        self.assertEqual(cleaned, "ขอบคุณครับ ขอบคุณครับ")

        # Auto mode with Thai text and keywords
        thai_with_keywords = "สวัสดีครับ boss เล่น quest นี้"
        cleaned_dynamic = ThaiTextCleaner.process_transcript(thai_with_keywords, language=None)
        self.assertEqual(cleaned_dynamic, "สวัสดีครับ Boss เล่น Quest นี้")

    def test_word_timestamp_boundary_refinement(self):
        from core.models import PipelineState
        from collections import namedtuple

        Word = namedtuple("Word", ["start", "end", "word", "probability"])
        Segment = namedtuple("Segment", ["start", "end", "text", "words"])

        t = Transcriber(language="th")
        t.available = True
        t.model = MagicMock()

        # Mock segment spanning 1.0s to 5.0s, but words spoken only from 2.0s to 3.5s
        words = [
            Word(start=2.0, end=2.5, word="สวัสดี", probability=0.9),
            Word(start=2.6, end=3.5, word="ครับ", probability=0.95),
        ]
        mock_seg = Segment(start=1.0, end=5.0, text="สวัสดีครับ", words=words)
        info = MagicMock()
        info.language = "th"

        t.model.transcribe.return_value = ([mock_seg], info)

        state = PipelineState()
        ok = t.transcribe_and_segment(Path("mock.wav"), state, total_duration=10.0)

        self.assertTrue(ok)
        self.assertEqual(len(state.dialogues), 1)
        dialogue = state.dialogues[0]
        # First word starts at 2.0 -> refined_start = max(0.0, 2.0 - 0.10) = 1.90
        # Last word ends at 3.5 -> refined_end = 3.5 + 0.12 = 3.62
        self.assertAlmostEqual(dialogue.start, 1.90, places=2)
        self.assertAlmostEqual(dialogue.end, 3.62, places=2)
        self.assertEqual(dialogue.caption, "สวัสดีครับ")


if __name__ == "__main__":
    unittest.main()
