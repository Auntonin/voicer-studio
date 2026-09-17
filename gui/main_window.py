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
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QLabel, QPushButton, QToolBar, QStatusBar,
    QFileDialog, QFrame, QSizePolicy, QTextEdit, QPlainTextEdit, QLineEdit,
    QProgressBar, QApplication, QTabWidget, QMenuBar, QMenu,
    QMessageBox, QCheckBox, QGraphicsOpacityEffect, QScrollArea
)
from PySide6.QtCore import Qt, QSize, QTimer, QPropertyAnimation
from PySide6.QtGui import QAction, QIcon, QColor, QFont, QPalette

from config import (
    APP_NAME, APP_VERSION, COLORS, SETTINGS_FILE,
    WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT, WHISPER_MODEL_DEFAULT
)
from core.models import PipelineState, PipelineStep, UndoManager, SpeakerInfo, DialogueItem
from core.pipeline import PipelineWorker, ExportWorker, build_options_from_settings
from gui.dialogue_table import DialogueTable
from gui.clip_editor import ClipEditor
from gui.timeline_widget import TimelineWidget
from gui.speaker_panel import SpeakerPanel
from gui.progress_panel import ProgressPanel
from gui.pack_info_panel import PackInfoPanel
from gui.settings_dialog import SettingsDialog
from gui.preview_dialog import PreviewDialog
from gui.video_panel import VideoPanel


