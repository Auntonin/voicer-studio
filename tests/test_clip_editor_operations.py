"""
tests/test_clip_editor_operations.py
====================================
Unit tests for smart Merge Next (same character track scope) and
smart Split Clip (playhead position priority & smart caption splitting).
"""

import unittest
from core.models import PipelineState, DialogueItem, SpeakerInfo
try:
    from gui.main_window import MainWindow
    from PySide6.QtWidgets import QApplication
    _gui_available = True
except ImportError:
    _gui_available = False

app = QApplication.instance() or QApplication([]) if _gui_available else None


@unittest.skipIf(not _gui_available, "GUI not available")
class TestClipEditorOperations(unittest.TestCase):

    def setUp(self):
        self.state = PipelineState()
        self.state.speakers["SPEAKER_00"] = SpeakerInfo("SPEAKER_00", "p1")
        self.state.speakers["SPEAKER_01"] = SpeakerInfo("SPEAKER_01", "All Might")

        # Track A5 (p1): clips #1 (0-2s), #2 (4-6s)
        # Track A6 (All Might): clip #3 (2.5-3.5s)
        self.item1 = DialogueItem(index=1, speaker_id="SPEAKER_00", start=0.0, end=2.0, caption="Hello world")
        self.item3 = DialogueItem(index=3, speaker_id="SPEAKER_01", start=2.5, end=3.5, caption="All Might speak")
        self.item2 = DialogueItem(index=2, speaker_id="SPEAKER_00", start=4.0, end=6.0, caption="Second line p1")

        self.state.dialogues = [self.item1, self.item3, self.item2]
        self.state.video_duration = 60.0
        self.window = MainWindow()
        self.window._state = self.state
        self.window._timeline.duration = 60.0

    def test_merge_next_same_speaker_only(self):
        """Merge Next on clip #1 (p1) must skip clip #3 (All Might) and merge with clip #2 (p1)."""
        self.window._on_merge_next(1)
        active = self.window._state.active_dialogues()
        self.assertEqual(len(active), 2)
        
        # First active dialogue should now span from 0.0 to 6.0 and combine captions
        merged_item = active[0]
        self.assertEqual(merged_item.speaker_id, "SPEAKER_00")
        self.assertEqual(merged_item.start, 0.0)
        self.assertEqual(merged_item.end, 6.0)
        self.assertEqual(merged_item.caption, "Hello world Second line p1")

        # Clip #3 (All Might) must remain completely untouched!
        all_might_item = active[1]
        self.assertEqual(all_might_item.speaker_id, "SPEAKER_01")
        self.assertEqual(all_might_item.start, 2.5)

    def test_split_at_playhead_inside_clip(self):
        """Split Clip with playhead at 1.0s inside clip #1 (0-2s) must cut at 1.0s and split words."""
        self.window._timeline.current_time = 1.0
        self.window._on_split(1)
        active = self.window._state.active_dialogues()
        self.assertEqual(len(active), 4)

        # Clip #1 should now be 0.0 - 1.0s with "Hello"
        first = active[0]
        self.assertEqual(first.start, 0.0)
        self.assertEqual(first.end, 1.0)
        self.assertEqual(first.caption, "Hello")

        # Newly split clip should be 1.0 - 2.0s with "world"
        second = [d for d in active if d.start == 1.0][0]
        self.assertEqual(second.end, 2.0)
        self.assertEqual(second.caption, "world")
        self.assertEqual(second.speaker_id, "SPEAKER_00")

    def test_split_at_midpoint_when_playhead_outside(self):
        """Split Clip with playhead at 10.0s (outside clip #1 0-2s) must fall back to 50% midpoint (1.0s)."""
        self.window._timeline.current_time = 10.0
        self.window._on_split(1)
        active = self.window._state.active_dialogues()
        self.assertEqual(len(active), 4)

        first = active[0]
        self.assertEqual(first.start, 0.0)
        self.assertEqual(first.end, 1.0)

    def test_add_clip_defaults_to_top_track(self):
        """Add Clip without hover defaults to top layer track (SPEAKER_00) at playhead time."""
        self.window._timeline.populate(self.state)
        self.window._timeline.current_time = 7.5
        self.window._on_add_clip()
        
        active = self.window._state.active_dialogues()
        self.assertEqual(len(active), 4)
        new_clip = active[-1]
        self.assertEqual(new_clip.speaker_id, "SPEAKER_00")
        self.assertEqual(new_clip.start, 7.5)
        self.assertEqual(new_clip.end, 9.0)

    def test_add_clip_at_specific_track_and_time(self):
        """Add Clip with specific track/time places clip exactly at requested speaker track and timestamp."""
        self.window._timeline.populate(self.state)
        self.window._on_add_clip_at(spk_id="SPEAKER_01", t=12.0)
        
        active = self.window._state.active_dialogues()
        self.assertEqual(len(active), 4)
        new_clip = active[-1]
        self.assertEqual(new_clip.speaker_id, "SPEAKER_01")
        self.assertEqual(new_clip.start, 12.0)
        self.assertEqual(new_clip.end, 13.5)


if __name__ == "__main__":
    unittest.main()

