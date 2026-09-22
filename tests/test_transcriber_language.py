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


if __name__ == "__main__":
    unittest.main()
