import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.models import PipelineState, DialogueItem, SpeakerInfo
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

if __name__ == "__main__":
    test_core()
