from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QFormLayout,
    QLineEdit, QComboBox, QRadioButton, QSlider, QSpinBox, QCheckBox,
    QPushButton, QLabel, QMessageBox
)
from PySide6.QtCore import Qt

from config import WHISPER_INITIAL_PROMPT_THAI, VAD_PADDING_MS, DIARIZATION_MAX_SPEAKERS

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(520, 420)
        
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        
        # Tab 1: AI Models
        tab_ai = QWidget()
        form_ai = QFormLayout(tab_ai)
        
        hf_layout = QHBoxLayout()
        self.edit_hf = QLineEdit()
        self.edit_hf.setEchoMode(QLineEdit.EchoMode.Password)
        self.btn_test_hf = QPushButton("Test Token")
        self.btn_test_hf.clicked.connect(self._test_hf_token)
        hf_layout.addWidget(self.edit_hf)
        hf_layout.addWidget(self.btn_test_hf)
        form_ai.addRow("Hugging Face Token:", hf_layout)

        self.spin_max_speakers = QSpinBox()
        self.spin_max_speakers.setRange(2, 16)
        self.spin_max_speakers.setValue(DIARIZATION_MAX_SPEAKERS)
        self.spin_max_speakers.setSuffix(" speakers")
        form_ai.addRow("Max Speakers:", self.spin_max_speakers)
        
        self.combo_whisper = QComboBox()
        self.combo_whisper.addItems(["tiny", "base", "small", "medium", "large-v3"])
        form_ai.addRow("Whisper Model:", self.combo_whisper)
        
        self.combo_lang = QComboBox()
        self.combo_lang.addItems(["Auto", "Thai", "Japanese", "English", "Chinese"])
        form_ai.addRow("Whisper Language:", self.combo_lang)
        
        self.rb_sep_orig = QRadioButton("Original (no separation)")
        self.rb_sep_iso = QRadioButton("Voice Isolation (Demucs standard)")
        self.rb_sep_hq = QRadioButton("High Quality (Demucs htdemucs_6s)")
        sep_layout = QVBoxLayout()
        sep_layout.addWidget(self.rb_sep_orig)
        sep_layout.addWidget(self.rb_sep_iso)
        sep_layout.addWidget(self.rb_sep_hq)
        form_ai.addRow("Voice Separation:", sep_layout)
        
        self.tabs.addTab(tab_ai, "AI Models")
        
        # Tab 2: Processing
        tab_proc = QWidget()
        form_proc = QFormLayout(tab_proc)
        
        self.rb_ts_start = QRadioButton("Start Only e.g. [2.049]")
        self.rb_ts_start_end = QRadioButton("Start + End e.g. [2.049, 4.200]")
        self.rb_ts_rel = QRadioButton("Relative to clip e.g. [0.0]")
        ts_layout = QVBoxLayout()
        ts_layout.addWidget(self.rb_ts_start)
        ts_layout.addWidget(self.rb_ts_start_end)
        ts_layout.addWidget(self.rb_ts_rel)
        form_proc.addRow("Timestamp Mode:", ts_layout)
        
        vad_layout = QHBoxLayout()
        self.slider_vad = QSlider(Qt.Orientation.Horizontal)
        self.slider_vad.setRange(10, 90)
        self.lbl_vad = QLabel("0.50")
        self.slider_vad.valueChanged.connect(lambda v: self.lbl_vad.setText(f"{v/100:.2f}"))
        vad_layout.addWidget(self.slider_vad)
        vad_layout.addWidget(self.lbl_vad)
        form_proc.addRow("VAD Threshold:", vad_layout)
        
        self.spin_pad = QSpinBox()
        self.spin_pad.setRange(0, 1000)
        self.spin_pad.setSuffix(" ms")
        form_proc.addRow("VAD Padding:", self.spin_pad)
        
        self.spin_gap = QSpinBox()
        self.spin_gap.setRange(0, 2000)
        self.spin_gap.setSuffix(" ms")
        gap_hint = QLabel("<small style='color:#888'>ค่าน้อย = ซอยประโยคสั้น | ค่ามาก = รวมเป็นก้อนใหญ่</small>")
        gap_hint.setWordWrap(True)
        gap_layout = QVBoxLayout()
        gap_layout.setContentsMargins(0,0,0,0)
        gap_layout.setSpacing(2)
        gap_layout.addWidget(self.spin_gap)
        gap_layout.addWidget(gap_hint)
        form_proc.addRow("VAD Merge Gap:", gap_layout)
        
        self.spin_img = QSpinBox()
        self.spin_img.setRange(50, 100)
        form_proc.addRow("Image Quality:", self.spin_img)
        
        self.combo_bitrate = QComboBox()
        self.combo_bitrate.addItems(["128k", "192k", "256k", "320k"])
        form_proc.addRow("Audio Bitrate:", self.combo_bitrate)

        self.chk_sticky_headers = QCheckBox("Pin Speaker Track Headers (Sticky / ตรึงรายชื่อตัวละครติดขอบซ้าย)")
        self.chk_sticky_headers.setChecked(True)
        form_proc.addRow("Timeline:", self.chk_sticky_headers)

        self.chk_preview_proxy = QCheckBox("Generate Fast-Seek Preview Proxy (สร้างวิดีโอย่อส่วนเพื่อให้พรีวิวและเลื่อนไทม์ไลน์ได้ลื่นไหล)")
        self.chk_preview_proxy.setChecked(True)
        form_proc.addRow("Preview Proxy:", self.chk_preview_proxy)

        self.combo_proxy_res = QComboBox()
        self.combo_proxy_res.addItems(["540p (Fastest, Highly Recommended)", "720p (HD Proxy)", "Original (No Proxy)"])
        form_proc.addRow("Proxy Resolution:", self.combo_proxy_res)
        
        self.tabs.addTab(tab_proc, "Processing")

        # Tab 3: Thai Dubbing & Text Processing
        tab_thai = QWidget()
        form_thai = QFormLayout(tab_thai)
        
        self.chk_thai_opt = QCheckBox("Enable Thai Dubbing Optimization (Context Prompting)")
        self.chk_thai_opt.setChecked(True)
        form_thai.addRow("", self.chk_thai_opt)
        
        self.chk_clean_hallucinations = QCheckBox("Auto-clean Repetitive Hallucinations (e.g. repeated phrases)")
        self.chk_clean_hallucinations.setChecked(True)
        form_thai.addRow("", self.chk_clean_hallucinations)
        
        self.chk_format_keywords = QCheckBox("Contextual Keyword Preservation (Thai / English loanwords)")
        self.chk_format_keywords.setChecked(True)
        form_thai.addRow("", self.chk_format_keywords)
        
        self.edit_initial_prompt = QLineEdit()
        self.edit_initial_prompt.setPlaceholderText("Initial prompt for Whisper...")
        form_thai.addRow("Whisper Initial Prompt:", self.edit_initial_prompt)
        
        self.tabs.addTab(tab_thai, "Thai Dubbing")
        
        # Tab 4: Output
        tab_out = QWidget()
        form_out = QFormLayout(tab_out)
        
        out_layout = QHBoxLayout()
        self.edit_out_dir = QLineEdit()
        self.btn_browse = QPushButton("Browse...")
        self.btn_browse.clicked.connect(self._browse_output_dir)
        out_layout.addWidget(self.edit_out_dir)
        out_layout.addWidget(self.btn_browse)
        form_out.addRow("Output Directory:", out_layout)
        
        self.chk_dub = QCheckBox("Include dub_video.mp4")
        form_out.addRow("", self.chk_dub)
        
        self.edit_authors = QLineEdit()
        form_out.addRow("Default Pack Authors:", self.edit_authors)
        
        self.tabs.addTab(tab_out, "Output")

        
        layout.addWidget(self.tabs)
        
        # Bottom Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_ok = QPushButton("OK")
        self.btn_ok.setObjectName("btn_primary")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_apply = QPushButton("Apply")
        
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_apply.clicked.connect(self._on_apply)
        
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_apply)
        layout.addLayout(btn_layout)

    def _on_apply(self):
        """Save settings without closing the dialog."""
        settings = self.get_settings()
        if self.parent():
            self.parent()._settings = settings
            self.parent()._save_settings(settings)
            if hasattr(self.parent(), "_timeline"):
                self.parent()._timeline.set_sticky_headers(settings.get("timeline_sticky_headers", True))

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
        self.edit_hf.setText(settings.get("hf_token", ""))
        
        model = settings.get("whisper_model", "medium")
        idx = self.combo_whisper.findText(model)
        if idx >= 0:
            self.combo_whisper.setCurrentIndex(idx)
            
        lang_map = {None: "Auto", "th": "Thai", "ja": "Japanese", "en": "English", "zh": "Chinese"}
        lang_text = lang_map.get(settings.get("whisper_language", "th"), "Thai")
        lang_idx = self.combo_lang.findText(lang_text)
        if lang_idx >= 0:
            self.combo_lang.setCurrentIndex(lang_idx)
            
        sep_mode = settings.get("voice_sep_mode", "original")
        if sep_mode == "original":
            self.rb_sep_orig.setChecked(True)
        elif sep_mode == "isolate":
            self.rb_sep_iso.setChecked(True)
        elif sep_mode == "hq":
            self.rb_sep_hq.setChecked(True)
        else:
            self.rb_sep_orig.setChecked(True)
            
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
        self.spin_max_speakers.setValue(settings.get("max_speakers", DIARIZATION_MAX_SPEAKERS))
        
        bitrate = settings.get("audio_bitrate", "192k")
        br_idx = self.combo_bitrate.findText(bitrate)
        if br_idx >= 0:
            self.combo_bitrate.setCurrentIndex(br_idx)

        self.chk_sticky_headers.setChecked(settings.get("timeline_sticky_headers", True))
        self.chk_preview_proxy.setChecked(settings.get("preview_proxy_enabled", True))
        proxy_h = settings.get("preview_proxy_height", 540)
        if proxy_h == 540:
            self.combo_proxy_res.setCurrentIndex(0)
        elif proxy_h == 720:
            self.combo_proxy_res.setCurrentIndex(1)
        else:
            self.combo_proxy_res.setCurrentIndex(2)

        # Thai Dubbing settings
        self.chk_thai_opt.setChecked(settings.get("thai_dubbing_opt", True))
        self.chk_clean_hallucinations.setChecked(settings.get("clean_hallucinations", True))
        self.chk_format_keywords.setChecked(settings.get("format_keywords", True))
        self.edit_initial_prompt.setText(settings.get("whisper_initial_prompt", WHISPER_INITIAL_PROMPT_THAI))
            
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
            
        return {
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


