from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QComboBox, 
    QPlainTextEdit, QCheckBox, QLabel, QHBoxLayout
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QPixmap

from core.models import PackInfo, PipelineState

from config import COLORS

class PackInfoPanel(QWidget):
    pack_info_changed = Signal(PackInfo)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = None
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(12, 12, 12, 12)
        
        form = QFormLayout()
        
        self.edit_title = QLineEdit()
        self.edit_title.setPlaceholderText("Pack Title (e.g. SHANGRI LA FRONTIER)")
        self.edit_title.textChanged.connect(self._on_changed)
        form.addRow("Title:", self.edit_title)
        
        icon_layout = QHBoxLayout()
        self.combo_icon = QComboBox()
        self.combo_icon.currentIndexChanged.connect(self._on_icon_changed)
        icon_layout.addWidget(self.combo_icon)
        self.lbl_icon_preview = QLabel("No Icon")
        self.lbl_icon_preview.setFixedSize(64, 64)
        self.lbl_icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_icon_preview.setStyleSheet(f"background-color: {COLORS['bg_input']}; border: 1px solid {COLORS['border']}; border-radius: 6px;")
        icon_layout.addWidget(self.lbl_icon_preview)
        form.addRow("Icon:", icon_layout)
        
        self.edit_authors = QPlainTextEdit()
        self.edit_authors.setPlaceholderText("One author per line")
        self.edit_authors.setFixedHeight(60)
        self.edit_authors.textChanged.connect(self._on_changed)
        form.addRow("Authors:", self.edit_authors)
        
        self.chk_dub_video = QCheckBox("Include dub_video.ogv")
        self.chk_dub_video.setChecked(True)
        self.chk_dub_video.stateChanged.connect(self._on_changed)
        form.addRow("", self.chk_dub_video)
        
        self.layout.addLayout(form)
        self.layout.addStretch()

    def populate(self, state: PipelineState):
        self.state = state
        self.combo_icon.blockSignals(True)
        
        # Preserve current selection
        prev_icon = self.combo_icon.currentText()
        self.combo_icon.clear()
        
        # Populate available frame images
        for d in state.active_dialogues():
            spk_name = state.get_speaker_safe_name(d.speaker_id)
            fname = f"{d.id_str}_{spk_name}.png"
            self.combo_icon.addItem(fname, d.image_path)
        
        # Restore previous selection if still available
        if prev_icon:
            restore_idx = self.combo_icon.findText(prev_icon)
            if restore_idx >= 0:
                self.combo_icon.setCurrentIndex(restore_idx)
            
        self.combo_icon.blockSignals(False)
        self._on_icon_changed()

    def _on_icon_changed(self):
        img_path = self.combo_icon.currentData()
        if img_path and hasattr(img_path, 'exists') and img_path.exists():
            pix = QPixmap(str(img_path)).scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio)
            self.lbl_icon_preview.setPixmap(pix)
        else:
            self.lbl_icon_preview.setText("No Icon")
        self._on_changed()

    def get_pack_info(self) -> PackInfo:
        info = PackInfo()
        info.title = self.edit_title.text().strip() or "Untitled Pack"
        info.icon = self.combo_icon.currentText()
        info.authors = [a.strip() for a in self.edit_authors.toPlainText().split('\n') if a.strip()]
        if not info.authors:
            info.authors = ["unknown"]
        info.include_dub_video = self.chk_dub_video.isChecked()
        return info

    def set_pack_info(self, info: PackInfo):
        self.edit_title.blockSignals(True)
        self.combo_icon.blockSignals(True)
        self.edit_authors.blockSignals(True)
        self.chk_dub_video.blockSignals(True)
        
        self.edit_title.setText(info.title)
        
        if self.combo_icon.findText(info.icon) == -1 and info.icon:
            self.combo_icon.addItem(info.icon)
        self.combo_icon.setCurrentText(info.icon)
        
        self.edit_authors.setPlainText("\n".join(info.authors))
        self.chk_dub_video.setChecked(info.include_dub_video)
        
        self.edit_title.blockSignals(False)
        self.combo_icon.blockSignals(False)
        self.edit_authors.blockSignals(False)
        self.chk_dub_video.blockSignals(False)
        
    def _on_changed(self, *args):
        self.pack_info_changed.emit(self.get_pack_info())

