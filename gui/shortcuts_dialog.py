"""
gui/shortcuts_dialog.py
=======================
Professional Keyboard Shortcuts reference dialog for Voicer Studio.
Clean, minimal aesthetic inspired by Adobe Creative Cloud and Figma.
Zero emojis, refined typography, and authentic hardware-style keycaps.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QScrollArea, QWidget, QFrame, QPushButton, QGridLayout
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QFont

from config import ASSETS_DIR
from core.i18n import tr
from gui.ui_utils import apply_dark_title_bar


SHORTCUT_DATA = [
    {
        "category": "TIMELINE NAVIGATION & PLAYBACK",
        "items": [
            ("Play / Pause Timeline", ["Space"], "Toggle master timeline audio playback"),
            ("Zoom Timeline (Anchored)", ["Ctrl + Wheel", "Alt + Wheel"], "Zoom timeline centered directly under mouse cursor"),
            ("Scroll Timeline (H)", ["Shift + Wheel"], "Pan timeline canvas horizontally left or right"),
            ("Scroll Tracks (V / H)", ["Wheel"], "Scroll track lanes vertically or horizontally"),
            ("2D Canvas Pan", ["Middle Mouse Drag"], "Pan freely across timeline canvas with hand tool"),
            ("Zoom In", ["+ / ="], "Zoom in timeline view increments"),
            ("Zoom Out", ["-"], "Zoom out timeline view increments"),
            ("Scrub Playhead", ["Click Ruler / Track"], "Jump playhead directly to clicked time position"),
            ("Center Clip & Track", ["Double-click Table / Clip"], "Smooth-pan camera to center dialogue clip and character track"),
            ("Seek to Dialogue", ["Click Table Row"], "Move playhead and video player to dialogue start time"),
        ]
    },
    {
        "category": "CLIP EDITING & TRIMMING",
        "items": [
            ("Split at Playhead", ["S", "Ctrl+B"], "Slice active clip at current playhead position"),
            ("Delete Left to Playhead", ["Q"], "Trim and delete clip segment from start to playhead"),
            ("Delete Right from Playhead", ["W"], "Trim and delete clip segment from playhead to end"),
            ("Delete Selected Clip", ["Del", "Backspace"], "Remove selected dialogue clip from timeline"),
            ("Slip / Move Clip", ["Drag Clip Body"], "Reposition dialogue start and end timings together"),
            ("Trim Clip Boundary", ["Drag Clip Edge"], "Adjust start or end boundary with 10px snapping"),
            ("Move Between Tracks", ["Drag Vertically"], "Reassign dialogue clip to a different character track"),
        ]
    },
    {
        "category": "TRACKS & CHARACTERS",
        "items": [
            ("Add Character Track", ["+ Add Track"], "Create new track and prompt character name immediately"),
            ("Rename Character", ["Double-click Track"], "Directly edit character display name"),
            ("Track Context Menu", ["Right-click Track"], "Rename, delete track, or toggle sticky pinning"),
            ("Pin Tracks to Edge", ["Pin Icon"], "Keep character headers visible while scrolling right"),
            ("Reorder Tracks", ["Drag Track Grip"], "Grab left grip handle to reorder track rows"),
        ]
    },
    {
        "category": "PROJECT & APPLICATION",
        "items": [
            ("Undo Action", ["Ctrl+Z"], "Revert last timeline, text, or dialogue edit"),
            ("Redo Action", ["Ctrl+Y", "Ctrl+Shift+Z"], "Restore undone edit"),
            ("Save Project", ["Ctrl+S"], "Save current project to .voicer file"),
            ("Save Project As...", ["Ctrl+Shift+S"], "Save project to a new file location"),
            ("New Project", ["Ctrl+N"], "Start a new project"),
            ("Open Project...", ["Ctrl+O"], "Open an existing .voicer project"),
            ("Import Video...", ["Ctrl+I"], "Import video for dialogue extraction"),
            ("Export Pack ZIP...", ["Ctrl+E"], "Export final game dialogue pack archive"),
            ("Toggle Full Screen", ["F11"], "Enter or exit borderless full screen mode"),
            ("Keyboard Shortcuts", ["F1", "?"], "Open this keyboard shortcuts reference sheet"),
        ]
    }
]


class ShortcutsDialog(QDialog):
    def showEvent(self, event):
        super().showEvent(event)
        apply_dark_title_bar(self)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("sc_dialog_title"))
        self.resize(880, 600)
        self.setMinimumSize(720, 480)

        icon_path = ASSETS_DIR / "icons" / "keyboard.svg"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.setStyleSheet("""
            QDialog {
                background-color: #181818;
                color: #e4e4e7;
                font-family: 'Segoe UI', system-ui, sans-serif;
            }
            QLineEdit {
                background-color: #121212;
                border: 1px solid #333333;
                border-radius: 5px;
                padding: 6px 12px;
                color: #f4f4f5;
                font-size: 8.5pt;
            }
            QLineEdit:focus {
                border: 1px solid #0078d4;
                background-color: #181818;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                background: #141414;
                width: 8px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #333333;
                min-height: 24px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #484848;
            }
            QPushButton#close_btn {
                background-color: #262626;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                padding: 6px 20px;
                color: #ffffff;
                font-size: 8.5pt;
                font-weight: 500;
            }
            QPushButton#close_btn:hover {
                background-color: #303030;
                border-color: #505050;
            }
            QPushButton#close_btn:pressed {
                background-color: #1f1f1f;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(14)

        # ── Header ──
        top_bar = QHBoxLayout()
        header_text = QVBoxLayout()
        header_text.setSpacing(2)

        title_lbl = QLabel(tr("sc_dialog_title"))
        title_lbl.setStyleSheet("font-size: 13pt; font-weight: bold; color: #ffffff; letter-spacing: -0.2px;")
        sub_lbl = QLabel("Quick reference guide for Voicer Studio editing controls and keybindings")
        sub_lbl.setStyleSheet("font-size: 8.5pt; color: #888888;")

        header_text.addWidget(title_lbl)
        header_text.addWidget(sub_lbl)
        top_bar.addLayout(header_text)
        top_bar.addStretch()

        # Search Filter Box
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(tr("sc_search_placeholder"))
        self.search_box.setFixedWidth(240)
        self.search_box.textChanged.connect(self._filter_shortcuts)
        top_bar.addWidget(self.search_box)

        layout.addLayout(top_bar)

        # ── Separator ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #282828; border: none; max-height: 1px;")
        layout.addWidget(sep)

        # ── Content Scroll Area ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        self.content_layout = QVBoxLayout(self.container)
        self.content_layout.setContentsMargins(0, 4, 8, 8)
        self.content_layout.setSpacing(14)

        self._category_widgets = []
        self._build_shortcut_list()

        scroll.setWidget(self.container)
        layout.addWidget(scroll)

        # ── Footer ──
        footer = QHBoxLayout()
        tip_lbl = QLabel("Tip: You can also hover your cursor over toolbar buttons to see their shortcuts.")
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
                    background-color: #1f1f1f;
                    border: 1px solid #2a2a2a;
                    border-radius: 6px;
                    padding: 8px 12px;
                }
            """)
            card_layout = QVBoxLayout(cat_card)
            card_layout.setContentsMargins(14, 12, 14, 14)
            card_layout.setSpacing(8)

            cat_map = {
                "TIMELINE NAVIGATION & PLAYBACK": "sc_cat_timeline",
                "CLIP EDITING & TRIMMING": "sc_cat_editing",
                "TRACKS & CHARACTERS": "sc_cat_tracks",
                "PROJECT & APPLICATION": "sc_cat_project",
            }
            cat_text = tr(cat_map.get(cat_data["category"], cat_data["category"]))
            cat_title = QLabel(cat_text)
            cat_title.setStyleSheet("""
                font-size: 8pt;
                font-weight: bold;
                color: #a1a1aa;
                letter-spacing: 0.6px;
                border: none;
                border-bottom: 1px solid #2c2c2c;
                padding-bottom: 6px;
                margin-bottom: 2px;
            """)
            card_layout.addWidget(cat_title)

            grid = QGridLayout()
            grid.setContentsMargins(0, 4, 0, 0)
            grid.setHorizontalSpacing(16)
            grid.setVerticalSpacing(8)

            item_records = []
            for row_idx, (name, keys_list, desc) in enumerate(cat_data["items"]):
                name_lbl = QLabel(name)
                name_lbl.setStyleSheet("font-size: 8.5pt; font-weight: 500; color: #e4e4e7; border: none;")

                keys_widget = self._create_keycaps_widget(keys_list)

                desc_lbl = QLabel(desc)
                desc_lbl.setWordWrap(True)
                desc_lbl.setStyleSheet("font-size: 8pt; color: #888888; border: none;")

                grid.addWidget(name_lbl, row_idx, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                grid.addWidget(keys_widget, row_idx, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                grid.addWidget(desc_lbl, row_idx, 2, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

                search_keys_str = " ".join(keys_list)
                item_records.append((name, search_keys_str, desc, name_lbl, keys_widget, desc_lbl))

            grid.setColumnStretch(0, 0)
            grid.setColumnStretch(1, 0)
            grid.setColumnStretch(2, 1)
            card_layout.addLayout(grid)

            self.content_layout.addWidget(cat_card)
            self._category_widgets.append((cat_card, cat_data["category"], item_records))

        self.content_layout.addStretch()

    def _create_keycaps_widget(self, keys_list: list[str]) -> QWidget:
        container = QWidget()
        container.setStyleSheet("background: transparent; border: none;")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        badge_style = """
            QLabel {
                background-color: #27272a;
                border: 1px solid #3f3f46;
                border-bottom: 2px solid #52525b;
                border-radius: 4px;
                padding: 2px 7px;
                color: #f4f4f5;
                font-family: 'Segoe UI', system-ui, sans-serif;
                font-weight: 600;
                font-size: 8pt;
            }
        """
        sep_style = "color: #71717a; font-size: 8pt; font-weight: 500; border: none;"
        or_style = "color: #52525b; font-size: 7.5pt; font-weight: bold; margin: 0 3px; border: none;"

        for combo_idx, combo_str in enumerate(keys_list):
            if combo_idx > 0:
                or_lbl = QLabel("/")
                or_lbl.setStyleSheet(or_style)
                layout.addWidget(or_lbl)

            if "+" in combo_str and combo_str.strip() not in ("+", "+ / ="):
                tokens = [t.strip() for t in combo_str.split("+") if t.strip()]
                for t_idx, token in enumerate(tokens):
                    if t_idx > 0:
                        plus_lbl = QLabel("+")
                        plus_lbl.setStyleSheet(sep_style)
                        layout.addWidget(plus_lbl)
                    k_lbl = QLabel(token)
                    k_lbl.setStyleSheet(badge_style)
                    layout.addWidget(k_lbl)
            else:
                k_lbl = QLabel(combo_str)
                k_lbl.setStyleSheet(badge_style)
                layout.addWidget(k_lbl)

        layout.addStretch()
        return container

    def _filter_shortcuts(self, query: str):
        query = query.strip().lower()
        for cat_card, cat_title, items in self._category_widgets:
            any_matched = False
            for name, keys_str, desc, name_lbl, keys_widget, desc_lbl in items:
                search_blob = f"{name} {keys_str} {desc}".lower()
                matches = (not query) or (query in search_blob)
                name_lbl.setVisible(matches)
                keys_widget.setVisible(matches)
                desc_lbl.setVisible(matches)
                if matches:
                    any_matched = True

            cat_card.setVisible(any_matched)
