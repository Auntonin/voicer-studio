import time
from datetime import timedelta
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTextEdit, QFrame
)
from PySide6.QtCore import Qt, QTimer
from core.models import PipelineStep
from core.i18n import tr
from config import COLORS
import datetime


class ProgressPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self._current_step_enum: PipelineStep | None = None
        self._last_elapsed_sec: int = 0
        self.setStyleSheet(f"""
            QProgressBar {{
                background-color: {COLORS['bg_input']};
                border: 1px solid {COLORS['border']};
                border-radius: 2px;
                height: 8px;
                text-align: center;
                color: transparent;
            }}
            QProgressBar::chunk {{
                background-color: {COLORS['accent']};
                border-radius: 1px;
            }}
            QProgressBar#subBar::chunk {{
                background-color: {COLORS['accent_green']};
            }}
            QTextEdit {{
                background-color: {COLORS['bg_input']};
                color: {COLORS['text_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 2px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 9pt;
                padding: 4px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # ── Top header ────────────────────────────────────────────────
        header = QHBoxLayout()
        self.lbl_title = QLabel(tr("pp_title"))
        self.lbl_title.setStyleSheet(f"color:{COLORS['text_primary']};font-weight:bold;font-size:10pt;")
        header.addWidget(self.lbl_title)
        header.addStretch()

        self.lbl_elapsed = QLabel(tr("pp_elapsed", time="00:00"))
        self.lbl_elapsed.setStyleSheet(f"color:{COLORS['text_muted']};font-family:monospace;font-size:9pt;")
        header.addWidget(self.lbl_elapsed)
        layout.addLayout(header)

        # ── Step nodes ────────────────────────────────────────────────
        self.step_layout = QHBoxLayout()
        self.step_layout.setSpacing(0)
        self.steps = [
            (PipelineStep.AUDIO_EXTRACT, "pp_step_extract"),
            (PipelineStep.VAD,           "pp_step_vad"),
            (PipelineStep.DIARIZATION,   "pp_step_diarize"),
            (PipelineStep.TRANSCRIPTION, "pp_step_transcribe"),
            (PipelineStep.VOICE_SEPARATION,"pp_step_separate"),
            (PipelineStep.CLIP_GENERATION,"pp_step_clips"),
            (PipelineStep.FRAME_EXTRACTION,"pp_step_frames"),
            (PipelineStep.BACKING_TRACK, "pp_step_bgtrack"),
            (PipelineStep.PACK_BUILD,    "pp_step_pack"),
            (PipelineStep.VALIDATION,    "pp_step_validate"),
        ]

        self.step_widgets = {}
        for i, (step, key) in enumerate(self.steps):
            col = QVBoxLayout()
            col.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            col.setSpacing(3)

            node = QLabel()
            node.setFixedSize(12, 12)
            node.setStyleSheet(
                f"background-color:{COLORS['bg_input']};"
                f"border:2px solid {COLORS['border']};border-radius:6px;"
            )

            lbl = QLabel(tr(key))
            lbl.setStyleSheet(f"color:{COLORS['text_muted']};font-size:7pt;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

            col.addWidget(node, 0, Qt.AlignmentFlag.AlignHCenter)
            col.addWidget(lbl,  0, Qt.AlignmentFlag.AlignHCenter)
            self.step_widgets[step] = (node, lbl)
            self.step_layout.addLayout(col)

            if i < len(self.steps) - 1:
                connector = QFrame()
                connector.setFrameShape(QFrame.Shape.HLine)
                connector.setFixedHeight(2)
                connector.setStyleSheet(f"background-color:{COLORS['border']};border:none;")
                line_wrap = QVBoxLayout()
                line_wrap.setContentsMargins(0, 5, 0, 0)
                line_wrap.addWidget(connector)
                self.step_layout.addLayout(line_wrap)
                self.step_layout.setStretchFactor(line_wrap, 1)

        layout.addLayout(self.step_layout)

        # ── Overall progress bar ──────────────────────────────────────
        overall_row = QHBoxLayout()
        self.lbl_current_step = QLabel(tr("pp_ready"))
        self.lbl_current_step.setFixedWidth(80)
        self.lbl_current_step.setStyleSheet(
            f"color:{COLORS['text_primary']};font-weight:bold;font-size:9pt;"
        )
        overall_row.addWidget(self.lbl_current_step)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(8)
        overall_row.addWidget(self.progress_bar)

        self.btn_cancel = QPushButton(tr("pp_btn_cancel"))
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setFixedWidth(64)
        self.btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_input']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 2px;
                padding: 3px 8px;
                font-size: 9pt;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_red']};
                border-color: {COLORS['accent_red']};
                color: white;
            }}
        """)
        overall_row.addWidget(self.btn_cancel)
        layout.addLayout(overall_row)

        # ── Sub-step progress bar + detail label ──────────────────────
        sub_row = QHBoxLayout()
        sub_row.setSpacing(6)

        self.lbl_sub_pct = QLabel("0%")
        self.lbl_sub_pct.setFixedWidth(36)
        self.lbl_sub_pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_sub_pct.setStyleSheet(f"color:{COLORS['accent_green']};font-size:8pt;font-weight:bold;")
        sub_row.addWidget(self.lbl_sub_pct)

        self.sub_bar = QProgressBar()
        self.sub_bar.setObjectName("subBar")
        self.sub_bar.setRange(0, 100)
        self.sub_bar.setValue(0)
        self.sub_bar.setFixedHeight(5)
        sub_row.addWidget(self.sub_bar)

        self.lbl_sub_detail = QLabel("")
        self.lbl_sub_detail.setStyleSheet(f"color:{COLORS['text_muted']};font-size:8pt;")
        self.lbl_sub_detail.setFixedWidth(340)
        self.lbl_sub_detail.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        sub_row.addWidget(self.lbl_sub_detail)
        sub_row.addStretch()
        layout.addLayout(sub_row)

        # ── Log ───────────────────────────────────────────────────────
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFixedHeight(100)
        layout.addWidget(self.log_text)

        # ── Timer ─────────────────────────────────────────────────────
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_elapsed)
        self.start_time = None

    # ── Elapsed timer ─────────────────────────────────────────────────

    def _update_elapsed(self):
        if self.start_time:
            self._last_elapsed_sec = int(time.time() - self.start_time)
            m, s = divmod(self._last_elapsed_sec, 60)
            self.lbl_elapsed.setText(tr("pp_elapsed", time=f"{m:02d}:{s:02d}"))

    def set_elapsed(self, seconds: float):
        self._last_elapsed_sec = int(seconds)
        m, s = divmod(self._last_elapsed_sec, 60)
        self.lbl_elapsed.setText(tr("pp_elapsed", time=f"{m:02d}:{s:02d}"))

    # ── Step state ────────────────────────────────────────────────────

    def set_step(self, step: PipelineStep):
        self._current_step_enum = step
        for s, (node, lbl) in self.step_widgets.items():
            if s == step:
                node.setStyleSheet(
                    f"background-color:{COLORS['accent']};"
                    f"border:2px solid {COLORS['accent_hover']};border-radius:6px;"
                )
                lbl.setStyleSheet(f"color:{COLORS['text_primary']};font-weight:bold;font-size:7pt;")
                self.lbl_current_step.setText(lbl.text())
                self.lbl_sub_detail.setText("")
                self.sub_bar.setValue(0)
                self.lbl_sub_pct.setText("0%")
                if not self.start_time:
                    self.start_time = time.time()
                    self.timer.start(1000)

    def set_progress(self, value: int):
        self.progress_bar.setValue(value)

    def set_sub_progress(self, current: int, total: int, detail: str):
        """Called by sub_progress signal from PipelineWorker."""
        if total > 0:
            pct = int(current / total * 100)
            self.sub_bar.setValue(pct)
            self.lbl_sub_pct.setText(f"{pct}%")
        else:
            self.sub_bar.setValue(0)
            self.lbl_sub_pct.setText("—")
        # Truncate long messages so they don't overflow the label
        if len(detail) > 60:
            detail = detail[:57] + "..."
        self.lbl_sub_detail.setText(detail)

    def on_step_complete(self, step: PipelineStep):
        if step in self.step_widgets:
            node, lbl = self.step_widgets[step]
            node.setStyleSheet(
                f"background-color:{COLORS['accent_green']};"
                f"border:2px solid {COLORS['accent_green']};border-radius:6px;"
            )
            lbl.setStyleSheet(f"color:{COLORS['accent_green']};font-size:7pt;")
        self.sub_bar.setValue(100)
        self.lbl_sub_pct.setText("100%")

    def on_step_error(self, step: PipelineStep):
        if step in self.step_widgets:
            node, lbl = self.step_widgets[step]
            node.setStyleSheet(
                f"background-color:{COLORS['accent_red']};"
                f"border:2px solid {COLORS['accent_red']};border-radius:6px;"
            )
            lbl.setStyleSheet(f"color:{COLORS['accent_red']};font-size:7pt;")
        self.timer.stop()

    # ── Log ───────────────────────────────────────────────────────────

    def log(self, message: str, level: str = "info"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        clr_map = {
            "info":  COLORS["text_secondary"],
            "ok":    COLORS["accent_green"],
            "warn":  COLORS["accent_yellow"],
            "error": COLORS["accent_red"],
        }
        color = clr_map.get(level, clr_map["info"])
        self.log_text.append(
            f'<span style="color:{COLORS["text_muted"]}">[{ts}] </span>'
            f'<span style="color:{color}">{message}</span>'
        )

    def log_html(self, html: str):
        self.log_text.append(html)

    # ── Reset ─────────────────────────────────────────────────────────

    def reset(self):
        self.log_text.clear()
        self.progress_bar.setValue(0)
        self.sub_bar.setValue(0)
        self.lbl_sub_pct.setText("0%")
        self.lbl_sub_detail.setText("")
        self._current_step_enum = None
        self.lbl_current_step.setText(tr("pp_ready"))
        self.start_time = None
        self.timer.stop()
        self._last_elapsed_sec = 0
        self.lbl_elapsed.setText(tr("pp_elapsed", time="00:00"))
        for s, (node, lbl) in self.step_widgets.items():
            node.setStyleSheet(
                f"background-color:{COLORS['bg_input']};"
                f"border:2px solid {COLORS['border']};border-radius:6px;"
            )
            lbl.setStyleSheet(f"color:{COLORS['text_muted']};font-size:7pt;")

    def retranslate_ui(self):
        """Update strings when language changes."""
        self.lbl_title.setText(tr("pp_title"))
        self.btn_cancel.setText(tr("pp_btn_cancel"))
        m, s = divmod(self._last_elapsed_sec, 60)
        self.lbl_elapsed.setText(tr("pp_elapsed", time=f"{m:02d}:{s:02d}"))
        
        # Step labels
        for step, key in self.steps:
            if step in self.step_widgets:
                _, lbl = self.step_widgets[step]
                lbl.setText(tr(key))

        if self._current_step_enum and self._current_step_enum in self.step_widgets:
            _, lbl = self.step_widgets[self._current_step_enum]
            self.lbl_current_step.setText(lbl.text())
        else:
            self.lbl_current_step.setText(tr("pp_ready"))
