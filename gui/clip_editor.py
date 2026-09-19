import tempfile
import subprocess
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QComboBox, QPlainTextEdit, QDoubleSpinBox, QGridLayout, QFrame,
    QApplication
)
from PySide6.QtCore import Qt, Signal, QUrl, QTimer, QSize
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtGui import QPixmap, QImage, QIcon, QTextCursor

from core.models import DialogueItem, PipelineState
from config import COLORS, ASSETS_DIR
from core.i18n import tr


class CaptionTextEdit(QPlainTextEdit):
    """QPlainTextEdit subclass that ensures Ctrl+Z, Ctrl+Y, and Ctrl+Shift+Z are reliably handled for caption undo/redo."""
    def keyPressEvent(self, event):
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z:
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    if self.document().isRedoAvailable():
                        self.redo()
                        event.accept()
                        return
                else:
                    if self.document().isUndoAvailable():
                        self.undo()
                        event.accept()
                        return
            elif event.key() == Qt.Key.Key_Y:
                if self.document().isRedoAvailable():
                    self.redo()
                    event.accept()
                    return
        super().keyPressEvent(event)


class ClipEditor(QWidget):
    caption_changed = Signal(int, str)
    speaker_changed = Signal(int, str)
    timestamps_changed = Signal(int, float, float)
    regenerate_audio_requested = Signal(int)
    regenerate_caption_requested = Signal(int)
    change_image_requested = Signal(int)
    delete_requested = Signal(int)
    split_requested = Signal(int)
    merge_requested = Signal(int)
    play_started = Signal()
    _frame_qimage_ready = Signal(int, QImage)
    _preview_audio_ready = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.item = None
        self.state = None
        self._temp_audio_file = None
        self._is_loading = False

        # Asynchronous frame preview state (prevents UI freeze during scrubbing/cutting)
        self._frame_preview_timer = QTimer(self)
        self._frame_preview_timer.setSingleShot(True)
        self._frame_preview_timer.setInterval(60)
        self._frame_preview_timer.timeout.connect(self._do_async_frame_preview)
        self._frame_preview_req_id = 0
        self._frame_qimage_ready.connect(self._on_frame_qimage_ready)
        self._preview_audio_ready.connect(self._on_preview_audio_ready)

        # Auto-save debounce timers
        self._caption_timer = QTimer(self)
        self._caption_timer.setSingleShot(True)
        self._caption_timer.setInterval(300)
        self._caption_timer.timeout.connect(self._auto_save_caption)

        self._timing_timer = QTimer(self)
        self._timing_timer.setSingleShot(True)
        self._timing_timer.setInterval(200)
        self._timing_timer.timeout.connect(self._auto_save_timing)

        self.setStyleSheet(f"""
            QWidget {{
                background-color: {COLORS['bg_secondary']};
                color: {COLORS['text_primary']};
                font-family: 'Segoe UI', 'Leelawadee UI', 'Tahoma', system-ui, sans-serif;
                font-size: 9pt;
            }}
            QFrame#editor_card {{
                background-color: #222222;
                border: 1px solid #383838;
                border-radius: 8px;
            }}
            QLabel {{
                color: {COLORS['text_primary']};
            }}
            QLabel#section_title {{
                font-size: 9.5pt;
                font-weight: bold;
                color: #ffffff;
                background: transparent;
                border-left: 3px solid #1473E6;
                padding-left: 8px;
            }}
            QPushButton {{
                background-color: {COLORS['bg_input']};
                color: {COLORS['text_primary']};
                border: 1px solid #383838;
                border-radius: 4px;
                padding: 5px 12px;
                font-size: 8.5pt;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: #323232;
                border-color: {COLORS['accent']};
                color: #ffffff;
            }}
            QPushButton#btn_primary {{
                background-color: {COLORS['accent']};
                color: #ffffff;
                border: none;
                font-weight: bold;
                padding: 6px 14px;
            }}
            QPushButton#btn_primary:hover {{
                background-color: {COLORS['accent_hover']};
            }}
            QPushButton#btn_danger {{
                background-color: #2b1d24;
                color: {COLORS['accent_red']};
                border: 1px solid #4a2028;
                font-weight: bold;
            }}
            QPushButton#btn_danger:hover {{
                background-color: {COLORS['accent_red']};
                color: #ffffff;
                border-color: {COLORS['accent_red']};
            }}
            QLineEdit, QPlainTextEdit, QDoubleSpinBox, QComboBox {{
                background-color: #181818;
                color: {COLORS['text_primary']};
                border: 1px solid #383838;
                border-radius: 4px;
                padding: 4px 8px;
            }}
            QLineEdit:focus, QPlainTextEdit:focus, QDoubleSpinBox:focus, QComboBox:focus {{
                border-color: {COLORS['accent']};
            }}
        """)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(8)

        # ── Frame Card (Col 1: Image & Audio Controls) ──
        frame_card = QFrame()
        frame_card.setObjectName("editor_card")
        fc_layout = QVBoxLayout(frame_card)
        fc_layout.setContentsMargins(10, 10, 10, 10)
        fc_layout.setSpacing(6)

        self.image_preview = QLabel(tr("ed_no_frame"))
        self.image_preview.setFixedSize(160, 90)
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setStyleSheet(
            "background-color: #181818; border: 1px solid #383838; border-radius: 6px; color: #888888;"
        )
        fc_layout.addWidget(self.image_preview)

        play_layout = QHBoxLayout()
        play_layout.setSpacing(4)
        self.btn_play = QPushButton(tr("ed_play_audio"))
        self.btn_stop = QPushButton(tr("ed_stop_audio"))
        play_layout.addWidget(self.btn_play)
        play_layout.addWidget(self.btn_stop)
        fc_layout.addLayout(play_layout)

        self.btn_change_image = QPushButton(tr("ed_recapture_frame"))
        self.btn_change_image.setToolTip(tr("ed_recapture_frame_tip"))
        self.btn_change_image.clicked.connect(self.on_change_image)
        fc_layout.addWidget(self.btn_change_image)

        main_layout.addWidget(frame_card, stretch=0)

        # ── Timing & Speaker Card (Col 2: Character & Timestamps) ──
        time_card = QFrame()
        time_card.setObjectName("editor_card")
        tc_layout = QVBoxLayout(time_card)
        tc_layout.setContentsMargins(10, 10, 10, 10)
        tc_layout.setSpacing(6)

        self.lbl_title_timing = QLabel(tr("ed_timing_title"), objectName="section_title")
        tc_layout.addWidget(self.lbl_title_timing)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)

        self.lbl_spk = QLabel(tr("ed_speaker_label"))
        grid.addWidget(self.lbl_spk, 0, 0)
        self.combo_speaker = QComboBox()
        self.combo_speaker.currentIndexChanged.connect(self._on_speaker_changed)
        grid.addWidget(self.combo_speaker, 0, 1)

        self.lbl_start = QLabel(tr("ed_start_label"))
        grid.addWidget(self.lbl_start, 1, 0)
        self.spin_start = QDoubleSpinBox()
        self.spin_start.setDecimals(3)
        self.spin_start.setRange(0, 99999)
        self.spin_start.setSingleStep(0.1)
        self.spin_start.valueChanged.connect(self._on_time_changed)
        grid.addWidget(self.spin_start, 1, 1)

        self.lbl_end = QLabel(tr("ed_end_label"))
        grid.addWidget(self.lbl_end, 2, 0)
        self.spin_end = QDoubleSpinBox()
        self.spin_end.setDecimals(3)
        self.spin_end.setRange(0, 99999)
        self.spin_end.setSingleStep(0.1)
        self.spin_end.valueChanged.connect(self._on_time_changed)
        grid.addWidget(self.spin_end, 2, 1)

        self.lbl_duration = QLabel(tr("ed_duration_val", dur=0.0))
        self.lbl_duration.setStyleSheet(f"color: {COLORS['accent_green']}; font-weight: bold;")
        grid.addWidget(self.lbl_duration, 3, 0, 1, 2)

        tc_layout.addLayout(grid)
        tc_layout.addStretch()

        main_layout.addWidget(time_card, stretch=1)

        # ── Caption & Actions Card (Col 3: Dialogue Text & Quick Actions) ──
        cap_card = QFrame()
        cap_card.setObjectName("editor_card")
        cc_layout = QVBoxLayout(cap_card)
        cc_layout.setContentsMargins(12, 10, 12, 10)
        cc_layout.setSpacing(8)

        # Header with title, active clip badge, live metrics, and AI Re-Transcribe
        cap_header = QHBoxLayout()
        cap_header.setContentsMargins(0, 0, 0, 0)
        cap_header.setSpacing(8)

        self.lbl_title_cap = QLabel(tr("ed_caption_title"), objectName="section_title")
        cap_header.addWidget(self.lbl_title_cap)

        self.lbl_clip_badge = QLabel(tr("ed_no_selection"))
        self.lbl_clip_badge.setStyleSheet(
            "font-size: 7.5pt; font-weight: bold; color: #38bdf8; background: #132338; "
            "border: 1px solid #0284c7; border-radius: 3px; padding: 1px 6px;"
        )
        cap_header.addWidget(self.lbl_clip_badge)

        cap_header.addStretch()

        self.lbl_caption_stats = QLabel(f"0 {tr('ed_chars_unit')}")
        self.lbl_caption_stats.setStyleSheet(
            "font-size: 8pt; color: #888888; margin-right: 4px;"
        )
        cap_header.addWidget(self.lbl_caption_stats)

        self.btn_regen_caption = QPushButton(tr("ed_retranscribe"))
        self.btn_regen_caption.setToolTip(tr("ed_retranscribe_tip"))
        sparkles_icon = ASSETS_DIR / "icons" / "sparkles.svg"
        if sparkles_icon.exists():
            self.btn_regen_caption.setIcon(QIcon(str(sparkles_icon)))
            self.btn_regen_caption.setIconSize(QSize(13, 13))
        self.btn_regen_caption.clicked.connect(self.on_regen_caption)
        cap_header.addWidget(self.btn_regen_caption)
        cc_layout.addLayout(cap_header)

        # Minimalist Adobe Dark Text Area with full Undo/Redo support
        self.txt_caption = CaptionTextEdit()
        self.txt_caption.setPlaceholderText(tr("ed_placeholder_caption"))
        self.txt_caption.setMinimumHeight(64)
        self.txt_caption.setMaximumHeight(74)
        self.txt_caption.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: #171717;
                color: #f3f4f6;
                border: 1px solid #333333;
                border-radius: 5px;
                padding: 6px 8px;
                font-size: 9.5pt;
                line-height: 1.4;
            }}
            QPlainTextEdit:focus {{
                border-color: {COLORS['accent']};
                background-color: #141414;
            }}
        """)
        self.txt_caption.textChanged.connect(self._on_caption_text_changed)
        cc_layout.addWidget(self.txt_caption)

        # Balanced 2-Sided Action Buttons Row
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(6)

        def _make_btn(text: str, icon_name: str = "", tip: str = "", is_danger: bool = False) -> QPushButton:
            b = QPushButton(text)
            if icon_name:
                p = ASSETS_DIR / "icons" / icon_name
                if p.exists():
                    b.setIcon(QIcon(str(p)))
                    b.setIconSize(QSize(13, 13))
            if tip:
                b.setToolTip(tip)
            if is_danger:
                b.setObjectName("btn_danger")
            return b

        # Left Group: Clip operations
        self.btn_split = _make_btn(tr("ed_split_clip"), "split.svg", tr("ed_split_clip_tip"))
        self.btn_merge = _make_btn(tr("ed_merge_next"), "merge.svg", tr("ed_merge_next_tip"))
        self.btn_delete = _make_btn(tr("ed_delete_clip"), "trash.svg", tr("ed_delete_clip_tip"), is_danger=True)

        self.btn_split.clicked.connect(self.on_split)
        self.btn_merge.clicked.connect(self.on_merge)
        self.btn_delete.clicked.connect(self.on_delete)

        btn_layout.addWidget(self.btn_split)
        btn_layout.addWidget(self.btn_merge)
        btn_layout.addWidget(self.btn_delete)

        btn_layout.addStretch()

        # Right Group: Utilities & Audio Tools
        self.btn_copy = _make_btn(tr("ed_copy"), "copy.svg", tr("ed_copy_tip"))
        self.btn_clear = _make_btn(tr("ed_clear"), "clear.svg", tr("ed_clear_tip"))
        self.btn_regen_audio = _make_btn(tr("ed_reslice_audio"), "wave.svg", tr("ed_reslice_audio_tip"))

        self.btn_copy.clicked.connect(self._on_copy_caption)
        self.btn_clear.clicked.connect(self._on_clear_caption)
        self.btn_regen_audio.clicked.connect(self.on_regen_audio)

        btn_layout.addWidget(self.btn_copy)
        btn_layout.addWidget(self.btn_clear)
        btn_layout.addWidget(self.btn_regen_audio)

        cc_layout.addLayout(btn_layout)
        main_layout.addWidget(cap_card, stretch=2)

        # Audio player setup
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.btn_play.clicked.connect(self.play_audio)
        self.btn_stop.clicked.connect(self.player.stop)

        self.clear()

    def _on_time_changed(self):
        dur = max(0.0, self.spin_end.value() - self.spin_start.value())
        self.lbl_duration.setText(tr("ed_duration_val", dur=dur))
        if not self._is_loading and self.item:
            self._set_save_status("Saving...")
            self._timing_timer.start()
        # Seek frame preview to updated start timestamp
        if self.state and self.state.video_path and self.state.video_path.exists():
            QTimer.singleShot(150, self._seek_frame_preview)

    def _on_caption_text_changed(self):
        self._update_caption_stats()
        if self._is_loading or not self.item:
            return
        self._caption_timer.start()

    def _update_caption_stats(self):
        text = self.txt_caption.toPlainText().strip()
        chars = len(text)
        words = len(text.split()) if text else 0
        if chars > 0:
            self.lbl_caption_stats.setText(f"{chars} {tr('ed_chars_unit')} • {words} {tr('ed_words_unit')}")
        else:
            self.lbl_caption_stats.setText(f"0 {tr('ed_chars_unit')}")

    def _on_copy_caption(self):
        text = self.txt_caption.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)
            self.btn_copy.setText(tr("ed_copied"))
            QTimer.singleShot(1200, lambda: self.btn_copy.setText(tr("ed_copy")))

    def _on_clear_caption(self):
        text = self.txt_caption.toPlainText()
        if not text:
            return
        cursor = self.txt_caption.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.removeSelectedText()
        self.txt_caption.setFocus()
        self._auto_save_caption()

    def _auto_save_caption(self):
        if self._is_loading or not self.item:
            return
        new_text = self.txt_caption.toPlainText()
        if self.item.caption != new_text:
            # Emit signal first so MainWindow can snapshot the previous state for undo!
            self.caption_changed.emit(self.item.index, new_text)
            self.item.caption = new_text

    def _on_speaker_changed(self, idx: int):
        if self._is_loading or not self.item:
            return
        new_spk = self.combo_speaker.currentData()
        if new_spk and new_spk != self.item.speaker_id:
            self.item.speaker_id = new_spk
            self.speaker_changed.emit(self.item.index, new_spk)
            self._set_save_status("Saved")

    def _auto_save_timing(self):
        if self._is_loading or not self.item:
            return
        s = self.spin_start.value()
        e = max(s + 0.05, self.spin_end.value())
        if abs(self.item.start - s) > 0.001 or abs(self.item.end - e) > 0.001:
            self.item.start = s
            self.item.end = e
            self.timestamps_changed.emit(self.item.index, s, e)
        self._set_save_status("Saved")

    def _set_save_status(self, text: str):
        pass

    def _on_frame_qimage_ready(self, req_id: int, qimg: QImage):
        if req_id == self._frame_preview_req_id and not qimg.isNull():
            pix = QPixmap.fromImage(qimg).scaled(160, 90, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.image_preview.setPixmap(pix)

    def _on_preview_audio_ready(self, file_path_str: str):
        if file_path_str and Path(file_path_str).exists():
            self.player.setSource(QUrl.fromLocalFile(file_path_str))
            self.player.play()

    def _seek_frame_preview(self):
        """Debounce frame seek request so rapid scrubbing/splitting never freezes the GUI thread."""
        self._frame_preview_req_id += 1
        self._frame_preview_timer.start()

    def _do_async_frame_preview(self):
        """Asynchronously extract video frame in background thread (zero GUI freeze)."""
        if not self.state or not self.state.video_path:
            return
        ts = self.spin_start.value()
        req_id = self._frame_preview_req_id
        # Prioritize lightweight proxy video (seeks in < 2ms) if available
        video_src = self.state.preview_proxy_path if (self.state.preview_proxy_path and self.state.preview_proxy_path.exists()) else self.state.video_path

        def _worker():
            try:
                import cv2
                cap = cv2.VideoCapture(str(video_src))
                if not cap.isOpened():
                    return
                cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000)
                ret, frame = cap.read()
                cap.release()
                if ret and frame is not None and req_id == self._frame_preview_req_id:
                    h, w, ch = frame.shape
                    bytes_per_line = ch * w
                    # QImage copy is thread-safe across threads
                    qimg = QImage(frame.data, w, h, bytes_per_line, QImage.Format.Format_BGR888).copy()
                    self._frame_qimage_ready.emit(req_id, qimg)
            except Exception:
                pass

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def load_item(self, item: DialogueItem, state: PipelineState):
        self._is_loading = True
        self.item = item
        self.state = state

        # Block spinbox signals during value setting
        self.spin_start.blockSignals(True)
        self.spin_end.blockSignals(True)

        # Smart combo population: only rebuild if speaker list keys changed
        current_spk_ids = [self.combo_speaker.itemData(i) for i in range(self.combo_speaker.count())]
        new_spk_ids = list(state.speakers.keys())
        if current_spk_ids != new_spk_ids:
            self.combo_speaker.blockSignals(True)
            self.combo_speaker.clear()
            for spk_id, spk in state.speakers.items():
                self.combo_speaker.addItem(spk.display_name, spk_id)
            self.combo_speaker.blockSignals(False)

        idx = self.combo_speaker.findData(item.speaker_id)
        if idx >= 0 and self.combo_speaker.currentIndex() != idx:
            self.combo_speaker.blockSignals(True)
            self.combo_speaker.setCurrentIndex(idx)
            self.combo_speaker.blockSignals(False)

        self.spin_start.setValue(item.start)
        self.spin_end.setValue(item.end)
        self.lbl_duration.setText(tr("ed_duration_val", dur=item.duration))
        
        # User requested: show placeholder text when caption is empty, don't fill dummy text
        self.txt_caption.blockSignals(True)
        self.txt_caption.setPlainText(item.caption if item.caption else "")
        self.txt_caption.setPlaceholderText(tr("ed_placeholder_caption"))
        self.txt_caption.blockSignals(False)

        self.lbl_clip_badge.setText(tr("ed_clip_badge", index=item.index))
        self._update_caption_stats()

        self.spin_start.blockSignals(False)
        self.spin_end.blockSignals(False)

        # Image preview (immediate if on disk, non-blocking async seek if not)
        if item.image_path and item.image_path.exists():
            pix = QPixmap(str(item.image_path)).scaled(160, 90, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.image_preview.setPixmap(pix)
        else:
            self._seek_frame_preview()

        self._is_loading = False

    def play_audio(self):
        if not self.item:
            return
            
        self.play_started.emit()
        self.player.stop()
        if self.item.audio_path and self.item.audio_path.exists():
            self.player.setSource(QUrl.fromLocalFile(str(self.item.audio_path)))
            self.player.play()
            return
            
        # Fallback: slice audio from work_audio_path asynchronously without freezing GUI
        audio_src = self.state.work_audio_path if self.state else None
        if audio_src and audio_src.exists():
            item_start = self.item.start
            item_dur = max(0.1, self.item.end - self.item.start)
            item_idx = self.item.index
            def _async_slice():
                try:
                    tmp = Path(tempfile.gettempdir()) / f"preview_clip_{item_idx}.wav"
                    cmd = [
                        "ffmpeg", "-y", "-ss", f"{item_start:.3f}",
                        "-i", str(audio_src), "-t", f"{item_dur:.3f}",
                        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                        str(tmp)
                    ]
                    from config import SUBPROCESS_FLAGS
                    res = subprocess.run(cmd, capture_output=True, timeout=10, creationflags=SUBPROCESS_FLAGS)
                    if res.returncode == 0 and tmp.exists():
                        self._preview_audio_ready.emit(str(tmp))
                except Exception as e:
                    print(f"Error previewing audio asynchronously: {e}")

            import threading
            threading.Thread(target=_async_slice, daemon=True).start()

    def clear(self):
        self._is_loading = True
        self.item = None
        self.combo_speaker.clear()
        self.spin_start.blockSignals(True)
        self.spin_end.blockSignals(True)
        self.spin_start.setValue(0)
        self.spin_end.setValue(0)
        self.spin_start.blockSignals(False)
        self.spin_end.blockSignals(False)
        self.txt_caption.blockSignals(True)
        self.txt_caption.clear()
        self.txt_caption.setPlaceholderText(tr("ed_placeholder_caption"))
        self.txt_caption.blockSignals(False)
        self.lbl_clip_badge.setText(tr("ed_no_selection"))
        self.lbl_caption_stats.setText(f"0 {tr('ed_chars_unit')}")
        self.image_preview.setText(tr("ed_no_frame"))
        self.lbl_duration.setText(tr("ed_duration_val", dur=0.0))
        self.player.stop()
        self._is_loading = False

    def on_change_image(self):
        if self.item:
            self.change_image_requested.emit(self.item.index)

    def on_regen_audio(self):
        if self.item:
            self.player.stop()
            self.player.setSource(QUrl())
            self.regenerate_audio_requested.emit(self.item.index)

    def on_regen_caption(self):
        if self.item:
            self.regenerate_caption_requested.emit(self.item.index)

    def on_delete(self):
        if self.item:
            self.delete_requested.emit(self.item.index)

    def on_split(self):
        if self.item:
            self.split_requested.emit(self.item.index)

    def on_merge(self):
        if self.item:
            self.merge_requested.emit(self.item.index)

    def on_apply(self):
        if self.item:
            self.caption_changed.emit(self.item.index, self.txt_caption.toPlainText())
            self.speaker_changed.emit(self.item.index, self.combo_speaker.currentData())
            self.timestamps_changed.emit(self.item.index, self.spin_start.value(), self.spin_end.value())
            self._set_save_status("Saved")

    def retranslate_ui(self):
        """Refreshes all labels and button texts in the Clip Editor."""
        self.btn_play.setText(tr("ed_play_audio"))
        self.btn_stop.setText(tr("ed_stop_audio"))
        self.btn_change_image.setText(tr("ed_recapture_frame"))
        self.btn_change_image.setToolTip(tr("ed_recapture_frame_tip"))

        self.lbl_title_timing.setText(tr("ed_timing_title"))
        self.lbl_spk.setText(tr("ed_speaker_label"))
        self.lbl_start.setText(tr("ed_start_label"))
        self.lbl_end.setText(tr("ed_end_label"))

        self.lbl_title_cap.setText(tr("ed_caption_title"))
        if not self.item:
            self.lbl_clip_badge.setText(tr("ed_no_selection"))
            self.image_preview.setText(tr("ed_no_frame"))
            self.lbl_duration.setText(tr("ed_duration_val", dur=0.0))
        else:
            self.lbl_clip_badge.setText(tr("ed_clip_badge", index=self.item.index))
            self.lbl_duration.setText(tr("ed_duration_val", dur=self.item.duration))
        self._update_caption_stats()

        self.btn_regen_caption.setText(tr("ed_retranscribe"))
        self.btn_regen_caption.setToolTip(tr("ed_retranscribe_tip"))
        self.txt_caption.setPlaceholderText(tr("ed_placeholder_caption"))

        self.btn_split.setText(tr("ed_split_clip"))
        self.btn_split.setToolTip(tr("ed_split_clip_tip"))
        self.btn_merge.setText(tr("ed_merge_next"))
        self.btn_merge.setToolTip(tr("ed_merge_next_tip"))
        self.btn_delete.setText(tr("ed_delete_clip"))
        self.btn_delete.setToolTip(tr("ed_delete_clip_tip"))

        self.btn_copy.setText(tr("ed_copy"))
        self.btn_copy.setToolTip(tr("ed_copy_tip"))
        self.btn_clear.setText(tr("ed_clear"))
        self.btn_clear.setToolTip(tr("ed_clear_tip"))
        self.btn_regen_audio.setText(tr("ed_reslice_audio"))
        self.btn_regen_audio.setToolTip(tr("ed_reslice_audio_tip"))

