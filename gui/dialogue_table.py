from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QLabel, QLineEdit, QHeaderView, QMenu, QCheckBox, QPushButton
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QAction

from core.models import DialogueItem, PipelineState
from core.i18n import tr

class DialogueTable(QWidget):
    dialogue_selected = Signal(DialogueItem)
    dialogue_double_clicked = Signal(DialogueItem)
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
        self.filter_input.setPlaceholderText(tr("dt_filter_placeholder"))
        self.filter_input.textChanged.connect(self.on_filter_changed)
        top_bar.addWidget(self.filter_input)
        
        self.count_label = QLabel(tr("dt_stats_empty"))
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
        self._apply_headers_and_tooltips()

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

    def _apply_headers_and_tooltips(self):
        headers = [
            tr("dt_col_index"),
            tr("dt_col_character"),
            tr("dt_col_start"),
            tr("dt_col_end"),
            tr("dt_col_duration"),
            tr("dt_col_caption"),
            tr("dt_col_img"),
            tr("dt_col_aud"),
            tr("dt_col_confirm"),
        ]
        self.table.setHorizontalHeaderLabels(headers)

        tooltips = [
            tr("dt_tip_index"),
            tr("dt_tip_character"),
            tr("dt_tip_start"),
            tr("dt_tip_end"),
            tr("dt_tip_duration"),
            tr("dt_tip_caption"),
            tr("dt_tip_img"),
            tr("dt_tip_aud"),
            tr("dt_tip_confirm"),
        ]
        for col, tip in enumerate(tooltips):
            h_item = self.table.horizontalHeaderItem(col)
            if h_item:
                h_item.setToolTip(tip)

    def retranslate_ui(self):
        """Retranslates table headers, tooltips, search placeholder, and labels."""
        self.filter_input.setPlaceholderText(tr("dt_filter_placeholder"))
        self._apply_headers_and_tooltips()
        self.refresh_table()

    def populate(self, state: PipelineState):
        self.state = state
        self._items = state.active_dialogues()
        self.refresh_table()

    def refresh_table(self):
        if not self.state:
            self.table.setRowCount(0)
            self.count_label.setText(tr("dt_stats_empty"))
            return

        filter_text = self.filter_input.text().lower()
        speakers = set()
        display_items = []
        for item in self._items:
            speaker_name = self.state.get_speaker_safe_name(item.speaker_id)
            speakers.add(speaker_name)
            if not filter_text or filter_text in speaker_name.lower() or filter_text in item.caption.lower():
                display_items.append(item)

        self.count_label.setText(tr("dt_stats_label", count=len(display_items), speakers=len(speakers)))

        speaker_colors = {}
        for idx, spk in enumerate(sorted(speakers)):
            speaker_colors[spk] = self.colors[idx % len(self.colors)]

        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(display_items))
            for row, item in enumerate(display_items):
                color_hex = speaker_colors.get(self.state.get_speaker_safe_name(item.speaker_id), "#ffffff")
                self._fill_row(row, item, color_hex)
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)

    def _fill_row(self, row: int, item: DialogueItem, color_hex: str):
        has_img = "Yes" if item.image_path and item.image_path.exists() else "—"
        has_aud = "Yes" if item.audio_path and item.audio_path.exists() else "—"
        col_data = [
            str(item.index),
            self.state.get_speaker(item.speaker_id).display_name if self.state and item.speaker_id in self.state.speakers else item.speaker_id,
            item.format_start(),
            item.format_end(),
            f"{item.duration:.3f}s",
            item.caption,
            has_img,
            has_aud
        ]

        for col, text in enumerate(col_data):
            t_item = self.table.item(row, col)
            if not t_item:
                t_item = QTableWidgetItem(text)
                self.table.setItem(row, col, t_item)
            else:
                t_item.setText(text)

            if col == 1:
                t_item.setForeground(QColor(color_hex))
            elif col in (6, 7) and text == "Yes":
                t_item.setForeground(QColor("#3fb950"))
            elif col in (6, 7):
                t_item.setForeground(QColor("#484f58"))

        existing_w = self.table.cellWidget(row, 8)
        if existing_w:
            cb = existing_w.findChild(QCheckBox)
            if cb:
                cb.blockSignals(True)
                cb.setChecked(getattr(item, 'caption_confirmed', False))
                cb.blockSignals(False)
        else:
            cb = QCheckBox()
            cb.setChecked(getattr(item, 'caption_confirmed', False))
            cb.setToolTip(tr("dt_proofread_tip"))
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
        for row in range(self.table.rowCount()):
            item_id = self.table.item(row, 0)
            if item_id and item_id.text() == str(item.index):
                speakers = sorted({self.state.get_speaker_safe_name(d.speaker_id) for d in self._items})
                spk_name = self.state.get_speaker_safe_name(item.speaker_id)
                try:
                    spk_idx = speakers.index(spk_name)
                except ValueError:
                    spk_idx = 0
                color_hex = self.colors[spk_idx % len(self.colors)]
                self._fill_row(row, item, color_hex)
                return
        self.refresh_table()

    def on_filter_changed(self):
        self.refresh_table()

    def _on_single_click(self, row, col):
        """Select item on single click."""
        if row < 0: return
        idx_item = self.table.item(row, 0)
        if not idx_item: return
        try:
            idx = int(idx_item.text())
        except ValueError:
            return
        for item in self._items:
            if item.index == idx:
                self.dialogue_selected.emit(item)
                break

    def on_double_click(self, row, col):
        """Select item and request smooth camera center on double click."""
        if row < 0: return
        idx_item = self.table.item(row, 0)
        if not idx_item: return
        try:
            idx = int(idx_item.text())
        except ValueError:
            return
        for item in self._items:
            if item.index == idx:
                self.dialogue_selected.emit(item)
                self.dialogue_double_clicked.emit(item)
                break

    def select_dialogue_by_index(self, idx: int):
        """Select and scroll to row with dialogue index idx without re-triggering recursive events."""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.text() == str(idx):
                self.table.blockSignals(True)
                self.table.selectRow(row)
                self.table.scrollToItem(item, QTableWidget.ScrollHint.EnsureVisible)
                self.table.blockSignals(False)
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
        play_action = menu.addAction(tr("dt_menu_play_audio"))
        view_action = menu.addAction(tr("dt_menu_view_image"))
        menu.addSeparator()
        merge_action = menu.addAction(tr("dt_menu_merge_next"))
        split_action = menu.addAction(tr("dt_menu_split"))
        menu.addSeparator()
        delete_action = menu.addAction(tr("dt_menu_delete"))
        
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
