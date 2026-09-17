from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QLabel, QLineEdit, QHeaderView, QMenu, QCheckBox, QPushButton
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QAction

from core.models import DialogueItem, PipelineState

class DialogueTable(QWidget):
    dialogue_selected = Signal(DialogueItem)
    dialogue_deleted = Signal(int)
    dialogue_changed = Signal(DialogueItem)
    play_audio_requested = Signal(DialogueItem)
    view_image_requested = Signal(DialogueItem)
    merge_next_requested = Signal(int)
    split_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = None
        self._items = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Top bar
        top_bar = QHBoxLayout()
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter by character name...")
        self.filter_input.textChanged.connect(self.on_filter_changed)
        top_bar.addWidget(self.filter_input)
        
        self.count_label = QLabel("0 dialogues / 0 speakers")
        top_bar.addWidget(self.count_label)
        layout.addLayout(top_bar)
        
        # Table - 9 columns
        self.table = QTableWidget(0, 9)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: #181818;
                color: #e0e0e0;
                gridline-color: #2e2e2e;
                border: 1px solid #383838;
                border-radius: 4px;
            }}
            QTableWidget::item {{
                padding: 4px 6px;
                border-bottom: 1px solid #242424;
            }}
            QTableWidget::item:selected {{
                background-color: #333333;
                color: #ffffff;
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
        """)
        headers = ["#", "Character", "Start", "End", "Duration", "Caption", "Img", "Aud", "Confirm"]
        self.table.setHorizontalHeaderLabels(headers)
        
        tooltips = [
            "Dialogue line sequence index",
            "Assigned character / speaker layer",
            "Start timestamp (HH:MM:SS.mmm)",
            "End timestamp (HH:MM:SS.mmm)",
            "Total segment duration in seconds",
            "Speech transcript caption text",
            "Companion image frame extracted on disk (Yes / —)",
            "Companion audio clip extracted on disk (Yes / —)",
            "Proofreading status checkbox: Check when verified and approved"
        ]
        for col, tip in enumerate(tooltips):
            h_item = self.table.horizontalHeaderItem(col)
            if h_item:
                h_item.setToolTip(tip)

        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.ResizeToContents)
        
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.cellDoubleClicked.connect(self.on_double_click)
        self.table.cellClicked.connect(self._on_single_click)
        layout.addWidget(self.table)
        
        self.colors = ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#a371f7"]

    def populate(self, state: PipelineState):
        self.state = state
        self._items = state.active_dialogues()
        self.refresh_table()

    def refresh_table(self):
        filter_text = self.filter_input.text().lower()
        self.table.setRowCount(0)
        
        speakers = set()
        display_items = []
        
        if not self.state:
            return
            
        for item in self._items:
            speaker_name = self.state.get_speaker_safe_name(item.speaker_id)
            speakers.add(speaker_name)
            if not filter_text or filter_text in speaker_name.lower() or filter_text in item.caption.lower():
                display_items.append(item)
                
        self.count_label.setText(f"{len(display_items)} dialogues / {len(speakers)} speakers")
        
        speaker_colors = {}
        for idx, spk in enumerate(sorted(speakers)):
            speaker_colors[spk] = self.colors[idx % len(self.colors)]
            
        for row, item in enumerate(display_items):
            self.table.insertRow(row)
            self._fill_row(row, item, speaker_colors.get(self.state.get_speaker_safe_name(item.speaker_id), "#ffffff"))

    def _fill_row(self, row: int, item: DialogueItem, color_hex: str):
        col_data = [
            str(item.index),
            self.state.get_speaker(item.speaker_id).display_name if self.state and item.speaker_id in self.state.speakers else item.speaker_id,
            item.format_start(),
            item.format_end(),
            f"{item.duration:.3f}s",
            item.caption,
            "Yes" if item.image_path and item.image_path.exists() else "—",
            "Yes" if item.audio_path and item.audio_path.exists() else "—"
        ]
        
        for col, text in enumerate(col_data):
            t_item = QTableWidgetItem(text)
            if col == 1:
                t_item.setForeground(QColor(color_hex))
            if col in (6, 7) and text == "Yes":
                t_item.setForeground(QColor("#3fb950"))
            elif col in (6, 7):
                t_item.setForeground(QColor("#484f58"))
            self.table.setItem(row, col, t_item)
            
        cb = QCheckBox()
        cb.setChecked(getattr(item, 'caption_confirmed', False))
        cb.setToolTip("Mark as verified and approved (Proofread QA)")
        def _on_confirm_toggled(state, itm=item):
            itm.caption_confirmed = (state == Qt.CheckState.Checked.value)
            self.dialogue_changed.emit(itm)
        cb.stateChanged.connect(_on_confirm_toggled)
        w = QWidget()
        l = QHBoxLayout(w)
        l.addWidget(cb)
        l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.setContentsMargins(0, 0, 0, 0)
        self.table.setCellWidget(row, 8, w)

    def update_row(self, item: DialogueItem, state: PipelineState):
        self.state = state
        self.refresh_table()

    def on_filter_changed(self):
        self.refresh_table()

    def _on_single_click(self, row, col):
        """Select item on single click."""
        if row < 0: return
        idx_item = self.table.item(row, 0)
        if not idx_item: return
        idx = int(idx_item.text())
        for item in self._items:
            if item.index == idx:
                self.dialogue_selected.emit(item)
                break

    def on_double_click(self, row, col):
        if row < 0: return
        idx_item = self.table.item(row, 0)
        if not idx_item: return
        idx = int(idx_item.text())
        for item in self._items:
            if item.index == idx:
                self.dialogue_selected.emit(item)
                break

    def show_context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0: return
        
        idx_item = self.table.item(row, 0)
        if not idx_item: return
        idx = int(idx_item.text())
        
        target_item = None
        for item in self._items:
            if item.index == idx:
                target_item = item
                break
                
        if not target_item: return

        menu = QMenu(self)
        play_action = menu.addAction("Play Audio")
        view_action = menu.addAction("View Image")
        menu.addSeparator()
        merge_action = menu.addAction("Merge with Next")
        split_action = menu.addAction("Split")
        menu.addSeparator()
        delete_action = menu.addAction("Delete")
        
        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action == delete_action:
            self.dialogue_deleted.emit(idx)
        elif action == play_action:
            self.play_audio_requested.emit(target_item)
        elif action == view_action:
            self.view_image_requested.emit(target_item)
        elif action == merge_action:
            self.merge_next_requested.emit(idx)
        elif action == split_action:
            self.split_requested.emit(idx)
