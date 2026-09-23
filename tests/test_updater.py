import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.updater import (
    parse_version, is_version_newer, get_current_app_path,
    check_for_updates, generate_updater_batch, UpdateInfo
)


class TestUpdater(unittest.TestCase):

    def test_parse_version(self):
        self.assertEqual(parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version("1.1.0"), (1, 1, 0))
        self.assertEqual(parse_version("v2.0"), (2, 0, 0))
        self.assertEqual(parse_version("2.1.4-beta.1"), (2, 1, 4))
        self.assertEqual(parse_version(""), (0, 0, 0))

    def test_is_version_newer(self):
        self.assertTrue(is_version_newer("v1.2.0", "1.1.0"))
        self.assertTrue(is_version_newer("2.0.0", "1.9.9"))
        self.assertFalse(is_version_newer("1.1.0", "1.1.0"))
        self.assertFalse(is_version_newer("1.0.9", "1.1.0"))
        self.assertFalse(is_version_newer("v1.0.0", "v1.1.0"))

    def test_get_current_app_path(self):
        app_path, is_frozen = get_current_app_path()
        self.assertIsInstance(app_path, Path)
        self.assertIsInstance(is_frozen, bool)

    def test_generate_updater_batch(self):
        tmp_dir = PROJECT_ROOT / "tests" / "fixtures"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        fake_file = tmp_dir / "VoicerStudio-update.zip"
        fake_file.write_text("dummy", encoding="utf-8")
        try:
            bat_path = generate_updater_batch(
                downloaded_file=fake_file,
                is_zip=True,
                target_app_dir=PROJECT_ROOT,
                target_exe=PROJECT_ROOT / "VoicerStudio.exe",
                current_pid=99999
            )
            self.assertTrue(bat_path.exists())
            content = bat_path.read_text(encoding="utf-8")
            self.assertIn("Voicer Studio Updater", content)
            self.assertIn("99999", content)
            bat_path.unlink(missing_ok=True)
        finally:
            fake_file.unlink(missing_ok=True)

    def test_check_for_updates_mock_release(self):
        mock_response_data = b'''{
            "tag_name": "v1.2.0",
            "name": "Voicer Studio v1.2.0",
            "body": "## What's new\\n- Auto-updater",
            "published_at": "2026-09-23T12:00:00Z",
            "html_url": "https://github.com/Auntonin/voicer-studio/releases/tag/v1.2.0",
            "assets": [
                {
                    "name": "VoicerStudio-v1.2.0-win64.zip",
                    "browser_download_url": "https://github.com/Auntonin/voicer-studio/releases/download/v1.2.0/VoicerStudio-v1.2.0-win64.zip",
                    "size": 1048576
                },
                {
                    "name": "VoicerStudio-v1.2.0-win64.zip.sha256",
                    "browser_download_url": "https://github.com/Auntonin/voicer-studio/releases/download/v1.2.0/VoicerStudio-v1.2.0-win64.zip.sha256",
                    "size": 64
                }
            ]
        }'''
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = mock_response_data
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            has_update, update_info, err = check_for_updates(current_version="1.1.0")
            self.assertTrue(has_update)
            self.assertIsNotNone(update_info)
            self.assertEqual(update_info.version, "1.2.0")
            self.assertEqual(update_info.asset_name, "VoicerStudio-v1.2.0-win64.zip")
            self.assertTrue(update_info.is_zip)
            self.assertEqual(update_info.sha256_url, "https://github.com/Auntonin/voicer-studio/releases/download/v1.2.0/VoicerStudio-v1.2.0-win64.zip.sha256")
            self.assertIsNone(err)


if __name__ == "__main__":
    unittest.main()