class MainWindow(QMainWindow):
    """
    Top-level application window — fully connected to pipeline, timeline, and video player.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.setStyleSheet(self._build_stylesheet())
        self.setAcceptDrops(True)

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
        self._output_dir: Path | None = None

        self._build_menubar()
        self._build_toolbar()
        self._build_central()
        self._build_statusbar()
        self._update_toolbar_state()
        
        self._apply_dark_title_bar()
        
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
            if path.suffix.lower() in {".mp4", ".mkv", ".mov", ".webm", ".avi"}:
                self.load_video(path)

    # ── Menu Bar & Toolbar ───────────────────────────────────────────────────

    def _build_menubar(self):
        menubar = self.menuBar()

        # File Menu
        menu_file = menubar.addMenu("File")
        act_import = menu_file.addAction("Import Video...")
        act_import.setShortcut("Ctrl+O")
        act_import.triggered.connect(self.on_import_video)

        self._menu_recent = menu_file.addMenu("Open Recent")
        self._rebuild_recent_menu()

        menu_file.addSeparator()

        act_export = menu_file.addAction("Export Pack ZIP...")
        act_export.setShortcut("Ctrl+E")
        act_export.triggered.connect(self.on_export)

        menu_file.addSeparator()
        act_quit = menu_file.addAction("Quit")
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)

        # Edit Menu (Undo / Redo)
        menu_edit = menubar.addMenu("Edit")
        
        self.act_undo = menu_edit.addAction("Undo")
        self.act_undo.setShortcut("Ctrl+Z")
        self.act_undo.triggered.connect(self.on_undo)

        self.act_redo = menu_edit.addAction("Redo")
        self.act_redo.setShortcut("Ctrl+Shift+Z")
        self.act_redo.triggered.connect(self.on_redo)

        menu_edit.addSeparator()
        act_settings = menu_edit.addAction("Settings...")
        act_settings.triggered.connect(self.on_settings)

        # View Menu (Toggle visibility of panels & Full Screen)
        menu_view = menubar.addMenu("View")

        self.act_fullscreen = menu_view.addAction("Full Screen")
        self.act_fullscreen.setShortcut("F11")
        self.act_fullscreen.setCheckable(True)
        self.act_fullscreen.setChecked(False)
        self.act_fullscreen.triggered.connect(self._toggle_fullscreen)

        menu_view.addSeparator()

        self.act_v_video = menu_view.addAction("Video Preview Player")
        self.act_v_video.setCheckable(True)
        self.act_v_video.setChecked(True)
        self.act_v_video.triggered.connect(lambda c: self._video_panel.setVisible(c))

        self.act_v_sidebar = menu_view.addAction("Sidebar Tabs (Dialogues / Speakers / Pack Info)")
        self.act_v_sidebar.setCheckable(True)
        self.act_v_sidebar.setChecked(True)
        self.act_v_sidebar.triggered.connect(lambda c: self._sidebar_tabs.setVisible(c))

        self.act_v_timeline = menu_view.addAction("Multi-Track Timeline")
        self.act_v_timeline.setCheckable(True)
        self.act_v_timeline.setChecked(True)
        self.act_v_timeline.triggered.connect(lambda c: self._timeline_container.setVisible(c))

        self.act_v_clip_editor = menu_view.addAction("Clip Editor")
        self.act_v_clip_editor.setCheckable(True)
        self.act_v_clip_editor.setChecked(True)
        self.act_v_clip_editor.triggered.connect(lambda c: self._clip_editor.setVisible(c))

        self.act_v_progress = menu_view.addAction("Processing Logs")
        self.act_v_progress.setCheckable(True)
        self.act_v_progress.setChecked(False)
        self.act_v_progress.triggered.connect(lambda c: self._progress_panel.setVisible(c))

        # Help Menu
        menu_help = menubar.addMenu("Help")
        act_about = menu_help.addAction("About")
        act_about.triggered.connect(self._show_about_dialog)

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
            f"About {APP_NAME}",
            f"<b>{APP_NAME}</b><br/>"
            f"Version {APP_VERSION}<br/><br/>"
            "An offline dialogue extraction suite tailored for <b>The Choice Voicer</b> game dialogue pack format.<br/><br/>"
            "• Faster-Whisper Speech Recognition<br/>"
            "• Silero VAD & Pyannote Diarization<br/>"
            "• RoFormer & Demucs Audio Stem Separation<br/>"
            "• Lossless Frame Extraction<br/><br/>"
            "Developed with Python & PySide6."
        )

    def _build_toolbar(self):
        tb = QToolBar("Main Toolbar")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(tb)

        def act(label: str, slot, shortcut: str = "", tip: str = "") -> QAction:
            a = QAction(label, self)
            if shortcut:
                a.setShortcut(shortcut)
            if tip:
                a.setToolTip(tip)
            a.triggered.connect(slot)
            return a

        self._act_import      = act("Import Video",          self.on_import_video,       "Ctrl+O", "Import a video file")
        self._act_analyze     = act("Analyze",                self.on_analyze,            "Ctrl+R", "One-Click: Run audio separation, speech extraction, and auto-export ZIP pack")
        self._act_export      = act("Export Pack ZIP",       self.on_export,             "Ctrl+E", "Export The Choice Voicer pack")
        self._act_open_folder = act("Open Output Folder",    self.on_open_export_folder, "",       "Open output folder in Explorer")
        self._act_settings    = act("Settings",              self.on_settings,           "",       "Application settings")

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

        top_h_splitter.addWidget(self._video_panel)

        # Right Sidebar QTabWidget
        self._sidebar_tabs = QTabWidget()
        
        self._dialogue_table = DialogueTable()
        self._sidebar_tabs.addTab(self._dialogue_table, "Dialogues")
        
        self._speaker_panel = SpeakerPanel()
        self._sidebar_tabs.addTab(self._speaker_panel, "Speakers")
        
        self._pack_info_panel = PackInfoPanel()
        self._sidebar_tabs.addTab(self._pack_info_panel, "Pack Info")
        
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

        # Timeline Header Controls Bar
        tl_header = QHBoxLayout()
        tl_title = QLabel("MULTI-TRACK TIMELINE", objectName="section_title")
        tl_title.setStyleSheet("font-size: 9.5pt; font-weight: bold; color: #ffffff; background: transparent; border-left: 3px solid #1473E6; padding-left: 8px;")
        tl_header.addWidget(tl_title)

        # Hotkey legend badges
        legend_label = QLabel(
            '<span style="color:#888;">Shortcuts: </span>'
            '<b style="color:#58a6ff;">Space</b> Play/Pause &nbsp;'
            '<b style="color:#58a6ff;">Ctrl+Z</b> Undo &nbsp;'
            '<b style="color:#58a6ff;">S</b> Split &nbsp;'
            '<b style="color:#58a6ff;">M</b> Merge &nbsp;'
            '<b style="color:#58a6ff;">Del</b> Delete'
        )
        legend_label.setStyleSheet("font-size: 8.5pt; padding-left: 16px; padding-right: 16px; margin-left: 12px;")
        tl_header.addWidget(legend_label)
        tl_header.addStretch()

        # Track & Clip manual management buttons
        btn_tl_add_track = QPushButton("[+] Add Track")
        btn_tl_del_track = QPushButton("[-] Delete Track")
        btn_tl_add_clip  = QPushButton("[+] Add Clip")
        
        btn_tl_play    = QPushButton("Play")
        btn_tl_stop    = QPushButton("Stop")
        btn_tl_zoomin  = QPushButton("Zoom +")
        btn_tl_zoomout = QPushButton("Zoom -")
        
        btn_tl_add_track.setToolTip("Add new character track")
        btn_tl_del_track.setToolTip("Delete last character track")
        btn_tl_add_clip.setToolTip("Add new audio clip on selected track")

        btn_tl_play.setToolTip("Play overall timeline audio (Space)")
        btn_tl_stop.setToolTip("Stop playback")

        tl_header.addWidget(btn_tl_add_track)
        tl_header.addWidget(btn_tl_del_track)
        tl_header.addWidget(btn_tl_add_clip)
        tl_header.addSpacing(12)
        tl_header.addWidget(btn_tl_play)
        tl_header.addWidget(btn_tl_stop)
        tl_header.addWidget(btn_tl_zoomin)
        tl_header.addWidget(btn_tl_zoomout)

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

        self._main_v_splitter.addWidget(self._timeline_container)

        # Connect Timeline Header buttons
        btn_tl_add_track.clicked.connect(self._on_add_track)
        btn_tl_del_track.clicked.connect(self._on_delete_last_track)
        btn_tl_add_clip.clicked.connect(self._on_add_clip)

        btn_tl_play.clicked.connect(self._toggle_global_playback)
        btn_tl_stop.clicked.connect(self._stop_global_playback)
        btn_tl_zoomin.clicked.connect(self._timeline.zoom_in)
        btn_tl_zoomout.clicked.connect(self._timeline.zoom_out)

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

        # ── Connect Dialogue Table Signals ──
        self._dialogue_table.dialogue_selected.connect(
            lambda item: self._clip_editor.load_item(item, self._state)
        )
        self._dialogue_table.dialogue_selected.connect(
            lambda item: self._on_select_dialogue(item)
        )
        self._dialogue_table.dialogue_deleted.connect(self._on_dialogue_deleted)
        self._dialogue_table.merge_next_requested.connect(self._on_merge_next)
        self._dialogue_table.split_requested.connect(self._on_split)

        # ── Connect Timeline Signals ──
        self._timeline.segment_selected.connect(self._select_dialogue_by_idx)
        self._timeline.segment_moved.connect(self._on_timeline_segment_moved)
        self._timeline.seek_requested.connect(self._on_timeline_seek)
        self._timeline.playhead_tick.connect(self._video_panel.set_position)
        self._video_panel.position_changed.connect(self._timeline.set_current_time)
        self._timeline.split_requested.connect(self._on_split)
        self._timeline.merge_requested.connect(self._on_merge_next)
        self._timeline.delete_requested.connect(self._on_dialogue_deleted)

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

    def _on_video_seek(self, t: float):
        self._timeline.set_current_time(t)

    def _on_timeline_seek(self, t: float):
        if self._video_panel.is_playing():
            self._video_panel.pause_playback()
        self._timeline.set_current_time(t)
        self._video_panel.set_position(t)
        for item in self._state.active_dialogues():
            if item.start <= t <= item.end:
                if not self._clip_editor.item or self._clip_editor.item.index != item.index:
                    self._clip_editor.load_item(item, self._state)
                    self._set_active_speaker(item.speaker_id)
                break

    def _on_select_dialogue(self, item: DialogueItem):
        self._timeline.set_current_time(item.start)
        self._video_panel.set_position(item.start)
        self._set_active_speaker(item.speaker_id)

    def _select_dialogue_by_idx(self, idx: int):
        for item in self._state.active_dialogues():
            if item.index == idx:
                self._clip_editor.load_item(item, self._state)
                self._video_panel.set_position(item.start)
                self._set_active_speaker(item.speaker_id)
                break

    # ── Undo / Redo Actions ──────────────────────────────────────────────────

    def on_undo(self):
        if self._undo_manager.undo(self._state):
            self._refresh_all_views()
            self._log_message("Undo executed", "info")

    def on_redo(self):
        if self._undo_manager.redo(self._state):
            self._refresh_all_views()
            self._log_message("Redo executed", "info")

    def _push_undo(self):
        self._undo_manager.push(self._state)

    # ── Manual Track & Speaker Handlers ──────────────────────────────────────

    def _on_add_track(self):
        self._push_undo()
        existing_indices = []
        for sid in self._state.speakers.keys():
            if sid.startswith("SPEAKER_"):
                try:
                    existing_indices.append(int(sid.replace("SPEAKER_", "")))
                except ValueError:
                    pass
        next_idx = max(existing_indices, default=-1) + 1
        new_spk_id = f"SPEAKER_{next_idx:02d}"
        
        self._state.speakers[new_spk_id] = SpeakerInfo(
            speaker_id=new_spk_id,
            display_name=f"Speaker {next_idx + 1}"
        )
        if new_spk_id not in self._state.speaker_order:
            self._state.speaker_order.append(new_spk_id)
            
        self._active_speaker_id = new_spk_id
        self._refresh_all_views()
        self._log_message(f"Added track '{new_spk_id}'", "ok")

    def _on_delete_last_track(self):
        if len(self._state.speakers) <= 1:
            QMessageBox.warning(self, "Delete Track", "Cannot delete the last remaining track.")
            return
        last_spk = self._state.get_speaker_order()[-1]
        self._on_delete_track(last_spk)

    def _on_delete_track(self, spk_id: str):
        if spk_id in self._state.speakers:
            if len(self._state.speakers) <= 1:
                QMessageBox.warning(self, "Delete Speaker", "Cannot delete the last remaining speaker track.")
                return
            spk_info = self._state.speakers[spk_id]
            reply = QMessageBox.question(
                self,
                "Confirm Delete Speaker",
                f"Are you sure you want to delete speaker '{spk_info.display_name}' ({spk_id})?\n"
                "All dialogue clips on this track will be reassigned to the default track.",
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
            caption="New Dialogue"
        )
        self._state.dialogues.append(new_d)
        self._state.renumber()
        self._refresh_all_views()
        self._log_message(f"Added new dialogue clip #{new_d.index} for speaker {spk_id}", "ok")

    def _on_speaker_added(self, spk_id: str):
        self._push_undo()
        self._active_speaker_id = spk_id
        self._refresh_all_views()

    def _on_speaker_deleted(self, spk_id: str):
        self._on_delete_track(spk_id)

    # ── Keyboard Shortcuts (Spacebar & Undo) ──────────────────────────────────

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

    def _on_dialogue_deleted(self, idx: int):
        self._push_undo()
        for item in self._state.dialogues:
            if item.index == idx:
                item.is_deleted = True
                break
        self._state.renumber()
        self._clip_editor.clear()
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
        self._refresh_all_views()

    def _on_caption_changed(self, idx: int, text: str):
        self._push_undo()
        for d in self._state.active_dialogues():
            if d.index == idx:
                d.caption = text
                break
        self._dialogue_table.populate(self._state)

    def _on_speaker_changed(self, idx: int, spk_id: str):
        if not spk_id: return
        self._push_undo()
        self._active_speaker_id = spk_id
        for d in self._state.active_dialogues():
            if d.index == idx:
                d.speaker_id = spk_id
                break
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

        self._dialogue_table.populate(self._state)
        self._timeline.populate(self._state)

    def _on_timeline_segment_moved(self, idx: int, start: float, end: float):
        self._on_timestamps_changed(idx, start, end)
        for d in self._state.active_dialogues():
            if d.index == idx:
                self._clip_editor.load_item(d, self._state)
                break

    def _on_speaker_renamed(self, spk_id: str, new_name: str):
        self._push_undo()
        self._dialogue_table.populate(self._state)
        self._timeline.populate(self._state)

    def _on_regen_audio(self, idx: int):
        for d in self._state.active_dialogues():
            if d.index == idx:
                try:
                    from core.clip_generator import ClipGenerator
                    gen = ClipGenerator()
                    out_dir = self._output_dir or (self._state.video_path.parent / "output" / "pack")
                    gen.regenerate_clip(d, self._state, out_dir)
                    self._dialogue_table.populate(self._state)
                    self._clip_editor.load_item(d, self._state)
                    self._log_message(f"Regenerated audio for clip #{d.index}", "ok")
                except Exception as e:
                    self._log_message(f"Error regenerating clip: {e}", "error")
                break

    def _on_regen_caption(self, idx: int):
        for d in self._state.active_dialogues():
            if d.index == idx:
                try:
                    from core.transcriber import Transcriber
                    t = Transcriber(
                        model_size=self._settings.get("whisper_model", WHISPER_MODEL_DEFAULT),
                        language=self._settings.get("whisper_language")
                    )
                    t.load_model()
                    audio_src = self._state.work_audio_path
                    if audio_src and audio_src.exists():
                        d.caption = t.transcribe_segment(audio_src, d.start, d.end)
                        self._dialogue_table.populate(self._state)
                        self._clip_editor.load_item(d, self._state)
                        self._log_message(f"Regenerated caption for clip #{d.index}", "ok")
                except Exception as e:
                    self._log_message(f"Error transcribing clip: {e}", "error")
                break

    def _on_change_image(self, idx: int):
        for d in self._state.active_dialogues():
            if d.index == idx:
                try:
                    from core.frame_extractor import FrameExtractor
                    if self._state.video_path and self._state.video_path.exists():
                        ext = FrameExtractor(self._state.video_path)
                        frame = ext.find_best_frame(d.start, d.end, num_candidates=9)
                        if frame is not None and self._output_dir:
                            spk_name = self._state.get_speaker_safe_name(d.speaker_id)
                            out_img = self._output_dir / f"{d.id_str}_{spk_name}.png"
                            ext.save_frame(frame, out_img)
                            d.image_path = out_img
                            self._dialogue_table.populate(self._state)
                            self._clip_editor.load_item(d, self._state)
                            self._pack_info_panel.populate(self._state)
                            self._log_message(f"Extracted new frame for clip #{d.index}", "ok")
                except Exception as e:
                    self._log_message(f"Error changing image: {e}", "error")
                break

    # ── Status Bar ───────────────────────────────────────────────────────────

    def _build_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._status_video = QLabel("No video loaded")
        self._status_version = QLabel(f"v{APP_VERSION}  |  The Choice Voicer Dialogue Extractor")
        sb.addWidget(self._status_video)
        sb.addPermanentWidget(self._status_version)

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

    def _rebuild_recent_menu(self):
        if not hasattr(self, "_menu_recent"):
            return
        self._menu_recent.clear()
        recents = self._settings.get("recent_videos", [])
        if not recents:
            act = self._menu_recent.addAction("No Recent Files")
            act.setEnabled(False)
            return

        for p_str in recents:
            p = Path(p_str)
            if p.exists():
                act = self._menu_recent.addAction(f"{p.name}  ({p.parent})")
                act.triggered.connect(lambda _, path=p: self.load_video(path))

        self._menu_recent.addSeparator()
        act_clear = self._menu_recent.addAction("Clear Recent List")
        act_clear.triggered.connect(self._clear_recent_videos)

    def _add_recent_video(self, path_str: str):
        recents = self._settings.get("recent_videos", [])
        if path_str in recents:
            recents.remove(path_str)
        recents.insert(0, path_str)
        self._settings["recent_videos"] = recents[:10]
        self._save_settings(self._settings)
        self._rebuild_recent_menu()

    def _clear_recent_videos(self):
        self._settings["recent_videos"] = []
        self._save_settings(self._settings)
        self._rebuild_recent_menu()

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
        self._log_message(f"Video loaded: {path.name}", "ok")

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
        self._update_toolbar_state()

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
                self, "Export Folder",
                f"Output directory does not exist yet:\n{out_dir or 'Not specified'}"
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
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-print_format", "json",
                    "-show_streams", "-show_format",
                    str(path),
                ],
                capture_output=True, text=True, timeout=15,
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
            QMessageBox.warning(self, "Pipeline Running",
                                "Analysis is already in progress.")
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
                    title="All-in-One Process Complete",
                    msg=f"Pack exported: {zip_path.name}",
                    level="ok"
                )
            except Exception as e:
                self._log_message(f"Auto-export ZIP error: {e}", "warn")
                self._show_toast(
                    title="Dialogue Extraction Finished",
                    msg="Pack folder created successfully.",
                    level="ok"
                )
        else:
            self._show_toast()

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
        """Show PreviewDialog then export ZIP."""
        from core.pack_builder import PackBuilder
        title = self._state.pack_info.title or (self._state.video_path.stem if self._state.video_path else "Dialogue_Pack")
        base = Path(self._settings.get("output_dir", "")) if self._settings.get("output_dir", "") else (self._state.video_path.parent / "output" if self._state.video_path else Path.cwd() / "output")
        
        builder = PackBuilder()
        options = {
            "timestamp_mode": self._settings.get("timestamp_mode", "start_only"),
            "include_dub_video": self._state.pack_info.include_dub_video
        }
        self._output_dir = builder.build_pack(self._state, base, options)

        # Run quality check
        from core.quality_checker import QualityChecker
        checker = QualityChecker()
        results = checker.check_all(self._state, self._output_dir)

        # Convert to (icon, message) tuples for PreviewDialog
        check_tuples = []
        for r in results:
            icon = {"ok": "OK", "warn": "WARN", "error": "FAIL"}.get(r.level, "·")
            check_tuples.append((icon, r.message))

        dlg = PreviewDialog(self)
        dlg.export_confirmed.connect(self._do_export_zip)
        dlg.show_for_state(self._state, self._output_dir, check_tuples)

    def _do_export_zip(self, _dummy: str):
        """Run ExportWorker after preview dialog confirms."""
        from core.pack_builder import PackBuilder
        title = self._state.pack_info.title or (self._state.video_path.stem if self._state.video_path else "Dialogue_Pack")
        base_dir = self._state.video_path.parent if self._state.video_path else Path.cwd()
        suggested_zip = PackBuilder.get_unique_zip_path(base_dir, title)

        zip_name, _ = QFileDialog.getSaveFileName(
            self, "Save Pack ZIP",
            str(suggested_zip),
            "ZIP files (*.zip)",
        )
        if not zip_name:
            return

        zip_p = Path(zip_name)
        self._export_worker = ExportWorker(self._output_dir, zip_p)
        self._export_worker.log_msg.connect(self._progress_panel.log)
        self._export_worker.progress.connect(self._progress_panel.set_progress)

        def on_finished(p_str: str):
            self._log_message(f"Pack ZIP Exported: {p_str}", "ok")
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Export Complete")
            msg_box.setText(
                f"<b>Pack exported successfully!</b><br/><br/>"
                f"<b>ZIP Archive:</b> {p_str}<br/>"
                f"<b>Pack Directory:</b> {self._output_dir}"
            )
            btn_open = msg_box.addButton("Open Output Folder", QMessageBox.ButtonRole.AcceptRole)
            btn_ok = msg_box.addButton("OK", QMessageBox.ButtonRole.RejectRole)
            msg_box.exec_()
            if msg_box.clickedButton() == btn_open:
                self.on_open_export_folder()

        self._export_worker.finished.connect(on_finished)
        self._export_worker.error.connect(
            lambda e: QMessageBox.critical(self, "Export Error", e)
        )
        self._export_worker.start()

    def on_settings(self):
        dlg = SettingsDialog(self)
        dlg.load_settings(self._settings)
        if dlg.exec_():
            self._settings = dlg.get_settings()
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
            self._worker.cancel()
            self._worker.wait(3000)
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
        """
