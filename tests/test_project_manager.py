import sys
import unittest
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import PipelineState, DialogueItem, SpeakerInfo, PackInfo, PipelineStep
from core.project_manager import ProjectManager


class TestProjectManager(unittest.TestCase):

    def test_project_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            proj_file = tmp_path / "test_session.voicer"

            # Create populated state
            state = PipelineState()
            state.video_path = tmp_path / "sample.mp4"
            state.video_duration = 45.5
            state.video_width = 1920
            state.video_height = 1080
            state.video_fps = 30.0

            state.pack_info.title = "Test Anime Pack"
            state.pack_info.authors = ["AuthorA", "AuthorB"]
            state.pack_info.icon = "001_Hero.png"

            state.speakers["SPEAKER_00"] = SpeakerInfo("SPEAKER_00", "Hero")
            state.speakers["SPEAKER_01"] = SpeakerInfo("SPEAKER_01", "Villain")
            state.speaker_order = ["SPEAKER_00", "SPEAKER_01"]

            item1 = DialogueItem(
                index=1,
                speaker_id="SPEAKER_00",
                start=1.5,
                end=3.8,
                caption="I will protect everyone!",
                audio_path=tmp_path / "001_Hero.mp3",
                image_path=tmp_path / "001_Hero.png"
            )
            item2 = DialogueItem(
                index=2,
                speaker_id="SPEAKER_01",
                start=4.2,
                end=6.9,
                caption="You are too late.",
                extra_speakers=["SPEAKER_00"]
            )
            state.dialogues = [item1, item2]
            state.step_completed[PipelineStep.VAD] = True
            state.step_completed[PipelineStep.TRANSCRIPTION] = True

            # Save project
            ok = ProjectManager.save_project(state, proj_file)
            self.assertTrue(ok, "save_project returned False")
            self.assertTrue(proj_file.exists(), "Project file was not created")

            # Load project
            loaded = ProjectManager.load_project(proj_file)
            self.assertEqual(loaded.pack_info.title, "Test Anime Pack")
            self.assertEqual(loaded.pack_info.authors, ["AuthorA", "AuthorB"])
            self.assertEqual(len(loaded.speakers), 2)
            self.assertEqual(loaded.speakers["SPEAKER_00"].display_name, "Hero")
            self.assertEqual(loaded.speakers["SPEAKER_01"].display_name, "Villain")
            self.assertEqual(loaded.speaker_order, ["SPEAKER_00", "SPEAKER_01"])
            self.assertEqual(len(loaded.dialogues), 2)
            self.assertEqual(loaded.dialogues[0].caption, "I will protect everyone!")
            self.assertEqual(loaded.dialogues[1].extra_speakers, ["SPEAKER_00"])
            self.assertTrue(loaded.step_completed.get(PipelineStep.TRANSCRIPTION))

    def test_pack_folder_import(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            pack_dir = Path(tmp_dir) / "Exported_Pack"
            pack_dir.mkdir()

            # Write _pack_info.ini
            ini_content = (
                "[data]\n"
                'title="Epic Quest Voicer"\n'
                'icon="001_Arthur.png"\n'
                'authors=["StudioX", "DubTeam"]\n'
            )
            (pack_dir / "_pack_info.ini").write_text(ini_content, encoding="utf-8")

            # Write 001_Arthur.txt
            txt1 = (
                "[data]\n"
                'caption="Excalibur, awaken!"\n'
                'image="001_Arthur.png"\n'
                'dub_timestamps=[1.250, 3.500]\n'
                'dub_characters=["Arthur"]\n'
            )
            (pack_dir / "001_Arthur.txt").write_text(txt1, encoding="utf-8")
            (pack_dir / "001_Arthur.mp3").write_bytes(b"mock_mp3_data")
            (pack_dir / "001_Arthur.png").write_bytes(b"mock_png_data")

            # Write 002_Merlin.txt
            txt2 = (
                "[data]\n"
                'caption="Use the magic now."\n'
                'image="002_Merlin.png"\n'
                'dub_timestamps=[4.100]\n'
                'dub_characters=["Merlin", "Arthur"]\n'
            )
            (pack_dir / "002_Merlin.txt").write_text(txt2, encoding="utf-8")
            (pack_dir / "002_Merlin.mp3").write_bytes(b"mock_mp3_data_2")

            # Import pack folder
            state = ProjectManager.load_from_pack_folder(pack_dir)

            self.assertEqual(state.pack_info.title, "Epic Quest Voicer")
            self.assertEqual(state.pack_info.authors, ["StudioX", "DubTeam"])
            self.assertEqual(len(state.dialogues), 2)

            d1 = state.dialogues[0]
            self.assertEqual(d1.index, 1)
            self.assertEqual(d1.caption, "Excalibur, awaken!")
            self.assertEqual(d1.start, 1.250)
            self.assertEqual(d1.end, 3.500)
            self.assertEqual(d1.audio_path.name, "001_Arthur.mp3")
            self.assertEqual(d1.image_path.name, "001_Arthur.png")

            d2 = state.dialogues[1]
            self.assertEqual(d2.index, 2)
            self.assertEqual(d2.caption, "Use the magic now.")
            self.assertEqual(d2.start, 4.100)
            self.assertGreater(d2.end, 4.100)
            self.assertIn("Arthur", d2.extra_speakers)

            # Check speaker reconstruction
            spk_arthur = state.get_speaker(d1.speaker_id)
            self.assertEqual(spk_arthur.display_name, "Arthur")
            spk_merlin = state.get_speaker(d2.speaker_id)
            self.assertEqual(spk_merlin.display_name, "Merlin")

    def test_auto_save(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            proj_file = tmp_path / "MyShow.voicer"

            state = PipelineState()
            state.pack_info.title = "AutoSave Show"
            state.dialogues.append(DialogueItem(index=1, speaker_id="SPEAKER_00", start=0.0, end=1.0, caption="Test"))

            # Auto save with project path
            as_path = ProjectManager.auto_save(state, current_project_path=proj_file)
            self.assertIsNotNone(as_path)
            self.assertEqual(as_path.name, "MyShow.autosave.voicer")
            self.assertTrue(as_path.exists())

            # Check that repeated autosave on the autosave file does NOT cascade into .autosave.autosave
            as_path2 = ProjectManager.auto_save(state, current_project_path=as_path)
            self.assertEqual(as_path2.name, "MyShow.autosave.voicer")

            # Check delete_autosave
            ProjectManager.delete_autosave(proj_file)
            self.assertFalse(as_path.exists(), "Autosave file should have been deleted")

    def test_pack_import_preserves_escaped_metadata(self):
        """Cue cards produced by PackBuilder must round-trip quotes and backslashes."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            pack_dir = Path(tmp_dir) / "Escaped_Pack"
            pack_dir.mkdir()
            (pack_dir / "_pack_info.ini").write_text(
                '[data]\n'
                'title="A \\"quoted\\" pack"\n'
                'authors=["Studio \\"A\\"", "Path\\\\Team"]\n',
                encoding="utf-8",
            )
            (pack_dir / "001_Hero.txt").write_text(
                '[data]\n'
                'caption="He said: \\"hello\\" from C:\\\\audio"\n'
                'image="001_Hero.png"\n'
                'dub_timestamps=[1.000, 2.000]\n'
                'dub_characters=["Hero \\"One\\"", "Path\\\\Team"]\n',
                encoding="utf-8",
            )

            state = ProjectManager.load_from_pack_folder(pack_dir)
            self.assertEqual(state.pack_info.title, 'A "quoted" pack')
            self.assertEqual(state.pack_info.authors, ['Studio "A"', 'Path\\Team'])
            self.assertEqual(state.dialogues[0].caption, 'He said: "hello" from C:\\audio')
            self.assertEqual(state.get_speaker(state.dialogues[0].speaker_id).display_name, 'Hero "One"')
            self.assertEqual(state.dialogues[0].extra_speakers, ['Path\\Team'])


if __name__ == "__main__":
    unittest.main()
