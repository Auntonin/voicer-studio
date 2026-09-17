import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from core.models import PipelineState
from config import FILENAME_ALLOWED_CHARS

logger = logging.getLogger(__name__)

@dataclass
class CheckResult:
    level: str  # 'ok', 'warn', 'error'
    message: str
    item_id: Optional[int] = None

class QualityChecker:
    def check_all(self, state: PipelineState, pack_dir: Path) -> List[CheckResult]:
        results = []
        logger.info(f"Running quality checks on {pack_dir}")
        
        # Check overall files
        if not (pack_dir / "_pack_info.ini").exists():
            results.append(CheckResult('error', "Missing _pack_info.ini"))
        else:
            txt = (pack_dir / "_pack_info.ini").read_text(encoding='utf-8')
            if "[data]" not in txt:
                results.append(CheckResult('error', "_pack_info.ini missing [data] section"))
                
        if not (pack_dir / "_backing_track.mp3").exists():
            results.append(CheckResult('warn', "Missing _backing_track.mp3"))
            
        seen_indices = set()
        
        for item in state.active_dialogues():
            speaker_safe_name = state.get_speaker_safe_name(item.speaker_id)
            base_name = item.filename_base(speaker_safe_name)
            
            # Duplicates
            if item.index in seen_indices:
                results.append(CheckResult('error', f"Duplicate dialogue index: {item.index}", item.index))
            seen_indices.add(item.index)
            
            # Valid filename chars
            invalid_chars = [c for c in speaker_safe_name if c not in FILENAME_ALLOWED_CHARS]
            if invalid_chars:
                results.append(CheckResult('error', f"Invalid characters in speaker name: {speaker_safe_name}", item.index))
                
            # Valid timestamp
            if state.video_duration > 0:
                if not (0 <= item.start < item.end <= state.video_duration + 1.0):
                    results.append(CheckResult('error', f"Invalid timestamps: start={item.start}, end={item.end}", item.index))
            else:
                if not (0 <= item.start < item.end):
                    results.append(CheckResult('error', f"Invalid timestamps: start={item.start}, end={item.end}", item.index))
                
            # Caption
            if not item.caption.strip():
                results.append(CheckResult('warn', "Empty caption", item.index))
                
            # Speaker exists
            if item.speaker_id not in state.speakers:
                results.append(CheckResult('error', f"Speaker ID not found: {item.speaker_id}", item.index))
                
            # File existence and names
            audio_f = pack_dir / f"{base_name}.mp3"
            image_f = pack_dir / f"{base_name}.png"
            txt_f = pack_dir / f"{base_name}.txt"
            
            if not audio_f.exists():
                results.append(CheckResult('error', f"Missing audio file: {base_name}.mp3", item.index))
            elif not self._check_audio_readable(audio_f):
                results.append(CheckResult('error', f"Unreadable audio file: {base_name}.mp3", item.index))
                
            if not image_f.exists():
                results.append(CheckResult('error', f"Missing image file: {base_name}.png", item.index))
            elif not self._check_png_readable(image_f):
                results.append(CheckResult('error', f"Unreadable image file: {base_name}.png", item.index))
                
            if not txt_f.exists():
                results.append(CheckResult('error', f"Missing txt file: {base_name}.txt", item.index))
            else:
                txt_content = txt_f.read_text(encoding='utf-8')
                if "[data]" not in txt_content:
                    results.append(CheckResult('error', f"txt missing [data] section: {base_name}.txt", item.index))
                if "caption=" not in txt_content or "dub_timestamps=" not in txt_content:
                    results.append(CheckResult('error', f"txt missing required keys: {base_name}.txt", item.index))

        return results

    def _check_audio_readable(self, path: Path) -> bool:
        return path.exists() and path.stat().st_size > 0

    def _check_png_readable(self, path: Path) -> bool:
        return path.exists() and path.stat().st_size > 0

    def has_errors(self, results: List[CheckResult]) -> bool:
        return any(r.level == 'error' for r in results)

    def summary(self, results: List[CheckResult]) -> str:
        errors = [r for r in results if r.level == 'error']
        warnings = [r for r in results if r.level == 'warn']
        
        out = []
        if errors:
            out.append(f"Errors ({len(errors)}):")
            for e in errors:
                item_str = f" [Item {e.item_id}]" if e.item_id else ""
                out.append(f"  - {e.message}{item_str}")
                
        if warnings:
            out.append(f"Warnings ({len(warnings)}):")
            for w in warnings:
                item_str = f" [Item {w.item_id}]" if w.item_id else ""
                out.append(f"  - {w.message}{item_str}")
                
        if not errors and not warnings:
            out.append("All checks passed successfully.")
            
        return "\n".join(out)
