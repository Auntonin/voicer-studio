"""
gui/export_dialog.py
====================
Adobe Media Encoder / DaVinci Resolve inspired Export Progress Dialog for Voicer Studio.
Features:
- Completely offloaded background execution (zero UI freezing, NO "Not Responding")
- Pre-export confirmation & settings page
- Live real-time progress bar (0% - 100%)
- Live Elapsed Time & Estimated Time Remaining (ETA)
- Dynamic task activity description & animated pulse
- Post-export success screen with instant "Open Output Folder" button
"""

from __future__ import annotations

import time
import subprocess
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QStackedWidget, QFrame,
    QFileDialog, QCheckBox, QMessageBox
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread, QUrl
from PySide6.QtGui import QIcon, QFont, QColor, QDesktopServices, QPixmap

from config import COLORS, ASSETS_DIR, SUBPROCESS_FLAGS
from core.models import PipelineState
from core.pack_builder import PackBuilder
from core.quality_checker import QualityChecker
from core.i18n import tr
from gui.ui_utils import apply_dark_title_bar


class FullExportWorker(QThread):
    """
    Background worker that runs build_pack and export_zip asynchronously,
    preventing the GUI thread from freezing.
    """
    progress = Signal(int, str)             # (percent, detail_message)
    finished = Signal(str, str, float, int) # (zip_path, pack_dir, elapsed_sec, zip_size_bytes)
    error    = Signal(str)

    def __init__(self, state: PipelineState, output_base: Path, zip_path: Path, options: dict, parent=None):
        super().__init__(parent)
        self.state = state
        self.output_base = output_base
        self.zip_path = zip_path
        self.options = options
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        t0 = time.time()
        try:
            builder = PackBuilder()

            def on_progress(pct: int, msg: str):
                if self._is_cancelled:
                    raise RuntimeError("Export cancelled by user")
                self.progress.emit(max(1, min(99, pct)), msg)

            self.progress.emit(2, tr("exp_step_assembling"))
            pack_dir = builder.build_pack(
                self.state, self.output_base, self.options,
                progress_cb=on_progress
            )

            if self._is_cancelled:
                raise RuntimeError("Export cancelled by user")

            self.progress.emit(74, tr("exp_step_validating"))
            checker = QualityChecker()
            checker.check_all(self.state, pack_dir)

            self.progress.emit(78, tr("exp_step_zipping"))
            PackBuilder.export_zip(pack_dir, self.zip_path, progress_cb=on_progress)

            if self._is_cancelled:
                raise RuntimeError("Export cancelled by user")

            elapsed = time.time() - t0
            zip_size = self.zip_path.stat().st_size if self.zip_path.exists() else 0
            self.progress.emit(100, tr("exp_step_success"))
            self.finished.emit(str(self.zip_path), str(pack_dir), elapsed, zip_size)

        except Exception as e:
            if not self._is_cancelled:
                self.error.emit(str(e))


