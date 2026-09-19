"""
gui/main_window.py
==================
Main application window — Adobe-minimal NLE interface.
"""

from __future__ import annotations

import sys
import json
import ctypes
import subprocess
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QLabel, QPushButton, QToolBar, QStatusBar,
    QFileDialog, QFrame, QSizePolicy, QTextEdit, QPlainTextEdit, QLineEdit,
    QProgressBar, QApplication, QTabWidget, QMenuBar, QMenu,
    QMessageBox, QCheckBox, QGraphicsOpacityEffect, QScrollArea, QInputDialog,
    QToolTip
)
from PySide6.QtCore import Qt, QSize, QTimer, QPropertyAnimation, QEvent
from PySide6.QtGui import QAction, QIcon, QColor, QFont, QPalette, QKeySequence, QShortcut

from config import (
    APP_NAME, APP_VERSION, COLORS, SETTINGS_FILE,
    WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT, WHISPER_MODEL_DEFAULT, ASSETS_DIR
)
from core.models import PipelineState, PipelineStep, UndoManager, SpeakerInfo, DialogueItem, PackInfo
from core.project_manager import ProjectManager, PROJECT_FILE_EXTENSION
from core.pipeline import PipelineWorker, ExportWorker, build_options_from_settings
from core.i18n import i18n, tr
from gui.dialogue_table import DialogueTable
from gui.clip_editor import ClipEditor
from gui.timeline_widget import TimelineWidget
from gui.speaker_panel import SpeakerPanel
from gui.progress_panel import ProgressPanel
from gui.pack_info_panel import PackInfoPanel
from gui.settings_dialog import SettingsDialog
from gui.preview_dialog import PreviewDialog
from gui.video_panel import VideoPanel
from gui.ui_utils import apply_dark_title_bar


