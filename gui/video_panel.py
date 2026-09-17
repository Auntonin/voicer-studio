"""
gui/video_panel.py
==================
Video Player & Preview Panel — synchronized with NLE timeline.
"""

from pathlib import Path
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QSlider, QStackedLayout, QWidget
)
from PySide6.QtCore import Qt, Signal, QUrl, QTime
from PySide6.QtGui import QFont, QDragEnterEvent, QDropEvent, QPixmap
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

from core.models import PipelineState
from config import COLORS


class VideoPanel(QFrame):
    """
    Video player panel — displays live video playback synced with audio timeline,
    or drop zone target when no video is loaded.
    """
    seek_requested = Signal(float)
    position_changed = Signal(float)
    video_dropped = Signal(Path)
    playback_toggled = Signal(bool)
    browse_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setAcceptDrops(True)
        self.setMinimumWidth(380)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._video_path: Path | None = None
        self._is_user_seeking = False

        # ── QMediaPlayer Setup ─────────────────────────────────────────
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)

        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background-color: #000000; border-radius: 6px;")
        self.player.setVideoOutput(self.video_widget)

        self.player.positionChanged.connect(self._on_player_position_changed)
        self.player.durationChanged.connect(self._on_player_duration_changed)

        # ── Main Layout ─────────────────────────────────────────────────
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        # Header Title Bar
        header = QHBoxLayout()
        lbl_title = QLabel("VIDEO PREVIEW PLAYER")
        lbl_title.setObjectName("section_title")
        lbl_title.setStyleSheet("font-size: 9.5pt; font-weight: bold; color: #ffffff; background: transparent; border-left: 3px solid #1473E6; padding-left: 8px;")
        header.addWidget(lbl_title)
        header.addStretch()

        self.lbl_time_code = QLabel("00:00.000 / 00:00.000")
        self.lbl_time_code.setStyleSheet(f"font-family: monospace; font-size: 9pt; color: {COLORS['text_secondary']};")
        header.addWidget(self.lbl_time_code)

        main_layout.addLayout(header)

        # ── Stacked Widget (Hero Drop Card vs Live Video) ───────────────────
        self._stack_container = QWidget()
        self._stack_layout = QStackedLayout(self._stack_container)
        self._stack_layout.setContentsMargins(0, 0, 0, 0)

        # Page 0: Hero Drop Card
        self._drop_widget = QFrame()
        self._drop_widget.setStyleSheet(f"""
            QFrame {{
                background-color: #191919;
                border: 2px dashed #333333;
                border-radius: 10px;
            }}
            QFrame:hover {{
                border-color: {COLORS['accent']};
                background-color: #202020;
            }}
        """)
        drop_layout = QVBoxLayout(self._drop_widget)
        drop_layout.setContentsMargins(32, 32, 32, 32)
        drop_layout.setSpacing(12)

        lbl_badge = QLabel("MEDIA IMPORT")
        lbl_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_badge.setStyleSheet("""
            font-size: 8pt;
            font-weight: bold;
            color: #888888;
            background-color: #242426;
            border: 1px solid #383838;
            border-radius: 3px;
            padding: 3px 12px;
            letter-spacing: 1.5px;
        """)

        badge_container = QHBoxLayout()
        badge_container.addStretch()
        badge_container.addWidget(lbl_badge)
        badge_container.addStretch()

        lbl_drag = QLabel("Drop Video File to Begin")
        lbl_drag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_drag.setStyleSheet("font-size: 14pt; font-weight: bold; color: #ffffff; background: transparent; border: none;")

        lbl_sub = QLabel("Supports: MP4, MKV, MOV, WEBM, AVI\nAudio separation & dialogue extraction pipeline")
        lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_sub.setStyleSheet("font-size: 9pt; color: #888888; line-height: 1.4; background: transparent; border: none;")

        self.btn_browse = QPushButton("  Browse Video File...  ")
        self.btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browse.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['accent']};
                color: #ffffff;
                font-weight: bold;
                font-size: 9.5pt;
                padding: 8px 20px;
                border-radius: 4px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_hover']};
            }}
        """)
        self.btn_browse.clicked.connect(lambda: self.browse_requested.emit())

        btn_container = QHBoxLayout()
        btn_container.addStretch()
        btn_container.addWidget(self.btn_browse)
        btn_container.addStretch()

        drop_layout.addStretch()
        drop_layout.addLayout(badge_container)
        drop_layout.addWidget(lbl_drag)
        drop_layout.addWidget(lbl_sub)
        drop_layout.addSpacing(6)
        drop_layout.addLayout(btn_container)
        drop_layout.addStretch()

        self._stack_layout.addWidget(self._drop_widget)

        # Page 1: Live Video Player
        self._player_container = QWidget()
        player_layout = QVBoxLayout(self._player_container)
        player_layout.setContentsMargins(0, 0, 0, 0)
        player_layout.setSpacing(6)
        player_layout.addWidget(self.video_widget, stretch=1)

        self._stack_layout.addWidget(self._player_container)

        main_layout.addWidget(self._stack_container, stretch=1)

        # ── Player Transport Controls Bar ──────────────────────────────
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)

        self.btn_play = QPushButton("Play")
        self.btn_stop = QPushButton("Stop")
        self.btn_play.setFixedWidth(68)
        self.btn_stop.setFixedWidth(68)

        self.btn_play.clicked.connect(self.toggle_playback)
        self.btn_stop.clicked.connect(self.stop_playback)

        controls.addWidget(self.btn_play)
        controls.addWidget(self.btn_stop)

        # Seek slider
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.seek_slider.sliderPressed.connect(self._on_slider_pressed)
        self.seek_slider.sliderReleased.connect(self._on_slider_released)
        controls.addWidget(self.seek_slider, stretch=1)

        main_layout.addLayout(controls)

        # Info summary label
        self._info_label = QLabel("")
        self._info_label.setObjectName("subheading")
        self._info_label.setStyleSheet(f"font-size: 8.5pt; color: {COLORS['text_secondary']};")
        self._info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self._info_label)

    # ── Drop Event Handlers ────────────────────────────────────────────

    def set_main_window(self, mw):
        self._main_window = mw

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(f"QFrame#panel {{ border: 2px solid {COLORS['accent']}; }}")

    def dragLeaveEvent(self, event):
        self.setStyleSheet("")

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet("")
        urls = event.mimeData().urls()
        if urls:
            path = Path(urls[0].toLocalFile())
            self.video_dropped.emit(path)

    # ── Player Actions ─────────────────────────────────────────────────

    def load_video(self, path: Path):
        self._video_path = path
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self._stack_layout.setCurrentIndex(1)
        self.btn_play.setText("Play")

    def show_video_info(self, state: PipelineState):
        name = state.video_path.name if state.video_path else "—"
        dur_m = int(state.video_duration // 60)
        dur_s = state.video_duration % 60
        self._info_label.setText(
            f"File: {name}  |  Duration: {dur_m:02d}:{dur_s:05.2f}  |  "
            f"Resolution: {state.video_width}x{state.video_height} @ {state.video_fps:.2f} fps"
        )

    def set_position(self, sec: float):
        """Seek player position without triggering recursive signals."""
        pos_ms = int(sec * 1000)
        if self.is_playing():
            # Do NOT force player.setPosition during playback — player advances naturally!
            self._update_time_code(pos_ms, self.player.duration())
            return
        if not self._is_user_seeking:
            self.player.setPosition(pos_ms)
            self._update_time_code(pos_ms, self.player.duration())

    def toggle_playback(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.pause_playback()
        else:
            self.start_playback()

    def start_playback(self):
        if self._video_path and self._video_path.exists():
            # Mute video player audio stream so master timeline audio is the single source
            self.audio_output.setMuted(True)
            self.player.play()
            self.btn_play.setText("Pause")
            self.playback_toggled.emit(True)

    def pause_playback(self):
        self.player.pause()
        self.btn_play.setText("Play")
        self.playback_toggled.emit(False)

    def stop_playback(self):
        self.player.stop()
        self.btn_play.setText("Play")
        self.playback_toggled.emit(False)

    def is_playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    # ── Internal Player Handlers ──────────────────────────────────────

    def _on_player_position_changed(self, pos_ms: int):
        dur_ms = self.player.duration()
        self._update_time_code(pos_ms, dur_ms)
        if dur_ms > 0 and not self._is_user_seeking:
            self.seek_slider.blockSignals(True)
            val = int((pos_ms / dur_ms) * 1000)
            self.seek_slider.setValue(val)
            self.seek_slider.blockSignals(False)
            if self.is_playing():
                self.position_changed.emit(pos_ms / 1000.0)
        elif self._is_user_seeking and dur_ms > 0:
            self.seek_requested.emit(pos_ms / 1000.0)


    def _on_player_duration_changed(self, dur_ms: int):
        self._update_time_code(self.player.position(), dur_ms)

    def _on_slider_pressed(self):
        self._is_user_seeking = True

    def _on_slider_released(self):
        self._is_user_seeking = False
        dur_ms = self.player.duration()
        if dur_ms > 0:
            val = self.seek_slider.value()
            target_ms = int((val / 1000.0) * dur_ms)
            self.player.setPosition(target_ms)
            self.seek_requested.emit(target_ms / 1000.0)

    def _update_time_code(self, pos_ms: int, dur_ms: int):
        pos_s = pos_ms / 1000.0
        dur_s = dur_ms / 1000.0
        pm, ps = divmod(int(pos_s), 60)
        pms = int((pos_s - int(pos_s)) * 1000)
        dm, ds = divmod(int(dur_s), 60)
        dms = int((dur_s - int(dur_s)) * 1000)
        self.lbl_time_code.setText(f"{pm:02d}:{ps:02d}.{pms:03d} / {dm:02d}:{ds:02d}.{dms:03d}")

    def reset(self):
        self.player.stop()
        self.player.setSource(QUrl())
        self._stack_layout.setCurrentIndex(0)
        self._info_label.setText("")
        self.btn_play.setText("Play")
