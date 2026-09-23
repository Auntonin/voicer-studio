"""
gui/update_dialog.py
====================
Modern Adobe-style Update Dialog for Voicer Studio.

Displays:
- Current vs New version pills
- Formatted Release Notes / Changelog
- Real-time download progress bar with byte count, transfer speed, and ETA
- Self-update and restart trigger
- "Up-to-date" confirmation dialog for manual check
"""

from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTextBrowser, QFrame, QWidget, QMessageBox, QApplication
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QFont, QColor

from config import APP_NAME, APP_VERSION, COLORS, ASSETS_DIR
from core.updater import (
    UpdateInfo, UpdateDownloaderThread,
    apply_update_and_restart, get_current_app_path
)
from core.i18n import tr
from gui.ui_utils import apply_dark_title_bar


def format_bytes(num_bytes: int) -> str:
    """Formats bytes into human-readable string (KB, MB, GB)."""
    if num_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_idx = 0
    val = float(num_bytes)
    while val >= 1024.0 and unit_idx < len(units) - 1:
        val /= 1024.0
        unit_idx += 1
    return f"{val:.1f} {units[unit_idx]}"


class UpdateDialog(QDialog):
    """
    Modern Adobe/DaVinci inspired software update dialog.
    """

    def showEvent(self, event):
        super().showEvent(event)
        apply_dark_title_bar(self)

    def __init__(self, parent=None, update_info: Optional[UpdateInfo] = None, is_up_to_date: bool = False):
        super().__init__(parent)
        self.update_info = update_info
        self.is_up_to_date = is_up_to_date
        self._downloader: Optional[UpdateDownloaderThread] = None
        self._downloaded_file: Optional[Path] = None
        self._is_zip: bool = False

        self.setWindowTitle(tr("update_dialog_title"))
        self.setMinimumWidth(560)
        self.resize(600, 480)
        self.setStyleSheet(self._build_stylesheet())

        # Window icon
        ico_path = ASSETS_DIR / "app_icon.ico"
        png_path = ASSETS_DIR / "app_icon.png"
        if ico_path.exists():
            self.setWindowIcon(QIcon(str(ico_path)))
        elif png_path.exists():
            self.setWindowIcon(QIcon(str(png_path)))

        self._build_ui()

    def _build_stylesheet(self) -> str:
        return f"""
        QDialog {{
            background-color: {COLORS['bg_primary']};
            color: {COLORS['text_primary']};
            font-family: 'Segoe UI', 'Leelawadee UI', 'Tahoma', system-ui, sans-serif;
            font-size: 9.5pt;
        }}
        QFrame#card_panel {{
            background-color: {COLORS['bg_panel']};
            border: 1px solid {COLORS['border']};
            border-radius: 8px;
        }}
        QTextBrowser {{
            background-color: {COLORS['bg_input']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            color: {COLORS['text_primary']};
            padding: 10px;
            font-size: 9pt;
            selection-background-color: {COLORS['accent']};
        }}
        QProgressBar {{
            background-color: {COLORS['bg_input']};
            border: 1px solid {COLORS['border']};
            border-radius: 4px;
            text-align: center;
            color: #ffffff;
            font-weight: bold;
            font-size: 8.5pt;
            height: 14px;
        }}
        QProgressBar::chunk {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #1473E6, stop:1 #3A96FF);
            border-radius: 3px;
        }}
        QPushButton {{
            background-color: {COLORS['bg_secondary']};
            color: {COLORS['text_primary']};
            border: 1px solid {COLORS['border']};
            border-radius: 5px;
            padding: 7px 18px;
            font-size: 9.5pt;
            font-weight: 500;
        }}
        QPushButton:hover {{
            background-color: #3e3e3e;
            border-color: {COLORS['border_light']};
        }}
        QPushButton#btn_primary {{
            background-color: {COLORS['accent']};
            color: #ffffff;
            border: none;
            font-weight: 600;
        }}
        QPushButton#btn_primary:hover {{
            background-color: {COLORS['accent_hover']};
        }}
        QPushButton#btn_primary:disabled {{
            background-color: #334e68;
            color: #829ab1;
        }}
        QPushButton#btn_link {{
            background: transparent;
            border: none;
            color: {COLORS['accent_hover']};
            text-decoration: underline;
            padding: 0px 4px;
            font-size: 9pt;
        }}
        QPushButton#btn_link:hover {{
            color: #63b3ed;
        }}
        """

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # ── Up-to-date screen ──
        if self.is_up_to_date or not self.update_info:
            self._build_up_to_date_view(main_layout)
            return

        # ── Header Banner Card ──
        header_card = QFrame()
        header_card.setObjectName("card_panel")
        header_layout = QHBoxLayout(header_card)
        header_layout.setContentsMargins(16, 14, 16, 14)
        header_layout.setSpacing(16)

        # App Logo
        lbl_logo = QLabel()
        png_path = ASSETS_DIR / "app_icon.png"
        if png_path.exists():
            lbl_logo.setPixmap(QIcon(str(png_path)).pixmap(QSize(48, 48)))
        lbl_logo.setFixedSize(48, 48)
        header_layout.addWidget(lbl_logo)

        # Title and Version Info
        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        lbl_title = QLabel(tr("update_available_title"))
        lbl_title.setStyleSheet("font-size: 13pt; font-weight: bold; color: #ffffff;")
        title_box.addWidget(lbl_title)

        version_layout = QHBoxLayout()
        version_layout.setSpacing(8)

        # Current version badge
        lbl_cur = QLabel(f"{tr('update_cur_ver')}: v{APP_VERSION}")
        lbl_cur.setStyleSheet("""
            background-color: #333333; color: #aaaaaa; 
            border-radius: 4px; padding: 2px 8px; font-size: 8.5pt;
        """)
        version_layout.addWidget(lbl_cur)

        lbl_arrow = QLabel("➔")
        lbl_arrow.setStyleSheet("color: #666666; font-size: 10pt; font-weight: bold;")
        version_layout.addWidget(lbl_arrow)

        # New version badge
        lbl_new = QLabel(f"{tr('update_new_ver')}: v{self.update_info.version}")
        lbl_new.setStyleSheet(f"""
            background-color: #064e3b; color: #34d399; 
            border: 1px solid #059669; border-radius: 4px; 
            padding: 2px 8px; font-weight: bold; font-size: 8.5pt;
        """)
        version_layout.addWidget(lbl_new)

        if self.update_info.asset_size > 0:
            size_str = format_bytes(self.update_info.asset_size)
            lbl_size = QLabel(f"• {size_str}")
            lbl_size.setStyleSheet("color: #888888; font-size: 8.5pt;")
            version_layout.addWidget(lbl_size)

        version_layout.addStretch()
        title_box.addLayout(version_layout)
        header_layout.addLayout(title_box)

        main_layout.addWidget(header_card)

        # ── Release Notes Section ──
        lbl_notes_title = QLabel(tr("update_whats_new"))
        lbl_notes_title.setStyleSheet("font-size: 10pt; font-weight: bold; color: #e0e0e0;")
        main_layout.addWidget(lbl_notes_title)

        self.text_notes = QTextBrowser()
        self.text_notes.setOpenExternalLinks(True)
        html_notes = self._format_markdown_notes(self.update_info.body or tr("update_no_notes"))
        self.text_notes.setHtml(html_notes)
        main_layout.addWidget(self.text_notes, stretch=1)

        # ── Progress Section (Hidden initially) ──
        self.progress_container = QWidget()
        prog_layout = QVBoxLayout(self.progress_container)
        prog_layout.setContentsMargins(0, 0, 0, 0)
        prog_layout.setSpacing(6)

        self.prog_bar = QProgressBar()
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setValue(0)
        prog_layout.addWidget(self.prog_bar)

        self.lbl_prog_status = QLabel(tr("update_downloading"))
        self.lbl_prog_status.setStyleSheet("font-size: 8.5pt; color: #aaaaaa;")
        prog_layout.addWidget(self.lbl_prog_status)

        self.progress_container.hide()
        main_layout.addWidget(self.progress_container)

        # ── Mode Hint ──
        _, is_frozen = get_current_app_path()
        if not is_frozen:
            lbl_dev_hint = QLabel(tr("update_dev_mode_hint"))
            lbl_dev_hint.setStyleSheet("color: #f59e0b; font-size: 8pt; font-style: italic;")
            lbl_dev_hint.setWordWrap(True)
            main_layout.addWidget(lbl_dev_hint)

        # ── Bottom Action Buttons ──
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(10)

        self.btn_web = QPushButton(tr("update_view_github"))
        self.btn_web.setObjectName("btn_link")
        self.btn_web.clicked.connect(self._open_release_page)
        bottom_layout.addWidget(self.btn_web)

        bottom_layout.addStretch()

        self.btn_later = QPushButton(tr("update_btn_later"))
        self.btn_later.clicked.connect(self.reject)
        bottom_layout.addWidget(self.btn_later)

        self.btn_action = QPushButton(tr("update_btn_install"))
        self.btn_action.setObjectName("btn_primary")
        self.btn_action.clicked.connect(self._on_action_clicked)
        bottom_layout.addWidget(self.btn_action)

        main_layout.addLayout(bottom_layout)

    def _build_up_to_date_view(self, layout: QVBoxLayout):
        """Builds clean up-to-date card when already on the latest version."""
        card = QFrame()
        card.setObjectName("card_panel")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 36, 32, 36)
        card_layout.setSpacing(14)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Checkmark badge
        lbl_icon = QLabel("✓")
        lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_icon.setStyleSheet(f"""
            font-size: 32pt; font-weight: bold; color: {COLORS['accent_green']};
            background-color: #143522; border: 2px solid {COLORS['accent_green']};
            border-radius: 35px; width: 70px; height: 70px;
        """)
        lbl_icon.setFixedSize(70, 70)
        card_layout.addWidget(lbl_icon, alignment=Qt.AlignmentFlag.AlignCenter)

        lbl_title = QLabel(tr("update_uptodate_title"))
        lbl_title.setStyleSheet("font-size: 14pt; font-weight: bold; color: #ffffff;")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(lbl_title)

        desc_text = tr("update_uptodate_desc", version=APP_VERSION)
        lbl_desc = QLabel(desc_text)
        lbl_desc.setStyleSheet(f"font-size: 9.5pt; color: {COLORS['text_secondary']};")
        lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(lbl_desc)

        layout.addWidget(card)

        # Close button
        btn_box = QHBoxLayout()
        btn_box.addStretch()

        self.btn_close = QPushButton(tr("btn_close"))
        self.btn_close.clicked.connect(self.accept)
        btn_box.addWidget(self.btn_close)
        layout.addLayout(btn_box)

    def _format_markdown_notes(self, markdown_text: str) -> str:
        """Converts basic markdown release notes to clean dark-theme HTML."""
        import html
        lines = markdown_text.splitlines()
        formatted_lines = []
        for line in lines:
            line_str = line.strip()
            if line_str.startswith("### "):
                header = html.escape(line_str[4:])
                formatted_lines.append(f"<h4 style='color: #60a5fa; margin-top: 10px; margin-bottom: 4px;'>{header}</h4>")
            elif line_str.startswith("## "):
                header = html.escape(line_str[3:])
                formatted_lines.append(f"<h3 style='color: #93c5fd; margin-top: 12px; margin-bottom: 6px;'>{header}</h3>")
            elif line_str.startswith("# "):
                header = html.escape(line_str[2:])
                formatted_lines.append(f"<h2 style='color: #bfdbfe; margin-top: 14px; margin-bottom: 8px;'>{header}</h2>")
            elif line_str.startswith("- ") or line_str.startswith("* "):
                bullet = html.escape(line_str[2:])
                formatted_lines.append(f"<div style='margin-left: 12px; margin-bottom: 3px;'>• {bullet}</div>")
            elif line_str:
                text = html.escape(line_str)
                formatted_lines.append(f"<div style='margin-bottom: 4px;'>{text}</div>")
            else:
                formatted_lines.append("<br/>")

        body_html = "\n".join(formatted_lines)
        return f"""
        <html>
        <body style="font-family: 'Segoe UI', 'Leelawadee UI', sans-serif; font-size: 9.5pt; color: #e0e0e0; line-height: 1.4;">
        {body_html}
        </body>
        </html>
        """

    def _open_release_page(self):
        if self.update_info and self.update_info.html_url:
            webbrowser.open(self.update_info.html_url)

    def _on_action_clicked(self):
        if self._downloaded_file and self._downloaded_file.exists():
            # Already downloaded, trigger restart now
            self._trigger_restart()
            return

        # Start downloading binary asset
        self.btn_action.setEnabled(False)
        self.btn_later.setEnabled(False)
        self.progress_container.show()
        self.prog_bar.setValue(0)
        self.lbl_prog_status.setText(tr("update_starting_download"))

        self._downloader = UpdateDownloaderThread(self.update_info)
        self._downloader.progress.connect(self._on_download_progress)
        self._downloader.finished.connect(self._on_download_finished)
        self._downloader.error.connect(self._on_download_error)
        self._downloader.start()

    def _on_download_progress(self, downloaded: int, total: int, speed: float, eta: float):
        if total > 0:
            pct = int((downloaded / total) * 100)
            self.prog_bar.setValue(pct)
            cur_mb = format_bytes(downloaded)
            tot_mb = format_bytes(total)
            speed_str = f"{format_bytes(int(speed))}/s" if speed > 0 else "--"
            eta_str = f"{int(eta)}s" if eta > 0 else "--"
            self.lbl_prog_status.setText(
                f"{cur_mb} / {tot_mb} ({pct}%) • {speed_str} • {tr('update_eta')}: {eta_str}"
            )
        else:
            cur_mb = format_bytes(downloaded)
            self.prog_bar.setRange(0, 0)  # Indeterminate
            self.lbl_prog_status.setText(f"{tr('update_downloaded')}: {cur_mb}")

    def _on_download_finished(self, path: Path, is_zip: bool):
        self._downloaded_file = path
        self._is_zip = is_zip
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setValue(100)
        self.lbl_prog_status.setText(tr("update_ready_to_restart"))
        self.btn_action.setText(tr("update_btn_restart_now"))
        self.btn_action.setEnabled(True)
        self.btn_later.setEnabled(True)

        # Offer immediate restart
        ret = QMessageBox.question(
            self,
            tr("update_complete_title"),
            tr("update_complete_prompt"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if ret == QMessageBox.StandardButton.Yes:
            self._trigger_restart()

    def _on_download_error(self, err_msg: str):
        self.progress_container.hide()
        if hasattr(self, 'btn_action'):
            self.btn_action.setEnabled(True)
        if hasattr(self, 'btn_later'):
            self.btn_later.setEnabled(True)
        if hasattr(self, 'btn_close'):
            self.btn_close.setEnabled(True)
        QMessageBox.warning(
            self,
            tr("update_failed_title"),
            tr("update_failed_msg", error=err_msg)
        )

    def _trigger_restart(self):
        if not self._downloaded_file or not self._downloaded_file.exists():
            return

        success, msg = apply_update_and_restart(
            downloaded_file=self._downloaded_file,
            is_zip=self._is_zip
        )

        if success:
            # Terminate running application gracefully so stager can replace files
            QApplication.quit()
        else:
            QMessageBox.critical(
                self,
                tr("update_error_title"),
                tr("update_apply_failed", error=msg)
            )

    def closeEvent(self, event):
        if self._downloader and self._downloader.isRunning():
            self._downloader.cancel()
            self._downloader.wait(1000)
        super().closeEvent(event)
