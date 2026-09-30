from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QLabel, QLineEdit, QHeaderView, QMenu, QCheckBox, QPushButton
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QAction

from core.models import DialogueItem, PipelineState
from core.i18n import tr

class _DialogueTableWidget(QTableWidget):
    playback_toggle_requested = Signal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.playback_toggle_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class DialogueTable(QWidget):
    dialogue_selected = Signal(DialogueItem)
    dialogue_double_clicked = Signal(DialogueItem)
    dialogue_deleted = Signal(int)
    dialogue_changed = Signal(DialogueItem)
    play_audio_requested = Signal(DialogueItem)
    view_image_requested = Signal(DialogueItem)
    merge_next_requested = Signal(int)
    split_requested = Signal(int)
    playback_toggle_requested = Signal()
    enroll_voiceprint_requested = Signal(DialogueItem)
    match_speakers_requested = Signal()
    refine_alignment_clip_requested = Signal(DialogueItem)
    refine_alignment_all_requested = Signal()
    batch_delete_requested = Signal(list)
    batch_reassign_requested = Signal(list, str)

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
        self.table = _DialogueTableWidget(0, 9)
        self.table.playback_toggle_requested.connect(self.playback_toggle_requested)
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
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.cellDoubleClicked.connect(self.on_double_click)
        self.table.cellClicked.connect(self._on_single_click)
        self.table.currentCellChanged.connect(self._on_current_cell_changed)
        layout.addWidget(self.table)
        
        self.colors = ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#a371f7"]

    def get_selected_dialogue_items(self) -> list:
        """Returns all selected DialogueItem objects in current table selection."""
        selected_rows = sorted(list({idx.row() for idx in self.table.selectedIndexes()}))
        items = []
        for r in selected_rows:
            item_id = self.table.item(r, 0)
            if item_id:
                try:
                    idx = int(item_id.text())
                    found = next((it for it in self._items if it.index == idx), None)
                    if found and found not in items:
                        items.append(found)
                except ValueError:
                    pass
        return items

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
        has_img = "✓" if item.image_path and item.image_path.exists() else "—"
        has_aud = "✓" if item.audio_path and item.audio_path.exists() else "—"
        speaker_name = self.state.get_speaker(item.speaker_id).display_name if self.state and item.speaker_id in self.state.speakers else item.speaker_id
        if getattr(item, 'needs_review', False):
            display_speaker = f"{speaker_name} [?]"
        else:
            display_speaker = speaker_name

        col_data = [
            str(item.index),
            display_speaker,
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
                if getattr(item, 'needs_review', False):
                    t_item.setForeground(QColor("#f59e0b"))
                    conf_pct = int(getattr(item, 'speaker_confidence', 0.0) * 100)
                    t_item.setToolTip(tr("dt_tip_needs_review", conf=f"{conf_pct}%"))
                else:
                    t_item.setForeground(QColor(color_hex))
                    conf_pct = int(getattr(item, 'speaker_confidence', 1.0) * 100)
                    t_item.setToolTip(f"{speaker_name} ({conf_pct}%)")
            elif col in (6, 7) and text == "✓":
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

    def _on_current_cell_changed(self, currentRow: int, currentColumn: int, previousRow: int, previousColumn: int):
        """Sync selection and playhead when navigating table with arrow keys."""
        if currentRow < 0 or currentRow == previousRow:
            return
        self._on_single_click(currentRow, currentColumn)

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
        selected_items = self.get_selected_dialogue_items()
        row = self.table.rowAt(pos.y())
        if row < 0: return

        idx_item = self.table.item(row, 0)
        if not idx_item: return
        idx = int(idx_item.text())

        target_item = next((it for it in self._items if it.index == idx), None)
        if not target_item: return

        # If clicked row is not in current selection, select only this row
        if target_item not in selected_items:
            selected_items = [target_item]

        menu = QMenu(self)

        # ── Multi-selection Batch Context Menu ──
        if len(selected_items) > 1:
            title_action = menu.addAction(tr("dt_batch_selected_count", count=len(selected_items)) if tr("dt_batch_selected_count", count=len(selected_items)) != "dt_batch_selected_count" else f"Selected ({len(selected_items)} clips)")
            title_action.setEnabled(False)
            menu.addSeparator()

            # Batch Assign Speaker Submenu
            spk_menu = menu.addMenu(tr("dt_menu_reassign_speaker") if tr("dt_menu_reassign_speaker") != "dt_menu_reassign_speaker" else "Assign Character")
            spk_actions = {}
            if self.state and self.state.speakers:
                for sid, spk in sorted(self.state.speakers.items(), key=lambda x: x[1].display_name):
                    act = spk_menu.addAction(spk.display_name or sid)
                    spk_actions[act] = sid

            # Batch Confirm Speakers
            has_unconfirmed = any(getattr(it, 'needs_review', False) for it in selected_items)
            batch_confirm_action = None
            if has_unconfirmed:
                batch_confirm_action = menu.addAction(tr("dt_menu_confirm_speaker") if tr("dt_menu_confirm_speaker") != "dt_menu_confirm_speaker" else "Confirm Characters")

            menu.addSeparator()
            batch_delete_action = menu.addAction(tr("dt_menu_delete") if tr("dt_menu_delete") != "dt_menu_delete" else f"Delete ({len(selected_items)} clips)")

            action = menu.exec(self.table.viewport().mapToGlobal(pos))
            if action in spk_actions:
                target_spk = spk_actions[action]
                self.batch_reassign_requested.emit(selected_items, target_spk)
                for itm in selected_items:
                    itm.speaker_id = target_spk
                    itm.needs_review = False
                    itm.speaker_confidence = 1.0
                    self.dialogue_changed.emit(itm)
                self.refresh_table()
            elif action == batch_confirm_action and batch_confirm_action is not None:
                for itm in selected_items:
                    itm.needs_review = False
                    itm.speaker_confidence = 1.0
                    self.dialogue_changed.emit(itm)
                self.refresh_table()
            elif action == batch_delete_action:
                self.batch_delete_requested.emit([it.index for it in selected_items])
            return

        # ── Single Item Context Menu ──
        play_action = menu.addAction(tr("dt_menu_play_audio"))
        view_action = menu.addAction(tr("dt_menu_view_image"))
        menu.addSeparator()

        # Single Reassign Speaker Submenu
        spk_menu = menu.addMenu(tr("dt_menu_reassign_speaker") if tr("dt_menu_reassign_speaker") != "dt_menu_reassign_speaker" else "Assign Character")
        spk_actions = {}
        if self.state and self.state.speakers:
            for sid, spk in sorted(self.state.speakers.items(), key=lambda x: x[1].display_name):
                act = spk_menu.addAction(spk.display_name or sid)
                if sid == target_item.speaker_id:
                    act.setIcon(menu.style().standardIcon(menu.style().StandardPixmap.SP_DialogApplyButton))
                spk_actions[act] = sid

        confirm_spk_action = None
        if getattr(target_item, 'needs_review', False):
            confirm_spk_action = menu.addAction(tr("dt_menu_confirm_speaker"))

        enroll_action = menu.addAction(tr("dt_menu_enroll_voiceprint"))
        match_action = menu.addAction(tr("dt_menu_match_speakers"))
        align_clip_action = menu.addAction(tr("dt_menu_refine_alignment_clip"))
        align_all_action = menu.addAction(tr("dt_menu_refine_alignment_all"))
        menu.addSeparator()

        merge_action = menu.addAction(tr("dt_menu_merge_next"))
        split_action = menu.addAction(tr("dt_menu_split"))
        menu.addSeparator()
        delete_action = menu.addAction(tr("dt_menu_delete"))
        
        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action in spk_actions:
            target_item.speaker_id = spk_actions[action]
            target_item.needs_review = False
            target_item.speaker_confidence = 1.0
            self.dialogue_changed.emit(target_item)
            self.update_row(target_item, self.state)
        elif action == delete_action:
            self.dialogue_deleted.emit(idx)
        elif action == play_action:
            self.play_audio_requested.emit(target_item)
        elif action == view_action:
            self.view_image_requested.emit(target_item)
        elif action == confirm_spk_action and confirm_spk_action is not None:
            target_item.needs_review = False
            target_item.speaker_confidence = 1.0
            self.dialogue_changed.emit(target_item)
            self.update_row(target_item, self.state)
        elif action == enroll_action:
            self.enroll_voiceprint_requested.emit(target_item)
        elif action == match_action:
            self.match_speakers_requested.emit()
        elif action == align_clip_action:
            self.refine_alignment_clip_requested.emit(target_item)
        elif action == align_all_action:
            self.refine_alignment_all_requested.emit()
        elif action == merge_action:
            self.merge_next_requested.emit(idx)
        elif action == split_action:
            self.split_requested.emit(idx)
