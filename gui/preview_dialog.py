from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
    QListWidget, QPushButton, QFrame, QListWidgetItem
)
from PySide6.QtCore import Qt, Signal
from pathlib import Path

from core.models import PipelineState
from config import COLORS
from gui.ui_utils import apply_dark_title_bar

class PreviewDialog(QDialog):
    export_confirmed = Signal(str)

    def showEvent(self, event):
        super().showEvent(event)
        apply_dark_title_bar(self)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Preview")
        self.resize(800, 600)
        self.setStyleSheet(f"""
            QDialog {{ background-color: {COLORS['bg_primary']}; color: {COLORS['text_primary']}; }}
            QLabel {{ color: {COLORS['text_primary']}; }}
            QFrame {{ background-color: {COLORS['bg_panel']}; border: 1px solid {COLORS['border']}; border-radius: 8px; }}
            QTreeWidget, QListWidget {{
                background-color: {COLORS['bg_panel']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                padding: 4px;
            }}
            QTreeWidget::item:hover, QListWidget::item:hover {{ background-color: {COLORS['bg_input']}; }}
            QPushButton {{
                background-color: {COLORS['bg_input']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 6px 16px;
            }}
            QPushButton:hover {{ background-color: {COLORS['accent']}; color: white; }}
        """)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(16)
        
        content_layout = QHBoxLayout()
        
        # Left Panel - Pack Summary
        left_panel = QFrame()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(16, 16, 16, 16)
        
        self.lbl_title = QLabel("Title: ")
        self.lbl_title.setStyleSheet(f"font-weight: bold; font-size: 11pt; border: none;")
        self.lbl_authors = QLabel("Authors: ")
        self.lbl_authors.setStyleSheet(f"color: {COLORS['text_secondary']}; border: none;")
        self.lbl_icon = QLabel("Icon preview")
        self.lbl_icon.setFixedSize(128, 128)
        self.lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_icon.setStyleSheet(f"background-color: {COLORS['bg_input']}; border-radius: 8px; border: 1px solid {COLORS['border']};")
        
        self.lbl_stats = QLabel("Dialogue count: 0\nCharacters: \nTotal duration: 00:00\nBacking track: No")
        self.lbl_stats.setStyleSheet(f"color: {COLORS['text_secondary']}; line-height: 1.5; border: none;")
        
        left_layout.addWidget(self.lbl_title)
        left_layout.addWidget(self.lbl_authors)
        left_layout.addWidget(self.lbl_icon)
        left_layout.addWidget(self.lbl_stats)
        left_layout.addStretch()
        
        content_layout.addWidget(left_panel, 1)
        
        # Right Panel - File Tree
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        content_layout.addWidget(self.tree, 2)
        
        main_layout.addLayout(content_layout, stretch=2)
        
        # Bottom - Validation Results
        self.list_validation = QListWidget()
        self.list_validation.setFixedHeight(100)
        main_layout.addWidget(self.list_validation, stretch=1)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_export = QPushButton("Export ZIP")
        self.btn_export.clicked.connect(self.on_export)
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_export)
        
        main_layout.addLayout(btn_layout)

    def show_for_state(self, state: PipelineState, pack_dir: Path, check_results: list):
        self.lbl_title.setText(f"Title: {state.pack_info.title}")
        self.lbl_authors.setText(f"Authors: {', '.join(state.pack_info.authors)}")
        
        dur = sum(d.duration for d in state.active_dialogues())
        dur_m = int(dur // 60)
        dur_s = int(dur % 60)
        
        spks = set(state.get_speaker_safe_name(d.speaker_id) for d in state.active_dialogues())
        has_bg = "Yes" if state.separated_bg_path else "No"
        
        self.lbl_stats.setText(
            f"Dialogue count: {len(state.active_dialogues())}\n"
            f"Characters: {', '.join(spks)}\n"
            f"Total duration: {dur_m:02d}:{dur_s:02d}\n"
            f"Backing track: {has_bg}"
        )
        
        # Tree
        self.tree.clear()
        root = QTreeWidgetItem([state.pack_info.title or "Untitled Pack"])
        self.tree.addTopLevelItem(root)
        
        items = ["_backing_track.mp3", "_pack_info.ini"]
        if state.pack_info.include_dub_video:
            items.append("dub_video.ogv")
            
        for item in items:
            child = QTreeWidgetItem([f"[FILE] {item}"])
            root.addChild(child)
            
        for d in state.active_dialogues():
            base = d.filename_base(state.get_speaker_safe_name(d.speaker_id))
            root.addChild(QTreeWidgetItem([f"[IMG] {base}.png"]))
            root.addChild(QTreeWidgetItem([f"[TXT] {base}.txt"]))
            root.addChild(QTreeWidgetItem([f"[AUD] {base}.mp3"]))
            
        self.tree.expandAll()
        
        # Validation
        self.list_validation.clear()
        has_errors = False
        for status, msg in check_results:
            item = QListWidgetItem(f"[{status}] {msg}")
            if status in ("OK", "[OK]"):
                item.setForeground(Qt.GlobalColor.green)
            elif status in ("WARN", "[WARN]"):
                item.setForeground(Qt.GlobalColor.yellow)
            elif status in ("FAIL", "ERROR", "[FAIL]"):
                item.setForeground(Qt.GlobalColor.red)
                has_errors = True
            self.list_validation.addItem(item)
            
        self.btn_export.setDisabled(has_errors)
        self.exec_()
        
    def on_export(self):
        self.export_confirmed.emit("dummy_path.zip")
        self.accept()
