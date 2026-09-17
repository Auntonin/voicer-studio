"""
main.py
=======
Voicer Studio — Application entry point.
Features:
- Professional Adobe-minimalist Splash Screen
- Smooth progressive subsystem loading
- System dependency verification
- Native Windows dark theming & taskbar icon setup
"""

import sys
import os
import time
from pathlib import Path

# ── Ensure project root is in sys.path ────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── PySide6 imports ───────────────────────────────────────────────────────────
try:
    from PySide6.QtWidgets import QApplication, QSplashScreen, QMessageBox, QWidget
    from PySide6.QtCore import Qt, QTimer, QRectF
    from PySide6.QtGui import QIcon, QPixmap, QFont, QPainter, QColor, QLinearGradient, QPen
except ImportError:
    print("[ERROR] PySide6 is not installed.")
    print("        Run VoicerStudio.exe or setup.bat first.")
    sys.exit(1)

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    import traceback
    err_text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    try:
        (PROJECT_ROOT / "crash.log").write_text(err_text, encoding="utf-8")
    except Exception:
        pass

sys.excepthook = handle_exception

# ── App config ────────────────────────────────────────────────────────────────
from config import APP_NAME, APP_VERSION, COLORS, WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT


class StudioSplashScreen(QSplashScreen):
    """
    Adobe / DaVinci Resolve inspired minimalist studio splash screen.
    Features dark obsidian matte aesthetic, app brand icon, dynamic status text,
    and a slim accent progress line.
    """

    def __init__(self, icon_pixmap: QPixmap | None = None):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        
        self._w = 620
        self._h = 350
        self._progress_pct = 10
        self._status_text = "Initializing Studio Engine..."
        self._icon_pixmap = icon_pixmap

        self.resize(self._w, self._h)

    def set_stage(self, pct: int, text: str):
        """Update loading stage progress percentage and message."""
        self._progress_pct = max(0, min(100, pct))
        self._status_text = text
        self.update()
        QApplication.processEvents()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self._w, self._h
        radius = 10.0

        # Background card (Matte Obsidian)
        card_rect = QRectF(1.0, 1.0, w - 2.0, h - 2.0)
        painter.setBrush(QColor(20, 21, 25))
        painter.setPen(QPen(QColor(42, 45, 54), 1.5))
        painter.drawRoundedRect(card_rect, radius, radius)

        # Subtle top edge highlight line
        painter.setPen(QPen(QColor(60, 65, 78, 120), 1.0))
        painter.drawLine(int(radius + 4), 2, int(w - radius - 4), 2)

        # App Icon on the left
        icon_x, icon_y = 48, 52
        if self._icon_pixmap and not self._icon_pixmap.isNull():
            scaled_icon = self._icon_pixmap.scaled(
                74, 74,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            painter.drawPixmap(icon_x, icon_y, scaled_icon)
        else:
            # Fallback monogram badge
            painter.setBrush(QColor(26, 29, 36))
            painter.setPen(QPen(QColor(20, 115, 230), 1.5))
            painter.drawRoundedRect(icon_x, icon_y, 74, 74, 8, 8)
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
            painter.drawText(icon_x, icon_y, 74, 74, Qt.AlignmentFlag.AlignCenter, "Vs")

        # Studio Typography
        text_x = icon_x + 92

        # Title: VOICER STUDIO
        painter.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(text_x, icon_y + 30, "VOICER STUDIO")

        # Subtitle / Category
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        painter.setPen(QColor(140, 148, 164))
        painter.drawText(text_x, icon_y + 54, "DIALOGUE EXTRACTION & AUDIO SEPARATION SUITE")

        # Middle descriptive feature labels
        feature_y = icon_y + 104
        painter.setFont(QFont("Segoe UI", 9))
        painter.setPen(QColor(105, 112, 128))
        painter.drawText(icon_x, feature_y, "Studio Engine  •  BS-RoFormer Vocal Isolation  •  Faster-Whisper Subtitles")
        painter.drawText(icon_x, feature_y + 20, "Automated Dialogue Cut & The Choice Voicer Pack Generator")

        # Bottom Area
        bottom_y = h - 42

        # Dynamic Status Text (Left)
        painter.setFont(QFont("Segoe UI", 9))
        painter.setPen(QColor(165, 172, 188))
        painter.drawText(icon_x, bottom_y, self._status_text)

        # Version & Platform info (Right)
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor(95, 102, 118))
        ver_text = f"v{APP_VERSION} (64-bit)  ·  2026 Studio Release"
        painter.drawText(w - icon_x - 220, bottom_y, 220, 20, Qt.AlignmentFlag.AlignRight, ver_text)

        # Slim Accent Progress Line (Bottom)
        bar_height = 2.5
        bar_y = h - 6
        bar_width = w - (icon_x * 2)

        # Background track
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(32, 35, 44))
        painter.drawRoundedRect(QRectF(icon_x, bar_y, bar_width, bar_height), 1.0, 1.0)

        # Active progress fill
        fill_width = bar_width * (self._progress_pct / 100.0)
        if fill_width > 0:
            grad = QLinearGradient(icon_x, 0, icon_x + fill_width, 0)
            grad.setColorAt(0.0, QColor(20, 115, 230))    # Electric Blue
            grad.setColorAt(1.0, QColor(0, 210, 255))     # Bright Cyan
            painter.setBrush(grad)
            painter.drawRoundedRect(QRectF(icon_x, bar_y, fill_width, bar_height), 1.0, 1.0)

        painter.end()


