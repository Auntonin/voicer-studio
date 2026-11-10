import logging
import re
import shutil
import subprocess
import zipfile
import time
from queue import Queue, Empty
from threading import Thread
from uuid import uuid4
from copy import copy
from collections import deque
from pathlib import Path
from typing import Callable, Optional

from core.models import PipelineState, DialogueItem, PackInfo
from config import FILENAME_ALLOWED_CHARS
from core.i18n import tr

logger = logging.getLogger(__name__)

class PackBuilder:
    @staticmethod
    def sanitize_pack_name(title: str) -> str:
        name = title.strip()
        name = re.sub(r'[\s/\\:*?"<>|]+', '_', name)
        name = "".join(c for c in name if c in FILENAME_ALLOWED_CHARS).strip("._")
        return name if name else "Untitled_Pack"

    @staticmethod
    def check_theora_encoder_available() -> bool:
        """Check if FFmpeg build has libtheora encoder available."""
        try:
            from config import SUBPROCESS_FLAGS
            res = subprocess.run(
                ["ffmpeg", "-encoders"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=SUBPROCESS_FLAGS
            )
            return res.returncode == 0 and "libtheora" in res.stdout
        except Exception:
            return False

    @staticmethod
    def _create_fallback_audio(dest_path: Path, duration_sec: float = 1.0):
        """Generate a valid silent MP3 file as fallback for missing audio clips."""
        try:
            from config import SUBPROCESS_FLAGS
            dur = max(0.1, duration_sec)
            cmd = [
                "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", f"{dur:.3f}", "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "44100",
                str(dest_path)
            ]
            res = subprocess.run(cmd, capture_output=True, timeout=15, creationflags=SUBPROCESS_FLAGS)
            if res.returncode == 0 and dest_path.exists() and dest_path.stat().st_size > 0:
                return
        except Exception as e:
            logger.warning(f"Could not generate fallback audio via ffmpeg: {e}")

        raise RuntimeError(f"Could not generate valid fallback audio: {dest_path.name}")

    @staticmethod
    def _create_fallback_image(dest_path: Path, speaker_name: str = "", clip_index: int = 1):
        """Generate a dark matte PNG image with 16:9 ratio as fallback."""
        try:
            from PIL import Image, ImageDraw
            img = Image.new("RGB", (1280, 720), color=(24, 24, 28))
            draw = ImageDraw.Draw(img)
            draw.rectangle([2, 2, 1277, 717], outline=(60, 60, 72), width=3)
            img.save(dest_path, "PNG")
        except Exception as e:
            raise RuntimeError(f"Could not generate fallback image: {dest_path.name}") from e

    @staticmethod
    def _copy_file_chunked(
        src: Path,
        dst: Path,
        base_pct: float,
        span_pct: float,
        progress_cb: Optional[Callable[[float, str], None]] = None,
        msg_template: str = ""
    ):
        """Copies file in 4MB chunks, reporting accurate real-time progress to avoid freezing."""
        total_bytes = max(1, src.stat().st_size)
        total_mb = total_bytes / (1024.0 * 1024.0)
        copied_bytes = 0
        chunk_size = 4 * 1024 * 1024  # 4MB streaming buffer

        with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
            while True:
                chunk = fsrc.read(chunk_size)
                if not chunk:
                    break
                fdst.write(chunk)
                copied_bytes += len(chunk)
                if progress_cb:
                    frac = min(1.0, copied_bytes / total_bytes)
                    cur_pct = base_pct + span_pct * frac
                    copied_mb = copied_bytes / (1024.0 * 1024.0)
                    detail = msg_template.format(cur=f"{copied_mb:.1f}", total=f"{total_mb:.1f}") if msg_template else f"Copying ({copied_mb:.1f}/{total_mb:.1f} MB)..."
                    progress_cb(cur_pct, detail)

    def build_txt(
        self,
        item: DialogueItem,
        state: PipelineState,
        timestamp_mode: str,
        speaker_display_names: list = None,
    ) -> str:
        speaker_safe_name = state.get_speaker_safe_name(item.speaker_id)
        image_name = item.image_path.name if item.image_path else f"{item.filename_base(speaker_safe_name)}.png"

        lines = ["[data]"]
        # Escape backslashes and double quotes, and clean newlines in caption
        caption = (item.caption or "").replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", " ")
        lines.append(f'caption="{caption}"')
        lines.append(f'image="{image_name}"')

        if timestamp_mode in ('start_only', 'absolute'):
            ts = f"[{item.start:.3f}]"
        elif timestamp_mode == 'start_end':
            ts = f"[{item.start:.3f}, {item.end:.3f}]"
        elif timestamp_mode == 'relative':
            ts = "[0.000]"
        else:
            ts = f"[{item.start:.3f}]"

        lines.append(f"dub_timestamps={ts}")

        # dub_characters — use provided names or fall back to state lookup
        chars = []
        if isinstance(speaker_display_names, (list, tuple)):
            chars = [str(c) for c in speaker_display_names if str(c).strip()]
        else:
            for sid in item.all_speakers:
                name = None
                if isinstance(speaker_display_names, dict):
                    name = speaker_display_names.get(sid)
                if not name or not str(name).strip():
                    if sid in state.speakers and state.speakers[sid].display_name.strip():
                        name = state.speakers[sid].display_name.strip()
                    elif item.imported_filename:
                        # Imported extra speakers are display names, not AI IDs.
                        name = sid
                    else:
                        name = state.get_speaker_safe_name(sid)
                if name and str(name).strip():
                    chars.append(str(name).strip())

        if not chars:
            chars = [state.get_speaker_safe_name(item.speaker_id)]

        def _escape_character(character: object) -> str:
            return str(character).replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", " ")

        chars_str = ", ".join(f'"{_escape_character(c)}"' for c in chars if c)
        lines.append(f"dub_characters=[{chars_str}]")

        return "\n".join(lines) + "\n"

    def build_pack_info(self, pack_info: PackInfo) -> str:
        return pack_info.to_ini_string()

    @staticmethod
    def get_unique_pack_dir(output_dir: Path, title: str, preserve_name: bool = False) -> Path:
        sanitized = PackBuilder.sanitize_pack_name(title)
        if preserve_name and title not in (".", "..") and Path(title).name == title:
            sanitized = title
        target = output_dir / sanitized
        if not target.exists():
            return target
        if target.is_dir() and not any(target.iterdir()):
            return target
            
        counter = 1
        while True:
            candidate = output_dir / f"{sanitized}_{counter}"
            if not candidate.exists():
                return candidate
            if candidate.is_dir() and not any(candidate.iterdir()):
                return candidate
            counter += 1

    @staticmethod
    def get_unique_zip_path(output_dir: Path, title: str) -> Path:
        sanitized = PackBuilder.sanitize_pack_name(title)
        candidate = output_dir / f"{sanitized}.zip"
        if not candidate.exists():
            return candidate
        counter = 1
        while True:
            candidate = output_dir / f"{sanitized}_{counter}.zip"
            if not candidate.exists():
                return candidate
            counter += 1

    def build_pack(
        self,
        state: PipelineState,
        output_dir: Path,
        options: dict,
        progress_cb: Optional[Callable[[float, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Path:
        pack_dir = self.get_unique_pack_dir(output_dir, state.imported_pack_name or state.pack_info.title,
                                            preserve_name=bool(state.imported_pack_name))
        pack_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Building pack in {pack_dir}")
        has_video = bool(options.get('include_dub_video', False) and state.video_path and state.video_path.exists())

        # Dynamic phase budget allocation based on presence of video
        if has_video:
            cues_base, cues_span = 0.5, 4.0        # 0.5% -> 4.5%
            vid_copy_base, vid_copy_span = 4.5, 7.5 # 4.5% -> 12.0%
            vid_enc_base, vid_enc_span = 12.0, 60.0 # 12.0% -> 72.0%
            end_pct = 72.0
        else:
            cues_base, cues_span = 1.0, 39.0       # 1.0% -> 40.0%
            end_pct = 40.0

        if progress_cb:
            progress_cb(cues_base, tr("exp_step_assembling"))

        timestamp_mode = options.get('timestamp_mode', 'start_only')
        active_items = state.active_dialogues()
        filenames = [item.filename_base(state.get_speaker_safe_name(item.speaker_id)).casefold()
                     for item in active_items]
        if len(filenames) != len(set(filenames)):
            raise ValueError("Duplicate dialogue filenames in export")
        total_items = max(1, len(active_items))
        from core.quality_checker import QualityChecker
        checker = QualityChecker()
        export_info = copy(state.pack_info)

        # Cache a frame extractor instance if video is available
        frame_extractor = None
        if state.video_path and state.video_path.exists():
            try:
                from core.frame_extractor import FrameExtractor
                frame_extractor = FrameExtractor(state.video_path)
            except Exception as e:
                logger.warning(f"Could not initialize FrameExtractor for export repair: {e}")

        clip_generator = None
        audio_src = next((Path(p) for p in (state.separated_vocals_path, state.work_audio_path, state.video_path)
                          if p and Path(p).is_file()), None)
        if audio_src and audio_src.exists():
            try:
                from core.clip_generator import ClipGenerator
                clip_generator = ClipGenerator()
            except Exception as e:
                logger.warning(f"Could not initialize ClipGenerator for export repair: {e}")

        try:
            for idx, item in enumerate(active_items):
                if cancel_check and cancel_check():
                    raise InterruptedError("Export cancelled by user")
                speaker_safe_name = state.get_speaker_safe_name(item.speaker_id)
                base_name = item.filename_base(speaker_safe_name)

                # 1. Copy/repair audio (.mp3)
                dest_audio = pack_dir / f"{base_name}.mp3"
                if item.audio_path and checker._check_audio_readable(Path(item.audio_path)):
                    if item.imported_filename:
                        dest_audio = pack_dir / f"{base_name}{item.audio_path.suffix}"
                    if Path(item.audio_path).resolve() != dest_audio.resolve():
                        shutil.copy2(item.audio_path, dest_audio)
                else:
                    # Auto-repair missing audio
                    if clip_generator and audio_src and audio_src.exists():
                        try:
                            clip_generator.generate_clip(item, audio_src, pack_dir, speaker_safe_name)
                        except Exception as e:
                            raise RuntimeError(f"Failed to generate clip audio #{item.index}: {e}") from e
                    else:
                        self._create_fallback_audio(dest_audio, max(0.1, item.end - item.start))
                item.audio_path = dest_audio

                # 2. Copy/repair image (.png)
                dest_image = pack_dir / f"{base_name}.png"
                old_image_name = Path(item.image_path).name if item.image_path else ""
                if item.image_path and (checker._check_image_readable(Path(item.image_path))
                                        if item.imported_filename else checker._check_png_readable(Path(item.image_path))):
                    if item.imported_filename:
                        dest_image = pack_dir / f"{base_name}{item.image_path.suffix}"
                    if Path(item.image_path).resolve() != dest_image.resolve():
                        shutil.copy2(item.image_path, dest_image)
                else:
                    # Auto-repair missing image
                    extracted_ok = False
                    if frame_extractor and frame_extractor.available:
                        try:
                            frame = frame_extractor.find_best_frame(item.start, item.end, num_candidates=5)
                            if frame is not None:
                                frame_extractor.save_frame(frame, dest_image)
                                extracted_ok = checker._check_png_readable(dest_image)
                        except Exception as e:
                            logger.warning(f"Failed to auto-extract frame for clip #{item.index}: {e}")
                    if not extracted_ok:
                        self._create_fallback_image(dest_image, speaker_safe_name, item.index)
                item.image_path = dest_image
                if old_image_name and export_info.icon == old_image_name:
                    export_info.icon = dest_image.name

                # 3. Write txt
                txt_path = pack_dir / f"{base_name}.txt"
                txt_content = self.build_txt(item, state, timestamp_mode, speaker_display_names=options.get('speaker_display_names'))
                txt_path.write_text(txt_content, encoding='utf-8')
                item.txt_path = txt_path

                if progress_cb and (idx % 2 == 0 or idx == total_items - 1):
                    item_pct = cues_base + (cues_span * (idx + 1) / total_items)
                    progress_cb(item_pct, tr("exp_step_cues", current=idx + 1, total=total_items))
        finally:
            if frame_extractor and hasattr(frame_extractor, 'release'):
                frame_extractor.release()

        # Write pack info
        if export_info.icon and not (pack_dir / export_info.icon).is_file():
            export_info.icon = active_items[0].image_path.name if active_items else ""
        pack_info_path = pack_dir / "_pack_info.ini"
        pack_info_path.write_text(self.build_pack_info(export_info), encoding='utf-8')

        # Copy/repair backing track (_backing_track.mp3)
        dest_bg = pack_dir / "_backing_track.mp3"
        if state.pack_backing_track_path and checker._check_audio_readable(Path(state.pack_backing_track_path)):
            if Path(state.pack_backing_track_path).resolve() != dest_bg.resolve():
                shutil.copy2(state.pack_backing_track_path, dest_bg)
        elif not dest_bg.exists():
            bg_src = next((Path(p) for p in (state.separated_bg_path, state.work_audio_path, state.video_path)
                           if p and Path(p).is_file()), None)
            if bg_src and Path(bg_src).exists():
                try:
                    from config import SUBPROCESS_FLAGS
                    cmd = [
                        "ffmpeg", "-y", "-i", str(bg_src),
                        "-vn", "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "44100",
                        str(dest_bg)
                    ]
                    res = subprocess.run(cmd, capture_output=True, timeout=60, creationflags=SUBPROCESS_FLAGS)
                    if res.returncode != 0 or not checker._check_audio_readable(dest_bg):
                        logger.error('Backing track FFmpeg failed: %s', res.stderr.decode('utf-8', errors='replace')[-4096:], extra={'operation': 'export', 'stage': 'backing_track'})
                        raise RuntimeError("FFmpeg failed to encode the backing track")
                except Exception as e:
                    raise RuntimeError(f"Could not generate backing track: {e}") from e
            else:
                self._create_fallback_audio(dest_bg, max(1.0, state.video_duration))

        # Share the same video creation path with Analyze.
        if has_video:
            if state.imported_pack_name and state.video_path.name in ("dub_video.ogv", "dub_video.mp4"):
                def report_copy(pct, msg):
                    if cancel_check and cancel_check():
                        raise InterruptedError("Export cancelled by user")
                    if progress_cb:
                        progress_cb(pct, msg)
                self._copy_file_chunked(state.video_path, pack_dir / state.video_path.name,
                                        vid_copy_base, end_pct - vid_copy_base, report_copy)
            else:
                self.build_dub_videos(
                    state, pack_dir, progress_cb, cancel_check,
                    copy_base=vid_copy_base, copy_span=vid_copy_span,
                    encode_base=vid_enc_base, encode_span=vid_enc_span,
                    require_ogv=False,
                )

        if progress_cb:
            progress_cb(end_pct, tr("exp_step_validating"))
        state.pack_info.icon = export_info.icon
        state.pack_backing_track_path = dest_bg
        return pack_dir

    @staticmethod
    def _encode_video(command, destination, progress_cb=None, cancel_check=None,
                      stall_timeout=600.0):
        """Allow long encodes while frames advance; publish only complete files."""
        from config import SUBPROCESS_FLAGS
        temporary = destination.with_name(f".{destination.stem}.{uuid4().hex}.part{destination.suffix}")
        cmd = ["ffmpeg", "-nostdin", "-y", *command,
               "-progress", "pipe:1", "-nostats", "-v", "error", str(temporary)]
        proc = None
        reader = None
        recent_output = deque(maxlen=20)
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                                    creationflags=SUBPROCESS_FLAGS)
            lines = Queue()

            def read_output():
                try:
                    for line in proc.stdout:
                        lines.put(line)
                except Exception as exc:
                    lines.put(exc)
                finally:
                    lines.put(None)

            reader = Thread(target=read_output, daemon=True)
            reader.start()
            last_advance = time.monotonic()
            last_values = {}
            while True:
                if cancel_check and cancel_check():
                    raise InterruptedError(tr("video_encode_cancelled"))
                if time.monotonic() - last_advance > stall_timeout:
                    raise TimeoutError(tr("video_encode_stalled", seconds=f"{stall_timeout:g}",
                                          detail="\n".join(recent_output)))
                try:
                    line = lines.get(timeout=0.2)
                except Empty:
                    continue
                if line is None:
                    break
                if isinstance(line, Exception):
                    raise line
                line = line.strip()
                recent_output.append(line[-2048:])
                key, _, value = line.partition("=")
                if key in ("out_time_us", "frame", "total_size"):
                    try:
                        current = int(value)
                    except ValueError:
                        continue
                    if current > last_values.get(key, 0):
                        last_advance = time.monotonic()
                        last_values[key] = current
                    if key == "out_time_us" and progress_cb:
                        progress_cb(max(0.0, current / 1_000_000.0))
            # Keep cancellation responsive even after FFmpeg closes its output pipe.
            while True:
                if cancel_check and cancel_check():
                    raise InterruptedError(tr("video_encode_cancelled"))
                if time.monotonic() - last_advance > stall_timeout:
                    raise TimeoutError(tr("video_encode_stalled", seconds=f"{stall_timeout:g}",
                                          detail="\n".join(recent_output)))
                try:
                    proc.wait(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if proc.returncode != 0 or not temporary.is_file() or temporary.stat().st_size == 0:
                detail = "\n".join(recent_output)
                logger.error("Video FFmpeg failed: %s", detail)
                kind = "OGV" if destination.suffix == ".ogv" else "MP4"
                raise RuntimeError(tr("video_encode_failed", kind=kind, code=proc.returncode, detail=detail))
            temporary.replace(destination)
        finally:
            if proc is not None:
                if proc.returncode is None:
                    proc.kill()
                    proc.wait()
                if reader:
                    reader.join(timeout=2)
                if proc.stdout:
                    proc.stdout.close()
            temporary.unlink(missing_ok=True)

    def build_dub_videos(self, state, pack_dir, progress_cb=None, cancel_check=None,
                         copy_base=0.0, copy_span=10.0, encode_base=10.0, encode_span=90.0,
                         require_ogv=True):
        """Create genuine MP4/OGV containers without reusing interrupted outputs."""
        source = state.video_path
        total_duration = max(0.0, state.video_duration or 0.0)

        def check_cancel():
            if cancel_check and cancel_check():
                raise InterruptedError(tr("video_encode_cancelled"))

        def copy_video(destination, base, span):
            if source.resolve() == destination.resolve():
                return
            temporary = destination.with_name(f".{destination.stem}.{uuid4().hex}.part{destination.suffix}")
            def report(pct, detail):
                check_cancel()
                if progress_cb:
                    progress_cb(pct, detail)
            try:
                check_cancel()
                self._copy_file_chunked(source, temporary, base, span, report,
                                        tr("exp_step_copying_source", cur="{cur}", total="{total}"))
                check_cancel()
                if temporary.stat().st_size == 0:
                    raise RuntimeError(tr("video_source_empty"))
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)

        check_cancel()
        has_theora = source.suffix.lower() == ".ogv" or self.check_theora_encoder_available()
        if not has_theora and require_ogv:
            raise RuntimeError(tr("video_theora_missing"))
        mp4 = pack_dir / "dub_video.mp4"
        if source.suffix.lower() == ".mp4":
            copy_video(mp4, copy_base, copy_span)
        else:
            common = ["-i", str(source), "-map", "0:v:0", "-map", "0:a:0?"]
            try:
                self._encode_video([*common, "-c", "copy", "-movflags", "+faststart"], mp4,
                                   cancel_check=cancel_check)
            except RuntimeError:
                # Theora and other codecs cannot be remuxed into MP4.
                self._encode_video([*common, "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                                    "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart"], mp4,
                                   cancel_check=cancel_check)
        check_cancel()
        if not has_theora:
            # Preserve Export's existing MP4-only fallback on limited FFmpeg builds.
            logger.warning("FFmpeg build lacks libtheora encoder. Skipping dub_video.ogv encoding.")
            return
        ogv = pack_dir / "dub_video.ogv"
        if source.suffix.lower() == ".ogv":
            copy_video(ogv, encode_base, encode_span)
        else:
            def report(seconds):
                fraction = min(1.0, seconds / total_duration) if total_duration else 0.0
                if progress_cb:
                    progress_cb(encode_base + encode_span * fraction,
                                tr("exp_step_encoding_ogv", cur=f"{seconds:.1f}",
                                   total=f"{total_duration:.1f}", pct=int(fraction * 100)))
            report(0.0)
            self._encode_video(
                ["-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
                 "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                 "-c:v", "libtheora", "-qscale:v", "10", "-b:v", "12M", "-maxrate", "16M",
                 "-bufsize", "20M", "-pix_fmt", "yuv420p", "-g", "15",
                 "-c:a", "libvorbis", "-qscale:a", "8"], ogv, report, cancel_check)
        check_cancel()

    @staticmethod
    def export_zip(
        pack_dir: Path,
        zip_path: Path,
        base_pct: float = 74.0,
        span_pct: float = 25.5,
        progress_cb: Optional[Callable[[float, str], None]] = None
    ) -> Path:
        logger.info(f"Exporting ZIP to {zip_path}")
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        files = [f for f in sorted(pack_dir.iterdir()) if f.is_file()]
        total_bytes = max(1, sum(f.stat().st_size for f in files))
        total_mb = total_bytes / (1024.0 * 1024.0)
        bytes_compressed = 0
        chunk_size = 4 * 1024 * 1024  # 4MB streaming buffer

        temp_zip_path = zip_path.with_name(f".{zip_path.name}.part")
        temp_zip_path.unlink(missing_ok=True)
        try:
            with zipfile.ZipFile(temp_zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zipf:
                for file_path in files:
                    arcname = f"{pack_dir.name}/{file_path.name}"
                    f_size = file_path.stat().st_size
                    if f_size <= chunk_size:
                        zipf.write(file_path, arcname)
                        bytes_compressed += f_size
                        if progress_cb:
                            frac = min(1.0, bytes_compressed / total_bytes)
                            cur_pct = base_pct + span_pct * frac
                            comp_mb = bytes_compressed / (1024.0 * 1024.0)
                            progress_cb(cur_pct, tr("exp_step_compressing_zip", name=file_path.name, cur=f"{comp_mb:.1f}", total=f"{total_mb:.1f}"))
                    else:
                        with zipf.open(arcname, 'w', force_zip64=True) as dest_f:
                            with open(file_path, 'rb') as src_f:
                                while chunk := src_f.read(chunk_size):
                                    dest_f.write(chunk)
                                    bytes_compressed += len(chunk)
                                    if progress_cb:
                                        frac = min(1.0, bytes_compressed / total_bytes)
                                        cur_pct = base_pct + span_pct * frac
                                        comp_mb = bytes_compressed / (1024.0 * 1024.0)
                                        progress_cb(cur_pct, tr("exp_step_compressing_zip", name=file_path.name, cur=f"{comp_mb:.1f}", total=f"{total_mb:.1f}"))
            temp_zip_path.replace(zip_path)
        except Exception:
            temp_zip_path.unlink(missing_ok=True)
            raise

        if progress_cb:
            progress_cb(base_pct + span_pct, tr("exp_step_success"))
        return zip_path
