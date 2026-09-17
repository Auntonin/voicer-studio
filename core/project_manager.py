"""
core/project_manager.py
=======================
Manages project persistence (.voicer), importing exported pack folders,
and safe atomic background auto-saving.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Tuple

from config import TEMP_DIR
from core.models import PipelineState, PipelineStep, DialogueItem, SpeakerInfo, PackInfo
from core.audio_extractor import AudioExtractor

logger = logging.getLogger(__name__)

PROJECT_FILE_EXTENSION = ".voicer"
AUTOSAVE_DIR = TEMP_DIR / "autosave"



class ProjectManager:
    """Handles project save/load, pack folder import, and auto-save operations."""

    @staticmethod
    def save_project(state: PipelineState, path: Path) -> bool:
        """
        Save the current pipeline state into a .voicer project file atomically.
        Paths are stored relative to the project directory for portability.
        """
        try:
            path = Path(path).resolve()
            if not path.suffix:
                path = path.with_suffix(PROJECT_FILE_EXTENSION)

            path.parent.mkdir(parents=True, exist_ok=True)

            data = state.to_dict(base_dir=path.parent)

            # Atomic write via temporary file
            temp_path = path.with_suffix(f"{path.suffix}.tmp_{os.getpid()}")
            temp_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            # Atomic replacement
            os.replace(temp_path, path)

            logger.info(f"Project successfully saved to {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save project to {path}: {e}", exc_info=True)
            return False

    @staticmethod
    def load_project(path: Path) -> PipelineState:
        """
        Load a .voicer (or .json) project file into a PipelineState instance.
        Resolves relative paths against the project folder.
        """
        path = Path(path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Project file not found: {path}")

        try:
            raw_text = path.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        except Exception as e:
            raise ValueError(f"Invalid project file format ({path.name}): {e}")

        state = PipelineState.from_dict(data, base_dir=path.parent)

        # Post-load sanity check
        if not state.speakers:
            state.speakers["SPEAKER_00"] = SpeakerInfo(speaker_id="SPEAKER_00", display_name="Speaker 1")
            state.speaker_order = ["SPEAKER_00"]

        if not state.speaker_order:
            state.speaker_order = list(state.speakers.keys())

        # If video exists and duration is 0, probe it
        if state.video_path and state.video_path.exists() and state.video_duration <= 0.0:
            try:
                probe = AudioExtractor().probe_video(state.video_path)
                state.video_duration = probe.get("duration", 0.0)
                state.video_width = probe.get("width", 0)
                state.video_height = probe.get("height", 0)
                state.video_fps = probe.get("fps", 0.0)
                state.video_audio_tracks = probe.get("audio_tracks", 0)
            except Exception as e:
                logger.warning(f"Could not probe video duration after project load: {e}")

        logger.info(f"Project loaded from {path} with {len(state.dialogues)} dialogues.")
        return state

    @classmethod
    def load_from_pack_folder(cls, pack_dir: Path) -> PipelineState:
        """
        Reconstruct a complete PipelineState from an existing exported pack folder.
        Parses _pack_info.ini, individual 001_*.txt cue cards, and pairs
        companion .mp3 audio clips, .png frames, and dub_video.mp4.
        """
        pack_dir = Path(pack_dir).resolve()
        if not pack_dir.is_dir():
            raise NotADirectoryError(f"Directory not found: {pack_dir}")

        state = PipelineState()

        # 1. Parse _pack_info.ini if present
        ini_file = pack_dir / "_pack_info.ini"
        if ini_file.exists():
            cls._parse_pack_info_ini(ini_file, state.pack_info)
        else:
            state.pack_info.title = pack_dir.name.replace("_", " ")

        # 2. Discover companion video file in pack folder or parent
        video_candidates = [
            pack_dir / "dub_video.mp4",
            pack_dir / "dub_video.ogv",
        ]
        # Also check any other video in pack directory
        for ext in (".mp4", ".mkv", ".mov", ".webm", ".avi"):
            video_candidates.extend(pack_dir.glob(f"*{ext}"))

        for cand in video_candidates:
            if cand.exists() and cand.is_file():
                state.video_path = cand
                try:
                    probe = AudioExtractor().probe_video(cand)
                    state.video_duration = probe.get("duration", 0.0)
                    state.video_width = probe.get("width", 0)
                    state.video_height = probe.get("height", 0)
                    state.video_fps = probe.get("fps", 0.0)
                    state.video_audio_tracks = probe.get("audio_tracks", 0)
                except Exception:
                    pass
                break

        # 3. Discover backing track
        bg_track = pack_dir / "_backing_track.mp3"
        if bg_track.exists():
            state.pack_backing_track_path = bg_track

        # 4. Scan and parse all dialogue cue text files (e.g. 001_Character.txt)
        txt_files = [
            f for f in pack_dir.glob("*.txt")
            if not f.name.startswith("_") and f.name != "_pack_info.ini"
        ]

        def _sort_key(p: Path) -> Tuple[int, str]:
            m = re.match(r"^(\d+)", p.stem)
            idx = int(m.group(1)) if m else 999999
            return (idx, p.stem)

        txt_files.sort(key=_sort_key)

        display_name_to_spk_id: Dict[str, str] = {}
        spk_counter = 0

        for txt_path in txt_files:
            try:
                content = txt_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"Could not read cue file {txt_path}: {e}")
                continue

            # Parse metadata lines from cue card
            caption = ""
            m_cap = re.search(r'caption="(.*?)"(?:\r?\n|$)', content, re.DOTALL)
            if m_cap:
                caption = m_cap.group(1).replace('\\"', '"')

            image_name = ""
            m_img = re.search(r'image="(.*?)"', content)
            if m_img:
                image_name = m_img.group(1)

            timestamps: List[float] = []
            m_ts = re.search(r'dub_timestamps=\[([\d.,\s\-]+)\]', content)
            if m_ts:
                try:
                    timestamps = [float(x.strip()) for x in m_ts.group(1).split(",") if x.strip()]
                except Exception:
                    timestamps = []

            char_names: List[str] = []
            m_chars = re.search(r'dub_characters=\[(.*?)\]', content)
            if m_chars:
                raw_chars = m_chars.group(1)
                char_names = [
                    c.strip().strip('"').strip("'")
                    for c in raw_chars.split(",")
                    if c.strip().strip('"').strip("'")
                ]

            # Determine speaker name
            speaker_name = "Speaker"
            if char_names:
                speaker_name = char_names[0]
            else:
                # Fallback: extract from filename (e.g. 001_Weazemon -> Weazemon)
                parts = txt_path.stem.split("_", 1)
                if len(parts) > 1 and parts[1]:
                    speaker_name = parts[1].replace("_", " ")

            if speaker_name not in display_name_to_spk_id:
                spk_id = f"SPEAKER_{spk_counter:02d}"
                spk_counter += 1
                display_name_to_spk_id[speaker_name] = spk_id
                state.speakers[spk_id] = SpeakerInfo(speaker_id=spk_id, display_name=speaker_name)
                state.speaker_order.append(spk_id)

            spk_id = display_name_to_spk_id[speaker_name]

            # Determine index
            m_idx = re.match(r"^(\d+)", txt_path.stem)
            item_index = int(m_idx.group(1)) if m_idx else (len(state.dialogues) + 1)

            # Companion audio file (.mp3 or .wav)
            audio_path = pack_dir / f"{txt_path.stem}.mp3"
            if not audio_path.exists():
                for alt_ext in (".wav", ".ogg", ".m4a"):
                    alt_p = pack_dir / f"{txt_path.stem}{alt_ext}"
                    if alt_p.exists():
                        audio_path = alt_p
                        break

            # Companion image file
            image_path = None
            if image_name:
                cand_img = pack_dir / image_name
                if cand_img.exists():
                    image_path = cand_img
            if not image_path:
                for alt_ext in (".png", ".jpg", ".jpeg", ".webp"):
                    cand_img = pack_dir / f"{txt_path.stem}{alt_ext}"
                    if cand_img.exists():
                        image_path = cand_img
                        break

            # Calculate timing
            start = timestamps[0] if len(timestamps) > 0 else 0.0
            end = timestamps[1] if len(timestamps) > 1 else 0.0

            if end <= start:
                # Measure audio duration from companion audio clip
                audio_dur = cls._get_audio_file_duration(audio_path) if audio_path.exists() else 2.5
                end = start + audio_dur

            item = DialogueItem(
                index=item_index,
                speaker_id=spk_id,
                start=start,
                end=end,
                caption=caption,
                audio_path=audio_path if (audio_path and audio_path.exists()) else None,
                image_path=image_path if (image_path and image_path.exists()) else None,
                txt_path=txt_path,
                caption_confirmed=bool(caption),
                image_confirmed=bool(image_path),
                audio_confirmed=bool(audio_path and audio_path.exists()),
            )

            if len(char_names) > 1:
                item.extra_speakers = char_names[1:]

            state.dialogues.append(item)

        # Fallback default speaker if none found
        if not state.speakers:
            state.speakers["SPEAKER_00"] = SpeakerInfo(speaker_id="SPEAKER_00", display_name="Speaker 1")
            state.speaker_order = ["SPEAKER_00"]

        state.renumber()

        # Update duration if not yet set
        if state.video_duration <= 0.0 and state.dialogues:
            state.video_duration = max(d.end for d in state.dialogues) + 2.0

        # Mark pipeline completion status
        state.step_completed[PipelineStep.AUDIO_EXTRACT] = True
        state.step_completed[PipelineStep.VAD] = True
        state.step_completed[PipelineStep.TRANSCRIPTION] = True
        state.step_completed[PipelineStep.DIARIZATION] = True
        state.step_completed[PipelineStep.PACK_BUILD] = True
        state.current_step = PipelineStep.DONE

        logger.info(f"Loaded {len(state.dialogues)} items from pack folder {pack_dir.name}")
        return state

    @staticmethod
    def _parse_pack_info_ini(ini_path: Path, pack_info: PackInfo):
        """Parse _pack_info.ini file content into PackInfo dataclass."""
        try:
            text = ini_path.read_text(encoding="utf-8")
            m_title = re.search(r'title="(.*?)"', text)
            if m_title:
                pack_info.title = m_title.group(1)

            m_icon = re.search(r'icon="(.*?)"', text)
            if m_icon:
                pack_info.icon = m_icon.group(1)

            m_authors = re.search(r'authors=\[(.*?)\]', text)
            if m_authors:
                raw = m_authors.group(1)
                authors = [
                    a.strip().strip('"').strip("'")
                    for a in raw.split(",")
                    if a.strip().strip('"').strip("'")
                ]
                if authors:
                    pack_info.authors = authors
        except Exception as e:
            logger.warning(f"Failed to parse _pack_info.ini: {e}")

    @staticmethod
    def _get_audio_file_duration(path: Path) -> float:
        """Quickly inspect audio file length in seconds."""
        if not path or not path.exists():
            return 2.5
        try:
            probe = AudioExtractor().probe_video(path)
            dur = probe.get("duration", 0.0)
            if dur > 0.0:
                return dur
        except Exception:
            pass
        return 2.5

    @staticmethod
    def clean_stem(stem: str) -> str:
        """Strip any repeating '.autosave' or '.recovery' suffix and leading dots to prevent cascading names."""
        s = stem
        while True:
            new_s = re.sub(r'\.(autosave|recovery)$', '', s, flags=re.IGNORECASE)
            if new_s == s:
                break
            s = new_s
        s = s.lstrip('.')
        return s or "untitled"

    @classmethod
    def auto_save(
        cls,
        state: PipelineState,
        current_project_path: Optional[Path] = None,
        fallback_dir: Optional[Path] = None
    ) -> Optional[Path]:
        """
        Background safe auto-save.
        - If current_project_path is known, writes <clean_stem>.autosave.voicer next to it.
        - If only video or unsaved project, writes to isolated TEMP_DIR / 'autosave' to keep user folders clean.
        - Strips any existing '.autosave' to eliminate '.autosave.autosave' cascading.
        """
        if not state:
            return None

        target_path: Optional[Path] = None

        if current_project_path:
            p = Path(current_project_path)
            clean = cls.clean_stem(p.stem)
            target_path = p.with_name(f"{clean}.autosave{p.suffix or PROJECT_FILE_EXTENSION}")
        else:
            # When no project file is explicitly saved, isolate autosaves in TEMP_DIR / "autosave"
            # Never clutter user folders (Downloads, Videos, Desktop) with hidden files
            AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
            if state.video_path:
                clean = cls.clean_stem(Path(state.video_path).stem)
            elif state.pack_info and state.pack_info.title and state.pack_info.title != "Untitled Pack":
                clean = cls.clean_stem(state.pack_info.title)
            else:
                clean = "untitled"
            target_path = AUTOSAVE_DIR / f"{clean}.autosave{PROJECT_FILE_EXTENSION}"

        if not target_path:
            return None

        success = cls.save_project(state, target_path)
        return target_path if success else None

    @classmethod
    def delete_autosave(cls, project_or_video_path: Optional[Path]) -> None:
        """Remove autosave recovery files upon clean project save or discard."""
        if not project_or_video_path:
            cand = AUTOSAVE_DIR / f"untitled.autosave{PROJECT_FILE_EXTENSION}"
            if cand.exists():
                try:
                    cand.unlink()
                except Exception:
                    pass
            return

        p = Path(project_or_video_path)
        clean = cls.clean_stem(p.stem)
        candidates = [
            p.with_name(f"{clean}.autosave{p.suffix or PROJECT_FILE_EXTENSION}"),
            p.parent / f".{clean}.autosave{PROJECT_FILE_EXTENSION}",
            AUTOSAVE_DIR / f"{clean}.autosave{PROJECT_FILE_EXTENSION}",
        ]
        for cand in candidates:
            if cand.exists() and cand.is_file():
                try:
                    cand.unlink()
                    logger.debug(f"Removed autosave recovery file: {cand}")
                except Exception as e:
                    logger.warning(f"Could not delete autosave {cand}: {e}")

    @classmethod
    def find_autosave(cls, project_or_video_path: Path) -> Optional[Path]:
        """Check if an autosave recovery file exists and is valid."""
        p = Path(project_or_video_path)
        clean = cls.clean_stem(p.stem)
        candidates = [
            p.with_name(f"{clean}.autosave{p.suffix or PROJECT_FILE_EXTENSION}"),
            AUTOSAVE_DIR / f"{clean}.autosave{PROJECT_FILE_EXTENSION}",
            p.parent / f".{clean}.autosave{PROJECT_FILE_EXTENSION}",
        ]
        for cand in candidates:
            if cand.exists() and cand.is_file() and cand.stat().st_size > 0:
                return cand
        return None