def check_ffmpeg() -> bool:
    """Check if ffmpeg is available in PATH."""
    import subprocess
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def main():
    # ── Windows Taskbar & Shell App ID ──────────────────────────────────────────
    # Explicit AppUserModelID decouples the process from generic python.exe,
    # ensuring the Windows taskbar displays the official studio app icon.
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TheChoiceVoicer.VoicerStudio.1.1.0")
        except Exception:
            pass

    # Enable high-DPI scaling
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("TheChoiceVoicer")

    # Load application icon (prefer .ico with full multi-resolution mipmaps)
    ico_path = PROJECT_ROOT / "assets" / "app_icon.ico"
    png_path = PROJECT_ROOT / "assets" / "app_icon.png"
    app_icon = QIcon()
    if ico_path.exists():
        app_icon = QIcon(str(ico_path))
    elif png_path.exists():
        app_icon = QIcon(str(png_path))

    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    icon_pixmap = None
    if png_path.exists():
        icon_pixmap = QPixmap(str(png_path))
    elif ico_path.exists():
        icon_pixmap = QPixmap(str(ico_path))

    # App-wide font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    # ── Modern Adobe-Style Splash Screen ───────────────────────────────────────
    splash = StudioSplashScreen(icon_pixmap)
    splash.show()
    splash.set_stage(20, "Initializing Core Audio Processing Engine...")
    app.processEvents()
    time.sleep(0.1)

    # ── Dependency check ───────────────────────────────────────────────────────
    splash.set_stage(45, "Verifying FFmpeg & Hardware Codecs...")
    app.processEvents()

    if not check_ffmpeg():
        splash.hide()
        QMessageBox.critical(
            None,
            "FFmpeg Required",
            "FFmpeg is required for audio/video extraction but was not found in PATH.\n\n"
            "Please install FFmpeg via winget:\n"
            "  winget install Gyan.FFmpeg\n\n"
            "Then restart Voicer Studio.",
        )
        sys.exit(1)

    # ── Neural models & environment ───────────────────────────────────────────
    splash.set_stage(70, "Loading BS-RoFormer & Speech Recognition Pipelines...")
    app.processEvents()
    time.sleep(0.08)

    # ── Import & create main window ────────────────────────────────────────────
    splash.set_stage(90, "Constructing Studio Workspace...")
    app.processEvents()

    from gui.main_window import MainWindow

    window = MainWindow()
    window.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

    splash.set_stage(100, "Starting Workspace...")
    app.processEvents()
    time.sleep(0.05)

    window.showMaximized()

    # Smooth handoff to main window
    splash.finish(window)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