class MainWindow(QMainWindow):
    """
    Top-level application window — fully connected to pipeline, timeline, and video player.
    """

    def showEvent(self, event):
        super().showEvent(event)
        apply_dark_title_bar(self)

    def _apply_dark_title_bar(self):
        apply_dark_title_bar(self)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.setStyleSheet(self._build_stylesheet())
        self.setAcceptDrops(True)

        tip_pal = QToolTip.palette()
        tip_pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#18181b"))
        tip_pal.setColor(QPalette.ColorRole.ToolTipText, QColor("#e4e4e7"))
        QToolTip.setPalette(tip_pal)

        ico_path = Path(__file__).resolve().parent.parent / "assets" / "app_icon.ico"
        png_path = Path(__file__).resolve().parent.parent / "assets" / "app_icon.png"
        if ico_path.exists():
            self.setWindowIcon(QIcon(str(ico_path)))
        elif png_path.exists():
            self.setWindowIcon(QIcon(str(png_path)))

        self._state = PipelineState()
        self._undo_manager = UndoManager()
        self._active_speaker_id: str = "SPEAKER_00"
        
        self._worker: PipelineWorker | None = None
        self._export_worker: ExportWorker | None = None
        self._settings: dict = self._load_settings()
        # Initialize UI language (defaults to 100% English)
        app_lang = self._settings.get("app_language", "en")
        i18n.set_language(app_lang)
        self._output_dir: Path | None = None
        self._current_project_path: Path | None = None
        self._is_dirty: bool = False
        self._last_saved_time: str | None = None

        # Background Auto-Save timer (checks dirty flag every 30 seconds)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(30000)
        self._autosave_timer.timeout.connect(self._on_autosave_timer_tick)
        self._autosave_timer.start()

        self._build_menubar()
        self._build_toolbar()
        self._build_central()
        self._build_statusbar()
        self._update_toolbar_state()
        
        # Global '?' shortcut to open Keyboard Shortcuts cheat sheet
        self._sc_shortcuts = QShortcut(QKeySequence("?"), self)
        self._sc_shortcuts.activated.connect(self._show_shortcuts_dialog)

        self._apply_dark_title_bar()

        # Install global studio application event filter for universal Spacebar Play/Pause
        q_app = QApplication.instance()
        if q_app:
            q_app.installEventFilter(self)
        # Professional Bottom-Right Toast Floating Card
        self._toast = QFrame(self)
        self._toast.setObjectName("toast_card")
        self._toast_layout = QHBoxLayout(self._toast)
        self._toast_layout.setContentsMargins(16, 12, 18, 12)
        self._toast_layout.setSpacing(12)

        self._toast_bar = QFrame()
        self._toast_bar.setFixedWidth(4)
        self._toast_bar.setStyleSheet(f"background-color: {COLORS['accent_green']}; border-radius: 2px;")
        self._toast_layout.addWidget(self._toast_bar)

        text_container = QVBoxLayout()
        text_container.setContentsMargins(0, 0, 0, 0)
        text_container.setSpacing(2)

        self._toast_title = QLabel("Dialogue Extraction Completed")
        self._toast_title.setStyleSheet("font-weight: bold; font-size: 10.5pt; color: #ffffff; background: transparent;")

        self._toast_msg = QLabel("All dialogue clips and character packs generated successfully.")
        self._toast_msg.setStyleSheet(f"font-size: 8.5pt; color: {COLORS['text_secondary']}; background: transparent;")

        text_container.addWidget(self._toast_title)
        text_container.addWidget(self._toast_msg)
        self._toast_layout.addLayout(text_container)

        self._toast.setStyleSheet(f"""
            QFrame#toast_card {{
                background-color: #222222;
                border: 1px solid #383838;
                border-radius: 10px;
            }}
        """)
        self._toast.hide()

        self._toast_effect = QGraphicsOpacityEffect(self._toast)
        self._toast.setGraphicsEffect(self._toast_effect)
        self._toast_anim = QPropertyAnimation(self._toast_effect, b"opacity")

    def _apply_dark_title_bar(self):
        """Apply Windows 10/11 immersive dark mode to native window title bar."""
        if sys.platform != "win32":
            return
        try:
            hwnd = int(self.winId())
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

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_dark_title_bar()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_toast') and self._toast and self._toast.isVisible():
            self._position_toast()

    def _position_toast(self):
        self._toast.adjustSize()
        margin_right = 24
        margin_bottom = 36
        x = self.width() - self._toast.width() - margin_right
        y = self.height() - self._toast.height() - margin_bottom
        self._toast.move(max(10, x), max(10, y))

    def _show_toast(self, title: str = "Dialogue Extraction Complete", msg: str = "Pack exported successfully.", level: str = "ok"):
        colors = {
            "ok": COLORS['accent_green'],
            "info": COLORS['accent'],
            "warn": "#f59e0b",
            "error": COLORS['accent_red']
        }
        bar_color = colors.get(level, COLORS['accent'])
        self._toast_bar.setStyleSheet(f"background-color: {bar_color}; border-radius: 2px;")
        self._toast_title.setText(title)
        self._toast_msg.setText(msg)

        self._position_toast()
        self._toast.show()
        self._toast.raise_()

        self._toast_anim.stop()
        self._toast_anim.setDuration(400)
        self._toast_anim.setStartValue(0.0)
        self._toast_anim.setEndValue(1.0)
        self._toast_anim.start()

        QTimer.singleShot(4000, self._hide_toast)

    def _hide_toast(self):
        self._toast_anim.stop()
        self._toast_anim.setDuration(400)
        self._toast_anim.setStartValue(1.0)
        self._toast_anim.setEndValue(0.0)
        try:
            self._toast_anim.finished.disconnect()
        except Exception:
            pass
        self._toast_anim.finished.connect(self._toast.hide)
        self._toast_anim.start()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = Path(urls[0].toLocalFile())
            if path.is_dir():
                if (path / "_pack_info.ini").exists() or any(path.glob("*.txt")):
                    self.load_pack_folder(path)
            elif path.suffix.lower() in {".voicer", ".json"}:
                self.load_project_file(path)
            elif path.suffix.lower() in {".mp4", ".mkv", ".mov", ".webm", ".avi"}:
                self.load_video(path)

    # ── Menu Bar & Toolbar ───────────────────────────────────────────────────

    def _build_menubar(self):
        menubar = self.menuBar()

        # File Menu
        self._menu_file = menubar.addMenu(tr("menu_file"))

        self._act_new_proj = self._menu_file.addAction(tr("menu_new_proj"))
        self._act_new_proj.setShortcut("Ctrl+N")
        self._act_new_proj.triggered.connect(self.on_new_project)

        self._act_open_proj = self._menu_file.addAction(tr("menu_open_proj"))
        self._act_open_proj.setShortcut("Ctrl+O")
        self._act_open_proj.triggered.connect(self.on_open_project)

        self._act_open_pack = self._menu_file.addAction(tr("menu_open_pack"))
        self._act_open_pack.triggered.connect(self.on_open_pack_folder)

        self._menu_recent_projects = self._menu_file.addMenu(tr("menu_recent_proj"))
        self._rebuild_recent_projects_menu()

        self._menu_file.addSeparator()

        self._act_save_proj = self._menu_file.addAction(tr("menu_save_proj"))
        self._act_save_proj.setShortcut("Ctrl+S")
        self._act_save_proj.triggered.connect(self.on_save_project)

        self._act_save_proj_as = self._menu_file.addAction(tr("menu_save_proj_as"))
        self._act_save_proj_as.setShortcut("Ctrl+Shift+S")
        self._act_save_proj_as.triggered.connect(self.on_save_project_as)

        self._menu_file.addSeparator()

        self._act_import_menu = self._menu_file.addAction(tr("menu_import_video"))
        self._act_import_menu.setShortcut("Ctrl+I")
        self._act_import_menu.triggered.connect(self.on_import_video)

        self._menu_recent_videos = self._menu_file.addMenu(tr("menu_recent_videos"))
        self._rebuild_recent_videos_menu()

        self._menu_file.addSeparator()

        self._act_export_menu = self._menu_file.addAction(tr("menu_export_pack"))
        self._act_export_menu.setShortcut("Ctrl+E")
        self._act_export_menu.triggered.connect(self.on_export)

        self._menu_file.addSeparator()
        self._act_quit = self._menu_file.addAction(tr("menu_quit"))
        self._act_quit.setShortcut("Ctrl+Q")
        self._act_quit.triggered.connect(self.close)

        # Edit Menu (Undo / Redo)
        self._menu_edit = menubar.addMenu(tr("menu_edit"))
        
        self.act_undo = self._menu_edit.addAction(tr("menu_undo"))
        self.act_undo.setShortcut("Ctrl+Z")
        self.act_undo.triggered.connect(self.on_undo)

        self.act_redo = self._menu_edit.addAction(tr("menu_redo"))
        self.act_redo.setShortcut("Ctrl+Shift+Z")
        self.act_redo.triggered.connect(self.on_redo)

        self._menu_edit.addSeparator()
        self._act_kb_shortcuts = self._menu_edit.addAction(tr("menu_shortcuts"))
        self._act_kb_shortcuts.triggered.connect(self._show_shortcuts_dialog)

        self._act_settings = self._menu_edit.addAction(tr("menu_settings"))
        self._act_settings.triggered.connect(self.on_settings)

        # View Menu (Toggle visibility of panels & Full Screen)
        self._menu_view = menubar.addMenu(tr("menu_view"))

        self.act_fullscreen = self._menu_view.addAction(tr("menu_fullscreen"))
        self.act_fullscreen.setShortcut("F11")
        self.act_fullscreen.setCheckable(True)
        self.act_fullscreen.setChecked(False)
        self.act_fullscreen.triggered.connect(self._toggle_fullscreen)

        self._menu_view.addSeparator()

        self.act_v_video = self._menu_view.addAction(tr("menu_video_player"))
        self.act_v_video.setCheckable(True)
        self.act_v_video.setChecked(True)
        self.act_v_video.triggered.connect(lambda c: self._video_panel.setVisible(c))

        self.act_v_sidebar = self._menu_view.addAction(tr("menu_sidebar_tabs"))
        self.act_v_sidebar.setCheckable(True)
        self.act_v_sidebar.setChecked(True)
        self.act_v_sidebar.triggered.connect(lambda c: self._sidebar_tabs.setVisible(c))

        self.act_v_timeline = self._menu_view.addAction(tr("menu_timeline"))
        self.act_v_timeline.setCheckable(True)
        self.act_v_timeline.setChecked(True)
        self.act_v_timeline.triggered.connect(lambda c: self._timeline_container.setVisible(c))

        self.act_v_clip_editor = self._menu_view.addAction(tr("menu_clip_editor"))
        self.act_v_clip_editor.setCheckable(True)
        self.act_v_clip_editor.setChecked(True)
        self.act_v_clip_editor.triggered.connect(lambda c: self._clip_editor.setVisible(c))

        self.act_v_progress = self._menu_view.addAction(tr("menu_processing_logs"))
        self.act_v_progress.setCheckable(True)
        self.act_v_progress.setChecked(False)
        self.act_v_progress.triggered.connect(lambda c: self._progress_panel.setVisible(c))

        # Help Menu
        self._menu_help = menubar.addMenu(tr("menu_help"))
        self._act_shortcuts_help = self._menu_help.addAction(tr("menu_shortcuts"))
        self._act_shortcuts_help.setShortcut("F1")
        self._act_shortcuts_help.triggered.connect(self._show_shortcuts_dialog)

        self._menu_help.addSeparator()
        self._act_about = self._menu_help.addAction(tr("menu_about"))
        self._act_about.triggered.connect(self._show_about_dialog)

    def _show_shortcuts_dialog(self):
        """Open the modern Keyboard Shortcuts reference sheet dialog."""
        from gui.shortcuts_dialog import ShortcutsDialog
        dlg = ShortcutsDialog(self)
        dlg.exec()

    def _toggle_fullscreen(self):
        """Toggle borderless fullscreen mode via F11."""
        if self.isFullScreen():
            self.showMaximized()
            self.act_fullscreen.setChecked(False)
        else:
            self.showFullScreen()
            self.act_fullscreen.setChecked(True)

    def _show_about_dialog(self):
        QMessageBox.about(
            self,
            tr("about_title", app_name=APP_NAME),
            tr("about_body", app_name=APP_NAME, version=APP_VERSION),
        )

    def _build_toolbar(self):
        tb = QToolBar("Main Toolbar")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        def act(label: str, slot, shortcut: str = "", tip: str = "", icon_name: str = "") -> QAction:
            a = QAction(label, self)
            if icon_name:
                icon_path = ASSETS_DIR / "icons" / icon_name
                if icon_path.exists():
                    a.setIcon(QIcon(str(icon_path)))
            if shortcut:
                a.setShortcut(shortcut)
            if tip:
                a.setToolTip(tip)
            a.triggered.connect(slot)
            return a

        self._act_import      = act(tr("tb_import"),          self.on_import_video,       "Ctrl+I", tr("tb_import_tip"), "import.svg")
        self._act_analyze     = act(tr("tb_analyze"),         self.on_analyze,            "Ctrl+R", tr("tb_analyze_tip"), "analyze.svg")
        self._act_export      = act(tr("tb_export"),          self.on_export,             "Ctrl+E", tr("tb_export_tip"), "package.svg")
        self._act_open_folder = act(tr("tb_open_folder"),     self.on_open_export_folder, "",       tr("tb_open_folder_tip"), "folder.svg")
        self._act_settings    = act(tr("tb_settings"),        self.on_settings,           "",       tr("tb_settings_tip"), "settings.svg")

        tb.addAction(self._act_import)
        tb.addSeparator()
        tb.addAction(self._act_analyze)

        # Style Analyze button with distinctive accent highlight
        btn_analyze = tb.widgetForAction(self._act_analyze)
        if btn_analyze:
            btn_analyze.setStyleSheet(f"""
                QToolButton {{
                    background-color: {COLORS['accent']};
                    color: #ffffff;
                    border: 1px solid {COLORS['accent_hover']};
                    border-radius: 3px;
                    font-weight: bold;
                    padding: 4px 14px;
                }}
                QToolButton:hover {{
                    background-color: {COLORS['accent_hover']};
                }}
                QToolButton:disabled {{
                    background-color: #333333;
                    color: #777777;
                    border-color: #444444;
                }}
            """)

        tb.addSeparator()
        tb.addAction(self._act_export)
        tb.addAction(self._act_open_folder)
        tb.addSeparator()
        tb.addAction(self._act_settings)

    # ── Central Resizable Layout ──────────────────────────────────────────────

    def _build_central(self):
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(6, 6, 6, 6)
        root_layout.setSpacing(4)

        # Main Vertical QSplitter
        self._main_v_splitter = QSplitter(Qt.Orientation.Vertical)
        self._main_v_splitter.setChildrenCollapsible(False)

        # Top Section: Video Preview Player | Sidebar Tabs
        top_h_splitter = QSplitter(Qt.Orientation.Horizontal)
        top_h_splitter.setChildrenCollapsible(False)

        # Video Panel
        self._video_panel = VideoPanel()
        self._video_panel.set_main_window(self)
        self._video_panel.video_dropped.connect(self.load_video)
        self._video_panel.browse_requested.connect(self.on_import_video)
        self._video_panel.seek_requested.connect(self._on_video_seek)
        self._video_panel.playback_toggled.connect(self._on_video_playback_toggled)
        self._video_panel.toggle_proxy_requested.connect(self._on_toggle_proxy_requested)

        top_h_splitter.addWidget(self._video_panel)

        # Right Sidebar QTabWidget
        self._sidebar_tabs = QTabWidget()
        
        self._dialogue_table = DialogueTable()
        self._sidebar_tabs.addTab(self._dialogue_table, tr("tab_dialogues"))
        
        self._speaker_panel = SpeakerPanel()
        self._sidebar_tabs.addTab(self._speaker_panel, tr("tab_speakers"))
        
        self._pack_info_panel = PackInfoPanel()
        self._sidebar_tabs.addTab(self._pack_info_panel, tr("tab_pack_info"))
        
        top_h_splitter.addWidget(self._sidebar_tabs)
        top_h_splitter.setSizes([450, 850])

        self._main_v_splitter.addWidget(top_h_splitter)

        # Middle Section: Multi-Track Timeline Container Panel
        self._timeline_container = QFrame()
        self._timeline_container.setObjectName("editor_card")
        self._timeline_container.setVisible(True)
        self.act_v_timeline.setChecked(True)
        tl_layout = QVBoxLayout(self._timeline_container)
        tl_layout.setContentsMargins(6, 6, 6, 6)
        tl_layout.setSpacing(4)

        def v_sep():
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.VLine)
            sep.setFixedWidth(1)
            sep.setFixedHeight(18)
            sep.setStyleSheet("background-color: #383838; border: none; margin: 4px 6px;")
            return sep

        # CapCut Style minimal flat toolbar buttons with clear hotkey tooltips
        def capcut_btn(text: str, icon_file: str, tip: str = "", compact: bool = False) -> QPushButton:
            b = QPushButton(text if not compact else "")
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            path = ASSETS_DIR / "icons" / icon_file
            if path.exists():
                b.setIcon(QIcon(str(path)))
                b.setIconSize(QSize(18, 18) if compact else QSize(14, 14))
            if tip:
                b.setToolTip(tip)
            if compact:
                b.setFixedSize(32, 28)
                b.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        border: none;
                        border-radius: 5px;
                        padding: 3px;
                    }
                    QPushButton:hover {
                        background-color: rgba(255, 255, 255, 0.12);
                    }
                    QPushButton:pressed {
                        background-color: rgba(255, 255, 255, 0.22);
                    }
                    QPushButton:disabled {
                        background-color: transparent;
                        opacity: 0.35;
                    }
                """)
            else:
                b.setFixedHeight(28)
                b.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        border: 1px solid #383838;
                        border-radius: 5px;
                        padding: 3px 10px;
                        color: #cccccc;
                        font-size: 8.5pt;
                        font-weight: 500;
                    }
                    QPushButton:hover {
                        background-color: rgba(255, 255, 255, 0.10);
                        border-color: #555555;
                        color: #ffffff;
                    }
                    QPushButton:pressed {
                        background-color: rgba(255, 255, 255, 0.20);
                    }
                """)
            return b

        # Timeline Header Controls Bar
        tl_header = QHBoxLayout()
        self._lbl_tl_title = QLabel(tr("tl_title"), objectName="section_title")
        self._lbl_tl_title.setStyleSheet("font-size: 9.5pt; font-weight: bold; color: #ffffff; background: transparent; border-left: 3px solid #1473E6; padding-left: 8px; margin-right: 4px;")
        tl_header.addWidget(self._lbl_tl_title)

        # Minimal info/keyboard shortcut button (hover shows clean cheat-sheet, click opens full shortcuts dialog)
        btn_tl_shortcuts = capcut_btn("", "keyboard.svg", "", compact=True)
        btn_tl_shortcuts.setToolTip(
            '<div style="background-color: #18181b; color: #e4e4e7; font-family: Segoe UI, system-ui, sans-serif; padding: 6px 10px; border-radius: 6px;">'
            '<div style="font-size: 8.5pt; font-weight: bold; color: #ffffff; margin-bottom: 6px; letter-spacing: 0.3px;">TIMELINE SHORTCUTS &amp; GESTURES</div>'
            '<table cellpadding="2" cellspacing="0" style="font-size: 8pt; color: #e4e4e7;">'
            '<tr><td style="padding-right: 12px;"><span style="background-color: #2c2c2e; border: 1px solid #3f3f46; border-radius: 3px; padding: 1px 5px; color: #ffffff; font-weight: 600;">Space</span></td><td style="color:#a1a1aa;">Play / Pause Timeline</td></tr>'
            '<tr><td style="padding-right: 12px;"><span style="background-color: #2c2c2e; border: 1px solid #3f3f46; border-radius: 3px; padding: 1px 5px; color: #ffffff; font-weight: 600;">S</span> / <span style="background-color: #2c2c2e; border: 1px solid #3f3f46; border-radius: 3px; padding: 1px 5px; color: #ffffff; font-weight: 600;">Ctrl+B</span></td><td style="color:#a1a1aa;">Split Clip at Playhead</td></tr>'
            '<tr><td style="padding-right: 12px;"><span style="background-color: #2c2c2e; border: 1px solid #3f3f46; border-radius: 3px; padding: 1px 5px; color: #ffffff; font-weight: 600;">Q</span></td><td style="color:#a1a1aa;">Delete Left to Playhead</td></tr>'
            '<tr><td style="padding-right: 12px;"><span style="background-color: #2c2c2e; border: 1px solid #3f3f46; border-radius: 3px; padding: 1px 5px; color: #ffffff; font-weight: 600;">W</span></td><td style="color:#a1a1aa;">Delete Right from Playhead</td></tr>'
            '<tr><td style="padding-right: 12px;"><span style="background-color: #2c2c2e; border: 1px solid #3f3f46; border-radius: 3px; padding: 1px 5px; color: #ffffff; font-weight: 600;">Del</span></td><td style="color:#a1a1aa;">Delete Selected Clip</td></tr>'
            '<tr><td style="padding-right: 12px;"><span style="background-color: #2c2c2e; border: 1px solid #3f3f46; border-radius: 3px; padding: 1px 5px; color: #ffffff; font-weight: 600;">Ctrl+Z</span> / <span style="background-color: #2c2c2e; border: 1px solid #3f3f46; border-radius: 3px; padding: 1px 5px; color: #ffffff; font-weight: 600;">Ctrl+Y</span></td><td style="color:#a1a1aa;">Undo / Redo</td></tr>'
            '<tr><td style="padding-right: 12px;"><span style="background-color: #2c2c2e; border: 1px solid #3f3f46; border-radius: 3px; padding: 1px 5px; color: #ffffff; font-weight: 600;">Ctrl + Wheel</span></td><td style="color:#a1a1aa;">Zoom at Cursor</td></tr>'
            '<tr><td style="padding-right: 12px;"><span style="background-color: #2c2c2e; border: 1px solid #3f3f46; border-radius: 3px; padding: 1px 5px; color: #ffffff; font-weight: 600;">Shift + Wheel</span></td><td style="color:#a1a1aa;">Scroll Horizontally</td></tr>'
            '<tr><td style="padding-right: 12px;"><span style="background-color: #2c2c2e; border: 1px solid #3f3f46; border-radius: 3px; padding: 1px 5px; color: #ffffff; font-weight: 600;">Middle Drag</span></td><td style="color:#a1a1aa;">Pan Canvas 2D</td></tr>'
            '</table>'
            '<div style="margin-top: 8px; border-top: 1px solid #27272a; padding-top: 6px; font-size: 7.5pt; color: #71717a;">Click to open full shortcuts reference (F1)</div>'
            '</div>'
        )
        btn_tl_shortcuts.clicked.connect(self._show_shortcuts_dialog)
        tl_header.addWidget(btn_tl_shortcuts)

        tl_header.addStretch()

        # CapCut Style Quick Edit Tools:
        self._btn_tl_undo       = capcut_btn("", "undo.svg", tr("tl_btn_undo_tip"), compact=True)
        self._btn_tl_redo       = capcut_btn("", "redo.svg", tr("tl_btn_redo_tip"), compact=True)

        self._btn_tl_split      = capcut_btn("", "split.svg", tr("tl_btn_split_tip"), compact=True)
        self._btn_tl_trim_left  = capcut_btn("", "trim-left.svg", tr("tl_btn_trim_left_tip"), compact=True)
        self._btn_tl_trim_right = capcut_btn("", "trim-right.svg", tr("tl_btn_trim_right_tip"), compact=True)
        self._btn_tl_del_clip   = capcut_btn("", "trash.svg", tr("tl_btn_delete_tip"), compact=True)

        self._btn_tl_add_track  = capcut_btn(tr("tl_btn_add_track"), "plus.svg", tr("tl_btn_add_track_tip"))
        self._btn_tl_add_clip   = capcut_btn(tr("tl_btn_add_clip"), "clip.svg", tr("tl_btn_add_clip_tip"))

        self._btn_tl_play    = capcut_btn(tr("tl_btn_play"), "play.svg", tr("tl_btn_play_tip"))
        self._btn_tl_stop    = capcut_btn(tr("tl_btn_stop"), "stop.svg", tr("tl_btn_stop_tip"))
        self._btn_tl_zoomin  = capcut_btn(tr("tl_btn_zoomin"), "zoom-in.svg", tr("tl_btn_zoom_in_tip"))
        self._btn_tl_zoomout = capcut_btn(tr("tl_btn_zoomout"), "zoom-out.svg", tr("tl_btn_zoom_out_tip"))

        tl_header.addWidget(self._btn_tl_undo)
        tl_header.addWidget(self._btn_tl_redo)
        tl_header.addWidget(v_sep())

        tl_header.addWidget(self._btn_tl_split)
        tl_header.addWidget(self._btn_tl_trim_left)
        tl_header.addWidget(self._btn_tl_trim_right)
        tl_header.addWidget(self._btn_tl_del_clip)
        tl_header.addWidget(v_sep())

        tl_header.addWidget(self._btn_tl_add_track)
        tl_header.addWidget(self._btn_tl_add_clip)
        tl_header.addWidget(v_sep())

        tl_header.addWidget(self._btn_tl_play)
        tl_header.addWidget(self._btn_tl_stop)
        tl_header.addWidget(v_sep())

        tl_header.addWidget(self._btn_tl_zoomin)
        tl_header.addWidget(self._btn_tl_zoomout)

        tl_layout.addLayout(tl_header)

        # Timeline Scroll Area
        self._timeline = TimelineWidget()
        self._timeline_scroll = QScrollArea()
        self._timeline_scroll.setWidgetResizable(True)
        self._timeline_scroll.setWidget(self._timeline)
        self._timeline_scroll.setMinimumHeight(160)
        self._timeline_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._timeline_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        tl_layout.addWidget(self._timeline_scroll)

        self._timeline.set_sticky_headers(self._settings.get("timeline_sticky_headers", True))
        self._timeline.sticky_headers_toggled.connect(self._on_timeline_sticky_toggled)

        self._main_v_splitter.addWidget(self._timeline_container)

        # Connect Timeline Header buttons
        self._btn_tl_undo.clicked.connect(self.on_undo)
        self._btn_tl_redo.clicked.connect(self.on_redo)
        self._btn_tl_split.clicked.connect(self._on_split_at_playhead)
        self._btn_tl_trim_left.clicked.connect(self._on_trim_left)
        self._btn_tl_trim_right.clicked.connect(self._on_trim_right)
        self._btn_tl_del_clip.clicked.connect(self._on_delete_selected_clip)

        self._btn_tl_add_track.clicked.connect(self._on_add_track)
        self._btn_tl_add_clip.clicked.connect(self._on_add_clip)

        self._btn_tl_play.clicked.connect(self._toggle_global_playback)
        self._btn_tl_stop.clicked.connect(self._stop_global_playback)
        self._btn_tl_zoomin.clicked.connect(self._timeline.zoom_in)
        self._btn_tl_zoomout.clicked.connect(self._timeline.zoom_out)

        # Section 3: Clip Editor
        self._clip_editor = ClipEditor()
        self._clip_editor.setFixedHeight(190)
        self._main_v_splitter.addWidget(self._clip_editor)
        
        # Section 4: Bottom Progress + Log Panel (Hidden by default)
        self._progress_panel = ProgressPanel()
        self._progress_panel.setVisible(False)
        self.act_v_progress.setChecked(False)
        self._main_v_splitter.addWidget(self._progress_panel)

        # Set initial splitter stretch ratios
        self._main_v_splitter.setSizes([450, 220, 190, 0])
        root_layout.addWidget(self._main_v_splitter)

        # Debounce timer for fast playhead scrubbing so clip editor doesn't freeze the GUI
        self._seek_editor_timer = QTimer(self)
        self._seek_editor_timer.setSingleShot(True)
        self._seek_editor_timer.setInterval(70)
        self._pending_seek_item = None
        self._seek_editor_timer.timeout.connect(self._on_seek_editor_timeout)

        # ── Connect Dialogue Table Signals ──
        self._dialogue_table.dialogue_selected.connect(
            lambda item: self._clip_editor.load_item(item, self._state)
        )
        self._dialogue_table.dialogue_selected.connect(
            lambda item: self._on_select_dialogue(item)
        )
        self._dialogue_table.dialogue_double_clicked.connect(
            self._on_dialogue_double_clicked
        )
        self._dialogue_table.dialogue_deleted.connect(self._on_dialogue_deleted)
        self._dialogue_table.merge_next_requested.connect(self._on_merge_next)
        self._dialogue_table.split_requested.connect(self._on_split)
        self._dialogue_table.dialogue_changed.connect(lambda itm: self._mark_dirty(True))
        self._dialogue_table.playback_toggle_requested.connect(self._toggle_global_playback)

        # ── Connect Timeline Signals ──
        self._timeline.segment_selected.connect(self._select_dialogue_by_idx)
        self._timeline.segment_moved.connect(self._on_timeline_segment_moved)
        self._timeline.seek_requested.connect(self._on_timeline_seek)
        self._timeline.playhead_tick.connect(self._video_panel.sync_master_time)
        self._timeline.split_at_playhead_requested.connect(self._on_split_at_playhead)
        self._timeline.trim_left_requested.connect(self._on_trim_left)
        self._timeline.trim_right_requested.connect(self._on_trim_right)
        self._timeline.delete_track_requested.connect(self._on_delete_track)
        self._timeline.track_renamed.connect(self._on_speaker_renamed)
        self._timeline.undo_requested.connect(self.on_undo)
        self._timeline.redo_requested.connect(self.on_redo)
        self._timeline.split_requested.connect(self._on_split)
        self._timeline.merge_requested.connect(self._on_merge_next)
        self._timeline.delete_requested.connect(self._on_dialogue_deleted)
        self._timeline.tracks_reordered.connect(self._on_timeline_tracks_reordered)
        self._timeline.playback_toggle_requested.connect(self._toggle_global_playback)
        self._timeline.playback_start_requested.connect(self._start_global_playback)
        self._timeline.playback_stop_requested.connect(self._stop_global_playback)

        # ── Connect Speaker Panel Signals ──
        self._speaker_panel.speaker_renamed.connect(self._on_speaker_renamed)
        self._speaker_panel.speaker_added.connect(self._on_speaker_added)
        self._speaker_panel.speaker_deleted.connect(self._on_speaker_deleted)
        self._speaker_panel.speaker_reordered.connect(self._refresh_all_views)
        self._speaker_panel.speaker_selected.connect(self._set_active_speaker)

        # ── Connect Clip Editor Signals ──
        self._clip_editor.caption_changed.connect(self._on_caption_changed)
        self._clip_editor.speaker_changed.connect(self._on_speaker_changed)
        self._clip_editor.timestamps_changed.connect(self._on_timestamps_changed)
        self._clip_editor.delete_requested.connect(self._on_dialogue_deleted)
        self._clip_editor.split_requested.connect(self._on_split)
        self._clip_editor.merge_requested.connect(self._on_merge_next)
        self._clip_editor.regenerate_audio_requested.connect(self._on_regen_audio)
        self._clip_editor.regenerate_caption_requested.connect(self._on_regen_caption)
        self._clip_editor.change_image_requested.connect(self._on_change_image)
        self._clip_editor.play_started.connect(self._stop_global_playback)

        # ── Connect Pack Info Panel & Table Edit Signals ──
        self._pack_info_panel.pack_info_changed.connect(self._on_pack_info_changed)
        self._dialogue_table.dialogue_changed.connect(self._on_dialogue_changed)

    def _set_active_speaker(self, spk_id: str):
        if spk_id and spk_id in self._state.speakers:
            self._active_speaker_id = spk_id

    # ── Playback & Seeking Sync Handlers ─────────────────────────────────────

    def _toggle_global_playback(self):
        """Toggle playback on both timeline and video player."""
        if self._video_panel.is_playing() or self._timeline._is_playing:
            self._stop_global_playback()
        else:
            self._start_global_playback()

    def _start_global_playback(self):
        # Stop any active clip preview audio first to avoid overlapping sounds
        if hasattr(self, '_clip_editor'):
            self._clip_editor.player.stop()
        cur_t = self._timeline.current_time
        self._video_panel.set_position(cur_t)
        self._timeline.start_playback()
        self._video_panel.start_playback()

    def _stop_global_playback(self):
        if hasattr(self, '_clip_editor'):
            self._clip_editor.player.stop()
        self._timeline.stop_playback()
        self._video_panel.pause_playback()

    def _on_video_playback_toggled(self, is_playing: bool):
        if is_playing and not self._timeline._is_playing:
            self._timeline.start_playback()
        elif not is_playing and self._timeline._is_playing:
            self._timeline.stop_playback()

    def seek_to_time(self, t: float, keep_playing: Optional[bool] = None):
        """
        Unified time seek across timeline and video panel.
        If keep_playing is None, preserves current playback state (seamlessly continues playing if playing).
        """
        was_playing = self._timeline._is_playing or self._video_panel.is_playing()
        should_play = was_playing if keep_playing is None else keep_playing

        # Seek timeline (master clock)
        self._timeline.seek(t)
        # Seek video panel
        self._video_panel.set_position(t)

        if should_play:
            if not self._timeline._is_playing:
                self._timeline.start_playback()
            if not self._video_panel.is_playing():
                self._video_panel.start_playback()
        else:
            if self._timeline._is_playing:
                self._timeline.stop_playback()
            if self._video_panel.is_playing():
                self._video_panel.pause_playback()

    def _on_video_seek(self, t: float):
        self._timeline.set_current_time(t)

    def _on_timeline_seek(self, t: float):
        self._video_panel.set_position(t)
        for item in self._state.active_dialogues():
            if item.start <= t <= item.end:
                if not self._clip_editor.item or self._clip_editor.item.index != item.index:
                    self._pending_seek_item = item
                    self._seek_editor_timer.start()
                    self._set_active_speaker(item.speaker_id)
                break

    def _on_seek_editor_timeout(self):
        if self._pending_seek_item and self._state:
            self._clip_editor.load_item(self._pending_seek_item, self._state)
            self._pending_seek_item = None

    def _on_select_dialogue(self, item: DialogueItem):
        self.seek_to_time(item.start)
        self._set_active_speaker(item.speaker_id)
        self._timeline.selected_index = item.index
        self._timeline.ensure_playhead_visible(margin=80)
        self._timeline.update()

    def _on_dialogue_double_clicked(self, item: DialogueItem):
        self.seek_to_time(item.start)
        self._set_active_speaker(item.speaker_id)
        self._timeline.selected_index = item.index
        self._timeline.center_on_dialogue(item, animated=True)
        self._timeline.update()

    def _select_dialogue_by_idx(self, idx: int):
        for item in self._state.active_dialogues():
            if item.index == idx:
                self._clip_editor.load_item(item, self._state)
                self.seek_to_time(item.start)
                self._set_active_speaker(item.speaker_id)
                self._dialogue_table.select_dialogue_by_index(idx)
                break

    # ── Undo / Redo Actions ──────────────────────────────────────────────────

    def on_undo(self):
        # 1. Prioritize caption text editor undo if active or has pending text undo
        if hasattr(self, '_clip_editor') and self._clip_editor.txt_caption.document().isUndoAvailable():
            focus = QApplication.focusWidget()
            if focus and (focus == self._clip_editor.txt_caption or self._clip_editor.isAncestorOf(focus)):
                self._clip_editor.txt_caption.undo()
                return

        # 2. Global Pipeline / Project Undo
        if self._undo_manager.undo(self._state):
            self._mark_dirty(True)
            self._refresh_all_views()
            self._log_message("Undo executed", "info")

    def on_redo(self):
        # 1. Prioritize caption text editor redo if active or has pending text redo
        if hasattr(self, '_clip_editor') and self._clip_editor.txt_caption.document().isRedoAvailable():
            focus = QApplication.focusWidget()
            if focus and (focus == self._clip_editor.txt_caption or self._clip_editor.isAncestorOf(focus)):
                self._clip_editor.txt_caption.redo()
                return

        # 2. Global Pipeline / Project Redo
        if self._undo_manager.redo(self._state):
            self._mark_dirty(True)
            self._refresh_all_views()
            self._log_message("Redo executed", "info")

    def _push_undo(self):
        self._undo_manager.push(self._state)

    # ── Manual Track & Speaker Handlers ──────────────────────────────────────

    def _on_add_track(self):
        existing_indices = []
        for sid in self._state.speakers.keys():
            if sid.startswith("SPEAKER_"):
                try:
                    existing_indices.append(int(sid.replace("SPEAKER_", "")))
                except ValueError:
                    pass
        next_idx = max(existing_indices, default=-1) + 1
        new_spk_id = f"SPEAKER_{next_idx:02d}"
        default_name = f"Speaker {next_idx + 1}"

        name, ok = QInputDialog.getText(
            self,
            "Add Character Track",
            "Enter character name for new track:",
            text=default_name
        )
        if not ok:
            return
        display_name = name.strip() if name.strip() else default_name

        self._push_undo()
        self._state.speakers[new_spk_id] = SpeakerInfo(
            speaker_id=new_spk_id,
            display_name=display_name
        )
        if new_spk_id not in self._state.speaker_order:
            self._state.speaker_order.append(new_spk_id)

        self._active_speaker_id = new_spk_id
        self._mark_dirty(True)
        self._refresh_all_views()
        self._log_message(f"Added track '{display_name}' ({new_spk_id})", "ok")

    def _on_delete_last_track(self):
        if len(self._state.speakers) <= 1:
            QMessageBox.warning(self, tr("msg_delete_track_title"), tr("msg_delete_track_cannot_last"))
            return
        last_spk = self._state.get_speaker_order()[-1]
        self._on_delete_track(last_spk)

    def _on_delete_track(self, spk_id: str):
        if spk_id in self._state.speakers:
            if len(self._state.speakers) <= 1:
                QMessageBox.warning(self, tr("msg_delete_speaker_title"), tr("msg_delete_speaker_cannot_last"))
                return
            spk_info = self._state.speakers[spk_id]
            clip_count = sum(1 for d in self._state.active_dialogues() if d.speaker_id == spk_id)
            reply = QMessageBox.question(
                self,
                tr("msg_confirm_delete_speaker_title"),
                tr("msg_confirm_delete_speaker_prompt", name=spk_info.display_name, id=spk_id, count=clip_count),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

            self._push_undo()
            del self._state.speakers[spk_id]
            if spk_id in self._state.speaker_order:
                self._state.speaker_order.remove(spk_id)
            default_spk = next(iter(self._state.speakers.keys()))
            for d in self._state.dialogues:
                if d.speaker_id == spk_id:
                    d.speaker_id = default_spk
            if self._active_speaker_id == spk_id:
                self._active_speaker_id = default_spk
            self._mark_dirty(True)
            self._refresh_all_views()
            self._log_message(f"Deleted speaker track '{spk_info.display_name}'", "info")

    def _on_add_clip(self):
        if not self._state.speakers:
            self._on_add_track()
        self._push_undo()
        cur_t = self._timeline.current_time
        spk_id = self._active_speaker_id if self._active_speaker_id in self._state.speakers else next(iter(self._state.speakers.keys()))
        new_d = DialogueItem(
            index=len(self._state.dialogues) + 1,
            speaker_id=spk_id,
            start=cur_t,
            end=cur_t + 1.5,
            caption=""
        )
        self._state.dialogues.append(new_d)
        self._state.renumber()
        self._mark_dirty(True)
        self._refresh_all_views()
        self._log_message(f"Added new dialogue clip #{new_d.index} for speaker {spk_id}", "ok")

    def _on_delete_selected_clip(self):
        idx = self._timeline.selected_index
        if idx >= 0:
            self._on_dialogue_deleted(idx)
        else:
            item = self._timeline._get_clip_at_time(self._timeline.current_time)
            if item:
                self._on_dialogue_deleted(item.index)

    def _on_split_at_playhead(self):
        cur_t = self._timeline.current_time
        target = self._timeline._get_clip_at_time(cur_t)
        if not target:
            self._log_message("Split: No clip under playhead to split.", "warn")
            return
        if cur_t <= target.start + 0.05 or cur_t >= target.end - 0.05:
            self._log_message("Split: Playhead too close to clip boundary.", "warn")
            return
        self._push_undo()
        for d in self._state.active_dialogues():
            if d.index == target.index:
                old_end = d.end
                d.end = cur_t
                new_d = DialogueItem(
                    index=len(self._state.dialogues) + 1,
                    speaker_id=d.speaker_id,
                    start=cur_t,
                    end=old_end,
                    caption="",
                )
                self._state.dialogues.append(new_d)
                break
        self._state.renumber()
        self._mark_dirty(True)
        self._refresh_all_views()
        self._log_message(f"Split clip #{target.index} at {cur_t:.2f}s", "ok")

    def _on_trim_left(self):
        cur_t = self._timeline.current_time
        target = self._timeline._get_clip_at_time(cur_t)
        if not target:
            self._log_message("Trim Left: No clip under playhead.", "warn")
            return
        if cur_t >= target.end - 0.05:
            self._log_message("Trim Left: Playhead at or past clip end.", "warn")
            return
        self._push_undo()
        for d in self._state.active_dialogues():
            if d.index == target.index:
                d.start = cur_t
                break
        self._mark_dirty(True)
        self._refresh_all_views()
        self._log_message(f"Trimmed start of clip #{target.index} to {cur_t:.2f}s (Q)", "ok")

    def _on_trim_right(self):
        cur_t = self._timeline.current_time
        target = self._timeline._get_clip_at_time(cur_t)
        if not target:
            self._log_message("Trim Right: No clip under playhead.", "warn")
            return
        if cur_t <= target.start + 0.05:
            self._log_message("Trim Right: Playhead at or before clip start.", "warn")
            return
        self._push_undo()
        for d in self._state.active_dialogues():
            if d.index == target.index:
                d.end = cur_t
                break
        self._mark_dirty(True)
        self._refresh_all_views()
        self._log_message(f"Trimmed end of clip #{target.index} to {cur_t:.2f}s (W)", "ok")

    def _on_speaker_added(self, spk_id: str):
        self._push_undo()
        self._active_speaker_id = spk_id
        self._mark_dirty(True)
        self._refresh_all_views()

    def _on_speaker_deleted(self, spk_id: str):
        self._on_delete_track(spk_id)

    # ── Keyboard Shortcuts (Spacebar & Global Event Filter) ───────────────────

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Space:
            # If target widget receiving the key is a text input field, let it type a space
            if isinstance(obj, (QLineEdit, QTextEdit, QPlainTextEdit)):
                return super().eventFilter(obj, event)

            # If a modal dialog is active, let it handle its own keys
            if QApplication.activeModalWidget() is not None:
                return super().eventFilter(obj, event)

            focus = QApplication.focusWidget()
            if focus:
                # If focus is inside a secondary window or dialog, let it pass
                if focus.window() != self:
                    return super().eventFilter(obj, event)
                # If user is actively typing in a text field, let it type a space
                if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit)):
                    return super().eventFilter(obj, event)

            self._toggle_global_playback()
            return True

        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Space:
            focus = QApplication.focusWidget()
            if focus and (isinstance(focus, QLineEdit) or isinstance(focus, QTextEdit) or isinstance(focus, QPlainTextEdit)):
                super().keyPressEvent(event)
                return
            self._toggle_global_playback()
        else:
            super().keyPressEvent(event)

    # ── Dialogue Editing Handlers ─────────────────────────────────────────────

    def _refresh_all_views(self):
        self._dialogue_table.populate(self._state)
        self._speaker_panel.populate(self._state)
        self._timeline.populate(self._state)
        self._pack_info_panel.populate(self._state)
        self._update_toolbar_state()

        # Keep active clip in clip editor in sync with restored state
        if hasattr(self, '_clip_editor') and self._clip_editor.item:
            cur_idx = self._clip_editor.item.index
            for d in self._state.active_dialogues():
                if d.index == cur_idx:
                    self._clip_editor.load_item(d, self._state)
                    break

    def _on_dialogue_deleted(self, idx: int):
        self._push_undo()
        for item in self._state.dialogues:
            if item.index == idx:
                item.is_deleted = True
                break
        self._state.renumber()
        self._clip_editor.clear()
        self._mark_dirty(True)
        self._refresh_all_views()

    def _on_merge_next(self, idx: int):
        self._push_undo()
        dialogues = self._state.active_dialogues()
        for i, d in enumerate(dialogues):
            if d.index == idx and i < len(dialogues) - 1:
                next_d = dialogues[i + 1]
                d.end = next_d.end
                if next_d.caption:
                    d.caption = f"{d.caption} {next_d.caption}".strip()
                next_d.is_deleted = True
                break
        self._state.renumber()
        self._mark_dirty(True)
        self._refresh_all_views()

    def _on_split(self, idx: int):
        self._push_undo()
        for d in self._state.active_dialogues():
            if d.index == idx:
                mid = d.start + (d.end - d.start) / 2.0
                old_end = d.end
                d.end = mid
                
                new_d = DialogueItem(
                    index=len(self._state.dialogues) + 1,
                    speaker_id=d.speaker_id,
                    start=mid,
                    end=old_end,
                    caption=""
                )
                self._state.dialogues.append(new_d)
                break
        self._state.renumber()
        self._mark_dirty(True)
        self._refresh_all_views()

    def _on_caption_changed(self, idx: int, text: str):
        for d in self._state.active_dialogues():
            if d.index == idx:
                if d.caption == text:
                    return
                # Push snapshot of previous state before mutating caption
                self._push_undo()
                d.caption = text
                break
        self._mark_dirty(True)
        self._dialogue_table.populate(self._state)

    def _on_speaker_changed(self, idx: int, spk_id: str):
        if not spk_id: return
        self._push_undo()
        self._active_speaker_id = spk_id
        for d in self._state.active_dialogues():
            if d.index == idx:
                d.speaker_id = spk_id
                break
        self._mark_dirty(True)
        self._refresh_all_views()

    def _on_timestamps_changed(self, idx: int, start: float, end: float):
        self._push_undo()
        target_item = None
        for d in self._state.active_dialogues():
            if d.index == idx:
                d.start = start
                d.end = max(start + 0.05, end)
                target_item = d
                break
        
        if target_item and (self._state.work_audio_path or self._state.separated_vocals_path):
            try:
                from core.clip_generator import ClipGenerator
                gen = ClipGenerator()
                out_dir = self._output_dir or (self._state.video_path.parent / "output" / "pack" if self._state.video_path else Path.cwd() / "output")
                gen.regenerate_clip(target_item, self._state, out_dir)
            except Exception as e:
                self._log_message(f"Could not auto-regenerate audio clip: {e}", "warn")

        self._mark_dirty(True)
        self._dialogue_table.populate(self._state)
        self._timeline.populate(self._state)

    def _on_timeline_segment_moved(self, idx: int, start: float, end: float):
        self._on_timestamps_changed(idx, start, end)
        for d in self._state.active_dialogues():
            if d.index == idx:
                self._clip_editor.load_item(d, self._state)
                break
        self._dialogue_table.populate(self._state)

    def _on_timeline_tracks_reordered(self):
        self._push_undo()
        self._mark_dirty(True)
        self._speaker_panel.populate(self._state)
        self._timeline.populate(self._state)
        self._show_toast(tr("msg_tracks_reordered_title"), tr("msg_tracks_reordered_desc"), "info")

    def _on_speaker_renamed(self, spk_id: str, new_name: str):
        self._push_undo()
        self._mark_dirty(True)
        self._dialogue_table.populate(self._state)
        self._timeline.populate(self._state)

    def _on_regen_audio(self, idx: int):
        for d in self._state.active_dialogues():
            if d.index == idx:
                self._log_message(f"Regenerating audio for clip #{d.index} in background...", "info")
                out_dir = self._output_dir or (self._state.video_path.parent / "output" / "pack")
                def _worker(itm=d):
                    try:
                        from core.clip_generator import ClipGenerator
                        gen = ClipGenerator()
                        gen.regenerate_clip(itm, self._state, out_dir)
                        def _done():
                            self._mark_dirty(True)
                            self._dialogue_table.update_row(itm, self._state)
                            self._clip_editor.load_item(itm, self._state)
                            self._log_message(f"Regenerated audio for clip #{itm.index}", "ok")
                        QTimer.singleShot(0, _done)
                    except Exception as e:
                        QTimer.singleShot(0, lambda err=e: self._log_message(f"Error regenerating clip: {err}", "error"))
                import threading
                threading.Thread(target=_worker, daemon=True).start()
                break

    def _on_regen_caption(self, idx: int):
        for d in self._state.active_dialogues():
            if d.index == idx:
                self._log_message(f"Transcribing clip #{d.index} with Whisper AI in background...", "info")
                model_size = self._settings.get("whisper_model", WHISPER_MODEL_DEFAULT)
                lang = self._settings.get("whisper_language")
                audio_src = self._state.work_audio_path
                def _worker(itm=d):
                    try:
                        from core.transcriber import Transcriber
                        t = Transcriber(model_size=model_size, language=lang)
                        t.load_model()
                        if audio_src and audio_src.exists():
                            res = t.transcribe_segment(audio_src, itm.start, itm.end)
                            def _done():
                                if res:
                                    itm.caption = res
                                    self._mark_dirty(True)
                                    self._dialogue_table.update_row(itm, self._state)
                                    self._clip_editor.load_item(itm, self._state)
                                    self._timeline.update()
                                    self._log_message(f"Re-transcribed clip #{itm.index}: '{res}'", "ok")
                            QTimer.singleShot(0, _done)
                    except Exception as e:
                        QTimer.singleShot(0, lambda err=e: self._log_message(f"Error transcribing clip: {err}", "error"))
                import threading
                threading.Thread(target=_worker, daemon=True).start()
                break

    def _on_change_image(self, idx: int):
        for d in self._state.active_dialogues():
            if d.index == idx:
                self._log_message(f"Extracting frame for clip #{d.index} in background...", "info")
                vid_path = self._state.video_path
                out_dir = self._output_dir
                def _worker(itm=d):
                    try:
                        from core.frame_extractor import FrameExtractor
                        if vid_path and vid_path.exists():
                            ext = FrameExtractor(vid_path)
                            frame = ext.find_best_frame(itm.start, itm.end, num_candidates=5)
                            ext.release()
                            if frame is not None and out_dir:
                                spk_name = self._state.get_speaker_safe_name(itm.speaker_id)
                                out_img = out_dir / f"{itm.id_str}_{spk_name}.png"
                                ext.save_frame(frame, out_img)
                                def _done():
                                    itm.image_path = out_img
                                    self._mark_dirty(True)
                                    self._dialogue_table.update_row(itm, self._state)
                                    self._clip_editor.load_item(itm, self._state)
                                    self._log_message(f"Extracted new frame for clip #{itm.index}", "ok")
                                QTimer.singleShot(0, _done)
                    except Exception as e:
                        QTimer.singleShot(0, lambda err=e: self._log_message(f"Error changing image: {err}", "error"))
                import threading
                threading.Thread(target=_worker, daemon=True).start()
                break

    def _on_pack_info_changed(self, info: PackInfo):
        self._state.pack_info = info
        self._mark_dirty(True)

    def _on_dialogue_changed(self, item: DialogueItem):
        self._mark_dirty(True)

    # ── Status Bar ───────────────────────────────────────────────────────────

    def _build_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._status_video = QLabel(tr("status_no_video"))
        self._status_save = QLabel(tr("status_ready"))
        self._status_save.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 8.5pt; padding-right: 12px;")
        self._status_version = QLabel(tr("status_version", version=APP_VERSION))
        sb.addWidget(self._status_video)
        sb.addPermanentWidget(self._status_save)
        sb.addPermanentWidget(self._status_version)

    # ── Project & Dirty State Tracking ────────────────────────────────────────

    def _mark_dirty(self, dirty: bool = True):
        self._is_dirty = dirty
        self._update_window_title()
        self._update_save_status()

    def _update_window_title(self):
        star = " *" if self._is_dirty else ""
        if self._current_project_path:
            self.setWindowTitle(f"{APP_NAME} — {self._current_project_path.name}{star}")
        elif self._state.video_path:
            self.setWindowTitle(f"{APP_NAME} — [{self._state.video_path.name}]{star}")
        else:
            self.setWindowTitle(f"{APP_NAME}{star}")

    def _update_save_status(self):
        if not hasattr(self, '_status_save'):
            return
        if self._is_dirty:
            self._status_save.setText(tr("status_unsaved"))
            self._status_save.setStyleSheet("color: #f59e0b; font-size: 8.5pt; font-weight: bold; padding-right: 12px;")
        else:
            t = f" {self._last_saved_time}" if self._last_saved_time else ""
            self._status_save.setText(tr("status_saved", time=t).replace("  ", " "))
            self._status_save.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 8.5pt; padding-right: 12px;")

    def _on_autosave_timer_tick(self):
        if not self._is_dirty:
            return
        # Only auto-save if something has been loaded or created
        if not self._state.video_path and not self._state.dialogues:
            return

        as_path = ProjectManager.auto_save(
            self._state,
            self._current_project_path,
            fallback_dir=Path.cwd() / "output"
        )
        if as_path:
            t = datetime.now().strftime("%H:%M:%S")
            self._status_save.setText(tr("status_autosaved", time=t))
            self._status_save.setStyleSheet("color: #38bdf8; font-size: 8.5pt; padding-right: 12px;")

    # ── State helpers ─────────────────────────────────────────────────────────

    def _update_toolbar_state(self):
        has_video = self._state.video_path is not None
        has_dialogues = len(self._state.dialogues) > 0
        self._act_analyze.setEnabled(has_video)
        self._act_export.setEnabled(has_dialogues)

    def _log_message(self, msg: str, level: str = "info"):
        if hasattr(self, '_progress_panel'):
            self._progress_panel.log(msg, level)
        else:
            print(f"[{level}] {msg}")

    # ── Project Operations (New / Open / Save / Pack Import) ───────────────────

    def _check_unsaved_changes(self) -> bool:
        """Prompt to save if changes are unsaved. Returns True to proceed, False to abort."""
        if not self._is_dirty or (not self._state.video_path and not self._state.dialogues):
            return True

        proj_name = self._current_project_path.name if self._current_project_path else (self._state.pack_info.title or "Untitled Project")
        reply = QMessageBox.question(
            self,
            tr("msg_save_changes_title"),
            tr("msg_save_changes_named", name=proj_name),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save
        )
        if reply == QMessageBox.StandardButton.Save:
            return self.on_save_project()
        elif reply == QMessageBox.StandardButton.Discard:
            return True
        return False

    def on_new_project(self):
        """Reset workspace to a fresh empty project."""
        if not self._check_unsaved_changes():
            return

        self._state = PipelineState()
        self._undo_manager = UndoManager()
        self._current_project_path = None
        self._output_dir = None
        self._is_dirty = False
        self._last_saved_time = None

        self._video_panel.reset()
        self._clip_editor.clear()
        self._refresh_all_views()
        self._status_video.setText(tr("status_no_video"))
        self._update_window_title()
        self._update_save_status()
        self._log_message("New project initialized", "info")

    def on_open_project(self):
        """Open a .voicer project file."""
        if not self._check_unsaved_changes():
            return

        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Open Voicer Project",
            "",
            "Voicer Studio Project (*.voicer *.json);;All Files (*)",
        )
        if path_str:
            self.load_project_file(Path(path_str))

    def on_open_pack_folder(self):
        """Import an existing exported pack folder (with _pack_info.ini and cue cards)."""
        if not self._check_unsaved_changes():
            return

        dir_str = QFileDialog.getExistingDirectory(
            self,
            "Open Exported Pack Folder",
            ""
        )
        if dir_str:
            self.load_pack_folder(Path(dir_str))

    def load_project_file(self, path: Path):
        """Load project from .voicer file."""
        try:
            state = ProjectManager.load_project(path)
            self._state = state
            self._undo_manager = UndoManager()

            # If loaded path was an autosave file, sanitize the project path to base project name
            if ".autosave" in path.name.lower() or path.name.startswith("."):
                clean = ProjectManager.clean_stem(path.stem)
                orig_file = path.parent / f"{clean}.voicer"
                self._current_project_path = orig_file if orig_file.exists() else None
                self._mark_dirty(True)
            else:
                self._current_project_path = path
                self._is_dirty = False

            self._last_saved_time = datetime.now().strftime("%H:%M:%S")

            if state.video_path and state.video_path.exists():
                self._video_panel.load_video(state.video_path)
                self._video_panel.show_video_info(state)
                self._status_video.setText(tr("status_file", name=state.video_path.name))
                self._timeline.set_duration(state.video_duration)
                if state.preview_proxy_path and state.preview_proxy_path.exists():
                    proxy_h = self._settings.get("preview_proxy_height", 540)
                    self._video_panel.set_proxy_video(state.preview_proxy_path, proxy_h)
                else:
                    self._start_preview_proxy_generation(state.video_path)
            else:
                self._status_video.setText(tr("status_project_no_video", name=path.name))

            self._refresh_all_views()
            self._update_window_title()
            self._update_save_status()
            self._add_recent_project(str(path.resolve()))
            self._log_message(f"Opened project: {path.name} ({len(state.dialogues)} dialogues)", "ok")
            self._show_toast(tr("msg_project_loaded_title"), tr("msg_project_loaded_desc", count=len(state.dialogues), name=path.name), "ok")
        except Exception as e:
            self._log_message(f"Failed to open project: {e}", "error")
            QMessageBox.critical(self, tr("msg_open_error_title"), tr("msg_open_error", error=str(e)))

    def load_pack_folder(self, pack_dir: Path):
        """Reconstruct project from an exported pack directory."""
        try:
            state = ProjectManager.load_from_pack_folder(pack_dir)
            self._state = state
            self._undo_manager = UndoManager()
            self._output_dir = pack_dir
            self._current_project_path = pack_dir / f"{pack_dir.name}.voicer"
            self._is_dirty = False
            self._last_saved_time = datetime.now().strftime("%H:%M:%S")

            if state.video_path and state.video_path.exists():
                self._video_panel.load_video(state.video_path)
                self._video_panel.show_video_info(state)
                self._status_video.setText(tr("status_file", name=state.video_path.name))
                self._timeline.set_duration(state.video_duration)
                self._start_preview_proxy_generation(state.video_path)
            else:
                self._status_video.setText(f"Pack: {pack_dir.name}")

            self._refresh_all_views()
            self._update_window_title()
            self._update_save_status()
            self._add_recent_project(str(self._current_project_path.resolve()))
            self._log_message(f"Imported pack folder: {pack_dir.name} ({len(state.dialogues)} dialogues)", "ok")
            self._show_toast(tr("msg_pack_imported_title"), tr("msg_pack_imported_desc", count=len(state.dialogues)), "ok")
        except Exception as e:
            self._log_message(f"Failed to import pack folder: {e}", "error")
            QMessageBox.critical(self, tr("msg_import_pack_error_title"), tr("msg_import_pack_error", error=str(e)))

    def on_save_project(self) -> bool:
        """Save to current project path, or prompt for path if untitled."""
        if self._current_project_path:
            ok = ProjectManager.save_project(self._state, self._current_project_path)
            if ok:
                ProjectManager.delete_autosave(self._current_project_path)
                self._last_saved_time = datetime.now().strftime("%H:%M:%S")
                self._mark_dirty(False)
                self._add_recent_project(str(self._current_project_path.resolve()))
                self._log_message(f"Project saved: {self._current_project_path.name}", "ok")
                self._show_toast(tr("msg_project_saved_title"), self._current_project_path.name, "ok")
                return True
            else:
                self._log_message("Failed to save project file", "error")
                QMessageBox.critical(self, tr("msg_save_error_title"), tr("msg_save_error"))
                return False
        return self.on_save_project_as()

    def on_save_project_as(self) -> bool:
        """Prompt user for a destination and save project."""
        suggested_name = "Untitled_Project"
        if self._state.pack_info.title and self._state.pack_info.title != "Untitled Pack":
            suggested_name = self._state.pack_info.title.replace(" ", "_")
        elif self._state.video_path:
            suggested_name = self._state.video_path.stem

        default_dir = self._state.video_path.parent if self._state.video_path else Path.cwd()
        suggested_path = default_dir / f"{suggested_name}.voicer"

        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save Project As",
            str(suggested_path),
            "Voicer Studio Project (*.voicer);;JSON Files (*.json)",
        )
        if not path_str:
            return False

        path = Path(path_str)
        ok = ProjectManager.save_project(self._state, path)
        if ok:
            ProjectManager.delete_autosave(path)
            self._current_project_path = path
            self._last_saved_time = datetime.now().strftime("%H:%M:%S")
            self._mark_dirty(False)
            self._add_recent_project(str(path.resolve()))
            self._log_message(f"Project saved as: {path.name}", "ok")
            self._show_toast(tr("msg_project_saved_title"), path.name, "ok")
            return True
        else:
            self._log_message("Failed to save project file", "error")
            QMessageBox.critical(self, tr("msg_save_error_title"), tr("msg_save_error"))
            return False

    def _rebuild_recent_projects_menu(self):
        if not hasattr(self, "_menu_recent_projects"):
            return
        self._menu_recent_projects.clear()
        recents = self._settings.get("recent_projects", [])
        if not recents:
            act = self._menu_recent_projects.addAction(tr("menu_no_recent_projects"))
            act.setEnabled(False)
            return

        for p_str in recents:
            p = Path(p_str)
            if p.exists():
                act = self._menu_recent_projects.addAction(f"{p.name}  ({p.parent})")
                act.triggered.connect(lambda _, path=p: self.load_project_file(path))

        self._menu_recent_projects.addSeparator()
        act_clear = self._menu_recent_projects.addAction(tr("menu_clear_recent_projects"))
        act_clear.triggered.connect(self._clear_recent_projects)

    def _add_recent_project(self, path_str: str):
        recents = self._settings.get("recent_projects", [])
        if path_str in recents:
            recents.remove(path_str)
        recents.insert(0, path_str)
        self._settings["recent_projects"] = recents[:10]
        self._save_settings(self._settings)
        self._rebuild_recent_projects_menu()

    def _clear_recent_projects(self):
        self._settings["recent_projects"] = []
        self._save_settings(self._settings)
        self._rebuild_recent_projects_menu()

    def _rebuild_recent_videos_menu(self):
        if not hasattr(self, "_menu_recent_videos"):
            return
        self._menu_recent_videos.clear()
        recents = self._settings.get("recent_videos", [])
        if not recents:
            act = self._menu_recent_videos.addAction(tr("menu_no_recent_videos"))
            act.setEnabled(False)
            return

        for p_str in recents:
            p = Path(p_str)
            if p.exists():
                act = self._menu_recent_videos.addAction(f"{p.name}  ({p.parent})")
                act.triggered.connect(lambda _, path=p: self.load_video(path))

        self._menu_recent_videos.addSeparator()
        act_clear = self._menu_recent_videos.addAction(tr("menu_clear_recent_videos"))
        act_clear.triggered.connect(self._clear_recent_videos)

    def _add_recent_video(self, path_str: str):
        recents = self._settings.get("recent_videos", [])
        if path_str in recents:
            recents.remove(path_str)
        recents.insert(0, path_str)
        self._settings["recent_videos"] = recents[:10]
        self._save_settings(self._settings)
        self._rebuild_recent_videos_menu()

    def _clear_recent_videos(self):
        self._settings["recent_videos"] = []
        self._save_settings(self._settings)
        self._rebuild_recent_videos_menu()

    # ── Action Slots ──────────────────────────────────────────────────────────

    def on_import_video(self):
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Import Video",
            "",
            "Video Files (*.mp4 *.mkv *.mov *.webm *.avi);;All Files (*)",
        )
        if path_str:
            self.load_video(Path(path_str))

    def load_video(self, path: Path):
        """Load a video file into the pipeline state and update UI."""
        if not path.exists():
            self._log_message(f"File not found: {path}", "error")
            return

        suffix = path.suffix.lower()
        if suffix not in {".mp4", ".mkv", ".mov", ".webm", ".avi"}:
            self._log_message(f"Unsupported format: {suffix}", "warn")
            return

        self._add_recent_video(str(path.resolve()))
        self._state.video_path = path
        self._state.pack_info.title = path.stem

        # Auto-incremental output directory setup
        from core.pack_builder import PackBuilder
        pack_name = PackBuilder.sanitize_pack_name(path.stem)
        out_opt = self._settings.get("output_dir", "")
        base = Path(out_opt) if out_opt else (path.parent / "output")
        self._output_dir = PackBuilder.get_unique_pack_dir(base, pack_name)

        # Probe video metadata via ffprobe
        self._probe_video(path)

        self._video_panel.load_video(path)
        self._video_panel.show_video_info(self._state)
        self._status_video.setText(f"File: {path.name}")
        self._mark_dirty(True)
        self._update_toolbar_state()
        self._log_message(f"Video loaded: {path.name}", "ok")
        self._start_preview_proxy_generation(path)

    def _on_toggle_proxy_requested(self):
        """User clicked badge to request proxy generation or recreate."""
        if self._state.video_path:
            self._start_preview_proxy_generation(self._state.video_path, force=True)

    def _start_preview_proxy_generation(self, path: Path, force: bool = False):
        """Generate or load low-res fast-seek proxy video in background for smooth playback."""
        try:
            proxy_enabled = self._settings.get("preview_proxy_enabled", True)
            target_height = self._settings.get("preview_proxy_height", 540)
            if not proxy_enabled or target_height == 0:
                self._video_panel.switch_to_original()
                return

            from core.proxy_generator import ProxyGenerator, ProxyWorker
            proxy_path = ProxyGenerator.get_proxy_path(path, target_height)
            if not force and proxy_path.exists() and proxy_path.stat().st_size > 1024:
                self._state.preview_proxy_path = proxy_path
                self._video_panel.set_proxy_video(proxy_path, target_height)
                self._log_message(f"Loaded fast-seek preview proxy ({target_height}p): {proxy_path.name}", "ok")
                return

            self._video_panel.set_status_generating()
            self._log_message(f"Generating fast-seek preview proxy ({target_height}p) in background...", "info")
            if self.statusBar():
                self.statusBar().showMessage(f"Creating {target_height}p preview proxy video...", 5000)

            self._proxy_worker = ProxyWorker(path, target_height=target_height, force=force)

            def on_proxy_ready(out_path_str: str):
                out_path = Path(out_path_str)
                self._state.preview_proxy_path = out_path
                self._video_panel.set_proxy_video(out_path, target_height)
                if self.statusBar():
                    self.statusBar().showMessage(f"Preview proxy ({target_height}p) ready", 4000)
                self._log_message(f"Preview proxy ready: {out_path.name}", "ok")

            def on_proxy_failed(err: str):
                self._video_panel.switch_to_original()
                if self.statusBar():
                    self.statusBar().showMessage("Preview proxy skipped", 4000)
                self._log_message(f"Preview proxy skipped: {err}", "warn")

            self._proxy_worker.proxy_ready.connect(on_proxy_ready)
            self._proxy_worker.proxy_failed.connect(on_proxy_failed)
            self._proxy_worker.start()
        except Exception as e:
            self._video_panel.switch_to_original()
            self._log_message(f"Preview proxy error: {e}", "warn")

    def on_open_export_folder(self):
        """Open the output pack folder in Windows File Explorer."""
        import os
        out_dir = self._output_dir
        if not out_dir or not out_dir.exists():
            out_opt = self._settings.get("output_dir", "")
            if out_opt:
                out_dir = Path(out_opt)
            elif self._state.video_path:
                out_dir = self._state.video_path.parent / "output"

        if out_dir and out_dir.exists():
            os.startfile(out_dir)
            self._log_message(f"Opened folder: {out_dir}", "info")
        else:
            QMessageBox.information(
                self, tr("msg_export_folder_title"),
                tr("msg_export_folder_not_exist", path=str(out_dir or 'Not specified'))
            )

    def load_dialogues(self, state: PipelineState):
        self._state = state
        self._dialogue_table.populate(state)
        self._speaker_panel.populate(state)
        self._timeline.populate(state)
        self._update_toolbar_state()

    def _probe_video(self, path: Path):
        """Use ffprobe to extract video metadata."""
        import subprocess, json
        from config import SUBPROCESS_FLAGS
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-print_format", "json",
                    "-show_streams", "-show_format",
                    str(path),
                ],
                capture_output=True, text=True, timeout=15,
                creationflags=SUBPROCESS_FLAGS
            )
            data = json.loads(result.stdout)
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    self._state.video_width  = int(stream.get("width", 0))
                    self._state.video_height = int(stream.get("height", 0))
                    fps_str = stream.get("r_frame_rate", "0/1")
                    num, den = fps_str.split("/")
                    self._state.video_fps = round(int(num) / max(int(den), 1), 3)
            fmt = data.get("format", {})
            self._state.video_duration = float(fmt.get("duration", 0))
            audio_streams = sum(
                1 for s in data.get("streams", []) if s.get("codec_type") == "audio"
            )
            self._state.video_audio_tracks = audio_streams
        except Exception as e:
            self._log_message(f"ffprobe error: {e}", "warn")

    def on_analyze(self):
        """Start the full AI pipeline in a background worker thread."""
        if not self._state.video_path:
            return

        if self._worker and self._worker.isRunning():
            QMessageBox.warning(self, tr("msg_pipeline_running_title"),
                                tr("msg_pipeline_already_running"))
            return

        # Update pack info from panel
        pack_info = self._pack_info_panel.get_pack_info()
        if not pack_info.title:
            pack_info.title = self._state.video_path.stem
        self._state.pack_info = pack_info

        # Auto-incremental output dir setup
        from core.pack_builder import PackBuilder
        pack_name = PackBuilder.sanitize_pack_name(self._state.pack_info.title)
        out_opt = self._settings.get("output_dir", "")
        base = Path(out_opt) if out_opt else (self._state.video_path.parent / "output")
        self._output_dir = PackBuilder.get_unique_pack_dir(base, pack_name)

        # Build options from current settings
        options = build_options_from_settings(self._settings)
        options["output_dir"] = str(self._output_dir.parent)

        # Reset progress
        self._progress_panel.reset()
        self._progress_panel.setVisible(True)
        self.act_v_progress.setChecked(True)
        self._act_analyze.setEnabled(False)
        self._act_export.setEnabled(False)

        # Create and connect worker
        self._worker = PipelineWorker(self._state, options)
        self._worker.signals.step_started.connect(self._progress_panel.set_step)
        self._worker.signals.step_completed.connect(self._progress_panel.on_step_complete)
        self._worker.signals.step_failed.connect(
            lambda step, msg: self._progress_panel.on_step_error(step)
        )
        self._worker.signals.progress.connect(self._progress_panel.set_progress)
        self._worker.signals.log_message.connect(self._progress_panel.log)
        self._worker.signals.dialogues_ready.connect(self._on_dialogues_ready)
        self._worker.signals.finished.connect(self._on_pipeline_finished)
        self._worker.signals.cancelled.connect(
            lambda: self._progress_panel.log("Cancelled.", "warn")
        )

        # Sub-step progress (per-item)
        if hasattr(self._worker.signals, 'sub_progress') and hasattr(self._progress_panel, 'set_sub_progress'):
            self._worker.signals.sub_progress.connect(self._progress_panel.set_sub_progress)

        # Connect cancel button
        self._progress_panel.btn_cancel.setEnabled(True)
        self._progress_panel.btn_cancel.clicked.connect(self._on_cancel)

        # Connect elapsed time signal to progress panel
        if hasattr(self._worker.signals, 'elapsed_time') and hasattr(self._progress_panel, 'set_elapsed'):
            self._worker.signals.elapsed_time.connect(self._progress_panel.set_elapsed)

        # Connect pack_ready to auto-set output dir
        if hasattr(self._worker.signals, 'pack_ready'):
            self._worker.signals.pack_ready.connect(self._on_pack_ready)

        self._worker.start()

    def _on_dialogues_ready(self):
        """Called after VAD — populate table with initial segments."""
        self._dialogue_table.populate(self._state)
        self._speaker_panel.populate(self._state)
        self._timeline.populate(self._state)
        self._timeline.set_duration(self._state.video_duration)

    def _on_pipeline_finished(self):
        """Called when pipeline completes all steps."""
        self._dialogue_table.populate(self._state)
        self._speaker_panel.populate(self._state)
        self._timeline.populate(self._state)
        self._pack_info_panel.populate(self._state)
        self._act_analyze.setEnabled(True)
        self._act_export.setEnabled(True)
        self._progress_panel.btn_cancel.setEnabled(False)

        # Resolve actual output dir where clips and pack were generated
        if self._worker and self._worker.output_dir and self._worker.output_dir.exists():
            self._output_dir = self._worker.output_dir
        elif not self._output_dir or not self._output_dir.exists():
            from core.pack_builder import PackBuilder
            pack_name = PackBuilder.sanitize_pack_name(self._state.pack_info.title)
            out_opt = self._settings.get("output_dir", "")
            base = Path(out_opt) if out_opt else self._state.video_path.parent / "output"
            self._output_dir = PackBuilder.get_unique_pack_dir(base, pack_name)

        # One-Click Auto Export: create the final ZIP pack immediately
        from core.pack_builder import PackBuilder
        if self._output_dir and self._output_dir.exists():
            zip_path = self._output_dir.parent / f"{self._output_dir.name}.zip"
            try:
                self._log_message(f"Auto-exporting completed ZIP pack: {zip_path.name}...", "info")
                PackBuilder.export_zip(self._output_dir, zip_path)
                self._log_message(f"All-in-One Process Complete: {zip_path.name}", "ok")
                self._show_toast(
                    title=tr("msg_all_in_one_complete_title"),
                    msg=tr("msg_all_in_one_complete_desc", name=zip_path.name),
                    level="ok"
                )
            except Exception as e:
                self._log_message(f"Auto-export ZIP error: {e}", "warn")
                self._show_toast(
                    title=tr("msg_extraction_finished_title"),
                    msg=tr("msg_extraction_finished_desc"),
                    level="ok"
                )
        else:
            self._show_toast(
                title=tr("msg_extraction_finished_title"),
                msg=tr("msg_extraction_finished_desc"),
                level="ok"
            )

        self._mark_dirty(True)
        # Immediately auto-save project so newly extracted dialogues and pack data are persisted
        as_path = ProjectManager.auto_save(
            self._state,
            self._current_project_path,
            fallback_dir=Path.cwd() / "output"
        )
        if as_path:
            t = datetime.now().strftime("%H:%M:%S")
            self._status_save.setText(f"[Auto-saved {t}*]")
            self._status_save.setStyleSheet("color: #38bdf8; font-size: 8.5pt; padding-right: 12px;")
            self._log_message(f"Extraction results auto-saved to: {as_path.name}", "info")

    def _on_pack_ready(self, pack_dir_str: str):
        """Called when pipeline reports the pack output directory."""
        self._output_dir = Path(pack_dir_str)

    def _on_cancel(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._progress_panel.btn_cancel.setEnabled(False)
            self._act_analyze.setEnabled(True)

    def _ensure_all_clip_files_exist(self):
        """Ensures that all active dialogues have corresponding .m4a, .jpg, and .txt files in self._output_dir."""
        if not self._output_dir:
            return
        self._output_dir.mkdir(parents=True, exist_ok=True)
        from core.clip_generator import ClipGenerator
        from core.frame_extractor import FrameExtractor
        
        gen = ClipGenerator()
        ext = FrameExtractor(self._state.video_path) if (self._state.video_path and self._state.video_path.exists()) else None

        for d in self._state.active_dialogues():
            spk_name = self._state.get_speaker_safe_name(d.speaker_id)
            base_name = d.filename_base(spk_name)
            out_aud = self._output_dir / f"{base_name}.mp3"
            out_img = self._output_dir / f"{base_name}.png"
            out_txt = self._output_dir / f"{base_name}.txt"

            if not d.audio_path or not d.audio_path.exists():
                try:
                    gen.regenerate_clip(d, self._state, self._output_dir)
                except Exception:
                    pass

            if not d.image_path or not d.image_path.exists():
                if ext:
                    try:
                        frame = ext.find_best_frame(d.start, d.end, num_candidates=5)
                        if frame is not None:
                            ext.save_frame(frame, out_img)
                            d.image_path = out_img
                    except Exception:
                        pass
                if not d.image_path or not d.image_path.exists():
                    from PIL import Image
                    img = Image.new("RGB", (self._state.video_width or 1280, self._state.video_height or 720), (32, 32, 32))
                    img.save(out_img, "PNG")
                    d.image_path = out_img

            if not d.txt_path or not d.txt_path.exists():
                out_txt.write_text(d.caption or "", encoding="utf-8")
                d.txt_path = out_txt

        if ext:
            ext.release()

    def on_export(self):
        """Open Adobe-style Export Dialog with real-time progress, ETA, and background rendering."""
        from gui.export_dialog import ExportDialog
        dlg = ExportDialog(self, self._state, self._settings)
        dlg.exec_()

    def on_settings(self):
        dlg = SettingsDialog(self)
        dlg.load_settings(self._settings)
        if dlg.exec_():
            old_lang = i18n.current_language
            old_proxy_enabled = self._settings.get("preview_proxy_enabled", True)
            old_proxy_h = self._settings.get("preview_proxy_height", 540)

            self._settings = dlg.get_settings()
            self._save_settings(self._settings)
            self._timeline.set_sticky_headers(self._settings.get("timeline_sticky_headers", True))

            new_lang = self._settings.get("app_language", "en")
            if new_lang != old_lang:
                i18n.set_language(new_lang)
                self.retranslate_ui()

            new_proxy_enabled = self._settings.get("preview_proxy_enabled", True)
            new_proxy_h = self._settings.get("preview_proxy_height", 540)
            if self._state.video_path and (old_proxy_enabled != new_proxy_enabled or old_proxy_h != new_proxy_h):
                if not new_proxy_enabled or new_proxy_h == 0:
                    self._video_panel.switch_to_original()
                    self._state.preview_proxy_path = None
                else:
                    self._start_preview_proxy_generation(self._state.video_path)

    def retranslate_ui(self):
        """Retranslate all dynamic UI elements when the language setting changes."""
        # Menus
        if hasattr(self, '_menu_file'):
            self._menu_file.setTitle(tr("menu_file"))
            self._act_new_proj.setText(tr("menu_new_proj"))
            self._act_open_proj.setText(tr("menu_open_proj"))
            self._act_open_pack.setText(tr("menu_open_pack"))
            self._menu_recent_projects.setTitle(tr("menu_recent_proj"))
            self._act_save_proj.setText(tr("menu_save_proj"))
            self._act_save_proj_as.setText(tr("menu_save_proj_as"))
            self._act_import_menu.setText(tr("menu_import_video"))
            self._menu_recent_videos.setTitle(tr("menu_recent_videos"))
            self._act_export_menu.setText(tr("menu_export_pack"))
            self._act_quit.setText(tr("menu_quit"))

        if hasattr(self, '_menu_edit'):
            self._menu_edit.setTitle(tr("menu_edit"))
            self.act_undo.setText(tr("menu_undo"))
            self.act_redo.setText(tr("menu_redo"))
            self._act_kb_shortcuts.setText(tr("menu_shortcuts"))
            self._act_settings.setText(tr("menu_settings"))

        if hasattr(self, '_menu_view'):
            self._menu_view.setTitle(tr("menu_view"))
            self.act_fullscreen.setText(tr("menu_fullscreen"))
            self.act_v_video.setText(tr("menu_video_player"))
            self.act_v_sidebar.setText(tr("menu_sidebar_tabs"))
            self.act_v_timeline.setText(tr("menu_timeline"))
            self.act_v_clip_editor.setText(tr("menu_clip_editor"))
            self.act_v_progress.setText(tr("menu_processing_logs"))

        if hasattr(self, '_menu_help'):
            self._menu_help.setTitle(tr("menu_help"))
            self._act_shortcuts_help.setText(tr("menu_shortcuts"))
            self._act_about.setText(tr("menu_about"))

        self._rebuild_recent_projects_menu()
        self._rebuild_recent_videos_menu()

        # Toolbar
        if hasattr(self, '_act_import'):
            self._act_import.setText(tr("tb_import"))
            self._act_import.setToolTip(tr("tb_import_tip"))
            self._act_analyze.setText(tr("tb_analyze"))
            self._act_analyze.setToolTip(tr("tb_analyze_tip"))
            self._act_export.setText(tr("tb_export"))
            self._act_export.setToolTip(tr("tb_export_tip"))
            self._act_open_folder.setText(tr("tb_open_folder"))
            self._act_open_folder.setToolTip(tr("tb_open_folder_tip"))
            self._act_settings.setText(tr("tb_settings"))
            self._act_settings.setToolTip(tr("tb_settings_tip"))

        # Sidebar Tabs
        if hasattr(self, '_sidebar_tabs'):
            self._sidebar_tabs.setTabText(0, tr("tab_dialogues"))
            self._sidebar_tabs.setTabText(1, tr("tab_speakers"))
            self._sidebar_tabs.setTabText(2, tr("tab_pack_info"))

        # Timeline Header
        if hasattr(self, '_lbl_tl_title'):
            self._lbl_tl_title.setText(tr("tl_title"))
        if hasattr(self, '_btn_tl_undo'):
            self._btn_tl_undo.setToolTip(tr("tl_btn_undo_tip"))
            self._btn_tl_redo.setToolTip(tr("tl_btn_redo_tip"))
            self._btn_tl_split.setToolTip(tr("tl_btn_split_tip"))
            self._btn_tl_trim_left.setToolTip(tr("tl_btn_trim_left_tip"))
            self._btn_tl_trim_right.setToolTip(tr("tl_btn_trim_right_tip"))
            self._btn_tl_del_clip.setToolTip(tr("tl_btn_delete_tip"))
            self._btn_tl_add_track.setText(tr("tl_btn_add_track"))
            self._btn_tl_add_track.setToolTip(tr("tl_btn_add_track_tip"))
            self._btn_tl_add_clip.setText(tr("tl_btn_add_clip"))
            self._btn_tl_add_clip.setToolTip(tr("tl_btn_add_clip_tip"))
            self._btn_tl_play.setText(tr("tl_btn_play"))
            self._btn_tl_play.setToolTip(tr("tl_btn_play_tip"))
            self._btn_tl_stop.setText(tr("tl_btn_stop"))
            self._btn_tl_stop.setToolTip(tr("tl_btn_stop_tip"))
            self._btn_tl_zoomin.setText(tr("tl_btn_zoomin"))
            self._btn_tl_zoomin.setToolTip(tr("tl_btn_zoom_in_tip"))
            self._btn_tl_zoomout.setText(tr("tl_btn_zoomout"))
            self._btn_tl_zoomout.setToolTip(tr("tl_btn_zoom_out_tip"))

        # Clip Editor & Child Panels
        if hasattr(self, '_clip_editor'):
            self._clip_editor.retranslate_ui()
        if hasattr(self, '_dialogue_table'):
            self._dialogue_table.retranslate_ui()
        if hasattr(self, '_video_panel'):
            self._video_panel.retranslate_ui()
        if hasattr(self, '_speaker_panel'):
            self._speaker_panel.retranslate_ui()
        if hasattr(self, '_pack_info_panel'):
            self._pack_info_panel.retranslate_ui()
        if hasattr(self, '_progress_panel'):
            self._progress_panel.retranslate_ui()

        # Status Bar
        if hasattr(self, '_status_version'):
            self._status_version.setText(tr("status_version", version=APP_VERSION))
        if hasattr(self, '_status_video') and not self._state.video_path:
            self._status_video.setText(tr("status_no_video"))
        self._update_save_status()

    def _on_timeline_sticky_toggled(self, is_sticky: bool):
        self._settings["timeline_sticky_headers"] = is_sticky
        self._save_settings(self._settings)

    def _load_settings(self) -> dict:
        if SETTINGS_FILE.exists():
            try:
                return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_settings(self, settings: dict):
        try:
            SETTINGS_FILE.write_text(
                json.dumps(settings, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            self._log_message(f"Could not save settings: {e}", "warn")

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            reply = QMessageBox.question(
                self,
                tr("msg_pipeline_running_title"),
                tr("msg_pipeline_running_cancel_prompt"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._worker.cancel()
            self._worker.wait(3000)

        # Prompt for unsaved project changes
        if self._is_dirty and (self._state.video_path or self._state.dialogues):
            name = self._current_project_path.name if self._current_project_path else (self._state.pack_info.title or "Untitled Project")
            reply = QMessageBox.question(
                self,
                tr("msg_save_changes_title"),
                tr("msg_save_before_exit_named", name=name),
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save
            )
            if reply == QMessageBox.StandardButton.Save:
                if not self.on_save_project():
                    event.ignore()
                    return
            elif reply == QMessageBox.StandardButton.Discard:
                # Explicitly discard changes: clear dirty flag and delete temporary autosaves
                self._is_dirty = False
                try:
                    ProjectManager.delete_autosave(self._current_project_path or (self._state.video_path if self._state else None))
                except Exception:
                    pass
            elif reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return

        # Auto-save recovery backup before exit only if still dirty (e.g. abrupt close)
        if self._is_dirty and (self._state.video_path or self._state.dialogues):
            try:
                ProjectManager.auto_save(self._state, self._current_project_path)
            except Exception:
                pass

        event.accept()

    def _build_stylesheet(self) -> str:
        return f"""
        QMainWindow, QWidget {{
            background-color: {COLORS['bg_primary']};
            color: {COLORS['text_primary']};
            font-family: 'Segoe UI', system-ui, sans-serif;
            font-size: 9.5pt;
        }}
        QMenuBar {{
            background-color: #1a1a1a;
            color: #dcdcdc;
            border-bottom: 1px solid #2e2e2e;
            padding: 2px 6px;
        }}
        QMenuBar::item {{
            background-color: transparent;
            padding: 4px 10px;
            border-radius: 3px;
            color: #dcdcdc;
        }}
        QMenuBar::item:selected {{
            background-color: #383838;
            color: #ffffff;
        }}
        QMenuBar::item:pressed {{
            background-color: #444444;
            color: #ffffff;
        }}
        QMenu {{
            background-color: #222222;
            color: #dcdcdc;
            border: 1px solid #383838;
            border-radius: 4px;
            padding: 4px 0px;
        }}
        QMenu::item {{
            padding: 6px 28px 6px 14px;
            background-color: transparent;
        }}
        QMenu::item:selected {{
            background-color: #383838;
            color: #ffffff;
        }}
        QMenu::separator {{
            height: 1px;
            background-color: #333333;
            margin: 4px 8px;
        }}
        QCheckBox {{
            background: transparent;
            color: #e0e0e0;
            spacing: 6px;
        }}
        QCheckBox:hover {{
            color: #ffffff;
        }}
        QTabWidget::pane {{
            border: 1px solid {COLORS['border']};
            border-radius: 2px;
            background-color: {COLORS['bg_panel']};
            top: -1px;
        }}
        QTabBar::tab {{
            background-color: {COLORS['bg_secondary']};
            color: {COLORS['text_secondary']};
            border: 1px solid {COLORS['border']};
            border-bottom: none;
            border-top-left-radius: 2px;
            border-top-right-radius: 2px;
            padding: 6px 12px;
            margin-right: 1px;
            font-weight: 500;
        }}
        QTabBar::tab:selected {{
            background-color: {COLORS['bg_panel']};
            color: {COLORS['text_primary']};
            border-bottom: 2px solid {COLORS['accent']};
            font-weight: bold;
        }}
        QToolBar {{
            background-color: {COLORS['bg_secondary']};
            border-bottom: 1px solid {COLORS['border']};
            spacing: 6px;
            padding: 4px 10px;
        }}
        QToolBar QToolButton {{
            background-color: {COLORS['bg_input']};
            color: {COLORS['text_primary']};
            border: 1px solid {COLORS['border']};
            border-radius: 2px;
            padding: 4px 10px;
            font-weight: 500;
        }}
        QToolBar QToolButton:hover {{
            background-color: {COLORS['accent']};
            color: #ffffff;
        }}
        QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
            background-color: {COLORS['bg_input']};
            color: {COLORS['text_primary']};
            border: 1px solid {COLORS['border']};
            border-radius: 2px;
            padding: 4px 8px;
        }}
        QPushButton {{
            background-color: {COLORS['bg_input']};
            color: {COLORS['text_primary']};
            border: 1px solid {COLORS['border']};
            border-radius: 2px;
            padding: 5px 12px;
        }}
        QPushButton:hover {{
            background-color: {COLORS['accent']};
            color: #ffffff;
        }}
        QSplitter::handle {{ background-color: {COLORS['border']}; }}
        QFrame#panel, QFrame#editor_card {{
            background-color: {COLORS['bg_panel']};
            border: 1px solid {COLORS['border']};
            border-radius: 4px;
        }}
        QTableWidget {{
            background-color: #181818;
            color: #e0e0e0;
            gridline-color: #2e2e2e;
            border: 1px solid #383838;
            border-radius: 4px;
        }}
        QHeaderView::section {{
            background-color: #222222;
            color: #cccccc;
            font-weight: bold;
            font-size: 8.5pt;
            padding: 6px 8px;
            border: none;
            border-right: 1px solid #333333;
            border-bottom: 1px solid #333333;
        }}
        QTableCornerButton::section {{
            background-color: #222222;
            border: 1px solid #333333;
        }}
        QToolTip {{
            background-color: #18181b;
            color: #e4e4e7;
            border: 1px solid #3f3f46;
            border-radius: 6px;
            padding: 6px 10px;
            font-family: 'Segoe UI', system-ui, sans-serif;
            font-size: 8.5pt;
        }}
        """
