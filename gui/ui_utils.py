"""
gui/ui_utils.py
===============
Shared UI utilities and theming helpers for Voicer Studio.
"""

import sys
import ctypes
from PySide6.QtWidgets import QWidget


def apply_dark_title_bar(widget: QWidget):
    """
    Apply Windows 10/11 immersive dark mode (DWMWA_USE_IMMERSIVE_DARK_MODE)
    to any native window or floating dialog title bar.
    """
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 = 19
        value = ctypes.c_int(1)
        res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(value), ctypes.sizeof(value)
        )
        if res != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1,
                ctypes.byref(value), ctypes.sizeof(value)
            )
    except Exception:
        pass
