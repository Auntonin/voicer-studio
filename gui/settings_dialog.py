"""
gui/settings_dialog.py
======================
Settings & Preferences Dialog for Voicer Studio.

Tabs:
  1. General: Interface Language, Timeline display (Sticky Track Headers), Auto-save.
  2. AI Models: Hugging Face Token, Max Speakers, Whisper Model, Audio Language, Neural Voice Separation.
  3. Processing: Timestamp Mode, Silero VAD parameters, Image Quality, Audio Bitrate, Fast-Seek Proxy.
  4. Dubbing & Text: Dubbing contextual optimization, Hallucination filtering, Keywords, Whisper prompt.
  5. Output: Output directory, Game video formats, Pack Authors.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QFormLayout,
    QLineEdit, QComboBox, QRadioButton, QSlider, QSpinBox, QCheckBox,
    QPushButton, QLabel, QMessageBox
)
from PySide6.QtCore import Qt

from config import WHISPER_INITIAL_PROMPT_THAI, VAD_PADDING_MS, DIARIZATION_MAX_SPEAKERS
from core.i18n import i18n, tr
from gui.ui_utils import apply_dark_title_bar


class SettingsDialog(QDialog):
    def showEvent(self, event):
        super().showEvent(event)
        apply_dark_title_bar(self)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("settings_title"))
        self.resize(560, 460)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.tabs = QTabWidget()
        
        # ── Tab 1: General (Interface Language & Workspace Defaults) ──
        tab_gen = QWidget()
        form_gen = QFormLayout(tab_gen)
        form_gen.setContentsMargins(12, 12, 12, 12)
        form_gen.setSpacing(10)

        # Language dropdown with auto-discovered languages
        self.combo_app_lang = QComboBox()
        self._populate_language_combo()
        self.lbl_lang_hint = QLabel(tr("cfg_lang_hint"))
        self.lbl_lang_hint.setStyleSheet("color: #888888; font-size: 8pt;")
        self.lbl_lang_hint.setWordWrap(True)

        lang_box = QVBoxLayout()
        lang_box.setContentsMargins(0, 0, 0, 0)
        lang_box.setSpacing(2)
        lang_box.addWidget(self.combo_app_lang)
        lang_box.addWidget(self.lbl_lang_hint)
        form_gen.addRow(tr("cfg_lang_title"), lang_box)

        # Timeline Display options
        self.chk_sticky_headers = QCheckBox(tr("cfg_pin_headers"))
        self.chk_sticky_headers.setChecked(True)
        form_gen.addRow(tr("cfg_timeline_section"), self.chk_sticky_headers)

        self.chk_auto_save = QCheckBox(tr("cfg_auto_save"))
        self.chk_auto_save.setChecked(True)
        form_gen.addRow("", self.chk_auto_save)

        self.tabs.addTab(tab_gen, tr("tab_general"))

        # ── Tab 2: AI Models (Whisper, Demucs/BS-RoFormer, Diarization) ──
        tab_ai = QWidget()
        form_ai = QFormLayout(tab_ai)
        form_ai.setContentsMargins(12, 12, 12, 12)
        form_ai.setSpacing(10)
        
        hf_layout = QHBoxLayout()
        self.edit_hf = QLineEdit()
        self.edit_hf.setEchoMode(QLineEdit.EchoMode.Password)
        self.btn_test_hf = QPushButton(tr("cfg_hf_test"))
        self.btn_test_hf.clicked.connect(self._test_hf_token)
        hf_layout.addWidget(self.edit_hf)
        hf_layout.addWidget(self.btn_test_hf)
        form_ai.addRow(tr("cfg_hf_token"), hf_layout)

        self.spin_max_speakers = QSpinBox()
        self.spin_max_speakers.setRange(2, 16)
        self.spin_max_speakers.setValue(DIARIZATION_MAX_SPEAKERS)
        self.spin_max_speakers.setSuffix(" speakers")
        form_ai.addRow(tr("cfg_max_speakers"), self.spin_max_speakers)
        
        self.combo_whisper = QComboBox()
        self.combo_whisper.addItems(["tiny", "base", "small", "medium", "large-v3"])
        form_ai.addRow(tr("cfg_whisper_model"), self.combo_whisper)
        
        self.combo_lang = QComboBox()
        self.combo_lang.addItems(["Auto", "Thai", "Japanese", "English", "Chinese"])
        form_ai.addRow(tr("cfg_whisper_lang"), self.combo_lang)
        
        self.rb_sep_orig = QRadioButton(tr("cfg_sep_orig"))
        self.rb_sep_iso = QRadioButton(tr("cfg_sep_iso"))
        self.rb_sep_hq = QRadioButton(tr("cfg_sep_hq"))
        sep_layout = QVBoxLayout()
        sep_layout.addWidget(self.rb_sep_orig)
        sep_layout.addWidget(self.rb_sep_iso)
        sep_layout.addWidget(self.rb_sep_hq)
        form_ai.addRow(tr("cfg_voice_sep"), sep_layout)
        
        self.tabs.addTab(tab_ai, tr("tab_ai_models"))
        
        # ── Tab 3: Processing (VAD, Proxy, Formats, Bitrates) ──
        tab_proc = QWidget()
        form_proc = QFormLayout(tab_proc)
        form_proc.setContentsMargins(12, 12, 12, 12)
        form_proc.setSpacing(10)
        
        self.rb_ts_start = QRadioButton(tr("cfg_ts_start"))
        self.rb_ts_start_end = QRadioButton(tr("cfg_ts_start_end"))
        self.rb_ts_rel = QRadioButton(tr("cfg_ts_rel"))
        ts_layout = QVBoxLayout()
        ts_layout.addWidget(self.rb_ts_start)
        ts_layout.addWidget(self.rb_ts_start_end)
        ts_layout.addWidget(self.rb_ts_rel)
        form_proc.addRow(tr("cfg_ts_mode"), ts_layout)
        
        vad_layout = QHBoxLayout()
        self.slider_vad = QSlider(Qt.Orientation.Horizontal)
        self.slider_vad.setRange(10, 90)
        self.lbl_vad = QLabel("0.50")
        self.slider_vad.valueChanged.connect(lambda v: self.lbl_vad.setText(f"{v/100:.2f}"))
        vad_layout.addWidget(self.slider_vad)
        vad_layout.addWidget(self.lbl_vad)
        form_proc.addRow(tr("cfg_vad_thresh"), vad_layout)
        
        self.spin_pad = QSpinBox()
        self.spin_pad.setRange(0, 1000)
        self.spin_pad.setSuffix(" ms")
        form_proc.addRow(tr("cfg_vad_pad"), self.spin_pad)
        
        self.spin_gap = QSpinBox()
        self.spin_gap.setRange(0, 2000)
        self.spin_gap.setSuffix(" ms")
        self.gap_hint = QLabel(f"<small style='color:#888'>{tr('cfg_vad_gap_hint')}</small>")
        self.gap_hint.setWordWrap(True)
        gap_layout = QVBoxLayout()
        gap_layout.setContentsMargins(0, 0, 0, 0)
        gap_layout.setSpacing(2)
        gap_layout.addWidget(self.spin_gap)
        gap_layout.addWidget(self.gap_hint)
        form_proc.addRow(tr("cfg_vad_gap"), gap_layout)
        
        self.spin_img = QSpinBox()
        self.spin_img.setRange(50, 100)
        form_proc.addRow(tr("cfg_img_quality"), self.spin_img)
        
        self.combo_bitrate = QComboBox()
        self.combo_bitrate.addItems(["128k", "192k", "256k", "320k"])
        form_proc.addRow(tr("cfg_bitrate"), self.combo_bitrate)

        self.chk_preview_proxy = QCheckBox(tr("cfg_preview_proxy"))
        self.chk_preview_proxy.setChecked(True)
        form_proc.addRow("", self.chk_preview_proxy)

        self.combo_proxy_res = QComboBox()
        self.combo_proxy_res.addItems(["540p (Fastest, Highly Recommended)", "720p (HD Proxy)", "Original (No Proxy)"])
        form_proc.addRow(tr("cfg_proxy_res"), self.combo_proxy_res)
        
        self.tabs.addTab(tab_proc, tr("tab_processing"))

        # ── Tab 4: Dubbing & Text Processing ──
        tab_dub = QWidget()
        form_dub = QFormLayout(tab_dub)
        form_dub.setContentsMargins(12, 12, 12, 12)
        form_dub.setSpacing(10)
        
        self.chk_thai_opt = QCheckBox(tr("cfg_thai_opt"))
        self.chk_thai_opt.setChecked(True)
        form_dub.addRow("", self.chk_thai_opt)
        
        self.chk_clean_hallucinations = QCheckBox(tr("cfg_clean_hallucinations"))
        self.chk_clean_hallucinations.setChecked(True)
        form_dub.addRow("", self.chk_clean_hallucinations)
        
        self.chk_format_keywords = QCheckBox(tr("cfg_format_keywords"))
        self.chk_format_keywords.setChecked(True)
        form_dub.addRow("", self.chk_format_keywords)
        
        self.edit_initial_prompt = QLineEdit()
        self.edit_initial_prompt.setPlaceholderText("Initial prompt for Whisper...")
        form_dub.addRow(tr("cfg_whisper_prompt"), self.edit_initial_prompt)
        
        self.tabs.addTab(tab_dub, tr("tab_dubbing"))
        
        # ── Tab 5: Output ──
        tab_out = QWidget()
        form_out = QFormLayout(tab_out)
        form_out.setContentsMargins(12, 12, 12, 12)
        form_out.setSpacing(10)
        
        out_layout = QHBoxLayout()
        self.edit_out_dir = QLineEdit()
        self.btn_browse = QPushButton(tr("cfg_browse"))
        self.btn_browse.clicked.connect(self._browse_output_dir)
        out_layout.addWidget(self.edit_out_dir)
        out_layout.addWidget(self.btn_browse)
        form_out.addRow(tr("cfg_out_dir"), out_layout)
        
        self.chk_dub = QCheckBox(tr("cfg_inc_dub_video"))
        form_out.addRow("", self.chk_dub)
        
        self.edit_authors = QLineEdit()
        form_out.addRow(tr("cfg_pack_authors"), self.edit_authors)
        
        self.tabs.addTab(tab_out, tr("tab_output"))

        layout.addWidget(self.tabs)
        
        # ── Bottom Action Buttons ──
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_ok = QPushButton(tr("btn_ok"))
        self.btn_ok.setObjectName("btn_primary")
        self.btn_cancel = QPushButton(tr("btn_cancel"))
        self.btn_apply = QPushButton(tr("btn_apply"))
        
        self.btn_ok.clicked.connect(self._on_ok)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_apply.clicked.connect(self._on_apply)
        
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_apply)
        layout.addLayout(btn_layout)

    def _populate_language_combo(self):
        """Populate language dropdown with all available language packs."""
        self.combo_app_lang.clear()
        for code, name in i18n.get_available_languages().items():
            self.combo_app_lang.addItem(name, userData=code)

    def _on_apply(self):
        """Save settings without closing the dialog."""
        settings = self.get_settings()
        # Update active i18n language
        new_lang = settings.get("app_language", "en")
        i18n.set_language(new_lang)

        if self.parent():
            self.parent()._settings = settings
            self.parent()._save_settings(settings)
            if hasattr(self.parent(), "_timeline"):
                self.parent()._timeline.set_sticky_headers(settings.get("timeline_sticky_headers", True))
            if hasattr(self.parent(), "retranslate_ui"):
                self.parent().retranslate_ui()
        self.retranslate_ui()

    def _on_ok(self):
        """Apply settings and accept dialog."""
        self._on_apply()
        self.accept()

    def retranslate_ui(self):
        """Refreshes all texts in SettingsDialog when language changes."""
        self.setWindowTitle(tr("settings_title"))
        self.tabs.setTabText(0, tr("tab_general"))
        self.tabs.setTabText(1, tr("tab_ai_models"))
        self.tabs.setTabText(2, tr("tab_processing"))
        self.tabs.setTabText(3, tr("tab_dubbing"))
        self.tabs.setTabText(4, tr("tab_output"))

        self.lbl_lang_hint.setText(tr("cfg_lang_hint"))
        self.chk_sticky_headers.setText(tr("cfg_pin_headers"))
        self.chk_auto_save.setText(tr("cfg_auto_save"))
        self.btn_test_hf.setText(tr("cfg_hf_test"))
        self.rb_sep_orig.setText(tr("cfg_sep_orig"))
        self.rb_sep_iso.setText(tr("cfg_sep_iso"))
        self.rb_sep_hq.setText(tr("cfg_sep_hq"))
        self.rb_ts_start.setText(tr("cfg_ts_start"))
        self.rb_ts_start_end.setText(tr("cfg_ts_start_end"))
        self.rb_ts_rel.setText(tr("cfg_ts_rel"))
        self.gap_hint.setText(f"<small style='color:#888'>{tr('cfg_vad_gap_hint')}</small>")
        self.chk_preview_proxy.setText(tr("cfg_preview_proxy"))
        self.chk_thai_opt.setText(tr("cfg_thai_opt"))
        self.chk_clean_hallucinations.setText(tr("cfg_clean_hallucinations"))
        self.chk_format_keywords.setText(tr("cfg_format_keywords"))
        self.btn_browse.setText(tr("cfg_browse"))
        self.chk_dub.setText(tr("cfg_inc_dub_video"))
        self.btn_ok.setText(tr("btn_ok"))
        self.btn_cancel.setText(tr("btn_cancel"))
        self.btn_apply.setText(tr("btn_apply"))

    def _test_hf_token(self):
        token = self.edit_hf.text().strip()
        if not token:
            QMessageBox.warning(self, "Token Required", "Please enter a Hugging Face token.")
            return
            
        try:
            import urllib.request
            import json
            req = urllib.request.Request(
                "https://huggingface.co/api/whoami-v2",
                headers={"Authorization": f"Bearer {token}"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode('utf-8'))
                    name = data.get("name", "User")
                    QMessageBox.information(self, "Success", f"Token valid! Logged in as: {name}")
                else:
                    QMessageBox.warning(self, "Failed", f"Token check returned HTTP {resp.status}")
        except Exception as e:
            QMessageBox.critical(self, "Invalid Token", f"Token test failed: {e}")

    def _browse_output_dir(self):
        from PySide6.QtWidgets import QFileDialog
        dir_str = QFileDialog.getExistingDirectory(self, "Select Output Directory", self.edit_out_dir.text())
        if dir_str:
            self.edit_out_dir.setText(dir_str)

    def load_settings(self, settings: dict):
        # 1. General tab
        app_lang = settings.get("app_language", "en")
        idx = self.combo_app_lang.findData(app_lang)
        if idx >= 0:
            self.combo_app_lang.setCurrentIndex(idx)

        self.chk_sticky_headers.setChecked(settings.get("timeline_sticky_headers", True))
        self.chk_auto_save.setChecked(settings.get("auto_save_enabled", True))

        # 2. AI Models tab
        self.edit_hf.setText(settings.get("hf_token", ""))
        
        model = settings.get("whisper_model", "large-v3")
        idx = self.combo_whisper.findText(model)
        if idx >= 0:
            self.combo_whisper.setCurrentIndex(idx)
            
        lang_map = {None: "Auto", "th": "Thai", "ja": "Japanese", "en": "English", "zh": "Chinese"}
        lang_text = lang_map.get(settings.get("whisper_language", "th"), "Thai")
        lang_idx = self.combo_lang.findText(lang_text)
        if lang_idx >= 0:
            self.combo_lang.setCurrentIndex(lang_idx)
            
        sep_mode = settings.get("voice_sep_mode", "hq")
        if sep_mode == "original":
            self.rb_sep_orig.setChecked(True)
        elif sep_mode == "isolate":
            self.rb_sep_iso.setChecked(True)
        elif sep_mode == "hq":
            self.rb_sep_hq.setChecked(True)
        else:
            self.rb_sep_hq.setChecked(True)

        self.spin_max_speakers.setValue(settings.get("max_speakers", DIARIZATION_MAX_SPEAKERS))

        # 3. Processing tab
        ts_mode = settings.get("timestamp_mode", "start_only")
        if ts_mode == "start_only":
            self.rb_ts_start.setChecked(True)
        elif ts_mode == "start_end":
            self.rb_ts_start_end.setChecked(True)
        elif ts_mode == "relative":
            self.rb_ts_rel.setChecked(True)
        else:
            self.rb_ts_start.setChecked(True)
            
        vad = int(settings.get("vad_threshold", 0.5) * 100)
        self.slider_vad.setValue(max(10, min(90, vad)))
        self.lbl_vad.setText(f"{vad/100:.2f}")
        self.spin_pad.setValue(settings.get("vad_padding_ms", VAD_PADDING_MS))
        self.spin_gap.setValue(settings.get("vad_merge_gap_ms", 120))
        self.spin_img.setValue(settings.get("image_quality", 95))
        
        bitrate = settings.get("audio_bitrate", "320k")
        br_idx = self.combo_bitrate.findText(bitrate)
        if br_idx >= 0:
            self.combo_bitrate.setCurrentIndex(br_idx)

        self.chk_preview_proxy.setChecked(settings.get("preview_proxy_enabled", True))
        proxy_h = settings.get("preview_proxy_height", 540)
        if proxy_h == 540:
            self.combo_proxy_res.setCurrentIndex(0)
        elif proxy_h == 720:
            self.combo_proxy_res.setCurrentIndex(1)
        else:
            self.combo_proxy_res.setCurrentIndex(2)

        # 4. Dubbing tab
        self.chk_thai_opt.setChecked(settings.get("thai_dubbing_opt", True))
        self.chk_clean_hallucinations.setChecked(settings.get("clean_hallucinations", True))
        self.chk_format_keywords.setChecked(settings.get("format_keywords", True))
        self.edit_initial_prompt.setText(settings.get("whisper_initial_prompt", WHISPER_INITIAL_PROMPT_THAI))
            
        # 5. Output tab
        self.edit_out_dir.setText(settings.get("output_dir", ""))
        self.chk_dub.setChecked(settings.get("include_dub_video", True))
        authors = settings.get("pack_authors", ["unknown"])
        self.edit_authors.setText(", ".join(authors) if isinstance(authors, list) else str(authors))
        
    def get_settings(self) -> dict:
        lang_map = {"Auto": None, "Thai": "th", "Japanese": "ja", "English": "en", "Chinese": "zh"}
        lang_text = self.combo_lang.currentText()
        
        sep_mode = "original"
        if self.rb_sep_iso.isChecked():
            sep_mode = "isolate"
        elif self.rb_sep_hq.isChecked():
            sep_mode = "hq"
            
        ts_mode = "start_only"
        if self.rb_ts_start_end.isChecked():
            ts_mode = "start_end"
        elif self.rb_ts_rel.isChecked():
            ts_mode = "relative"
            
        authors_raw = self.edit_authors.text()
        authors = [a.strip() for a in authors_raw.split(",") if a.strip()]
        if not authors:
            authors = ["unknown"]

        proxy_h_map = {0: 540, 1: 720, 2: 0}
        proxy_h = proxy_h_map.get(self.combo_proxy_res.currentIndex(), 540)

        app_lang = self.combo_app_lang.currentData() or "en"
            
        return {
            "app_language":           app_lang,
            "hf_token":               self.edit_hf.text().strip(),
            "whisper_model":          self.combo_whisper.currentText(),
            "whisper_language":       lang_map.get(lang_text, "th"),
            "voice_sep_mode":         sep_mode,
            "timestamp_mode":         ts_mode,
            "vad_threshold":          self.slider_vad.value() / 100.0,
            "vad_padding_ms":         self.spin_pad.value(),
            "vad_merge_gap_ms":       self.spin_gap.value(),
            "max_speakers":           self.spin_max_speakers.value(),
            "timeline_sticky_headers": self.chk_sticky_headers.isChecked(),
            "auto_save_enabled":      self.chk_auto_save.isChecked(),
            "preview_proxy_enabled":   self.chk_preview_proxy.isChecked(),
            "preview_proxy_height":    proxy_h,
            "image_quality":          self.spin_img.value(),
            "audio_bitrate":          self.combo_bitrate.currentText(),
            "thai_dubbing_opt":       self.chk_thai_opt.isChecked(),
            "clean_hallucinations":   self.chk_clean_hallucinations.isChecked(),
            "format_keywords":        self.chk_format_keywords.isChecked(),
            "whisper_initial_prompt": self.edit_initial_prompt.text().strip(),
            "output_dir":             self.edit_out_dir.text().strip(),
            "include_dub_video":      self.chk_dub.isChecked(),
            "pack_authors":           authors,
        }
