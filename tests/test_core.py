import sys
import tempfile
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.models import PipelineState, DialogueItem, SpeakerInfo, PipelineStep
from core.pack_builder import PackBuilder
from core.quality_checker import QualityChecker

def test_core():
    print("Testing core modules...")
    state = PipelineState()
    state.video_duration = 10.0
    
    # Mock data
    spk = "SPEAKER_00"
    state.speakers[spk] = SpeakerInfo(speaker_id=spk, display_name="Weazemon")
    
    item = DialogueItem(index=1, speaker_id=spk, start=2.049, end=4.200, caption="Hello world")
    item.image_path = Path("001_Weazemon.png")
    state.dialogues.append(item)
    
    # Test PackBuilder
    pb = PackBuilder()
    txt = pb.build_txt(item, state, 'start_only')
    print("Generated TXT:")
    print(txt)
    
    assert "[data]" in txt
    assert 'caption="Hello world"' in txt
    assert 'image="001_Weazemon.png"' in txt
    assert "dub_timestamps=[2.049]" in txt
    assert 'dub_characters=["Weazemon"]' in txt
    
    # Test QualityChecker
    qc = QualityChecker()
    # Mock a non-existent pack dir
    pack_dir = Path("mock_pack_dir")
    results = qc.check_all(state, pack_dir)
    print("\nQuality Checks (Expected errors since no files exist):")
    print(qc.summary(results))
    
    print("\nTests complete!")


def test_pipeline_invalidation_keeps_expensive_analysis_cache():
    state = PipelineState()
    state.step_completed = {
        PipelineStep.AUDIO_EXTRACT: True,
        PipelineStep.VAD: True,
        PipelineStep.TRANSCRIPTION: True,
        PipelineStep.PACK_BUILD: True,
        PipelineStep.VALIDATION: True,
    }
    state.current_step = PipelineStep.DONE
    state.invalidate_from(PipelineStep.PACK_BUILD)
    assert state.is_step_done(PipelineStep.AUDIO_EXTRACT)
    assert state.is_step_done(PipelineStep.TRANSCRIPTION)
    assert not state.is_step_done(PipelineStep.PACK_BUILD)
    assert not state.is_step_done(PipelineStep.VALIDATION)
    assert state.current_step == PipelineStep.IDLE

    state.step_completed[PipelineStep.CLIP_GENERATION] = True
    state.step_completed[PipelineStep.FRAME_EXTRACTION] = True
    state.invalidate_from(PipelineStep.CLIP_GENERATION)
    assert not state.is_step_done(PipelineStep.CLIP_GENERATION)
    assert not state.is_step_done(PipelineStep.FRAME_EXTRACTION)


def test_zip_export_is_atomic_on_failure():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        pack_dir = tmp_path / "pack"
        pack_dir.mkdir()
        (pack_dir / "clip.txt").write_text("first", encoding="utf-8")
        zip_path = tmp_path / "pack.zip"
        PackBuilder.export_zip(pack_dir, zip_path)

        (pack_dir / "clip.txt").write_text("updated", encoding="utf-8")
        try:
            PackBuilder.export_zip(pack_dir, zip_path, progress_cb=lambda *_: (_ for _ in ()).throw(RuntimeError("cancel")))
        except RuntimeError:
            pass
        else:
            raise AssertionError("The progress callback should have interrupted export")

        assert not (tmp_path / ".pack.zip.part").exists()
        with zipfile.ZipFile(zip_path) as archive:
            assert archive.read("pack/clip.txt") == b"first"

if __name__ == "__main__":
    test_core()
    test_pipeline_invalidation_keeps_expensive_analysis_cache()
    test_zip_export_is_atomic_on_failure()
