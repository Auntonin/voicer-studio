"""
tests/test_media_playback.py
=============================
Automated test suite for VideoPanel and Timeline media playback & audio synchronization.
"""

import sys
import unittest
from pathlib import Path

# Add project root to sys.path for direct test execution
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QUrl

from core.models import PipelineState, DialogueItem
from gui.video_panel import VideoPanel
from gui.timeline_widget import TimelineWidget


class TestMediaPlayback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if not cls.app:
            cls.app = QApplication(sys.argv)

    def test_video_panel_audio_initialization(self):
        panel = VideoPanel()
        self.assertIsNotNone(panel.audio_output)
        self.assertEqual(panel.audio_output.volume(), 1.0)
        self.assertFalse(panel.audio_output.isMuted())
        self.assertEqual(panel._volume, 1.0)
        self.assertFalse(panel._is_muted)
        self.assertTrue(hasattr(panel, "btn_volume"))
        self.assertTrue(hasattr(panel, "slider_volume"))
        self.assertEqual(panel.slider_volume.value(), 100)

    def test_video_panel_volume_and_mute(self):
        panel = VideoPanel()
        
        # Test slider change
        panel.slider_volume.setValue(50)
        self.assertEqual(panel._volume, 0.5)
        self.assertEqual(panel.audio_output.volume(), 0.5)
        self.assertFalse(panel._is_muted)
        self.assertFalse(panel.btn_volume.icon().isNull())

        # Test mute toggle
        panel.toggle_mute()
        self.assertTrue(panel._is_muted)
        self.assertTrue(panel.audio_output.isMuted())
        self.assertEqual(panel.btn_volume.toolTip(), "Unmute")

        # Test unmute toggle
        panel.toggle_mute()
        self.assertFalse(panel._is_muted)
        self.assertFalse(panel.audio_output.isMuted())
        self.assertIn("Volume: 50%", panel.btn_volume.toolTip())

        # Test setting volume to 0
        panel.slider_volume.setValue(0)
        self.assertEqual(panel._volume, 0.0)
        self.assertEqual(panel.btn_volume.toolTip(), "Unmute")

    def test_timeline_set_playhead_time(self):
        timeline = TimelineWidget()
        timeline.set_duration(60.0)

        received_ticks = []
        timeline.playhead_tick.connect(lambda t: received_ticks.append(t))

        timeline.set_playhead_time(12.5)
        self.assertEqual(timeline.current_time, 12.5)
        self.assertIn(12.5, received_ticks)

        timeline.set_playhead_time(75.0)  # Beyond duration
        self.assertEqual(timeline.current_time, 60.0)

    def test_video_panel_seeking_and_timecode(self):
        panel = VideoPanel()
        panel._update_time_code(65432, 120000)
        self.assertEqual(panel.lbl_time_code.text(), "01:05.432 / 02:00.000")

        panel.set_position(15.0)
        panel._update_time_code(15000, 120000)
        self.assertEqual(panel.lbl_time_code.text(), "00:15.000 / 02:00.000")

    def test_timeline_unified_playback(self):
        timeline = TimelineWidget()
        timeline.set_duration(60.0)

        # Ensure timeline does not create duplicate audio players
        self.assertFalse(hasattr(timeline, "audio_output"))

        # Test toggle_playback signal emission
        toggle_called = []
        timeline.playback_toggle_requested.connect(lambda: toggle_called.append(True))
        timeline.toggle_playback()
        self.assertTrue(len(toggle_called) > 0)

        # Test start and stop playback state
        timeline.start_playback()
        self.assertTrue(timeline._is_playing)
        timeline.stop_playback()
        self.assertFalse(timeline._is_playing)

    def test_video_panel_play_timer(self):
        panel = VideoPanel()
        self.assertTrue(hasattr(panel, "play_timer"))
        self.assertEqual(panel.play_timer.interval(), 25)
        self.assertFalse(panel.play_timer.isActive())


if __name__ == "__main__":
    unittest.main()

