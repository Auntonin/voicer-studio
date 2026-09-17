from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QFrame, QPushButton, QMessageBox, QAbstractItemView
)
from PySide6.QtCore import Signal, Qt, QSize
from PySide6.QtGui import QIcon

from core.models import PipelineState, SpeakerInfo
from config import COLORS


class SpeakerListWidget(QListWidget):
    items_reordered = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLORS['bg_primary']};
                border: none;
            }}
            QListWidget::item {{
                background: transparent;
                border: none;
                padding: 3px 0px;
            }}
            QListWidget::item:selected {{
                background: transparent;
            }}
        """)

    def dropEvent(self, event):
        super().dropEvent(event)
        new_order = []
        for i in range(self.count()):
            item = self.item(i)
            spk_id = item.data(Qt.ItemDataRole.UserRole)
            if spk_id:
                new_order.append(spk_id)
        self.items_reordered.emit(new_order)


class SpeakerPanel(QWidget):
    speaker_renamed = Signal(str, str)
    speaker_added = Signal(str)
    speaker_deleted = Signal(str)
    speaker_reordered = Signal()
    speaker_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = None
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(8, 8, 8, 8)
        self.layout.setSpacing(6)

        # Top Bar with Add Speaker button
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        
        lbl_title = QLabel("CHARACTER SPEAKERS & LAYERS")
        lbl_title.setStyleSheet(f"color: {COLORS['text_primary']}; font-weight: bold; font-size: 9.5pt;")
        top_bar.addWidget(lbl_title)
        top_bar.addStretch()

        self.btn_add_speaker = QPushButton("[+] Add Speaker")
        self.btn_add_speaker.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_input']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 4px 10px;
                font-weight: bold;
                font-size: 8.5pt;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent']};
                color: white;
            }}
        """)
        self.btn_add_speaker.clicked.connect(self._on_add_speaker)
        top_bar.addWidget(self.btn_add_speaker)

        self.layout.addLayout(top_bar)
        
        # Drag and drop speaker list
        self.list_widget = SpeakerListWidget()
        self.list_widget.items_reordered.connect(self._on_items_reordered)
        self.layout.addWidget(self.list_widget)
        
        # Color palette for speakers
        self.colors = [
            COLORS['accent'], "#10b981", "#f59e0b", "#ef4444", "#a855f7",
            "#06b6d4", "#ec4899", "#84cc16", "#14b8a6", "#f97316"
        ]

    def populate(self, state: PipelineState):
        self.state = state
        self.list_widget.clear()
            
        if not self.state or not self.state.speakers:
            return

        speakers_list = self.state.get_speaker_order()
        
        for idx, spk_id in enumerate(speakers_list):
            if spk_id not in self.state.speakers:
                continue
            spk = self.state.speakers[spk_id]
            color = self.colors[idx % len(self.colors)]
            
            row = QFrame()
            row.setStyleSheet(f"""
                QFrame {{
                    background-color: {COLORS['bg_panel']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 6px;
                }}
            """)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(8, 6, 8, 6)
            row_layout.setSpacing(8)

            # Drag handle grip icon [≡]
            lbl_drag = QLabel("≡")
            lbl_drag.setToolTip("Drag & drop to reorder layer position")
            lbl_drag.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 13pt; font-weight: bold; cursor: grab; padding: 0 4px;")
            row_layout.addWidget(lbl_drag)
            
            # Dialogue count for this speaker
            count = sum(1 for d in self.state.active_dialogues() if d.speaker_id == spk_id)
            
            # Color indicator swatch
            swatch = QLabel()
            swatch.setFixedSize(14, 14)
            swatch.setStyleSheet(f"background-color: {color}; border-radius: 7px; border: none;")
            row_layout.addWidget(swatch)
            
            lbl_id = QLabel(f"A{idx+1}: {spk_id}")
            lbl_id.setStyleSheet(f"color: {COLORS['text_secondary']}; font-weight: bold; border: none;")
            row_layout.addWidget(lbl_id)
            
            edit = QLineEdit(spk.display_name)
            edit.setPlaceholderText("Display Name")
            edit.setStyleSheet(f"""
                QLineEdit {{
                    background-color: {COLORS['bg_input']};
                    color: {COLORS['text_primary']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 4px;
                    padding: 4px 8px;
                }}
                QLineEdit:focus {{ border: 1px solid {COLORS['accent']}; }}
            """)
            edit.editingFinished.connect(lambda sid=spk_id, e=edit: self._on_edit(sid, e.text()))
            edit.focusInEvent = lambda event, sid=spk_id, e=edit: (self.speaker_selected.emit(sid), QLineEdit.focusInEvent(e, event))
            row_layout.addWidget(edit, stretch=1)
            
            cnt_lbl = QLabel(f"{count} dialogues")
            cnt_lbl.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 8.5pt; border: none;")
            row_layout.addWidget(cnt_lbl)
            
            # Delete speaker button
            btn_del = QPushButton("Delete")
            btn_del.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['bg_input']};
                    color: {COLORS['accent_red']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 3px;
                    padding: 3px 8px;
                    font-size: 8pt;
                }}
                QPushButton:hover {{
                    background-color: {COLORS['accent_red']};
                    color: white;
                }}
            """)
            btn_del.clicked.connect(lambda _, sid=spk_id: self._on_delete_speaker(sid))
            row_layout.addWidget(btn_del)

            item = QListWidgetItem(self.list_widget)
            item.setData(Qt.ItemDataRole.UserRole, spk_id)
            item.setSizeHint(QSize(0, 48))
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, row)

    def _on_items_reordered(self, new_order: list):
        if self.state and new_order:
            self.state.speaker_order = new_order
            self.speaker_reordered.emit()
            self.populate(self.state)

    def _on_add_speaker(self):
        if not self.state:
            return
        existing_indices = []
        for sid in self.state.speakers.keys():
            if sid.startswith("SPEAKER_"):
                try:
                    existing_indices.append(int(sid.replace("SPEAKER_", "")))
                except ValueError:
                    pass
        next_idx = max(existing_indices, default=-1) + 1
        new_spk_id = f"SPEAKER_{next_idx:02d}"
        
        self.state.speakers[new_spk_id] = SpeakerInfo(
            speaker_id=new_spk_id,
            display_name=f"Speaker {next_idx + 1}"
        )
        if new_spk_id not in self.state.speaker_order:
            self.state.speaker_order.append(new_spk_id)
            
        self.speaker_selected.emit(new_spk_id)
        self.speaker_added.emit(new_spk_id)
        self.populate(self.state)

    def _on_delete_speaker(self, spk_id: str):
        if not self.state or spk_id not in self.state.speakers:
            return
        if len(self.state.speakers) <= 1:
            QMessageBox.warning(self, "Delete Speaker", "Cannot delete the last remaining speaker track.")
            return
        self.speaker_deleted.emit(spk_id)

    def _on_edit(self, spk_id: str, new_name: str):
        if self.state and spk_id in self.state.speakers:
            self.state.speakers[spk_id].display_name = new_name
            self.speaker_selected.emit(spk_id)
            self.speaker_renamed.emit(spk_id, new_name)
