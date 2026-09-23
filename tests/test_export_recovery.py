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
try:
    from PySide6.QtWidgets import QApplication
    _gui_available = True
except ImportError:
    _gui_available = False

app = QApplication.instance() or QApplication([]) if _gui_available else None


@unittest.skipIf(not _gui_available, "GUI not available")
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

    def test_export_dialog_missing_asset_detection(self):
        """
        Verify ExportDialog._detect_missing_assets safely detects missing assets without raising AttributeError.
        """
        from gui.export_dialog import ExportDialog
        state = PipelineState()
        state.pack_backing_track_path = None
        item = DialogueItem(index=1, speaker_id="1", start=0.0, end=1.0, caption="test")
        state.dialogues.append(item)

        settings = {"output_dir": str(self.temp_path), "auto_repair_missing_export_assets": True}
        dlg = ExportDialog(None, state, settings)
        missing_info = dlg._detect_missing_assets()
        
        self.assertTrue(missing_info["has_missing"])
        self.assertEqual(missing_info["images"], 1)
        self.assertEqual(missing_info["audio"], 1)
        self.assertFalse(missing_info["backing"])

    def test_packbuilder_speaker_roles_separation(self):
        """
        Verify that exported .txt files for each dialogue item contain only that dialogue's
        speaker/role in dub_characters, instead of dumping all project speakers together.
        """
        state = PipelineState()
        state.pack_info = PackInfo(title="MultiSpeakerTest", include_dub_video=False)
        state.speakers["SPEAKER_00"] = SpeakerInfo(speaker_id="SPEAKER_00", display_name="Hero")
        state.speakers["SPEAKER_01"] = SpeakerInfo(speaker_id="SPEAKER_01", display_name="Villain")
        state.speakers["SPEAKER_02"] = SpeakerInfo(speaker_id="SPEAKER_02", display_name="Narrator")

        item1 = DialogueItem(index=1, speaker_id="SPEAKER_00", start=0.0, end=2.0, caption="I am the hero")
        item2 = DialogueItem(index=2, speaker_id="SPEAKER_01", start=2.5, end=4.5, caption="I am the villain")
        state.dialogues.extend([item1, item2])

        builder = PackBuilder()
        speaker_map = {sid: spk.display_name for sid, spk in state.speakers.items()}
        pack_dir = builder.build_pack(
            state,
            output_dir=self.temp_path,
            options={"speaker_display_names": speaker_map}
        )

        txt1 = (pack_dir / f"{item1.filename_base(state.get_speaker_safe_name('SPEAKER_00'))}.txt").read_text(encoding="utf-8")
        txt2 = (pack_dir / f"{item2.filename_base(state.get_speaker_safe_name('SPEAKER_01'))}.txt").read_text(encoding="utf-8")

        self.assertIn('dub_characters=["Hero"]', txt1)
        self.assertNotIn("Villain", txt1)
        self.assertNotIn("Narrator", txt1)

        self.assertIn('dub_characters=["Villain"]', txt2)
        self.assertNotIn("Hero", txt2)
        self.assertNotIn("Narrator", txt2)


if __name__ == "__main__":
    unittest.main()
