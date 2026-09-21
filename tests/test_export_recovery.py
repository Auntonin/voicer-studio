"""
tests/test_export_recovery.py
=============================
Automated test suite for PackBuilder auto-repair & recovery mechanisms during export.
"""

import sys
import unittest
import tempfile
import shutil
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import PipelineState, DialogueItem, SpeakerInfo, PackInfo
from core.pack_builder import PackBuilder
from core.quality_checker import QualityChecker


class TestExportRecovery(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_packbuilder_auto_repairs_missing_audio_and_image(self):
        """
        Verify that when dialogue items have missing/non-existent audio and image paths,
        PackBuilder generates fallback valid assets so export succeeds and quality checks pass.
        """
        state = PipelineState()
        state.pack_info = PackInfo(title="AutoRepairTest", authors=["VoicerTester"], include_dub_video=False)
        state.speakers["1"] = SpeakerInfo(speaker_id="1", display_name="Actor 1")

        # Create dialogue item with non-existent audio and image paths
        item = DialogueItem(
            index=1,
            speaker_id="1",
            start=1.0,
            end=3.5,
            caption="Hello auto repair test",
            audio_path=self.temp_path / "non_existent_audio.wav",
            image_path=self.temp_path / "non_existent_image.png"
        )
        state.dialogues.append(item)

        builder = PackBuilder()
        pack_dir = builder.build_pack(
            state,
            output_dir=self.temp_path,
            options={"speaker_display_names": {"1": "Actor 1"}}
        )

        self.assertTrue(pack_dir.exists())
        self.assertTrue((pack_dir / "_pack_info.ini").exists())
        self.assertTrue((pack_dir / "_backing_track.mp3").exists())
        
        # Verify fallback files were created in the pack folder
        audio_files = list(pack_dir.glob("*.mp3"))
        png_files = list(pack_dir.glob("*.png"))
        txt_files = list(pack_dir.glob("*.txt"))

        self.assertGreaterEqual(len(audio_files), 2)  # _backing_track.mp3 + item audio
        self.assertGreaterEqual(len(png_files), 1)
        self.assertGreaterEqual(len(txt_files), 1)

        # Quality check should pass without fatal errors
        checker = QualityChecker()
        results = checker.check_all(state, pack_dir)
        errors = [r for r in results if r.level == "error"]
        self.assertEqual(len(errors), 0, f"Expected 0 errors after auto-repair, got: {errors}")


if __name__ == "__main__":
    unittest.main()
