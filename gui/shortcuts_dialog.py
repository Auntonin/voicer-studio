"""
gui/shortcuts_dialog.py
=======================
A modern, minimalist Keyboard Shortcuts reference sheet for Voicer Studio.
Inspired by CapCut, DaVinci Resolve, and Adobe Premiere Pro.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QScrollArea, QWidget, QFrame, QPushButton, QGridLayout
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QFont

from config import ASSETS_DIR


SHORTCUT_DATA = [
    {
        "category": "🎬 Timeline Navigation & Playback",
        "items": [
            ("Play / Pause Timeline", ["Space"], "Toggle master audio playback"),
            ("Zoom Timeline (Anchored)", ["Ctrl + Wheel", "Alt + Wheel"], "Zoom centered directly under mouse cursor"),
            ("Scroll Timeline (H)", ["Shift + Wheel"], "Pan timeline horizontally left / right"),
            ("Scroll Tracks (V / H)", ["Wheel"], "Scroll tracks vertically or horizontally"),
            ("2D Canvas Pan", ["Middle Mouse Drag"], "Pan freely across timeline canvas"),
            ("Zoom In", ["+ / ="], "Zoom in timeline increments"),
            ("Zoom Out", ["-"], "Zoom out timeline increments"),
            ("Scrub Playhead", ["Click Ruler / Track"], "Jump playhead directly to clicked time position"),
        ]
    },
    {
        "category": "✂️ Clip Editing & Trimming",
        "items": [
            ("Split at Playhead", ["S", "Ctrl+B"], "Slice selected clip at current playhead position"),
            ("Delete Left to Playhead", ["Q"], "Trim and delete segment from clip start to playhead"),
            ("Delete Right from Playhead", ["W"], "Trim and delete segment from playhead to clip end"),
            ("Delete Selected Clip", ["Del", "Backspace"], "Remove dialogue clip from timeline"),
            ("Slip / Move Clip", ["Drag Clip Body"], "Reposition dialogue start and end timings together"),
            ("Trim Clip Edge", ["Drag Edge"], "Adjust start or end boundary with snap support"),
            ("Move Between Tracks", ["Drag Vertically"], "Assign clip to a different speaker track"),
        ]
    },
    {
        "category": "🎭 Tracks & Characters",
        "items": [
            ("Add Character Track", ["+ Add Track"], "Create new track and set character name immediately"),
            ("Rename Character", ["Double-click Track"], "Directly edit character display name"),
            ("Track Options Menu", ["Right-click Track"], "Rename, delete track, or toggle sticky pinning"),
            ("Sticky Tracks Pin", ["📌 Pin Button"], "Keep character headers anchored on screen when scrolling"),
            ("Reorder Tracks", ["Drag Track Grip"], "Grab 6-dot handle on left to reorder track rows"),
        ]
    },
    {
        "category": "📁 Project & Application",
        "items": [
            ("Undo Action", ["Ctrl+Z"], "Revert last timeline or dialogue edit"),
            ("Redo Action", ["Ctrl+Y", "Ctrl+Shift+Z"], "Restore undone edit"),
            ("Save Project", ["Ctrl+S"], "Save current project to .voicer file"),
            ("Save Project As...", ["Ctrl+Shift+S"], "Save project to a new file location"),
            ("New Project", ["Ctrl+N"], "Start a fresh project"),
            ("Open Project...", ["Ctrl+O"], "Open existing .voicer project"),
            ("Import Video...", ["Ctrl+I"], "Import video for dialogue extraction"),
            ("Export Pack ZIP...", ["Ctrl+E"], "Export final game dialogue pack"),
            ("Toggle Full Screen", ["F11"], "Enter or exit borderless full screen mode"),
            ("Keyboard Shortcuts", ["F1", "?"], "Open this shortcuts cheat sheet"),
        ]
    }
]


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts & Gestures")
        self.resize(680, 560)
        self.setMinimumSize(540, 440)

        icon_path = ASSETS_DIR / "icons" / "keyboard.svg"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
                color: #e0e0e0;
            }
            QLineEdit {
                background-color: #141414;
                border: 1px solid #383838;
                border-radius: 6px;
                padding: 6px 12px;
                color: #ffffff;
                font-size: 9pt;
            }
            QLineEdit:focus {
                border-color: #1473E6;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                background: #1a1a1a;
                width: 8px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #3a3a3a;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #4f4f4f;
            }
            QPushButton#close_btn {
                background-color: #2b2b2b;
                border: 1px solid #3d3d3d;
                border-radius: 5px;
                padding: 6px 18px;
                color: #ffffff;
                font-size: 9pt;
                font-weight: 500;
            }
            QPushButton#close_btn:hover {
                background-color: #383838;
                border-color: #555555;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)

        # ── Header ──
        top_bar = QHBoxLayout()
        header_text = QVBoxLayout()
        header_text.setSpacing(2)

        title_lbl = QLabel("⌨️ Keyboard Shortcuts & Gestures")
        title_lbl.setStyleSheet("font-size: 13pt; font-weight: bold; color: #ffffff;")
        sub_lbl = QLabel("Quick reference guide for Voicer Studio timeline controls and keybindings")
        sub_lbl.setStyleSheet("font-size: 8.5pt; color: #888888;")

        header_text.addWidget(title_lbl)
        header_text.addWidget(sub_lbl)
        top_bar.addLayout(header_text)
        top_bar.addStretch()

        # Search Filter Box
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍 Filter shortcuts... (e.g. split, zoom, Q, S)")
        self.search_box.setFixedWidth(220)
        self.search_box.textChanged.connect(self._filter_shortcuts)
        top_bar.addWidget(self.search_box)

        layout.addLayout(top_bar)

        # ── Separator ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #2c2c2c; border: none; max-height: 1px;")
        layout.addWidget(sep)

        # ── Content Scroll Area ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        self.content_layout = QVBoxLayout(self.container)
        self.content_layout.setContentsMargins(0, 4, 10, 8)
        self.content_layout.setSpacing(16)

        self._category_widgets = []
        self._build_shortcut_list()

        scroll.setWidget(self.container)
        layout.addWidget(scroll)

        # ── Footer ──
        footer = QHBoxLayout()
        tip_lbl = QLabel("💡 Tip: You can also hover your mouse over toolbar buttons to see their shortcuts.")
        tip_lbl.setStyleSheet("font-size: 8pt; color: #777777;")
        footer.addWidget(tip_lbl)
        footer.addStretch()

        btn_close = QPushButton("Close (Esc)", objectName="close_btn")
        btn_close.clicked.connect(self.accept)
        footer.addWidget(btn_close)

        layout.addLayout(footer)

    def _build_shortcut_list(self):
        for cat_data in SHORTCUT_DATA:
            cat_card = QFrame()
            cat_card.setStyleSheet("""
                QFrame {
                    background-color: #232323;
                    border: 1px solid #303030;
                    border-radius: 8px;
                    padding: 8px 12px;
                }
            """)
            card_layout = QVBoxLayout(cat_card)
            card_layout.setContentsMargins(12, 10, 12, 12)
            card_layout.setSpacing(8)

            cat_title = QLabel(cat_data["category"])
            cat_title.setStyleSheet("font-size: 10pt; font-weight: bold; color: #58a6ff; border: none; padding-bottom: 2px;")
            card_layout.addWidget(cat_title)

            grid = QGridLayout()
            grid.setContentsMargins(0, 4, 0, 0)
            grid.setHorizontalSpacing(16)
            grid.setVerticalSpacing(7)

            item_records = []
            for row_idx, (name, keys, desc) in enumerate(cat_data["items"]):
                name_lbl = QLabel(name)
                name_lbl.setStyleSheet("font-size: 8.5pt; font-weight: 500; color: #ffffff; border: none;")

                # Render key badges (<kbd> style)
                keys_html = " &nbsp;".join(
                    f'<span style="background-color: #171717; border: 1px solid #444444; border-bottom: 2px solid #585858; border-radius: 4px; padding: 2px 6px; color: #38BDF8; font-family: Segoe UI, sans-serif; font-size: 8pt; font-weight: bold;">{k}</span>'
                    for k in keys
                )
                keys_lbl = QLabel(keys_html)
                keys_lbl.setStyleSheet("border: none;")

                desc_lbl = QLabel(desc)
                desc_lbl.setStyleSheet("font-size: 8pt; color: #888888; border: none;")

                grid.addWidget(name_lbl, row_idx, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                grid.addWidget(keys_lbl, row_idx, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                grid.addWidget(desc_lbl, row_idx, 2, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

                item_records.append((name, keys, desc, name_lbl, keys_lbl, desc_lbl))

            grid.setColumnStretch(0, 2)
            grid.setColumnStretch(1, 2)
            grid.setColumnStretch(2, 3)
            card_layout.addLayout(grid)

            self.content_layout.addWidget(cat_card)
            self._category_widgets.append((cat_card, cat_data["category"], item_records))

        self.content_layout.addStretch()

    def _filter_shortcuts(self, query: str):
        query = query.strip().lower()
        for cat_card, cat_title, items in self._category_widgets:
            any_matched = False
            for name, keys, desc, name_lbl, keys_lbl, desc_lbl in items:
                search_blob = f"{name} {' '.join(keys)} {desc}".lower()
                matches = (not query) or (query in search_blob)
                name_lbl.setVisible(matches)
                keys_lbl.setVisible(matches)
                desc_lbl.setVisible(matches)
                if matches:
                    any_matched = True

            cat_card.setVisible(any_matched)
