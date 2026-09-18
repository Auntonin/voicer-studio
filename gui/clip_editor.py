import tempfile
import subprocess
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QComboBox, QPlainTextEdit, QDoubleSpinBox, QGridLayout, QFrame
)
from PySide6.QtCore import Qt, Signal, QUrl, QTimer
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtGui import QPixmap, QImage

from core.models import DialogueItem, PipelineState
from config import COLORS

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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.item = None
        self.state = None
        self._temp_audio_file = None
        self._is_loading = False

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
                font-family: 'Segoe UI', system-ui, sans-serif;
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

        self.image_preview = QLabel("No Video Frame")
        self.image_preview.setFixedSize(160, 90)
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setStyleSheet(
            "background-color: #181818; border: 1px solid #383838; border-radius: 6px; color: #888888;"
        )
        fc_layout.addWidget(self.image_preview)

        play_layout = QHBoxLayout()
        play_layout.setSpacing(4)
        self.btn_play = QPushButton("Play Audio")
        self.btn_stop = QPushButton("Stop")
        play_layout.addWidget(self.btn_play)
        play_layout.addWidget(self.btn_stop)
        fc_layout.addLayout(play_layout)

        self.btn_change_image = QPushButton("Recapture Frame")
        self.btn_change_image.clicked.connect(self.on_change_image)
        fc_layout.addWidget(self.btn_change_image)

        main_layout.addWidget(frame_card, stretch=0)

        # ── Timing & Speaker Card (Col 2: Character & Timestamps) ──
        time_card = QFrame()
        time_card.setObjectName("editor_card")
        tc_layout = QVBoxLayout(time_card)
        tc_layout.setContentsMargins(10, 10, 10, 10)
        tc_layout.setSpacing(6)

        tc_layout.addWidget(QLabel("CHARACTER & TIMING", objectName="section_title"))

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)

        grid.addWidget(QLabel("Character:"), 0, 0)
        self.combo_speaker = QComboBox()
        self.combo_speaker.currentIndexChanged.connect(self._on_speaker_changed)
        grid.addWidget(self.combo_speaker, 0, 1)

        grid.addWidget(QLabel("Start (s):"), 1, 0)
        self.spin_start = QDoubleSpinBox()
        self.spin_start.setDecimals(3)
        self.spin_start.setRange(0, 99999)
        self.spin_start.setSingleStep(0.1)
        self.spin_start.valueChanged.connect(self._on_time_changed)
        grid.addWidget(self.spin_start, 1, 1)

        grid.addWidget(QLabel("End (s):"), 2, 0)
        self.spin_end = QDoubleSpinBox()
        self.spin_end.setDecimals(3)
        self.spin_end.setRange(0, 99999)
        self.spin_end.setSingleStep(0.1)
        self.spin_end.valueChanged.connect(self._on_time_changed)
        grid.addWidget(self.spin_end, 2, 1)

        self.lbl_duration = QLabel("Duration: 0.000s")
        self.lbl_duration.setStyleSheet(f"color: {COLORS['accent_green']}; font-weight: bold;")
        grid.addWidget(self.lbl_duration, 3, 0, 1, 2)

        tc_layout.addLayout(grid)
        tc_layout.addStretch()

        main_layout.addWidget(time_card, stretch=1)

        # ── Caption & Actions Card (Col 3: Dialogue Text & Quick Actions) ──
        cap_card = QFrame()
        cap_card.setObjectName("editor_card")
        cc_layout = QVBoxLayout(cap_card)
        cc_layout.setContentsMargins(10, 10, 10, 10)
        cc_layout.setSpacing(6)

        cap_header = QHBoxLayout()
        cap_header.addWidget(QLabel("DIALOGUE CAPTION TEXT", objectName="section_title"))
        cap_header.addStretch()
        self.btn_regen_caption = QPushButton("Re-Transcribe")
        self.btn_regen_caption.clicked.connect(self.on_regen_caption)
        cap_header.addWidget(self.btn_regen_caption)
        cc_layout.addLayout(cap_header)

        self.txt_caption = QPlainTextEdit()
        self.txt_caption.setPlaceholderText("Enter dialogue caption text...")
        self.txt_caption.setMaximumHeight(62)
        self.txt_caption.textChanged.connect(self._on_caption_text_changed)
        cc_layout.addWidget(self.txt_caption)

        # Action Buttons row
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)
        self.btn_split = QPushButton("Split Clip")
        self.btn_merge = QPushButton("Merge Next")
        self.btn_delete = QPushButton("Delete Clip")
        self.btn_delete.setObjectName("btn_danger")
        self.btn_apply = QPushButton("Auto-saved ✓")
        self.btn_apply.setToolTip("Changes are saved automatically in real-time. Click to force instant save.")
        self.btn_apply.setStyleSheet("background-color: #18281d; color: #4ade80; border: 1px solid #22A05B; font-weight: bold; border-radius: 4px; padding: 5px 12px;")

        self.btn_split.clicked.connect(self.on_split)
        self.btn_merge.clicked.connect(self.on_merge)
        self.btn_delete.clicked.connect(self.on_delete)
        self.btn_apply.clicked.connect(self.on_apply)

        btn_layout.addWidget(self.btn_split)
        btn_layout.addWidget(self.btn_merge)
        btn_layout.addWidget(self.btn_delete)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_apply)

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
        self.lbl_duration.setText(f"Duration: {dur:.3f}s")
        if not self._is_loading and self.item:
            self._set_save_status("Saving...")
            self._timing_timer.start()
        # Seek frame preview to updated start timestamp
        if self.state and self.state.video_path and self.state.video_path.exists():
            QTimer.singleShot(150, self._seek_frame_preview)

    def _on_caption_text_changed(self):
        if self._is_loading or not self.item:
            return
        self._set_save_status("Saving...")
        self._caption_timer.start()

    def _auto_save_caption(self):
        if self._is_loading or not self.item:
            return
        new_text = self.txt_caption.toPlainText()
        if self.item.caption != new_text:
            self.item.caption = new_text
            self.caption_changed.emit(self.item.index, new_text)
        self._set_save_status("Auto-saved ✓")

    def _on_speaker_changed(self, idx: int):
        if self._is_loading or not self.item:
            return
        new_spk = self.combo_speaker.currentData()
        if new_spk and new_spk != self.item.speaker_id:
            self.item.speaker_id = new_spk
            self.speaker_changed.emit(self.item.index, new_spk)
            self._set_save_status("Auto-saved ✓")

    def _auto_save_timing(self):
        if self._is_loading or not self.item:
            return
        s = self.spin_start.value()
        e = max(s + 0.05, self.spin_end.value())
        if abs(self.item.start - s) > 0.001 or abs(self.item.end - e) > 0.001:
            self.item.start = s
            self.item.end = e
            self.timestamps_changed.emit(self.item.index, s, e)
        self._set_save_status("Auto-saved ✓")

    def _set_save_status(self, text: str):
        if text == "Auto-saved ✓":
            self.btn_apply.setText("Auto-saved ✓")
            self.btn_apply.setStyleSheet(
                "background-color: #18281d; color: #4ade80; border: 1px solid #22A05B; "
                "font-weight: bold; border-radius: 4px; padding: 5px 12px;"
            )
        elif text == "Saving...":
            self.btn_apply.setText("Saving...")
            self.btn_apply.setStyleSheet(
                "background-color: #2b2518; color: #facc15; border: 1px solid #ca8a04; "
                "font-weight: bold; border-radius: 4px; padding: 5px 12px;"
            )
        else:
            self.btn_apply.setText(text)
            self.btn_apply.setStyleSheet("")

    def _seek_frame_preview(self):
        if not self.state or not self.state.video_path:
            return
        ts = self.spin_start.value()
        try:
            from core.frame_extractor import FrameExtractor
            extractor = FrameExtractor(self.state.video_path)
            frame = extractor.extract_frame(ts)
            extractor.release()
            if frame is not None:
                h, w, ch = frame.shape
                bytes_per_line = ch * w
                qimg = QImage(frame.data, w, h, bytes_per_line, QImage.Format.Format_BGR888)
                pix = QPixmap.fromImage(qimg).scaled(160, 90, Qt.AspectRatioMode.KeepAspectRatio)
                self.image_preview.setPixmap(pix)
        except Exception:
            pass

    def load_item(self, item: DialogueItem, state: PipelineState):
        self._is_loading = True
        self.item = item
        self.state = state

        # Block spinbox signals during value setting
        self.spin_start.blockSignals(True)
        self.spin_end.blockSignals(True)

        self.combo_speaker.blockSignals(True)
        self.combo_speaker.clear()
        for spk_id, spk in state.speakers.items():
            self.combo_speaker.addItem(spk.display_name, spk_id)

        idx = self.combo_speaker.findData(item.speaker_id)
        if idx >= 0:
            self.combo_speaker.setCurrentIndex(idx)
        self.combo_speaker.blockSignals(False)

        self.spin_start.setValue(item.start)
        self.spin_end.setValue(item.end)
        self.lbl_duration.setText(f"Duration: {item.duration:.3f}s")
        
        # User requested: show placeholder text when caption is empty, don't fill dummy text
        self.txt_caption.blockSignals(True)
        self.txt_caption.setPlainText(item.caption if item.caption else "")
        self.txt_caption.setPlaceholderText("Enter dialogue caption text...")
        self.txt_caption.blockSignals(False)

        self.spin_start.blockSignals(False)
        self.spin_end.blockSignals(False)

        # Image preview
        if item.image_path and item.image_path.exists():
            pix = QPixmap(str(item.image_path)).scaled(160, 90, Qt.AspectRatioMode.KeepAspectRatio)
            self.image_preview.setPixmap(pix)
        else:
            self._seek_frame_preview()

        self._set_save_status("Auto-saved ✓")
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
            
        # Fallback: slice audio from work_audio_path on the fly
        audio_src = self.state.work_audio_path if self.state else None
        if audio_src and audio_src.exists():
            try:
                tmp = Path(tempfile.gettempdir()) / "preview_clip.wav"
                dur = max(0.1, self.item.end - self.item.start)
                cmd = [
                    "ffmpeg", "-y", "-ss", f"{self.item.start:.3f}",
                    "-i", str(audio_src), "-t", f"{dur:.3f}",
                    "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                    str(tmp)
                ]
                from config import SUBPROCESS_FLAGS
                res = subprocess.run(cmd, capture_output=True, timeout=10, creationflags=SUBPROCESS_FLAGS)
                if res.returncode == 0 and tmp.exists():
                    self.player.setSource(QUrl.fromLocalFile(str(tmp)))
                    self.player.play()
            except Exception as e:
                print(f"Error previewing audio: {e}")

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
        self.txt_caption.setPlaceholderText("Enter dialogue caption text...")
        self.txt_caption.blockSignals(False)
        self.image_preview.setText("No Video Frame")
        self.lbl_duration.setText("Duration: 0.000s")
        self.player.stop()
        self._set_save_status("Auto-saved ✓")
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
            self._set_save_status("Auto-saved ✓")