class ExportDialog(QDialog):
    """
    Modern Adobe-style Export Dialog.
    """
    SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def showEvent(self, event):
        super().showEvent(event)
        apply_dark_title_bar(self)

    def __init__(self, parent, state: PipelineState, settings: dict):
        super().__init__(parent)
        self.state = state
        self.settings = settings
        self.worker: Optional[FullExportWorker] = None

        self.start_time: float = 0.0
        self.current_percent: int = 0
        self._spinner_idx: int = 0

        self.setWindowTitle(tr("exp_win_title"))
        self.setFixedSize(620, 440)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {COLORS['bg_primary']};
                color: {COLORS['text_primary']};
            }}
            QFrame#Card {{
                background-color: {COLORS['bg_panel']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
            }}
            QLabel {{
                color: {COLORS['text_primary']};
            }}
            QProgressBar {{
                background-color: #141414;
                border: 1px solid #333333;
                border-radius: 6px;
                text-align: center;
                color: #FFFFFF;
                font-weight: bold;
                font-size: 9pt;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284C7, stop:1 #38BDF8);
                border-radius: 5px;
            }}
            QPushButton {{
                background-color: {COLORS['bg_input']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 7px 18px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: #383838;
                border-color: #555555;
            }}
            QPushButton#PrimaryBtn {{
                background-color: #1473E6;
                color: #FFFFFF;
                border: 1px solid #2563EB;
                font-weight: bold;
            }}
            QPushButton#PrimaryBtn:hover {{
                background-color: #2563EB;
            }}
            QPushButton#DangerBtn {{
                background-color: #241416;
                color: #F87171;
                border: 1px solid #7F1D1D;
                border-radius: 6px;
                padding: 7px 18px;
                font-weight: 600;
            }}
            QPushButton#DangerBtn:hover {{
                background-color: #3B1215;
                border-color: #EF4444;
                color: #FFFFFF;
            }}
            QPushButton#DangerBtn:pressed {{
                background-color: #1F0A0C;
            }}
        """)

        ico_path = ASSETS_DIR / "app_icon.ico"
        if ico_path.exists():
            self.setWindowIcon(QIcon(str(ico_path)))

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(16)

        self.stack = QStackedWidget()
        self.main_layout.addWidget(self.stack)

        self._setup_page_confirm()
        self._setup_page_progress()
        self._setup_page_complete()

        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._on_timer_tick)

        self.stack.setCurrentIndex(0)

    def _get_preview_pixmap(self, width: int = 144, height: int = 81) -> Optional[QPixmap]:
        """Find or generate a video/dialogue preview thumbnail."""
        for d in self.state.dialogues:
            if not d.is_deleted and d.image_path and Path(d.image_path).exists():
                pix = QPixmap(str(d.image_path))
                if not pix.isNull():
                    return pix.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)

        if self.state.video_path and Path(self.state.video_path).exists():
            from config import TEMP_DIR, SUBPROCESS_FLAGS
            thumb_cache = TEMP_DIR / "thumbnails" / f"{Path(self.state.video_path).stem}_preview.jpg"
            thumb_cache.parent.mkdir(parents=True, exist_ok=True)
            if thumb_cache.exists():
                pix = QPixmap(str(thumb_cache))
                if not pix.isNull():
                    return pix.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            else:
                # Non-blocking background extraction: ExportDialog opens instantaneously with zero freezing
                def _gen_thumb():
                    try:
                        v_src = self.state.preview_proxy_path if (self.state.preview_proxy_path and self.state.preview_proxy_path.exists()) else self.state.video_path
                        cmd = [
                            "ffmpeg", "-y", "-ss", "00:00:01",
                            "-i", str(v_src),
                            "-frames:v", "1",
                            "-vf", f"scale={width*2}:{height*2}:force_original_aspect_ratio=increase,crop={width*2}:{height*2}",
                            "-q:v", "3",
                            str(thumb_cache)
                        ]
                        subprocess.run(cmd, capture_output=True, timeout=10, creationflags=SUBPROCESS_FLAGS)
                    except Exception:
                        pass
                import threading
                threading.Thread(target=_gen_thumb, daemon=True).start()
        return None

    # ── Page 0: Confirm & Pre-Export ──────────────────────────────────────────

    def _setup_page_confirm(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        lbl_header = QLabel(tr("exp_header"))
        lbl_header.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        lbl_sub = QLabel(tr("exp_sub"))
        lbl_sub.setStyleSheet("color: #9E9E9E; font-size: 9pt;")
        layout.addWidget(lbl_header)
        layout.addWidget(lbl_sub)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(12)

        # Preview Row: Left thumbnail, right metadata
        preview_row = QHBoxLayout()
        preview_row.setSpacing(14)

        lbl_thumb = QLabel()
        lbl_thumb.setFixedSize(144, 81)
        lbl_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_thumb.setStyleSheet("background-color: #121212; border: 1px solid #2D2D2D; border-radius: 6px;")
        pix = self._get_preview_pixmap(144, 81)
        if pix:
            lbl_thumb.setPixmap(pix)
        else:
            lbl_thumb.setText("Video")
            lbl_thumb.setStyleSheet("background-color: #141414; border: 1px solid #282828; border-radius: 6px; color: #777777; font-weight: bold;")
        preview_row.addWidget(lbl_thumb)

        vbox_meta = QVBoxLayout()
        vbox_meta.setSpacing(4)
        pack_title = self.state.pack_info.title or (self.state.video_path.stem if self.state.video_path else "Dialogue_Pack")
        self.lbl_pack_title = QLabel(f"<b>{tr('exp_pack_title')}</b> {pack_title}")
        self.lbl_pack_title.setStyleSheet("font-size: 10pt; color: #FFFFFF;")
        vbox_meta.addWidget(self.lbl_pack_title)

        active_items = self.state.active_dialogues()
        total_dur = sum(d.duration for d in active_items)
        dur_m = int(total_dur // 60)
        dur_s = int(total_dur % 60)
        spk_count = len(self.state.speakers)
        contents_str = tr("exp_clips_characters", clips=len(active_items), speakers=spk_count)
        lbl_stats = QLabel(f"<b>{tr('exp_contents')}</b> {contents_str}<br/><b>{tr('exp_total_duration')}</b> {dur_m:02d}:{dur_s:02d}")
        lbl_stats.setStyleSheet("color: #CCCCCC; font-size: 9pt;")
        vbox_meta.addWidget(lbl_stats)
        vbox_meta.addStretch()

        preview_row.addLayout(vbox_meta, 1)
        card_layout.addLayout(preview_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #282828; max-height: 1px;")
        card_layout.addWidget(sep)

        lbl_dest_hdr = QLabel(f"<b>{tr('exp_dest_zip')}</b>")
        card_layout.addWidget(lbl_dest_hdr)

        dest_row = QHBoxLayout()
        dest_row.setSpacing(8)
        base_dir = Path(self.settings.get("output_dir", "")) if self.settings.get("output_dir", "") else (self.state.video_path.parent / "output" if self.state.video_path else Path.cwd() / "output")
        suggested_zip = PackBuilder.get_unique_zip_path(base_dir, pack_title)

        self.lbl_dest_path = QLabel(str(suggested_zip))
        self.lbl_dest_path.setStyleSheet("background-color: #161616; padding: 6px 10px; border-radius: 4px; border: 1px solid #2D2D2D; color: #E0E0E0;")
        self.lbl_dest_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.target_zip_path = suggested_zip

        btn_browse = QPushButton(tr("exp_browse"))
        btn_browse.clicked.connect(self._on_browse_destination)

        dest_row.addWidget(self.lbl_dest_path, 1)
        dest_row.addWidget(btn_browse)
        card_layout.addLayout(dest_row)

        self.chk_dub_video = QCheckBox(tr("exp_include_game_video"))
        self.chk_dub_video.setChecked(self.state.pack_info.include_dub_video)
        self.chk_dub_video.setStyleSheet("margin-top: 4px; color: #CCCCCC;")
        card_layout.addWidget(self.chk_dub_video)

        layout.addWidget(card)
        layout.addStretch()

        btn_box = QHBoxLayout()
        btn_box.setSpacing(10)
        btn_box.addStretch()

        btn_cancel = QPushButton(tr("exp_btn_cancel"))
        btn_cancel.clicked.connect(self.reject)

        btn_export = QPushButton(tr("exp_btn_start"))
        btn_export.setObjectName("PrimaryBtn")
        btn_export.setMinimumWidth(120)
        btn_export.clicked.connect(self._start_export)

        btn_box.addWidget(btn_cancel)
        btn_box.addWidget(btn_export)
        layout.addLayout(btn_box)

        self.stack.addWidget(page)

    def _on_browse_destination(self):
        suggested = str(self.target_zip_path)
        path, _ = QFileDialog.getSaveFileName(
            self, tr("exp_choose_dest"),
            suggested, tr("exp_filter_zip")
        )
        if path:
            self.target_zip_path = Path(path)
            self.lbl_dest_path.setText(str(self.target_zip_path))

    # ── Page 1: Live Progress & ETA ───────────────────────────────────────────

    def _setup_page_progress(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        hdr_row = QHBoxLayout()
        lbl_header = QLabel(tr("exp_prog_header"))
        lbl_header.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        hdr_row.addWidget(lbl_header)
        hdr_row.addStretch()

        self.lbl_spinner = QLabel("⠋")
        self.lbl_spinner.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self.lbl_spinner.setStyleSheet("color: #38BDF8;")
        hdr_row.addWidget(self.lbl_spinner)
        layout.addLayout(hdr_row)

        self.lbl_progress_sub = QLabel(tr("exp_prog_sub"))
        self.lbl_progress_sub.setStyleSheet("color: #9E9E9E; font-size: 9pt;")
        layout.addWidget(self.lbl_progress_sub)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(12)

        # Mini thumbnail + current task row
        task_row = QHBoxLayout()
        task_row.setSpacing(12)

        self.lbl_prog_thumb = QLabel()
        self.lbl_prog_thumb.setFixedSize(96, 54)
        self.lbl_prog_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_prog_thumb.setStyleSheet("background-color: #121212; border: 1px solid #2D2D2D; border-radius: 4px;")
        task_row.addWidget(self.lbl_prog_thumb)

        vbox_task = QVBoxLayout()
        vbox_task.setSpacing(3)
        self.lbl_prog_title = QLabel()
        self.lbl_prog_title.setStyleSheet("font-weight: bold; color: #FFFFFF; font-size: 9.5pt;")
        self.lbl_step_detail = QLabel(tr("exp_init_engine"))
        self.lbl_step_detail.setStyleSheet("color: #38BDF8; font-weight: 500; font-size: 9pt;")
        vbox_task.addWidget(self.lbl_prog_title)
        vbox_task.addWidget(self.lbl_step_detail)
        vbox_task.addStretch()
        task_row.addLayout(vbox_task, 1)
        card_layout.addLayout(task_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(22)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        card_layout.addWidget(self.progress_bar)

        stats_frame = QFrame()
        stats_frame.setStyleSheet("background-color: #171717; border-radius: 6px; padding: 10px; border: 1px solid #282828;")
        stats_layout = QHBoxLayout(stats_frame)
        stats_layout.setContentsMargins(10, 6, 10, 6)

        vbox_elapsed = QVBoxLayout()
        vbox_elapsed.setSpacing(2)
        lbl_el_title = QLabel(tr("exp_elapsed_time"))
        lbl_el_title.setStyleSheet("color: #888888; font-size: 7.5pt; font-weight: bold;")
        self.lbl_elapsed = QLabel("00:00")
        self.lbl_elapsed.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.lbl_elapsed.setStyleSheet("color: #FFFFFF;")
        vbox_elapsed.addWidget(lbl_el_title)
        vbox_elapsed.addWidget(self.lbl_elapsed)
        stats_layout.addLayout(vbox_elapsed)

        vbox_eta = QVBoxLayout()
        vbox_eta.setSpacing(2)
        lbl_eta_title = QLabel(tr("exp_est_remaining"))
        lbl_eta_title.setStyleSheet("color: #888888; font-size: 7.5pt; font-weight: bold;")
        self.lbl_eta = QLabel(tr("exp_estimating"))
        self.lbl_eta.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.lbl_eta.setStyleSheet("color: #38BDF8;")
        vbox_eta.addWidget(lbl_eta_title)
        vbox_eta.addWidget(self.lbl_eta)
        stats_layout.addLayout(vbox_eta)

        vbox_pct = QVBoxLayout()
        vbox_pct.setSpacing(2)
        lbl_pct_title = QLabel(tr("exp_progress"))
        lbl_pct_title.setStyleSheet("color: #888888; font-size: 7.5pt; font-weight: bold;")
        self.lbl_pct = QLabel("0%")
        self.lbl_pct.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.lbl_pct.setStyleSheet("color: #10B981;")
        vbox_pct.addWidget(lbl_pct_title)
        vbox_pct.addWidget(self.lbl_pct)
        stats_layout.addLayout(vbox_pct)

        card_layout.addWidget(stats_frame)
        layout.addWidget(card)
        layout.addStretch()

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        self.btn_abort = QPushButton(tr("exp_btn_cancel_export"))
        self.btn_abort.setObjectName("DangerBtn")
        self.btn_abort.clicked.connect(self._on_cancel_export)
        btn_box.addWidget(self.btn_abort)
        layout.addLayout(btn_box)

        self.stack.addWidget(page)

    # ── Page 2: Completion ───────────────────────────────────────────────────

    def _setup_page_complete(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        lbl_header = QLabel(tr("exp_done_header"))
        lbl_header.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        lbl_header.setStyleSheet("color: #10B981;")
        lbl_sub = QLabel(tr("exp_done_sub"))
        lbl_sub.setStyleSheet("color: #9E9E9E; font-size: 9pt;")
        layout.addWidget(lbl_header)
        layout.addWidget(lbl_sub)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(10)

        self.lbl_done_path = QLabel()
        self.lbl_done_path.setStyleSheet("color: #FFFFFF; font-weight: 500; font-size: 10pt;")
        self.lbl_done_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card_layout.addWidget(self.lbl_done_path)

        sep_done = QFrame()
        sep_done.setFrameShape(QFrame.Shape.HLine)
        sep_done.setStyleSheet("background-color: #282828; max-height: 1px; margin: 4px 0px;")
        card_layout.addWidget(sep_done)

        self.lbl_done_size = QLabel()
        self.lbl_done_size.setStyleSheet("color: #CCCCCC; font-size: 9.5pt;")
        card_layout.addWidget(self.lbl_done_size)

        self.lbl_done_cues = QLabel()
        self.lbl_done_cues.setStyleSheet("color: #CCCCCC; font-size: 9.5pt;")
        card_layout.addWidget(self.lbl_done_cues)

        self.lbl_done_time = QLabel()
        self.lbl_done_time.setStyleSheet("color: #CCCCCC; font-size: 9.5pt;")
        card_layout.addWidget(self.lbl_done_time)

        self.lbl_done_folder = QLabel()
        self.lbl_done_folder.setStyleSheet("color: #888888; font-size: 8.5pt;")
        self.lbl_done_folder.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card_layout.addWidget(self.lbl_done_folder)


        layout.addWidget(card)
        layout.addStretch()

        btn_box = QHBoxLayout()
        btn_box.setSpacing(10)
        btn_box.addStretch()

        btn_open = QPushButton(tr("exp_btn_open_folder"))
        btn_open.setObjectName("PrimaryBtn")
        btn_open.clicked.connect(self._open_output_folder)

        btn_close = QPushButton(tr("exp_btn_done"))
        btn_close.clicked.connect(self.accept)

        btn_box.addWidget(btn_open)
        btn_box.addWidget(btn_close)
        layout.addLayout(btn_box)

        self.stack.addWidget(page)

    # ── Execution Handlers ────────────────────────────────────────────────────

    def _start_export(self):
        self.state.pack_info.include_dub_video = self.chk_dub_video.isChecked()

        # Update thumbnail & title on progress page
        pix = self._get_preview_pixmap(96, 54)
        if pix:
            self.lbl_prog_thumb.setPixmap(pix)
        else:
            self.lbl_prog_thumb.setText("Video")
            self.lbl_prog_thumb.setStyleSheet("background-color: #141414; border: 1px solid #282828; border-radius: 4px; color: #777777;")
        pack_title = self.state.pack_info.title or (self.state.video_path.stem if self.state.video_path else "Dialogue_Pack")
        self.lbl_prog_title.setText(pack_title)

        self.stack.setCurrentIndex(1)
        self.start_time = time.time()
        self.timer.start()

        options = {
            "timestamp_mode": self.settings.get("timestamp_mode", "start_only"),
            "include_dub_video": self.state.pack_info.include_dub_video,
            "speaker_display_names": {sid: spk.display_name for sid, spk in self.state.speakers.items()}
        }

        output_base = self.target_zip_path.parent
        self.worker = FullExportWorker(self.state, output_base, self.target_zip_path, options)
        self.worker.progress.connect(self._on_worker_progress)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.error.connect(self._on_worker_error)
        self.worker.start()

    def _on_worker_progress(self, percent: int, msg: str):
        self.current_percent = percent
        self.progress_bar.setValue(percent)
        self.lbl_step_detail.setText(msg)
        self.lbl_pct.setText(f"{percent}%")

    def _on_timer_tick(self):
        self._spinner_idx = (self._spinner_idx + 1) % len(self.SPINNER_FRAMES)
        self.lbl_spinner.setText(self.SPINNER_FRAMES[self._spinner_idx])

        if self.start_time <= 0:
            return
        elapsed = time.time() - self.start_time
        em = int(elapsed // 60)
        es = int(elapsed % 60)
        self.lbl_elapsed.setText(f"{em:02d}:{es:02d}")

        if self.current_percent > 3:
            total_est = elapsed / (self.current_percent / 100.0)
            remaining = max(0.0, total_est - elapsed)
            rm = int(remaining // 60)
            rs = int(remaining % 60)
            if rm > 0:
                self.lbl_eta.setText(f"~{rm}m {rs:02d}s")
            else:
                self.lbl_eta.setText(f"~{rs}s")
        else:
            self.lbl_eta.setText(tr("exp_estimating"))

    def _on_worker_finished(self, zip_path: str, pack_dir: str, elapsed: float, size_bytes: int):
        self.timer.stop()
        size_mb = size_bytes / (1024.0 * 1024.0)

        self.lbl_done_path.setText(f"<b>{tr('exp_zip_archive')}</b> {zip_path}")
        active_count = len(self.state.active_dialogues())
        self.lbl_done_size.setText(f"• <b>{tr('exp_archive_size')}</b> {size_mb:.2f} MB")
        cues_str = tr("exp_cues_generated", count=active_count)
        self.lbl_done_cues.setText(f"• <b>{tr('exp_total_dialogues')}</b> {cues_str}")
        sec_str = tr("exp_seconds", sec=elapsed)
        self.lbl_done_time.setText(f"• <b>{tr('exp_processing_time')}</b> {sec_str}")
        self.lbl_done_folder.setText(f"• <b>{tr('exp_pack_dir')}</b> {pack_dir}")

        self.stack.setCurrentIndex(2)

    def _on_worker_error(self, err_msg: str):
        self.timer.stop()
        QMessageBox.critical(self, tr("exp_msg_failed_title"), tr("exp_msg_failed", error=err_msg))
        self.reject()

    def _on_cancel_export(self):
        reply = QMessageBox.question(
            self, tr("exp_msg_cancel_title"),
            tr("exp_msg_cancel_prompt"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            if self.worker:
                self.worker.cancel()
                self.btn_abort.setEnabled(False)
                self.lbl_step_detail.setText(tr("exp_cancelling"))
                self.worker.wait(2000)
            self.reject()

    def _open_output_folder(self):
        folder = self.target_zip_path.parent
        if sys.platform == "win32" and self.target_zip_path.exists():
            subprocess.run(["explorer", f"/select,{self.target_zip_path}"], creationflags=SUBPROCESS_FLAGS)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
