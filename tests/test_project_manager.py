import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import PipelineState, DialogueItem, SpeakerInfo, PackInfo, PipelineStep
from core.project_manager import ProjectManager

def test_project_save_and_load():
    print("Testing ProjectManager save and load...")
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
        assert ok, "save_project returned False"
        assert proj_file.exists(), "Project file was not created"

        # Load project
        loaded = ProjectManager.load_project(proj_file)
        assert loaded.pack_info.title == "Test Anime Pack"
        assert loaded.pack_info.authors == ["AuthorA", "AuthorB"]
        assert len(loaded.speakers) == 2
        assert loaded.speakers["SPEAKER_00"].display_name == "Hero"
        assert loaded.speakers["SPEAKER_01"].display_name == "Villain"
        assert loaded.speaker_order == ["SPEAKER_00", "SPEAKER_01"]
        assert len(loaded.dialogues) == 2
        assert loaded.dialogues[0].caption == "I will protect everyone!"
        assert loaded.dialogues[1].extra_speakers == ["SPEAKER_00"]
        assert loaded.step_completed.get(PipelineStep.TRANSCRIPTION) is True

        print("-> Project save and load PASSED.")

def test_pack_folder_import():
    print("Testing ProjectManager load_from_pack_folder...")
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

        assert state.pack_info.title == "Epic Quest Voicer"
        assert state.pack_info.authors == ["StudioX", "DubTeam"]
        assert len(state.dialogues) == 2

        d1 = state.dialogues[0]
        assert d1.index == 1
        assert d1.caption == "Excalibur, awaken!"
        assert d1.start == 1.250
        assert d1.end == 3.500
        assert d1.audio_path.name == "001_Arthur.mp3"
        assert d1.image_path.name == "001_Arthur.png"

        d2 = state.dialogues[1]
        assert d2.index == 2
        assert d2.caption == "Use the magic now."
        assert d2.start == 4.100
        assert d2.end > 4.100
        assert "Arthur" in d2.extra_speakers

        # Check speaker reconstruction
        spk_arthur = state.get_speaker(d1.speaker_id)
        assert spk_arthur.display_name == "Arthur"
        spk_merlin = state.get_speaker(d2.speaker_id)
        assert spk_merlin.display_name == "Merlin"

        print("-> Pack folder import PASSED.")

def test_auto_save():
    print("Testing ProjectManager auto_save...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        proj_file = tmp_path / "MyShow.voicer"

        state = PipelineState()
        state.pack_info.title = "AutoSave Show"
        state.dialogues.append(DialogueItem(index=1, speaker_id="SPEAKER_00", start=0.0, end=1.0, caption="Test"))

        # Auto save with project path
        as_path = ProjectManager.auto_save(state, current_project_path=proj_file)
        assert as_path is not None
        assert as_path.name == "MyShow.autosave.voicer"
        assert as_path.exists()

        # Check that repeated autosave on the autosave file does NOT cascade into .autosave.autosave
        as_path2 = ProjectManager.auto_save(state, current_project_path=as_path)
        assert as_path2.name == "MyShow.autosave.voicer", f"Expected MyShow.autosave.voicer, got {as_path2.name}"

        # Check delete_autosave
        ProjectManager.delete_autosave(proj_file)
        assert not as_path.exists(), "Autosave file should have been deleted"

        print("-> Auto save PASSED.")

if __name__ == "__main__":
    test_project_save_and_load()
    test_pack_folder_import()
    test_auto_save()
    print("\nALL PROJECT MANAGER TESTS PASSED SUCCESSFULLY!")

