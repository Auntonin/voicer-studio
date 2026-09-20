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
from core.i18n import tr


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
    toggle_proxy_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setAcceptDrops(True)
        self.setMinimumWidth(380)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._video_path: Path | None = None
        self._proxy_path: Path | None = None
        self._is_using_proxy: bool = False
        self._proxy_height: int = 540
        self._is_user_seeking = False
        self._last_slider_seek_time = 0.0
        self._last_direct_seek_time = 0.0
        self._current_badge_status = "ORIGINAL"

        # ── QMediaPlayer Setup ─────────────────────────────────────────
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)

        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background-color: #000000; border-radius: 6px;")
        self.player.setVideoOutput(self.video_widget)

        self.player.positionChanged.connect(self._on_player_position_changed)
        self.player.durationChanged.connect(self._on_player_duration_changed)
        self.player.errorOccurred.connect(self._on_player_error)

        # ── Main Layout ─────────────────────────────────────────────────
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        # Header Title Bar
        header = QHBoxLayout()
        self.lbl_title = QLabel(tr("vp_title"))
        self.lbl_title.setObjectName("section_title")
        self.lbl_title.setStyleSheet("font-size: 9.5pt; font-weight: bold; color: #ffffff; background: transparent; border-left: 3px solid #1473E6; padding-left: 8px;")
        header.addWidget(self.lbl_title)

        self.lbl_proxy_badge = QPushButton(f"[{tr('vp_badge_original')}]")
        self.lbl_proxy_badge.setObjectName("proxy_badge")
        self.lbl_proxy_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_proxy_badge.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lbl_proxy_badge.clicked.connect(self._on_proxy_badge_clicked)
        self._update_badge("ORIGINAL")
        header.addWidget(self.lbl_proxy_badge)
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

        self.lbl_badge = QLabel(tr("vp_badge_media_import"))
        self.lbl_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_badge.setStyleSheet("""
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
        badge_container.addWidget(self.lbl_badge)
        badge_container.addStretch()

        self.lbl_drag = QLabel(tr("vp_drop_title"))
        self.lbl_drag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_drag.setStyleSheet("font-size: 14pt; font-weight: bold; color: #ffffff; background: transparent; border: none;")

        self.lbl_sub = QLabel(tr("vp_drop_sub"))
        self.lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_sub.setStyleSheet("font-size: 9pt; color: #888888; line-height: 1.4; background: transparent; border: none;")

        self.btn_browse = QPushButton(tr("vp_browse_btn"))
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
        drop_layout.addWidget(self.lbl_drag)
        drop_layout.addWidget(self.lbl_sub)
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

        self.btn_play = QPushButton(tr("vp_btn_play"))
        self.btn_stop = QPushButton(tr("vp_btn_stop"))
        self.btn_play.setMinimumWidth(68)
        self.btn_stop.setMinimumWidth(68)
        self.btn_play.setToolTip(tr("tip_sc_space"))
        self.btn_stop.setToolTip(tr("vp_btn_stop"))

        self.btn_play.clicked.connect(self.toggle_playback)
        self.btn_stop.clicked.connect(self.stop_playback)

        controls.addWidget(self.btn_play)
        controls.addWidget(self.btn_stop)

        # Seek slider
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.seek_slider.sliderPressed.connect(self._on_slider_pressed)
        self.seek_slider.sliderMoved.connect(self._on_slider_moved)
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

    # ── Player Actions & Proxy ─────────────────────────────────────────

    def load_video(self, path: Path):
        self._video_path = path
        self._proxy_path = None
        self._is_using_proxy = False
        self._update_badge("ORIGINAL")
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self._stack_layout.setCurrentIndex(1)
        self.btn_play.setText(tr("vp_btn_play"))

    def set_status_generating(self):
        """Show that the proxy is being actively created in background."""
        self._update_badge("GENERATING")

    def set_proxy_video(self, proxy_path: Path, height: int = 540):
        """Seamlessly hot-swap to the lightweight fast-seek proxy video."""
        if not proxy_path.exists():
            return
        self._proxy_path = proxy_path
        self._proxy_height = height
        self._is_using_proxy = True
        cur_pos = self.player.position()
        was_playing = self.is_playing()

        self.player.setSource(QUrl.fromLocalFile(str(proxy_path)))
        self.player.setPosition(cur_pos)
        if was_playing:
            self.player.play()

        self._update_badge("PROXY", height)

    def switch_to_original(self):
        """Switch video player back to the full-resolution original video."""
        if not self._video_path or not self._video_path.exists():
            return
        self._is_using_proxy = False
        cur_pos = self.player.position()
        was_playing = self.is_playing()

        self.player.setSource(QUrl.fromLocalFile(str(self._video_path)))
        self.player.setPosition(cur_pos)
        if was_playing:
            self.player.play()

        self._update_badge("ORIGINAL")

    def _on_proxy_badge_clicked(self):
        """Toggle between Proxy and Original when clicking the player badge."""
        if not self._video_path:
            return
        if self._is_using_proxy:
            self.switch_to_original()
        else:
            if self._proxy_path and self._proxy_path.exists():
                self.set_proxy_video(self._proxy_path, self._proxy_height)
            else:
                self.toggle_proxy_requested.emit()

    def retranslate_ui(self):
        """Retranslates all static labels, buttons, and proxy status in VideoPanel."""
        self.lbl_title.setText(tr("vp_title"))
        self.lbl_badge.setText(tr("vp_badge_media_import"))
        self.lbl_drag.setText(tr("vp_drop_title"))
        self.lbl_sub.setText(tr("vp_drop_sub"))
        self.btn_browse.setText(tr("vp_browse_btn"))
        if self.is_playing():
            self.btn_play.setText(tr("vp_btn_pause"))
        else:
            self.btn_play.setText(tr("vp_btn_play"))
        self.btn_stop.setText(tr("vp_btn_stop"))
        self._update_badge(self._current_badge_status, self._proxy_height)
        if hasattr(self, '_last_state') and self._last_state:
            self.show_video_info(self._last_state)

    def _update_badge(self, status: str, height: int = 540):
        self._current_badge_status = status
        self._proxy_height = height
        if status == "PROXY":
            proxy_txt = tr("vp_badge_proxy")
            self.lbl_proxy_badge.setText(f"[{proxy_txt}]")
            self.lbl_proxy_badge.setStyleSheet("""
                QPushButton#proxy_badge {
                    font-size: 7.5pt; font-weight: bold; color: #4ade80; background: #142a1b;
                    border: 1px solid #22A05B; border-radius: 3px; padding: 1px 7px; margin-left: 6px;
                }
                QPushButton#proxy_badge:hover {
                    background: #1c3d27; border-color: #4ade80;
                }
            """)
            self.lbl_proxy_badge.setToolTip(tr("vp_tip_proxy_active", height=height))
        elif status == "GENERATING":
            gen_txt = tr("vp_badge_creating_proxy")
            self.lbl_proxy_badge.setText(f"[{gen_txt}]")
            self.lbl_proxy_badge.setStyleSheet("""
                QPushButton#proxy_badge {
                    font-size: 7.5pt; font-weight: bold; color: #f59e0b; background: #261a06;
                    border: 1px solid #b45309; border-radius: 3px; padding: 1px 7px; margin-left: 6px;
                }
                QPushButton#proxy_badge:hover {
                    background: #382408;
                }
            """)
            self.lbl_proxy_badge.setToolTip(tr("vp_tip_proxy_generating"))
        else:
            orig_txt = tr("vp_badge_original")
            self.lbl_proxy_badge.setText(f"[{orig_txt}]")
            self.lbl_proxy_badge.setStyleSheet("""
                QPushButton#proxy_badge {
                    font-size: 7.5pt; font-weight: bold; color: #a1a1aa; background: #222222;
                    border: 1px solid #444444; border-radius: 3px; padding: 1px 7px; margin-left: 6px;
                }
                QPushButton#proxy_badge:hover {
                    background: #2a2a2a; border-color: #666666; color: #ffffff;
                }
            """)
            if self._proxy_path and self._proxy_path.exists():
                self.lbl_proxy_badge.setToolTip(tr("vp_tip_orig_active_can_switch"))
            else:
                self.lbl_proxy_badge.setToolTip(tr("vp_tip_orig_active_can_gen"))

    def show_video_info(self, state: PipelineState):
        self._last_state = state
        name = state.video_path.name if state.video_path else "—"
        dur_m = int(state.video_duration // 60)
        dur_s = state.video_duration % 60
        self._info_label.setText(
            f"{tr('vp_info_file')}: {name}  |  {tr('vp_info_duration')}: {dur_m:02d}:{dur_s:05.2f}  |  "
            f"{tr('vp_info_resolution')}: {state.video_width}x{state.video_height} @ {state.video_fps:.2f} fps"
        )

    def sync_master_time(self, audio_sec: float):
        """
        Authoritative clock sync driven by Timeline Audio.
        Checks drift between audio master clock and video player.
        If drift exceeds 80ms (~2.5 frames), re-aligns video immediately.
        """
        import time
        now = time.monotonic()
        target_ms = int(audio_sec * 1000)
        if self.is_playing():
            # If an explicit direct seek occurred within the last 250ms, give video decoder a grace window to settle
            if now - getattr(self, '_last_direct_seek_time', 0.0) < 0.25:
                self._update_time_code(target_ms, self.player.duration())
                return

            cur_ms = self.player.position()
            drift_ms = abs(target_ms - cur_ms)
            if drift_ms > 80:
                self.player.setPosition(target_ms)
        else:
            if not self._is_user_seeking:
                self.player.setPosition(target_ms)
        self._update_time_code(target_ms, self.player.duration())

    def set_position(self, sec: float):
        """Seek player position directly without triggering recursive signals."""
        import time
        self._last_direct_seek_time = time.monotonic()
        target_ms = int(sec * 1000)
        self.player.setPosition(target_ms)
        self._update_time_code(target_ms, self.player.duration())

    def toggle_playback(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.pause_playback()
        else:
            self.start_playback()

    def start_playback(self):
        active_src = self._proxy_path or self._video_path
        if active_src and active_src.exists():
            # Mute video player audio stream so master timeline audio is the single source
            self.audio_output.setMuted(True)
            self.player.play()
            self.btn_play.setText(tr("vp_btn_pause"))
            self.playback_toggled.emit(True)

    def pause_playback(self):
        self.player.pause()
        self.btn_play.setText(tr("vp_btn_play"))
        self.playback_toggled.emit(False)

    def stop_playback(self):
        self.player.stop()
        self.btn_play.setText(tr("vp_btn_play"))
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
            # NOTE: During playback, we do NOT emit position_changed to alter timeline!
            # Timeline Audio is the authoritative master clock.

    def _on_player_duration_changed(self, dur_ms: int):
        self._update_time_code(self.player.position(), dur_ms)

    def _on_slider_pressed(self):
        self._is_user_seeking = True

    def _on_slider_moved(self, val: int):
        """Throttled seeking while actively dragging the slider (30ms rate limiter)."""
        import time
        now = time.monotonic()
        if now - self._last_slider_seek_time >= 0.030:
            dur_ms = self.player.duration()
            if dur_ms > 0:
                target_ms = int((val / 1000.0) * dur_ms)
                self.player.setPosition(target_ms)
                self.seek_requested.emit(target_ms / 1000.0)
                self._update_time_code(target_ms, dur_ms)
            self._last_slider_seek_time = now

    def _on_slider_released(self):
        self._is_user_seeking = False
        dur_ms = self.player.duration()
        if dur_ms > 0:
            val = self.seek_slider.value()
            target_ms = int((val / 1000.0) * dur_ms)
            self.player.setPosition(target_ms)
            self.seek_requested.emit(target_ms / 1000.0)
            self._update_time_code(target_ms, dur_ms)

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
        self._update_badge("ORIGINAL")
        self.btn_play.setText(tr("vp_btn_play"))

    def _on_player_error(self, error, error_string: str = ""):
        """Gracefully handle playback errors such as audio device disconnect or corrupt media frame."""
        import logging
        log = logging.getLogger("VoicerStudio")
        log.warning(f"VideoPanel playback error ({error}): {error_string}")
        if hasattr(self, 'btn_play'):
            self.btn_play.setText(tr("vp_btn_play"))


