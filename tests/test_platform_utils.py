"""
tests/test_platform_utils.py
============================
Unit tests for core/platform_utils.py cross-platform OS abstraction layer.
"""

import sys
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

from core.platform_utils import (
    platform_utils,
    is_windows,
    is_macos,
    is_linux,
    format_shortcut,
    is_primary_modifier,
    is_secondary_modifier,
    get_default_font_family,
    get_thai_font_family,
    get_appdata_dir,
    get_short_path,
)


class TestPlatformUtils(unittest.TestCase):

    def test_platform_detection(self):
        """Verify OS detection flags reflect current system."""
        if sys.platform == "win32":
            self.assertTrue(is_windows())
            self.assertFalse(is_macos())
            self.assertFalse(is_linux())
        elif sys.platform == "darwin":
            self.assertFalse(is_windows())
            self.assertTrue(is_macos())
            self.assertFalse(is_linux())
        elif sys.platform.startswith("linux"):
            self.assertFalse(is_windows())
            self.assertFalse(is_macos())
            self.assertTrue(is_linux())

    def test_format_shortcut_macos(self):
        """Verify shortcut string formatting translates to macOS symbols."""
        with patch("core.platform_utils.IS_MACOS", True):
            self.assertEqual(format_shortcut("Ctrl+Z"), "⌘Z")
            self.assertEqual(format_shortcut("Ctrl + Wheel"), "⌘ + Wheel")
            self.assertEqual(format_shortcut("Ctrl+Shift+Z"), "⌘⇧Z")
            self.assertEqual(format_shortcut("Ctrl+Alt+S"), "⌘⌥S")
            self.assertEqual(format_shortcut("Cmd+N"), "⌘N")
            self.assertEqual(format_shortcut("Option + Drag"), "⌥ + Drag")
            self.assertEqual(format_shortcut("Backspace"), "⌫")
            self.assertEqual(format_shortcut("Delete"), "⌫ Delete")

    def test_format_shortcut_windows_linux(self):
        """Verify Windows / Linux shortcuts remain untranslated."""
        with patch("core.platform_utils.IS_MACOS", False):
            self.assertEqual(format_shortcut("Ctrl+Z"), "Ctrl+Z")
            self.assertEqual(format_shortcut("Ctrl+Shift+Z"), "Ctrl+Shift+Z")
            self.assertEqual(format_shortcut("Alt + Drag"), "Alt + Drag")

    def test_primary_modifier_detection(self):
        """Test primary modifier recognition across platforms."""
        class MockModifier:
            ControlModifier = 0x04000000
            MetaModifier = 0x10000000
            AltModifier = 0x08000000
            ShiftModifier = 0x02000000

        mock_module = MagicMock()
        mock_module.Qt = MagicMock()
        mock_module.Qt.KeyboardModifier = MockModifier

        with patch.dict("sys.modules", {"PySide6": MagicMock(), "PySide6.QtCore": mock_module}):
            # Windows / Linux: ControlModifier
            with patch("core.platform_utils.IS_MACOS", False):
                self.assertTrue(is_primary_modifier(MockModifier.ControlModifier))
                self.assertFalse(is_primary_modifier(MockModifier.AltModifier))
                self.assertFalse(is_primary_modifier(MockModifier.ShiftModifier))

            # macOS: ControlModifier (Cmd in Qt) and MetaModifier (external key)
            with patch("core.platform_utils.IS_MACOS", True):
                self.assertTrue(is_primary_modifier(MockModifier.ControlModifier))
                self.assertTrue(is_primary_modifier(MockModifier.MetaModifier))
                self.assertFalse(is_primary_modifier(MockModifier.ShiftModifier))

    def test_secondary_modifier_detection(self):
        """Test secondary modifier (Alt / Option)."""
        class MockModifier:
            ControlModifier = 0x04000000
            MetaModifier = 0x10000000
            AltModifier = 0x08000000

        mock_module = MagicMock()
        mock_module.Qt = MagicMock()
        mock_module.Qt.KeyboardModifier = MockModifier

        with patch.dict("sys.modules", {"PySide6": MagicMock(), "PySide6.QtCore": mock_module}):
            self.assertTrue(is_secondary_modifier(MockModifier.AltModifier))
            self.assertFalse(is_secondary_modifier(MockModifier.ControlModifier))

    def test_font_family_resolution(self):
        """Ensure standard UI fonts are defined for all OSes."""
        with patch("core.platform_utils.IS_WINDOWS", True), patch("core.platform_utils.IS_MACOS", False):
            self.assertEqual(get_default_font_family(), "Segoe UI")
            self.assertEqual(get_thai_font_family(), "Leelawadee UI")

        with patch("core.platform_utils.IS_WINDOWS", False), patch("core.platform_utils.IS_MACOS", True):
            self.assertEqual(get_default_font_family(), ".AppleSystemUIFont")
            self.assertEqual(get_thai_font_family(), "Thonburi")

        with patch("core.platform_utils.IS_WINDOWS", False), patch("core.platform_utils.IS_MACOS", False):
            self.assertEqual(get_default_font_family(), "Ubuntu")
            self.assertEqual(get_thai_font_family(), "Noto Sans Thai")

    def test_appdata_dir_resolution(self):
        """Ensure application data directory returns a valid Path."""
        appdata = get_appdata_dir()
        self.assertIsInstance(appdata, Path)
        self.assertTrue(appdata.exists())

    def test_short_path_posix(self):
        """Ensure short path returns unchanged path on POSIX."""
        with patch("core.platform_utils.IS_WINDOWS", False):
            path_str = "/User/test/วิดีโอ/sample.mp4"
            self.assertEqual(get_short_path(path_str), path_str)


if __name__ == "__main__":
    unittest.main()
