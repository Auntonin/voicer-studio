"""
core/models.py
==============
Data models shared across the entire pipeline.

All pipeline steps read from and write to these dataclasses.
The GUI observes these models via Qt signals.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import List, Optional, Dict

from config import FILENAME_ALLOWED_CHARS


# ── Speaker ────────────────────────────────────────────────────────────────────

@dataclass
class SpeakerInfo:
    """
    Represents one identified speaker in the video.

    speaker_id  : internal AI label, e.g. "SPEAKER_00"
    display_name: user-assigned name, e.g. "Weazemon"
    """
    speaker_id: str                  # e.g. "SPEAKER_00"
    display_name: str = ""           # e.g. "Weazemon"

    def __post_init__(self):
        if not self.display_name:
            # Default display name from id: SPEAKER_00 → Speaker_1
            idx = self._extract_index()
            self.display_name = f"Speaker_{idx + 1}"

    def _extract_index(self) -> int:
        m = re.search(r"\d+", self.speaker_id)
        if m:
            return int(m.group())
        if "UNKNOWN" in self.speaker_id.upper() or "UNASSIGNED" in self.speaker_id.upper():
            return 99
        return 0

    @property
    def safe_name(self) -> str:
        """Sanitized name safe for Windows filenames."""
        name = self.display_name.strip()
        # Replace spaces with underscores
        name = name.replace(" ", "_")
        # Keep only allowed chars
        name = "".join(c for c in name if c in FILENAME_ALLOWED_CHARS)
        return name or f"Speaker_{self._extract_index() + 1}"

    def to_dict(self) -> dict:
        return {
            "speaker_id": self.speaker_id,
            "display_name": self.display_name,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SpeakerInfo:
        return cls(
            speaker_id=str(data.get("speaker_id", "SPEAKER_00")),
            display_name=str(data.get("display_name", ""))
        )


# ── Dialogue Item ──────────────────────────────────────────────────────────────

@dataclass
class DialogueItem:
    """
    Represents one dialogue segment.

    This is the primary data unit that flows through the pipeline.
    Each step fills in more fields.
    """
    # ── Identity ────────────────────────────────────────────────────────────
    index: int                           # 1-based sequential number (001, 002, …)
    speaker_id: str                      # e.g. "SPEAKER_00"

    # ── Timing (seconds, float) ─────────────────────────────────────────────
    start: float                         # Absolute timestamp in source video
    end: float                           # Absolute timestamp in source video

    # ── Content ─────────────────────────────────────────────────────────────
    caption: str = ""                    # Transcribed text (may be empty)
    caption_language: Optional[str] = None  # ISO 639-1: "th", "ja", "en"

    # ── File Paths (set after generation) ──────────────────────────────────
    audio_path: Optional[Path] = None    # .mp3 clip
    image_path: Optional[Path] = None    # .png frame
    txt_path:   Optional[Path] = None    # .txt metadata

    # ── Flags ───────────────────────────────────────────────────────────────
    caption_confirmed: bool = False      # User manually confirmed caption
    image_confirmed:   bool = False      # User manually selected image
    audio_confirmed:   bool = False      # User manually regenerated audio
    is_deleted:        bool = False      # Soft-delete

    # ── Raw video frame index (for image selection) ─────────────────────────
    selected_frame_idx: Optional[int] = None

    # ── Additional speakers (multi-speaker dialogue) ─────────────────────────
    extra_speakers: List[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def id_str(self) -> str:
        """Zero-padded 3-digit index string: '001', '002', …"""
        return f"{self.index:03d}"

    def filename_base(self, speaker_safe_name: str) -> str:
        """
        Returns the base filename (no extension).

        e.g. "001_Weazemon"
        """
        return f"{self.id_str}_{speaker_safe_name}"

    @property
    def all_speakers(self) -> List[str]:
        """All speaker IDs for this segment, primary first."""
        return [self.speaker_id] + self.extra_speakers

    def format_start(self) -> str:
        """Human-readable start time: '00:08.118'"""
        return _format_ts(self.start)

    def format_end(self) -> str:
        """Human-readable end time: '00:10.520'"""
        return _format_ts(self.end)

    def to_dict(self, base_dir: Optional[Path] = None) -> dict:
        def _rel_or_abs(p: Optional[Path]) -> Optional[str]:
            if not p:
                return None
            if base_dir:
                try:
                    return str(p.relative_to(base_dir).as_posix())
                except ValueError:
                    pass
            return str(p.as_posix()) if hasattr(p, 'as_posix') else str(p)

        return {
            "index": self.index,
            "speaker_id": self.speaker_id,
            "start": round(self.start, 4),
            "end": round(self.end, 4),
            "caption": self.caption,
            "caption_language": self.caption_language,
            "audio_path": _rel_or_abs(self.audio_path),
            "image_path": _rel_or_abs(self.image_path),
            "txt_path": _rel_or_abs(self.txt_path),
            "caption_confirmed": self.caption_confirmed,
            "image_confirmed": self.image_confirmed,
            "audio_confirmed": self.audio_confirmed,
            "is_deleted": self.is_deleted,
            "selected_frame_idx": self.selected_frame_idx,
            "extra_speakers": list(self.extra_speakers),
        }

    @classmethod
    def from_dict(cls, data: dict, base_dir: Optional[Path] = None) -> DialogueItem:
        def _resolve_path(p_str: Optional[str]) -> Optional[Path]:
            if not p_str:
                return None
            p = Path(p_str)
            if p.is_absolute() and p.exists():
                return p
            if base_dir:
                candidate = (base_dir / p).resolve()
                if candidate.exists():
                    return candidate
            return p

        return cls(
            index=int(data.get("index", 1)),
            speaker_id=str(data.get("speaker_id", "SPEAKER_00")),
            start=float(data.get("start", 0.0)),
            end=float(data.get("end", 0.0)),
            caption=str(data.get("caption", "")),
            caption_language=data.get("caption_language"),
            audio_path=_resolve_path(data.get("audio_path")),
            image_path=_resolve_path(data.get("image_path")),
            txt_path=_resolve_path(data.get("txt_path")),
            caption_confirmed=bool(data.get("caption_confirmed", False)),
            image_confirmed=bool(data.get("image_confirmed", False)),
            audio_confirmed=bool(data.get("audio_confirmed", False)),
            is_deleted=bool(data.get("is_deleted", False)),
            selected_frame_idx=data.get("selected_frame_idx"),
            extra_speakers=list(data.get("extra_speakers", [])),
        )


def _format_ts(seconds: float) -> str:
    """Format seconds as mm:ss.mmm"""
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m:02d}:{s:06.3f}"


# ── Pack Info ──────────────────────────────────────────────────────────────────

@dataclass
class PackInfo:
    """
    Metadata written to _pack_info.ini

    [data]
    title="SHANGRI LA FRONTIER"
    icon="001_Weazemon.jpg"
    authors=["test"]
    """
    title: str = "Untitled Pack"
    icon: str = ""                       # filename only, e.g. "001_Weazemon.png"
    authors: List[str] = field(default_factory=lambda: ["unknown"])
    include_dub_video: bool = True

    def to_ini_string(self) -> str:
        authors_str = "[" + ", ".join(f'"{a}"' for a in self.authors) + "]"
        return (
            "[data]\n"
            f'title="{self.title}"\n'
            f'icon="{self.icon}"\n'
            f"authors={authors_str}\n"
        )

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "icon": self.icon,
            "authors": list(self.authors),
            "include_dub_video": self.include_dub_video,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PackInfo:
        return cls(
            title=str(data.get("title", "Untitled Pack")),
            icon=str(data.get("icon", "")),
            authors=list(data.get("authors", ["unknown"])),
            include_dub_video=bool(data.get("include_dub_video", True)),
        )


# ── Pipeline State ─────────────────────────────────────────────────────────────

class PipelineStep(Enum):
    IDLE            = auto()
    AUDIO_EXTRACT   = auto()
    VAD             = auto()
    DIARIZATION     = auto()
    TRANSCRIPTION   = auto()
    VOICE_SEPARATION= auto()
    CLIP_GENERATION = auto()
    FRAME_EXTRACTION= auto()
    BACKING_TRACK   = auto()
    PACK_BUILD      = auto()
    VALIDATION      = auto()
    EXPORT          = auto()
    DONE            = auto()
    ERROR           = auto()


PIPELINE_STEP_LABELS: Dict[PipelineStep, str] = {
    PipelineStep.IDLE:             "Ready",
    PipelineStep.AUDIO_EXTRACT:    "Extracting video audio…",
    PipelineStep.VAD:              "Detecting speech segments…",
    PipelineStep.DIARIZATION:      "Identifying speakers…",
    PipelineStep.TRANSCRIPTION:    "Transcribing dialogue…",
    PipelineStep.VOICE_SEPARATION: "Separating voices…",
    PipelineStep.CLIP_GENERATION:  "Generating audio clips…",
    PipelineStep.FRAME_EXTRACTION: "Extracting representative frames…",
    PipelineStep.BACKING_TRACK:    "Generating backing track…",
    PipelineStep.PACK_BUILD:       "Building pack…",
    PipelineStep.VALIDATION:       "Validating pack…",
    PipelineStep.EXPORT:           "Exporting ZIP…",
    PipelineStep.DONE:             "Done",
    PipelineStep.ERROR:            "Error",
}

PIPELINE_STEP_PROGRESS: Dict[PipelineStep, int] = {
    PipelineStep.IDLE:             0,
    PipelineStep.AUDIO_EXTRACT:    8,
    PipelineStep.VAD:              18,
    PipelineStep.TRANSCRIPTION:    38,
    PipelineStep.DIARIZATION:      52,
    PipelineStep.VOICE_SEPARATION: 65,
    PipelineStep.CLIP_GENERATION:  75,
    PipelineStep.FRAME_EXTRACTION: 85,
    PipelineStep.BACKING_TRACK:    92,
    PipelineStep.PACK_BUILD:       96,
    PipelineStep.VALIDATION:       98,
    PipelineStep.EXPORT:           99,
    PipelineStep.DONE:             100,
    PipelineStep.ERROR:            -1,
}


@dataclass
class PipelineState:
    """
    Holds all runtime data produced by the pipeline.
    Passed between steps and exposed to the GUI.
    """
    video_path: Optional[Path] = None
    work_audio_path: Optional[Path] = None       # Full extracted WAV
    separated_vocals_path: Optional[Path] = None  # Demucs vocals
    separated_bg_path: Optional[Path] = None      # Demucs background
    pack_backing_track_path: Optional[Path] = None

    speakers: Dict[str, SpeakerInfo] = field(default_factory=dict)  # {speaker_id: SpeakerInfo}
    speaker_order: List[str] = field(default_factory=list)          # Ordered list of speaker IDs for UI layer ordering
    dialogues: List[DialogueItem] = field(default_factory=list)

    pack_info: PackInfo = field(default_factory=PackInfo)

    current_step: PipelineStep = PipelineStep.IDLE
    step_errors: Dict[PipelineStep, str] = field(default_factory=dict)
    step_completed: Dict[PipelineStep, bool] = field(default_factory=dict)

    # Video metadata
    video_duration: float = 0.0
    video_width: int = 0
    video_height: int = 0
    video_fps: float = 0.0
    video_audio_tracks: int = 0

    def get_speaker(self, speaker_id: str) -> SpeakerInfo:
        if speaker_id not in self.speakers:
            self.speakers[speaker_id] = SpeakerInfo(speaker_id=speaker_id)
            if speaker_id not in self.speaker_order:
                self.speaker_order.append(speaker_id)
        return self.speakers[speaker_id]

    def get_speaker_order(self) -> List[str]:
        """Returns sorted list of active speaker_ids according to speaker_order layout."""
        if not self.speakers:
            return ["SPEAKER_00"]
        # Filter existing order to valid speakers
        ordered = [s for s in self.speaker_order if s in self.speakers]
        # Append any missing speakers
        for s in sorted(self.speakers.keys()):
            if s not in ordered:
                ordered.append(s)
        self.speaker_order = ordered
        return ordered

    def move_speaker_layer(self, speaker_id: str, direction: int):
        """Move speaker up (direction=-1) or down (direction=1) in layer order."""
        order = self.get_speaker_order()
        if speaker_id not in order:
            return
        idx = order.index(speaker_id)
        new_idx = idx + direction
        if 0 <= new_idx < len(order):
            order[idx], order[new_idx] = order[new_idx], order[idx]
            self.speaker_order = order

    def get_speaker_safe_name(self, speaker_id: str) -> str:
        spk = self.get_speaker(speaker_id)
        return spk.safe_name if spk else speaker_id

    def active_dialogues(self) -> List[DialogueItem]:
        """Return non-deleted dialogues sorted by start time."""
        return sorted(
            [d for d in self.dialogues if not d.is_deleted],
            key=lambda d: d.start
        )

    def renumber(self):
        """Re-assign sequential 1-based index to all active dialogues."""
        for i, d in enumerate(self.active_dialogues(), start=1):
            d.index = i

    def is_step_done(self, step: PipelineStep) -> bool:
        return self.step_completed.get(step, False)

    def to_dict(self, base_dir: Optional[Path] = None) -> dict:
        def _rel_or_abs(p: Optional[Path]) -> Optional[str]:
            if not p:
                return None
            if base_dir:
                try:
                    return str(p.relative_to(base_dir).as_posix())
                except ValueError:
                    pass
            return str(p.as_posix()) if hasattr(p, 'as_posix') else str(p)

        return {
            "version": 1,
            "video_path": _rel_or_abs(self.video_path),
            "work_audio_path": _rel_or_abs(self.work_audio_path),
            "separated_vocals_path": _rel_or_abs(self.separated_vocals_path),
            "separated_bg_path": _rel_or_abs(self.separated_bg_path),
            "pack_backing_track_path": _rel_or_abs(self.pack_backing_track_path),
            "video_duration": self.video_duration,
            "video_width": self.video_width,
            "video_height": self.video_height,
            "video_fps": self.video_fps,
            "video_audio_tracks": self.video_audio_tracks,
            "speakers": {k: v.to_dict() for k, v in self.speakers.items()},
            "speaker_order": list(self.speaker_order),
            "dialogues": [d.to_dict(base_dir) for d in self.dialogues],
            "pack_info": self.pack_info.to_dict(),
            "current_step": self.current_step.name,
            "step_completed": {k.name: v for k, v in self.step_completed.items()},
        }

    @classmethod
    def from_dict(cls, data: dict, base_dir: Optional[Path] = None) -> PipelineState:
        def _resolve_path(p_str: Optional[str]) -> Optional[Path]:
            if not p_str:
                return None
            p = Path(p_str)
            if p.is_absolute() and p.exists():
                return p
            if base_dir:
                candidate = (base_dir / p).resolve()
                if candidate.exists():
                    return candidate
            return p

        state = cls()
        state.video_path = _resolve_path(data.get("video_path"))
        state.work_audio_path = _resolve_path(data.get("work_audio_path"))
        state.separated_vocals_path = _resolve_path(data.get("separated_vocals_path"))
        state.separated_bg_path = _resolve_path(data.get("separated_bg_path"))
        state.pack_backing_track_path = _resolve_path(data.get("pack_backing_track_path"))

        state.video_duration = float(data.get("video_duration", 0.0))
        state.video_width = int(data.get("video_width", 0))
        state.video_height = int(data.get("video_height", 0))
        state.video_fps = float(data.get("video_fps", 0.0))
        state.video_audio_tracks = int(data.get("video_audio_tracks", 0))

        # Speakers
        speakers_dict = {}
        for k, v in data.get("speakers", {}).items():
            speakers_dict[k] = SpeakerInfo.from_dict(v)
        state.speakers = speakers_dict
        state.speaker_order = list(data.get("speaker_order", list(speakers_dict.keys())))

        # Dialogues
        state.dialogues = [
            DialogueItem.from_dict(d, base_dir)
            for d in data.get("dialogues", [])
        ]

        # Pack Info
        if "pack_info" in data:
            state.pack_info = PackInfo.from_dict(data["pack_info"])

        # Steps
        step_name = data.get("current_step", "IDLE")
        try:
            state.current_step = PipelineStep[step_name]
        except KeyError:
            state.current_step = PipelineStep.IDLE

        state.step_completed = {}
        for k, v in data.get("step_completed", {}).items():
            try:
                state.step_completed[PipelineStep[k]] = bool(v)
            except KeyError:
                pass

        return state


# ── Undo / Redo State Manager ──────────────────────────────────────────────────

import copy

class UndoManager:
    """Manages undo/redo stack for dialogue and speaker state changes."""

    def __init__(self, max_depth: int = 50):
        self.undo_stack: List[Dict] = []
        self.redo_stack: List[Dict] = []
        self.max_depth = max_depth

    def snapshot(self, state: PipelineState) -> Dict:
        return {
            "dialogues": copy.deepcopy(state.dialogues),
            "speakers": copy.deepcopy(state.speakers),
            "speaker_order": copy.deepcopy(state.speaker_order),
        }

    def push(self, state: PipelineState):
        self.undo_stack.append(self.snapshot(state))
        if len(self.undo_stack) > self.max_depth:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def undo(self, current_state: PipelineState) -> bool:
        if not self.undo_stack:
            return False
        self.redo_stack.append(self.snapshot(current_state))
        snap = self.undo_stack.pop()
        current_state.dialogues = snap["dialogues"]
        current_state.speakers = snap["speakers"]
        current_state.speaker_order = snap.get("speaker_order", list(snap["speakers"].keys()))
        return True

    def redo(self, current_state: PipelineState) -> bool:
        if not self.redo_stack:
            return False
        self.undo_stack.append(self.snapshot(current_state))
        snap = self.redo_stack.pop()
        current_state.dialogues = snap["dialogues"]
        current_state.speakers = snap["speakers"]
        current_state.speaker_order = snap.get("speaker_order", list(snap["speakers"].keys()))
        return True


