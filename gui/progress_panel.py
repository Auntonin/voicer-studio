import time
from datetime import timedelta
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTextEdit, QFrame
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QIcon
from core.models import PipelineStep
from core.i18n import tr
from config import COLORS, ASSETS_DIR
import datetime


class ProgressPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self._current_step_enum: PipelineStep | None = None
        self._last_elapsed_sec: int = 0
        self._log_expanded = False

        self.setStyleSheet(f"""
            QWidget#panel {{
                background-color: #141417;
                border: 1px solid #26262c;
                border-radius: 6px;
            }}
            QProgressBar {{
                background-color: #101013;
                border: 1px solid #222227;
                border-radius: 3px;
                height: 6px;
                text-align: center;
                color: transparent;
            }}
            QProgressBar::chunk {{
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #38bdf8);
                border-radius: 2px;
            }}
            QProgressBar#subBar {{
                height: 4px;
                border-radius: 2px;
            }}
            QProgressBar#subBar::chunk {{
                background-color: #34d399;
                border-radius: 2px;
            }}
            QTextEdit {{
                background-color: #0c0c0e;
                color: #cbd5e1;
                border: 1px solid #222227;
                border-radius: 4px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 8pt;
                padding: 4px 6px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(5)

        # ── 1. Top Header Row: Stage badge, Details, Elapsed time, and Actions ──
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        self.lbl_title = QLabel(tr("pp_title"))
        self.lbl_title.setStyleSheet("font-size: 7.5pt; font-weight: 700; letter-spacing: 0.8px; color: #71717a; text-transform: uppercase;")
        header.addWidget(self.lbl_title)

        self.lbl_current_step = QLabel(tr("pp_ready"))
        self.lbl_current_step.setStyleSheet(
            "font-size: 7.5pt; font-weight: 700; color: #38bdf8; background: #08283d; "
            "border: 1px solid #075985; border-radius: 4px; padding: 2px 7px;"
        )
        header.addWidget(self.lbl_current_step)

        self.lbl_sub_detail = QLabel("")
        self.lbl_sub_detail.setStyleSheet("color: #94a3b8; font-size: 8pt; font-weight: 500;")
        header.addWidget(self.lbl_sub_detail, stretch=1)

        self.lbl_elapsed = QLabel(tr("pp_elapsed", time="00:00"))
        self.lbl_elapsed.setStyleSheet(
            "background: #18181c; border: 1px solid #27272a; color: #a1a1aa; "
            "font-family: 'Consolas', monospace; font-size: 8pt; font-weight: 600; "
            "border-radius: 4px; padding: 2px 8px;"
        )
        header.addWidget(self.lbl_elapsed)

        self.btn_toggle_log = QPushButton("📜 " + tr("pp_btn_log", default="ดู Log"))
        self.btn_toggle_log.setToolTip("สลับแสดง/ซ่อนบันทึกการทำงานอย่างละเอียด (Detailed Log)")
        self.btn_toggle_log.setStyleSheet("""
            QPushButton {
                background-color: #18181c;
                border: 1px solid #282830;
                color: #a1a1aa;
                font-size: 8pt;
                font-weight: 600;
                border-radius: 4px;
                padding: 2px 8px;
            }
            QPushButton:hover {
                background-color: #26262e;
                border-color: #3f3f4a;
                color: #ffffff;
            }
        """)
        self.btn_toggle_log.clicked.connect(self._toggle_log_drawer)
        header.addWidget(self.btn_toggle_log)

        self.btn_cancel = QPushButton(tr("pp_btn_cancel"))
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #1a1a1e;
                border: 1px solid #282830;
                color: #d4d4d8;
                font-size: 8pt;
                font-weight: 600;
                border-radius: 4px;
                padding: 2px 10px;
            }
            QPushButton:hover {
                background-color: #27161b;
                border-color: #4a2028;
                color: #fca5a5;
            }
            QPushButton:disabled {
                background-color: #121215;
                color: #404048;
                border-color: #1a1a1e;
            }
        """)
        header.addWidget(self.btn_cancel)
        layout.addLayout(header)

        # ── 2. Segmented Step Pipeline Bar (Modern 10-Stage Studio Pills) ──
        self.step_layout = QHBoxLayout()
        self.step_layout.setContentsMargins(0, 2, 0, 2)
        self.step_layout.setSpacing(3)

        self.steps = [
            (PipelineStep.AUDIO_EXTRACT,   "pp_step_extract"),
            (PipelineStep.VAD,             "pp_step_vad"),
            (PipelineStep.DIARIZATION,     "pp_step_diarize"),
            (PipelineStep.TRANSCRIPTION,   "pp_step_transcribe"),
            (PipelineStep.VOICE_SEPARATION,"pp_step_separate"),
            (PipelineStep.CLIP_GENERATION, "pp_step_clips"),
            (PipelineStep.FRAME_EXTRACTION,"pp_step_frames"),
            (PipelineStep.BACKING_TRACK,   "pp_step_bgtrack"),
            (PipelineStep.PACK_BUILD,      "pp_step_pack"),
            (PipelineStep.VALIDATION,      "pp_step_validate"),
        ]

        self.step_widgets = {}
        for i, (step, key) in enumerate(self.steps):
            pill = QLabel(f"{i+1}. {tr(key)}")
            pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pill.setFixedHeight(22)
            pill.setStyleSheet("""
                background-color: #121215;
                border: 1px solid #222227;
                color: #52525b;
                border-radius: 3px;
                font-size: 7.5pt;
                font-weight: 500;
                padding: 1px 4px;
            """)
            self.step_widgets[step] = (pill, pill)
            self.step_layout.addWidget(pill, stretch=1)

        layout.addLayout(self.step_layout)

        # ── 3. High-Precision Progress Track Row ──
        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(6)

        # Overall progress bar + percentage pill
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(6)
        progress_row.addWidget(self.progress_bar, stretch=3)

        self.lbl_pct = QLabel("0%")
        self.lbl_pct.setFixedWidth(40)
        self.lbl_pct.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_pct.setStyleSheet(
            "background: #08283d; border: 1px solid #075985; color: #38bdf8; "
            "font-size: 7.5pt; font-weight: 700; border-radius: 3px; padding: 1px 4px;"
        )
        progress_row.addWidget(self.lbl_pct)

        # Sub-step bar + percentage readout
        self.sub_bar = QProgressBar()
        self.sub_bar.setObjectName("subBar")
        self.sub_bar.setRange(0, 100)
        self.sub_bar.setValue(0)
        self.sub_bar.setFixedHeight(4)
        progress_row.addWidget(self.sub_bar, stretch=2)

        self.lbl_sub_pct = QLabel("0%")
        self.lbl_sub_pct.setFixedWidth(36)
        self.lbl_sub_pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_sub_pct.setStyleSheet("color: #34d399; font-size: 7.5pt; font-weight: 600; font-family: 'Consolas', monospace;")
        progress_row.addWidget(self.lbl_sub_pct)

        layout.addLayout(progress_row)

        # ── 4. Live Single-Line Ticker (Minimalist default state) ──
        self.lbl_latest_log = QLabel(f"• {tr('status_ready')}")
        self.lbl_latest_log.setStyleSheet("color: #71717a; font-size: 7.5pt; font-family: 'Consolas', monospace; padding-left: 2px;")
        layout.addWidget(self.lbl_latest_log)

        # ── 5. Expandable Detailed Terminal Log (Hidden by default to keep UI minimal) ──
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFixedHeight(75)
        self.log_text.setVisible(False)
        layout.addWidget(self.log_text)

        # ── Timer ──
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_elapsed)
        self.start_time = None

    def _toggle_log_drawer(self):
        self._log_expanded = not self._log_expanded
        self.log_text.setVisible(self._log_expanded)
        self.lbl_latest_log.setVisible(not self._log_expanded)
        if self._log_expanded:
            self.btn_toggle_log.setText("📜 " + tr("pp_btn_log_hide", default="ซ่อน Log"))
        else:
            self.btn_toggle_log.setText("📜 " + tr("pp_btn_log", default="ดู Log"))

    def _update_elapsed(self):
        if self.start_time:
            self._last_elapsed_sec = int(time.time() - self.start_time)
            m, s = divmod(self._last_elapsed_sec, 60)
            self.lbl_elapsed.setText(tr("pp_elapsed", time=f"{m:02d}:{s:02d}"))

    def set_elapsed(self, seconds: float):
        self._last_elapsed_sec = int(seconds)
        m, s = divmod(self._last_elapsed_sec, 60)
        self.lbl_elapsed.setText(tr("pp_elapsed", time=f"{m:02d}:{s:02d}"))

    def set_step(self, step: PipelineStep):
        self._current_step_enum = step
        current_idx = -1
        for i, (s, _) in enumerate(self.steps):
            if s == step:
                current_idx = i
                break

        for i, (s, key) in enumerate(self.steps):
            pill, _ = self.step_widgets[s]
            if i < current_idx:
                # Prior completed steps
                pill.setStyleSheet("""
                    background-color: #072115;
                    border: 1px solid #134e32;
                    color: #34d399;
                    border-radius: 3px;
                    font-size: 7.5pt;
                    font-weight: 600;
                    padding: 1px 4px;
                """)
                pill.setText(f"✓ {tr(key)}")
            elif i == current_idx:
                # Current active step
                pill.setStyleSheet("""
                    background-color: #0c2b42;
                    border: 1.5px solid #0284c7;
                    color: #38bdf8;
                    border-radius: 3px;
                    font-size: 7.5pt;
                    font-weight: 700;
                    padding: 1px 4px;
                """)
                pill.setText(f"▶ {tr(key)}")
                self.lbl_current_step.setText(tr(key))
                self.lbl_sub_detail.setText("")
                self.sub_bar.setValue(0)
                self.lbl_sub_pct.setText("0%")
                if not self.start_time:
                    self.start_time = time.time()
                    self.timer.start(1000)
            else:
                # Upcoming pending steps
                pill.setStyleSheet("""
                    background-color: #121215;
                    border: 1px solid #222227;
                    color: #52525b;
                    border-radius: 3px;
                    font-size: 7.5pt;
                    font-weight: 500;
                    padding: 1px 4px;
                """)
                pill.setText(f"{i+1}. {tr(key)}")

    def set_progress(self, value: int):
        self.progress_bar.setValue(value)
        self.lbl_pct.setText(f"{value}%")

    def set_sub_progress(self, current: int, total: int, detail: str):
        """Called by sub_progress signal from PipelineWorker."""
        if total > 0:
            pct = int(current / total * 100)
            self.sub_bar.setValue(pct)
            self.lbl_sub_pct.setText(f"{pct}%")
        else:
            self.sub_bar.setValue(0)
            self.lbl_sub_pct.setText("—")
        if len(detail) > 65:
            detail = detail[:62] + "..."
        self.lbl_sub_detail.setText(detail)

    def on_step_complete(self, step: PipelineStep):
        if step in self.step_widgets:
            pill, _ = self.step_widgets[step]
            pill.setStyleSheet("""
                background-color: #072115;
                border: 1px solid #134e32;
                color: #34d399;
                border-radius: 3px;
                font-size: 7.5pt;
                font-weight: 600;
                padding: 1px 4px;
            """)
            for s, key in self.steps:
                if s == step:
                    pill.setText(f"✓ {tr(key)}")
                    break
        self.sub_bar.setValue(100)
        self.lbl_sub_pct.setText("100%")

    def on_step_error(self, step: PipelineStep):
        if step in self.step_widgets:
            pill, _ = self.step_widgets[step]
            pill.setStyleSheet("""
                background-color: #27161b;
                border: 1.5px solid #4a2028;
                color: #fca5a5;
                border-radius: 3px;
                font-size: 7.5pt;
                font-weight: 700;
                padding: 1px 4px;
            """)
            for s, key in self.steps:
                if s == step:
                    pill.setText(f"✕ {tr(key)}")
                    break
        self.timer.stop()

    def log(self, message: str, level: str = "info"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        clr_map = {
            "info":  "#94a3b8",
            "ok":    "#34d399",
            "warn":  "#fbbf24",
            "error": "#f87171",
        }
        color = clr_map.get(level, clr_map["info"])
        self.log_text.append(
            f'<span style="color:#52525b">[{ts}] </span>'
            f'<span style="color:{color}">{message}</span>'
        )
        # Update live 1-line ticker
        self.lbl_latest_log.setText(f"• [{ts}] {message}")

    def log_html(self, html: str):
        self.log_text.append(html)

    def reset(self):
        self.log_text.clear()
        self.progress_bar.setValue(0)
        self.lbl_pct.setText("0%")
        self.sub_bar.setValue(0)
        self.lbl_sub_pct.setText("0%")
        self.lbl_sub_detail.setText("")
        self._current_step_enum = None
        self.lbl_current_step.setText(tr("pp_ready"))
        self.lbl_latest_log.setText(f"• {tr('status_ready')}")
        self.start_time = None
        self.timer.stop()
        self._last_elapsed_sec = 0
        self.lbl_elapsed.setText(tr("pp_elapsed", time="00:00"))
        for i, (s, key) in enumerate(self.steps):
            pill, _ = self.step_widgets[s]
            pill.setStyleSheet("""
                background-color: #121215;
                border: 1px solid #222227;
                color: #52525b;
                border-radius: 3px;
                font-size: 7.5pt;
                font-weight: 500;
                padding: 1px 4px;
            """)
            pill.setText(f"{i+1}. {tr(key)}")

    def retranslate_ui(self):
        """Update strings when language changes."""
        self.lbl_title.setText(tr("pp_title"))
        self.btn_cancel.setText(tr("pp_btn_cancel"))
        m, s = divmod(self._last_elapsed_sec, 60)
        self.lbl_elapsed.setText(tr("pp_elapsed", time=f"{m:02d}:{s:02d}"))
        
        # Step labels
        for i, (step, key) in enumerate(self.steps):
            if step in self.step_widgets:
                pill, _ = self.step_widgets[step]
                if self._current_step_enum == step:
                    pill.setText(f"▶ {tr(key)}")
                elif self._current_step_enum and self.steps.index((step, key)) < self.steps.index((self._current_step_enum, next(k for s, k in self.steps if s == self._current_step_enum))):
                    pill.setText(f"✓ {tr(key)}")
                else:
                    pill.setText(f"{i+1}. {tr(key)}")

        if self._current_step_enum and self._current_step_enum in self.step_widgets:
            _, lbl = self.step_widgets[self._current_step_enum]
            self.lbl_current_step.setText(lbl.text().replace("▶ ", ""))
        else:
            self.lbl_current_step.setText(tr("pp_ready"))
