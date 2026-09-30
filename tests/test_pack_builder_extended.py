import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.models import PipelineState, SpeakerInfo, DialogueItem, PackInfo
from core.pack_builder import PackBuilder
from core.quality_checker import QualityChecker, CheckResult
from config import FILENAME_ALLOWED_CHARS


class TestPackBuilderExtended(unittest.TestCase):
    def test_thai_speaker_safe_name(self):
        # 1. Pure Thai name
        spk_thai = SpeakerInfo(speaker_id="SPEAKER_00", display_name="ซันราคุ")
        self.assertEqual(spk_thai.safe_name, "ซันราคุ")

        # 2. Thai name with spaces and special characters
        spk_mixed = SpeakerInfo(speaker_id="SPEAKER_01", display_name="  อาร์เธอร์ / เพนดรากอน : 01  ")
        self.assertEqual(spk_mixed.safe_name, "อาร์เธอร์_เพนดรากอน_01")

        # 3. Speaker safe_name allowed chars validation
        for char in spk_thai.safe_name:
            self.assertIn(char, FILENAME_ALLOWED_CHARS)

        # 4. Fallback when name contains only disallowed chars
        spk_invalid = SpeakerInfo(speaker_id="SPEAKER_02", display_name="???***///")
        self.assertEqual(spk_invalid.safe_name, "Speaker_3")

    def test_sanitize_pack_name_thai_and_english(self):
        self.assertEqual(PackBuilder.sanitize_pack_name("Shangri-La Frontier พากย์ไทย"), "Shangri-La_Frontier_พากย์ไทย")
        self.assertEqual(PackBuilder.sanitize_pack_name("   "), "Untitled_Pack")

    def test_theora_encoder_check_and_fallback(self):
        # Check encoder check function returns a bool
        has_theora = PackBuilder.check_theora_encoder_available()
        self.assertIsInstance(has_theora, bool)

    def test_pack_integrity_validator(self):
        qc = QualityChecker()
        with tempfile.TemporaryDirectory() as tmp_dir:
            pack_dir = Path(tmp_dir) / "test_pack"
            pack_dir.mkdir()

            # Empty directory should fail
            is_valid, results = qc.validate_pack_integrity(pack_dir)
            self.assertFalse(is_valid)

            # Create valid pack structure
            (pack_dir / "_pack_info.ini").write_text("[data]\ntitle=Test Pack\n", encoding="utf-8")
            (pack_dir / "_backing_track.mp3").write_bytes(b"ID3" + b"\x00" * 100)
            (pack_dir / "001_ซันราคุ.mp3").write_bytes(b"ID3" + b"\x00" * 100)
            (pack_dir / "001_ซันราคุ.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
            (pack_dir / "001_ซันราคุ.txt").write_text(
                '[data]\ncaption="สวัสดี"\nimage="001_ซันราคุ.png"\ndub_timestamps=[1.000]\ndub_characters=["ซันราคุ"]\n',
                encoding="utf-8"
            )

            # Standalone validation on disk
            is_valid, results = qc.validate_pack_integrity(pack_dir)
            self.assertTrue(is_valid)

    def test_build_pack_info_ini_and_cues(self):
        builder = PackBuilder()
        info = PackInfo(
            title="มหาเวทย์ผนึกมาร",
            authors=["สตูดิโอแมปปา", "ทีมพากย์ไทย"],
            icon="001_โกโจ.png",
            include_dub_video=True
        )

        ini_content = builder.build_pack_info(info)
        self.assertIn('title="มหาเวทย์ผนึกมาร"', ini_content)
        self.assertIn('"สตูดิโอแมปปา"', ini_content)
        self.assertIn('"ทีมพากย์ไทย"', ini_content)
        self.assertIn('icon="001_โกโจ.png"', ini_content)

        # Cue text generation with Thai characters
        state = PipelineState()
        state.speakers["SPEAKER_00"] = SpeakerInfo("SPEAKER_00", "โกโจ ซาโตรุ")
        item = DialogueItem(
            index=1,
            speaker_id="SPEAKER_00",
            start=2.500,
            end=5.750,
            caption="กางอาณาเขต พื้นที่ไร้มาตร",
            extra_speakers=["สุคุนะ"]
        )

        cue_content = builder.build_txt(
            item,
            state,
            timestamp_mode="start_end",
            speaker_display_names=["โกโจ ซาโตรุ", "สุคุนะ"]
        )
        self.assertIn('caption="กางอาณาเขต พื้นที่ไร้มาตร"', cue_content)
        self.assertIn('"โกโจ ซาโตรุ"', cue_content)
        self.assertIn('"สุคุนะ"', cue_content)
        self.assertIn('dub_timestamps=[2.500, 5.750]', cue_content)

    def test_export_zip_archive(self):
        import zipfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            pack_dir = Path(tmp_dir) / "Export_Test_Pack"
            pack_dir.mkdir()
            (pack_dir / "_pack_info.ini").write_text("[data]\ntitle=Test\n", encoding="utf-8")
            (pack_dir / "001_Test.mp3").write_bytes(b"mp3_bytes")

            zip_path = Path(tmp_dir) / "Export_Test_Pack.zip"
            PackBuilder.export_zip(pack_dir, zip_path)

            self.assertTrue(zip_path.exists())
            with zipfile.ZipFile(zip_path, "r") as zf:
                namelist = zf.namelist()
                self.assertTrue(any(name.endswith("_pack_info.ini") for name in namelist))
                self.assertTrue(any(name.endswith("001_Test.mp3") for name in namelist))

    def test_backward_compatibility_legacy_project_format(self):
        from core.project_manager import ProjectManager
        with tempfile.TemporaryDirectory() as tmp_dir:
            legacy_file = Path(tmp_dir) / "legacy_v1.voicer"
            # Legacy serialized JSON with older/missing fields
            legacy_json = """{
                "version": 1,
                "video_path": "test_video.mp4",
                "video_duration": 12.0,
                "pack_info": {
                    "title": "Legacy Project"
                },
                "speakers": {
                    "SPEAKER_00": {
                        "speaker_id": "SPEAKER_00",
                        "display_name": "Old Speaker"
                    }
                },
                "dialogues": [
                    {
                        "index": 1,
                        "speaker_id": "SPEAKER_00",
                        "start": 0.5,
                        "end": 2.0,
                        "caption": "Hello world"
                    }
                ]
            }"""
            legacy_file.write_text(legacy_json, encoding="utf-8")

            loaded_state = ProjectManager.load_project(legacy_file)
            self.assertEqual(loaded_state.pack_info.title, "Legacy Project")
            self.assertEqual(len(loaded_state.dialogues), 1)
            self.assertEqual(loaded_state.dialogues[0].caption, "Hello world")
            self.assertEqual(loaded_state.speakers["SPEAKER_00"].display_name, "Old Speaker")


if __name__ == "__main__":
    unittest.main()
