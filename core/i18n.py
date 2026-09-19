"""
core/i18n.py
============
Centralized Internationalization (i18n) Engine for Voicer Studio.

Features:
- Built-in complete English (en) and Thai (th) language dictionaries.
- Extensible: auto-discovers external JSON language packs in the `locales/` directory.
- Safe fallback: if a translation key is missing in any language, it falls back seamlessly to English.
- Formatting support: format strings with kwargs, e.g. tr("pipe_slicing", completed=5, total=20).
- Industry-standard, professional audio/video studio terminology.
- Accurate distinction between AI models (Whisper, Demucs, BS-RoFormer, Pyannote)
  and DSP/algorithmic processes (Audio slicing, Frame extraction, Proxy video, Pack building).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

log = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
LOCALES_DIR = ROOT_DIR / "locales"

# ── Built-in Language Dictionaries ─────────────────────────────────────────────

STRINGS_EN: Dict[str, str] = {
    # ── Application Metadata & Menus ──
    "app_name": "Voicer Studio",
    "app_tagline": "The Choice Voicer Dialogue Extractor & Vocal Separator",
    "menu_file": "File",
    "menu_new_proj": "New Project",
    "menu_open_proj": "Open Project...",
    "menu_open_pack": "Open Pack Folder...",
    "menu_recent_proj": "Open Recent Project",
    "menu_recent_videos": "Open Recent Video",
    "menu_no_recent": "No Recent Items",
    "menu_no_recent_projects": "No Recent Projects",
    "menu_clear_recent_projects": "Clear Recent Projects",
    "menu_no_recent_videos": "No Recent Videos",
    "menu_clear_recent_videos": "Clear Recent Videos",
    "menu_save_proj": "Save Project",
    "menu_save_proj_as": "Save Project As...",
    "menu_import_video": "Import Video...",
    "menu_export_pack": "Export Pack ZIP...",
    "menu_quit": "Quit",
    
    "menu_edit": "Edit",
    "menu_undo": "Undo",
    "menu_redo": "Redo",
    "menu_shortcuts": "Keyboard Shortcuts...",
    "menu_settings": "Settings...",

    "menu_view": "View",
    "menu_fullscreen": "Full Screen",
    "menu_video_player": "Video Preview Player",
    "menu_sidebar_tabs": "Sidebar Tabs (Dialogues / Speakers / Pack Info)",
    "menu_timeline": "Multi-Track Timeline",
    "menu_clip_editor": "Clip Editor",
    "menu_processing_logs": "Processing Logs",

    "menu_help": "Help",
    "menu_about": "About",

    # ── Main Toolbar ──
    "tb_import": "Import Video",
    "tb_import_tip": "Import a video file (Ctrl+I)",
    "tb_analyze": "Analyze",
    "tb_analyze_tip": "One-Click: Neural vocal isolation, speech transcription, and automated dialogue extraction",
    "tb_export": "Export Pack ZIP",
    "tb_export_tip": "Export The Choice Voicer game dialogue pack (Ctrl+E)",
    "tb_open_folder": "Open Output Folder",
    "tb_open_folder_tip": "Open output folder in Windows Explorer",
    "tb_settings": "Settings",
    "tb_settings_tip": "Application settings and preferences",

    # ── Sidebar Tabs ──
    "tab_dialogues": "Dialogues",
    "tab_speakers": "Speakers",
    "tab_pack_info": "Pack Info",

    # ── Dialogue Table Columns ──
    "col_index": "#",
    "col_time": "Time",
    "col_speaker": "Speaker",
    "col_caption": "Caption",
    "col_status": "Status",

    # ── Timeline & Track Headers ──
    "tl_title": "MULTI-TRACK TIMELINE",
    "tl_add_track": "+ Add Track",
    "tl_btn_add_track": "Add Track",
    "tl_btn_add_track_tip": "Add Character Track (+)",
    "tl_btn_add_clip": "Add Clip",
    "tl_btn_add_clip_tip": "Add Dialogue Clip at Playhead",
    "tl_btn_play": "Play",
    "tl_btn_play_tip": "Play / Pause Timeline (Space)",
    "tl_btn_stop": "Stop",
    "tl_btn_stop_tip": "Stop Playback",
    "tl_btn_zoomin": "Zoom In",
    "tl_btn_zoomin_tip": "Zoom In Timeline (+ / =)",
    "tl_btn_zoomout": "Zoom Out",
    "tl_btn_zoomout_tip": "Zoom Out Timeline (-)",
    "tl_btn_split_tip": "Split at Playhead (S / Ctrl+B)",
    "tl_btn_trim_left_tip": "Delete Left to Playhead (Q)",
    "tl_btn_trim_right_tip": "Delete Right from Playhead (W)",
    "tl_btn_delete_tip": "Delete Selected Clip (Del)",
    "tl_btn_undo_tip": "Undo (Ctrl+Z)",
    "tl_btn_redo_tip": "Redo (Ctrl+Y)",
    "tl_btn_zoom_in_tip": "Zoom In Timeline (+)",
    "tl_btn_zoom_out_tip": "Zoom Out Timeline (-)",
    "tl_sticky_on": "Sticky Tracks: ON (Click to unpin)",
    "tl_sticky_off": "Sticky Tracks: OFF (Click to pin)",
    "tl_dialog_add_track_title": "Add New Speaker Track",
    "tl_dialog_add_track_msg": "Enter character / speaker name:",
    "tl_dialog_rename_track_title": "Rename Speaker Track",
    "tl_dialog_rename_track_msg": "Enter new name for '{name}':",
    "tl_dialog_delete_track_title": "Delete Track",
    "tl_dialog_delete_track_msg": "Delete track '{name}' with {count} clips? This action can be undone with Ctrl+Z.",

    # ── Clip Editor Panel ──
    "ed_frame_title": "VIDEO FRAME",
    "ed_no_frame": "No Video Frame",
    "ed_play_audio": "Play Audio",
    "ed_stop_audio": "Stop",
    "ed_recapture_frame": "Recapture Frame",
    "ed_recapture_frame_tip": "Extract representative keyframe from video for this dialogue segment",

    "ed_timing_title": "CHARACTER & TIMING",
    "ed_speaker_label": "Character:",
    "ed_start_label": "Start (s):",
    "ed_end_label": "End (s):",
    "ed_duration_label": "Duration: {duration}s",

    "ed_caption_title": "DIALOGUE CAPTION",
    "ed_no_selection": "No Selection",
    "ed_clip_badge": "Clip #{index}",
    "ed_caption_stats": "{chars} chars • {words} words",
    "ed_retranscribe": "Re-Transcribe",
    "ed_retranscribe_tip": "Re-transcribe this clip audio using Whisper AI",
    "ed_placeholder_caption": "Enter dialogue caption text...",
    "ed_split_clip": "Split Clip",
    "ed_split_clip_tip": "Split clip at playhead or midpoint",
    "ed_merge_next": "Merge Next",
    "ed_merge_next_tip": "Merge dialogue line with the next clip",
    "ed_delete_clip": "Delete Clip",
    "ed_delete_clip_tip": "Delete this clip (Del)",
    "ed_copy": "Copy",
    "ed_copy_tip": "Copy dialogue caption to clipboard",
    "ed_copied": "Copied!",
    "ed_clear": "Clear",
    "ed_clear_tip": "Clear caption text (Can be undone with Ctrl+Z)",
    "ed_reslice_audio": "Re-slice Audio",
    "ed_reslice_audio_tip": "Re-extract audio slice for this clip from source file",

    # ── Status Bar ──
    "status_ready": "[Ready]",
    "status_unsaved": "[Unsaved Changes*]",
    "status_saved": "[Saved {time}]",
    "status_autosaved": "[Auto-saved {time}*]",
    "status_no_video": "No video loaded",
    "status_file": "File: {name}",
    "status_project_no_video": "Project: {name} (No video file)",
    "status_version": "v{version}  |  The Choice Voicer Dialogue Extractor",

    # ── Settings Dialog ──
    "settings_title": "Settings",
    "tab_general": "General",
    "tab_ai_models": "AI Models",
    "tab_processing": "Processing",
    "tab_dubbing": "Dubbing & Text",
    "tab_output": "Output",

    # Settings: General
    "cfg_lang_title": "Application Interface Language:",
    "cfg_lang_hint": "Display language for menus, buttons, tooltips, dialogs, and progress status.",
    "cfg_timeline_section": "Timeline & Display:",
    "cfg_pin_headers": "Pin Speaker Track Headers (Sticky headers remain visible on left)",
    "cfg_auto_save": "Enable Background Auto-Save",

    # Settings: AI Models
    "cfg_hf_token": "Hugging Face Token:",
    "cfg_hf_test": "Test Token",
    "cfg_max_speakers": "Max Speakers:",
    "cfg_whisper_model": "Whisper Model:",
    "cfg_whisper_lang": "Audio Spoken Language:",
    "cfg_voice_sep": "Neural Voice Separation:",
    "cfg_sep_orig": "Original Audio (No separation)",
    "cfg_sep_iso": "Voice Isolation (Demucs standard)",
    "cfg_sep_hq": "High Quality (Demucs htdemucs_6s)",

    # Settings: Processing
    "cfg_ts_mode": "Timestamp Mode:",
    "cfg_ts_start": "Start Only e.g. [2.049]",
    "cfg_ts_start_end": "Start + End e.g. [2.049, 4.200]",
    "cfg_ts_rel": "Relative to clip e.g. [0.0]",
    "cfg_vad_thresh": "VAD Sensitivity Threshold:",
    "cfg_vad_pad": "VAD Padding:",
    "cfg_vad_gap": "VAD Merge Silence Gap:",
    "cfg_vad_gap_hint": "Lower = shorter sliced sentences | Higher = merges into longer lines",
    "cfg_img_quality": "Frame Image Quality:",
    "cfg_bitrate": "Audio Bitrate:",
    "cfg_preview_proxy": "Generate Fast-Seek Preview Proxy (Lightweight 540p video for smooth scrubbing)",
    "cfg_proxy_res": "Proxy Resolution:",

    # Settings: Dubbing & Text
    "cfg_thai_opt": "Enable Thai Dubbing Optimization (Context Prompting)",
    "cfg_clean_hallucinations": "Auto-clean Repetitive Hallucinations (e.g. repeated Whisper phrases)",
    "cfg_format_keywords": "Contextual Keyword Preservation (Thai / English loanwords)",
    "cfg_whisper_prompt": "Whisper Initial Prompt:",

    # Settings: Output
    "cfg_out_dir": "Output Directory:",
    "cfg_browse": "Browse...",
    "cfg_inc_dub_video": "Include dub_video.mp4 (Lossless source copy)",
    "cfg_pack_authors": "Default Pack Authors:",

    # Settings: Buttons
    "btn_ok": "OK",
    "btn_cancel": "Cancel",
    "btn_apply": "Apply",

    # ── Pipeline & Progress Messages ──
    "pipe_starting": "Starting dialogue extraction pipeline...",
    "pipe_extracting_audio": "Extracting audio stream from video...",
    "pipe_audio_extracted": "Audio stream extracted successfully ({duration:.1f}s)",
    "pipe_loading_whisper": "Loading Whisper speech recognition model...",
    "pipe_whisper_segmenting": "Analyzing and segmenting dialogue with Whisper...",
    "pipe_whisper_seg_done": "Whisper segmented {count} dialogue lines",
    "pipe_whisper_seg_fallback": "Whisper segmentation unavailable, using VAD segments instead",
    "pipe_vad_detecting": "Detecting voice activity (Silero VAD)...",
    "pipe_vad_done": "VAD detected {count} speech segments",
    "pipe_diarization_running": "Identifying characters with Pyannote diarization...",
    "pipe_diarization_done": "Character identification complete ({count} speakers)",
    "pipe_separating_voices": "Separating vocals from background music (BS-RoFormer / Demucs)...",
    "pipe_separation_done": "Voice isolation complete",
    "pipe_slicing_clips": "Slicing audio clips [{current}/{total}] {id}...",
    "pipe_slicing_done": "Audio slicing complete ({count} clips)",
    "pipe_capturing_frames": "Capturing video keyframes [{current}/{total}] {id}...",
    "pipe_frames_done": "Keyframe capture complete ({count} frames)",
    "pipe_encoding_backing": "Encoding backing track (BGM + SFX, {bitrate} MP3)...",
    "pipe_backing_done": "Backing track ready",
    "pipe_building_pack": "Generating pack files [{current}/{total}]...",
    "pipe_encoding_ogv": "Encoding dub_video.ogv (Theora/Vorbis)...",
    "pipe_pack_done": "Dialogue pack generated successfully ({count} files)",
    "pipe_validating": "Validating dialogue pack integrity...",
    "pipe_exporting_zip": "Compressing dialogue pack ZIP archive...",
    "pipe_finished": "Dialogue extraction complete!",

    # ── Toast & Notifications ──
    "toast_extraction_done_title": "Dialogue Extraction Complete",
    "toast_extraction_done_msg": "Pack exported successfully to: {path}",
    "toast_save_proj_title": "Project Saved",
    "toast_save_proj_msg": "Project successfully saved to: {path}",

    # ── Shortcuts Dialog ──
    "sc_dialog_title": "KEYBOARD SHORTCUTS & STUDIO GESTURES",
    "sc_search_placeholder": "Search shortcuts (e.g. split, zoom, play)...",
    "sc_cat_timeline": "TIMELINE NAVIGATION & PLAYBACK",
    "sc_cat_editing": "CLIP EDITING & TRIMMING",
    "sc_cat_tracks": "TRACKS & CHARACTERS",
    "sc_cat_project": "PROJECT & APPLICATION",
}

STRINGS_TH: Dict[str, str] = {
    # ── Application Metadata & Menus ──
    "app_name": "Voicer Studio",
    "app_tagline": "โปรแกรมแยกเสียงบทสนทนาและตัดต่อคำพากย์ The Choice Voicer",
    "menu_file": "ไฟล์",
    "menu_new_proj": "สร้างโปรเจกต์ใหม่",
    "menu_open_proj": "เปิดโปรเจกต์...",
    "menu_open_pack": "เปิดโฟลเดอร์แพ็ก...",
    "menu_recent_proj": "เปิดโปรเจกต์ล่าสุด",
    "menu_recent_videos": "เปิดวิดีโอล่าสุด",
    "menu_no_recent": "ไม่มีรายการล่าสุด",
    "menu_no_recent_projects": "ไม่มีประวัติโปรเจกต์ล่าสุด",
    "menu_clear_recent_projects": "ล้างประวัติโปรเจกต์ล่าสุด",
    "menu_no_recent_videos": "ไม่มีประวัติวิดีโอล่าสุด",
    "menu_clear_recent_videos": "ล้างประวัติวิดีโอล่าสุด",
    "menu_save_proj": "บันทึกโปรเจกต์",
    "menu_save_proj_as": "บันทึกโปรเจกต์เป็น...",
    "menu_import_video": "นำเข้าวิดีโอ...",
    "menu_export_pack": "ส่งออกแพ็ก (ZIP)...",
    "menu_quit": "ออกจากโปรแกรม",
    
    "menu_edit": "แก้ไข",
    "menu_undo": "เลิกทำ",
    "menu_redo": "ทำซ้ำ",
    "menu_shortcuts": "คีย์ลัดและท่าทางสัมผัส...",
    "menu_settings": "การตั้งค่า...",

    "menu_view": "มุมมอง",
    "menu_fullscreen": "แสดงเต็มจอ",
    "menu_video_player": "หน้าจอพรีวิววิดีโอ",
    "menu_sidebar_tabs": "แถบเครื่องมือด้านข้าง (บทสนทนา / ตัวละคร / ข้อมูลแพ็ก)",
    "menu_timeline": "ไทม์ไลน์มัลติแทร็ก",
    "menu_clip_editor": "แผงแก้ไขคลิป",
    "menu_processing_logs": "บันทึกการประมวลผล",

    "menu_help": "ช่วยเหลือ",
    "menu_about": "เกี่ยวกับโปรแกรม",

    # ── Main Toolbar ──
    "tb_import": "นำเข้าวิดีโอ",
    "tb_import_tip": "นำเข้าไฟล์วิดีโอ (Ctrl+I)",
    "tb_analyze": "วิเคราะห์และแยกเสียง",
    "tb_analyze_tip": "คลิกเดียว: แยกเสียงร้องด้วย AI, ถอดคำพูด และสร้างแพ็กบทสนทนาอัตโนมัติ",
    "tb_export": "ส่งออกแพ็ก ZIP",
    "tb_export_tip": "ส่งออกแพ็กบทสนทนาสำหรับ The Choice Voicer (Ctrl+E)",
    "tb_open_folder": "เปิดโฟลเดอร์ผลลัพธ์",
    "tb_open_folder_tip": "เปิดโฟลเดอร์ผลลัพธ์ใน Windows Explorer",
    "tb_settings": "การตั้งค่า",
    "tb_settings_tip": "การตั้งค่าโปรแกรมและโมเดล",

    # ── Sidebar Tabs ──
    "tab_dialogues": "บทสนทนา",
    "tab_speakers": "ตัวละคร",
    "tab_pack_info": "ข้อมูลแพ็ก",

    # ── Dialogue Table Columns ──
    "col_index": "#",
    "col_time": "เวลา",
    "col_speaker": "ตัวละคร",
    "col_caption": "ข้อความบทสนทนา",
    "col_status": "สถานะ",

    # ── Timeline & Track Headers ──
    "tl_title": "ไทม์ไลน์มัลติแทร็ก",
    "tl_add_track": "+ เพิ่มแทร็ก",
    "tl_btn_add_track": "เพิ่มแทร็ก",
    "tl_btn_add_track_tip": "เพิ่มแทร็กตัวละครใหม่ (+)",
    "tl_btn_add_clip": "เพิ่มคลิป",
    "tl_btn_add_clip_tip": "เพิ่มคลิปบทสนทนา ณ ตำแหน่งหัวอ่าน",
    "tl_btn_play": "เล่น",
    "tl_btn_play_tip": "เล่น / หยุด ไทม์ไลน์ชั่วคราว (Space)",
    "tl_btn_stop": "หยุด",
    "tl_btn_stop_tip": "หยุดการเล่น",
    "tl_btn_zoomin": "ขยาย",
    "tl_btn_zoomin_tip": "ขยายมุมมองไทม์ไลน์ (+ / =)",
    "tl_btn_zoomout": "ย่อ",
    "tl_btn_zoomout_tip": "ย่อมุมมองไทม์ไลน์ (-)",
    "tl_btn_split_tip": "ตัดแบ่งที่หัวอ่าน (S / Ctrl+B)",
    "tl_btn_trim_left_tip": "ลบด้านหน้าถึงหัวอ่าน (Q)",
    "tl_btn_trim_right_tip": "ลบด้านหลังจากหัวอ่าน (W)",
    "tl_btn_delete_tip": "ลบคลิปที่เลือก (Del)",
    "tl_btn_undo_tip": "เลิกทำ (Ctrl+Z)",
    "tl_btn_redo_tip": "ทำซ้ำ (Ctrl+Y)",
    "tl_btn_zoom_in_tip": "ขยายไทม์ไลน์ (+)",
    "tl_btn_zoom_out_tip": "ย่อไทม์ไลน์ (-)",
    "tl_sticky_on": "ตรึงรายชื่อตัวละคร: เปิด (คลิกเพื่อปลด)",
    "tl_sticky_off": "ตรึงรายชื่อตัวละคร: ปิด (คลิกเพื่อตรึง)",
    "tl_dialog_add_track_title": "เพิ่มแทร็กตัวละครใหม่",
    "tl_dialog_add_track_msg": "พิมพ์ชื่อตัวละคร / ผู้พูด:",
    "tl_dialog_rename_track_title": "เปลี่ยนชื่อตัวละคร",
    "tl_dialog_rename_track_msg": "พิมพ์ชื่อใหม่สำหรับ '{name}':",
    "tl_dialog_delete_track_title": "ลบแทร็ก",
    "tl_dialog_delete_track_msg": "ต้องการลบแทร็ก '{name}' ซึ่งมี {count} คลิปใช่หรือไม่? (สามารถเลิกทำด้วย Ctrl+Z ได้)",

    # ── Clip Editor Panel ──
    "ed_frame_title": "ภาพนิ่งวิดีโอ",
    "ed_no_frame": "ไม่มีภาพวิดีโอ",
    "ed_play_audio": "ฟังเสียงคลิป",
    "ed_stop_audio": "หยุด",
    "ed_recapture_frame": "แคปภาพใหม่",
    "ed_recapture_frame_tip": "สกัดภาพนิ่งจากวิดีโอในช่วงเวลาของบทพูดนี้ใหม่",

    "ed_timing_title": "ตัวละครและเวลา",
    "ed_speaker_label": "ตัวละคร:",
    "ed_start_label": "เริ่ม (วินาที):",
    "ed_end_label": "สิ้นสุด (วินาที):",
    "ed_duration_label": "ความยาว: {duration} วินาที",

    "ed_caption_title": "ข้อความบทสนทนา",
    "ed_no_selection": "ยังไม่ได้เลือกคลิป",
    "ed_clip_badge": "คลิป #{index}",
    "ed_caption_stats": "{chars} ตัวอักษร • {words} คำ",
    "ed_retranscribe": "ถอดเสียงใหม่",
    "ed_retranscribe_tip": "ถอดเสียงเฉพาะคลิปนี้ใหม่ด้วย Whisper AI",
    "ed_placeholder_caption": "พิมพ์ข้อความบทสนทนา...",
    "ed_split_clip": "ตัดแบ่งคลิป",
    "ed_split_clip_tip": "ตัดแบ่งคลิป ณ ตำแหน่งหัวอ่านหรือกึ่งกลางคลิป",
    "ed_merge_next": "รวมคลิปถัดไป",
    "ed_merge_next_tip": "รวมข้อความและเสียงกับคลิปถัดไป",
    "ed_delete_clip": "ลบคลิป",
    "ed_delete_clip_tip": "ลบคลิปนี้ออกจากโปรเจกต์ (Del)",
    "ed_copy": "คัดลอก",
    "ed_copy_tip": "คัดลอกข้อความบทสนทนาลงคลิปบอร์ด",
    "ed_copied": "คัดลอกแล้ว!",
    "ed_clear": "ล้างข้อความ",
    "ed_clear_tip": "ล้างข้อความทั้งหมด (กด Ctrl+Z เพื่อกู้คืนได้)",
    "ed_reslice_audio": "ตัดเสียงใหม่",
    "ed_reslice_audio_tip": "สั่งตัดซอยไฟล์เสียงของคลิปนี้ใหม่จากไฟล์เสียงต้นฉบับ",

    # ── Status Bar ──
    "status_ready": "[พร้อมทำงาน]",
    "status_unsaved": "[ยังไม่ได้บันทึก*]",
    "status_saved": "[บันทึกเรียบร้อย {time}]",
    "status_autosaved": "[บันทึกอัตโนมัติ {time}*]",
    "status_no_video": "ยังไม่ได้เปิดไฟล์วิดีโอ",
    "status_file": "ไฟล์: {name}",
    "status_project_no_video": "โปรเจกต์: {name} (ไม่มีไฟล์วิดีโอ)",
    "status_version": "v{version}  |  The Choice Voicer Dialogue Extractor",

    # ── Settings Dialog ──
    "settings_title": "การตั้งค่า",
    "tab_general": "ทั่วไป",
    "tab_ai_models": "โมเดล AI",
    "tab_processing": "การประมวลผล",
    "tab_dubbing": "การถอดความและบทพากย์",
    "tab_output": "การส่งออก",

    # Settings: General
    "cfg_lang_title": "ภาษาของส่วนติดต่อผู้ใช้ (Interface Language):",
    "cfg_lang_hint": "กำหนดภาษาสำหรับเมนู, ปุ่มกด, คำแนะนำเครื่องมือ, และข้อความสถานะการทำงาน",
    "cfg_timeline_section": "ไทม์ไลน์และการแสดงผล:",
    "cfg_pin_headers": "ตรึงแถบรายชื่อตัวละคร (แสดงคอลัมน์ชื่อตัวละครติดขอบซ้ายเสมอ)",
    "cfg_auto_save": "เปิดระบบบันทึกงานอัตโนมัติในเบื้องหลัง",

    # Settings: AI Models
    "cfg_hf_token": "Hugging Face Token:",
    "cfg_hf_test": "ทดสอบโทเค็น",
    "cfg_max_speakers": "จำนวนตัวละครสูงสุด:",
    "cfg_whisper_model": "โมเดลถอดเสียง Whisper:",
    "cfg_whisper_lang": "ภาษาเสียงพูดต้นฉบับ:",
    "cfg_voice_sep": "การแยกเสียงร้องด้วย AI:",
    "cfg_sep_orig": "เสียงต้นฉบับ (ไม่แยกเสียงร้อง)",
    "cfg_sep_iso": "แยกเฉพาะเสียงพูด (Demucs มาตรฐาน)",
    "cfg_sep_hq": "คุณภาพสูงพิเศษ (Demucs 6 สเต็ม)",

    # Settings: Processing
    "cfg_ts_mode": "รูปแบบ Timestamp ในไฟล์:",
    "cfg_ts_start": "เฉพาะเวลาเริ่ม เช่น [2.049]",
    "cfg_ts_start_end": "เริ่ม + สิ้นสุด เช่น [2.049, 4.200]",
    "cfg_ts_rel": "นับจากเริ่มคลิป เช่น [0.0]",
    "cfg_vad_thresh": "ระดับความไวในการตรวจจับเสียงพูด (VAD):",
    "cfg_vad_pad": "ระยะเว้นหัวท้ายเสียงพูด (Padding):",
    "cfg_vad_gap": "ช่วงเงียบสูงสุดที่จะรวมเป็นประโยคเดียวกัน:",
    "cfg_vad_gap_hint": "ค่าน้อย = ซอยประโยคสั้น | ค่ามาก = รวมเป็นประโยคยาว",
    "cfg_img_quality": "คุณภาพไฟล์ภาพแคปเจอร์:",
    "cfg_bitrate": "บิตเรตไฟล์เสียง MP3:",
    "cfg_preview_proxy": "สร้างวิดีโอพรีวิว Fast-Seek Proxy (ย่อขนาด 540p เพื่อให้เลื่อนดูไทม์ไลน์ได้ลื่นไหล)",
    "cfg_proxy_res": "ความละเอียดวิดีโอพรีวิว:",

    # Settings: Dubbing & Text
    "cfg_thai_opt": "เปิดระบบปรับแต่งบริบทบทพากย์ไทย (Context Prompting)",
    "cfg_clean_hallucinations": "กรองคำที่ถอดเสียงซ้ำผิดพลาดโดยอัตโนมัติ",
    "cfg_format_keywords": "รักษาคำทับศัพท์ภาษาอังกฤษและชื่อเฉพาะ",
    "cfg_whisper_prompt": "Prompt ตั้งต้นสำหรับ Whisper:",

    # Settings: Output
    "cfg_out_dir": "โฟลเดอร์ปลายทางสำหรับส่งออก:",
    "cfg_browse": "เลือก...",
    "cfg_inc_dub_video": "แนบไฟล์วิดีโอ dub_video.mp4 ไปด้วย",
    "cfg_pack_authors": "ผู้จัดทำแพ็กเริ่มต้น:",

    # Settings: Buttons
    "btn_ok": "ตกลง",
    "btn_cancel": "ยกเลิก",
    "btn_apply": "นำไปใช้",

    # ── Pipeline & Progress Messages ──
    "pipe_starting": "กำลังเริ่มต้นกระบวนการแยกบทสนทนา...",
    "pipe_extracting_audio": "กำลังสกัดแทร็กเสียงจากวิดีโอ...",
    "pipe_audio_extracted": "สกัดแทร็กเสียงเรียบร้อยแล้ว ({duration:.1f} วินาที)",
    "pipe_loading_whisper": "กำลังโหลดโมเดลถอดเสียง Whisper...",
    "pipe_whisper_segmenting": "กำลังวิเคราะห์และตัดแบ่งประโยคด้วย Whisper...",
    "pipe_whisper_seg_done": "Whisper แบ่งช่วงบทสนทนาได้ {count} ประโยค",
    "pipe_whisper_seg_fallback": "ไม่สามารถแบ่งประโยคด้วย Whisper ได้ — สลับไปใช้ช่วงเวลาจาก VAD",
    "pipe_vad_detecting": "กำลังตรวจจับช่วงเวลาเสียงพูด (Silero VAD)...",
    "pipe_vad_done": "ตรวจพบช่วงเสียงพูด {count} ช่วง",
    "pipe_diarization_running": "กำลังระบุตัวละครผู้พูดด้วย AI (Pyannote)...",
    "pipe_diarization_done": "ระบุตัวละครเสร็จสิ้น ({count} ตัวละคร)",
    "pipe_separating_voices": "กำลังแยกเสียงร้องออกจากดนตรีประกอบด้วย AI (BS-RoFormer / Demucs)...",
    "pipe_separation_done": "แยกเสียงร้องและดนตรีประกอบเสร็จสมบูรณ์",
    "pipe_slicing_clips": "กำลังตัดซอยคลิปเสียง [{current}/{total}] {id}...",
    "pipe_slicing_done": "ตัดซอยคลิปเสียงเสร็จสิ้น ({count} คลิป)",
    "pipe_capturing_frames": "กำลังสกัดภาพนิ่งจากวิดีโอ [{current}/{total}] {id}...",
    "pipe_frames_done": "สกัดภาพนิ่งเสร็จสิ้น ({count} ภาพ)",
    "pipe_encoding_backing": "กำลังเข้ารหัสแทร็กดนตรีประกอบ ({bitrate} MP3)...",
    "pipe_backing_done": "แทร็กดนตรีประกอบ Backing Track พร้อมแล้ว",
    "pipe_building_pack": "กำลังสร้างไฟล์แพ็กบทสนทนา [{current}/{total}]...",
    "pipe_encoding_ogv": "กำลังสร้างวิดีโอสำหรับเกม dub_video.ogv...",
    "pipe_pack_done": "สร้างแพ็กบทสนทนาเสร็จสมบูรณ์ ({count} ไฟล์)",
    "pipe_validating": "กำลังตรวจสอบความถูกต้องของไฟล์แพ็ก...",
    "pipe_exporting_zip": "กำลังบีบอัดไฟล์แพ็ก ZIP...",
    "pipe_finished": "การแยกบทสนทนาเสร็จสมบูรณ์ทุกขั้นตอน!",

    # ── Toast & Notifications ──
    "toast_extraction_done_title": "แยกบทสนทนาเสร็จสมบูรณ์",
    "toast_extraction_done_msg": "ส่งออกแพ็กเรียบร้อยแล้วที่: {path}",
    "toast_save_proj_title": "บันทึกโปรเจกต์สำเร็จ",
    "toast_save_proj_msg": "บันทึกโปรเจกต์ลงไฟล์: {path}",

    # ── Shortcuts Dialog ──
    "sc_dialog_title": "คีย์ลัดและท่าทางสัมผัสการทำงาน (KEYBOARD SHORTCUTS)",
    "sc_search_placeholder": "ค้นหาคีย์ลัด (เช่น ตัด, ซูม, เล่น, บันทึก)...",
    "sc_cat_timeline": "การเลื่อนมุมมองและเล่นไทม์ไลน์",
    "sc_cat_editing": "การตัดต่อและแก้ไขคลิป",
    "sc_cat_tracks": "แทร็กและตัวละคร",
    "sc_cat_project": "โปรเจกต์และแอปพลิเคชัน",
}


# ── Internationalization Manager Class ─────────────────────────────────────────

class I18nManager:
    """
    Manages active application locale, translation resolution, and locale file loading.
    """

    def __init__(self, default_lang: str = "en", locales_dir: Optional[Path] = None):
        self._current_lang: str = default_lang
        self._locales_dir: Path = locales_dir or LOCALES_DIR
        self._languages: Dict[str, str] = {
            "en": "English",
            "th": "ไทย (Thai)",
        }
        self._dicts: Dict[str, Dict[str, str]] = {
            "en": dict(STRINGS_EN),
            "th": dict(STRINGS_TH),
        }
        self._load_external_locales()

    @property
    def current_language(self) -> str:
        """Active language code, e.g. 'en' or 'th'."""
        return self._current_lang

    @property
    def locales_dir(self) -> Path:
        return self._locales_dir

    @locales_dir.setter
    def locales_dir(self, new_dir: Path):
        self._locales_dir = Path(new_dir)

    def _load_external_locales(self):
        """Scans _locales_dir for any .json files and registers them."""
        self.load_from_directory(self._locales_dir)

    def load_from_directory(self, dir_path: Path):
        """Scans a specified directory for .json locale files and registers them."""
        path = Path(dir_path)
        if not path.exists():
            return
        for json_file in path.glob("*.json"):
            code = json_file.stem.lower()
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    # Check for optional display name metadata
                    meta_name = data.get("_meta", {}).get("name") if isinstance(data.get("_meta"), dict) else None
                    if not meta_name:
                        meta_name = code.upper()
                    self._languages[code] = meta_name
                    if code not in self._dicts:
                        self._dicts[code] = {}
                    self._dicts[code].update({k: str(v) for k, v in data.items() if k != "_meta"})
            except Exception as e:
                log.warning(f"Could not load locale pack '{json_file.name}': {e}")

    def reload_locales(self):
        """Reload all locale packs from disk."""
        self._load_external_locales()

    def get_available_languages(self) -> Dict[str, str]:
        """Returns dict of code -> display name, e.g. {'en': 'English', 'th': 'ไทย (Thai)'}."""
        return dict(self._languages)

    def set_language(self, lang_code: str):
        """Sets active UI language."""
        if lang_code in self._dicts:
            self._current_lang = lang_code
        else:
            log.warning(f"Requested language '{lang_code}' not found, falling back to 'en'.")
            self._current_lang = "en"

    def get_language(self) -> str:
        """Returns active language code."""
        return self._current_lang

    def t(self, key: str, default: Optional[str] = None, **kwargs) -> str:
        """
        Translates `key` into the current language, falling back to English if missing.
        Optionally formats with kwargs.
        """
        # 1. Try active language
        active_dict = self._dicts.get(self._current_lang, {})
        text = active_dict.get(key)

        # 2. Fallback to English
        if text is None:
            text = self._dicts.get("en", {}).get(key)

        # 3. Fallback to default or key
        if text is None:
            text = default if default is not None else key

        # 4. Format kwargs if present
        if kwargs:
            try:
                text = text.format(**kwargs)
            except Exception:
                pass

        return text

    # Convenience alias
    tr = t


# Global singleton instance
i18n = I18nManager(default_lang="en")


def tr(key: str, default: Optional[str] = None, **kwargs) -> str:
    """Convenience helper function for translation."""
    return i18n.t(key, default=default, **kwargs)
