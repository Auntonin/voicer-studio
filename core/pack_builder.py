import logging
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Callable, Optional

from core.models import PipelineState, DialogueItem, PackInfo
from config import FILENAME_ALLOWED_CHARS
from core.i18n import tr

logger = logging.getLogger(__name__)

class PackBuilder:
    @staticmethod
    def sanitize_pack_name(title: str) -> str:
        name = title.strip().replace(" ", "_")
        name = "".join(c for c in name if c in FILENAME_ALLOWED_CHARS)
        return name if name else "Untitled_Pack"

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
            subprocess.run(cmd, capture_output=True, timeout=15, creationflags=SUBPROCESS_FLAGS)
        except Exception as e:
            logger.warning(f"Could not generate fallback audio: {e}")

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
            logger.warning(f"Could not generate fallback image: {e}")

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
    def get_unique_pack_dir(output_dir: Path, title: str) -> Path:
        sanitized = PackBuilder.sanitize_pack_name(title)
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
        progress_cb: Optional[Callable[[float, str], None]] = None
    ) -> Path:
        pack_dir = self.get_unique_pack_dir(output_dir, state.pack_info.title)
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
        total_items = max(1, len(active_items))

        # Cache a frame extractor instance if video is available
        frame_extractor = None
        if state.video_path and state.video_path.exists():
            try:
                from core.frame_extractor import FrameExtractor
                frame_extractor = FrameExtractor(state.video_path)
            except Exception as e:
                logger.warning(f"Could not initialize FrameExtractor for export repair: {e}")

        clip_generator = None
        audio_src = state.separated_vocals_path or state.work_audio_path or (state.video_path if (state.video_path and state.video_path.exists()) else None)
        if audio_src and audio_src.exists():
            try:
                from core.clip_generator import ClipGenerator
                clip_generator = ClipGenerator()
            except Exception as e:
                logger.warning(f"Could not initialize ClipGenerator for export repair: {e}")

        try:
            for idx, item in enumerate(active_items):
                speaker_safe_name = state.get_speaker_safe_name(item.speaker_id)
                base_name = item.filename_base(speaker_safe_name)

                # 1. Copy/repair audio (.mp3)
                dest_audio = pack_dir / f"{base_name}.mp3"
                if item.audio_path and Path(item.audio_path).exists():
                    if Path(item.audio_path).resolve() != dest_audio.resolve():
                        shutil.copy2(item.audio_path, dest_audio)
                else:
                    # Auto-repair missing audio
                    if clip_generator and audio_src and audio_src.exists():
                        try:
                            clip_generator.generate_clip(item, audio_src, pack_dir, speaker_safe_name)
                        except Exception as e:
                            logger.warning(f"Failed to auto-generate clip audio #{item.index}: {e}")
                            self._create_fallback_audio(dest_audio, max(0.1, item.end - item.start))
                    else:
                        self._create_fallback_audio(dest_audio, max(0.1, item.end - item.start))
                item.audio_path = dest_audio

                # 2. Copy/repair image (.png)
                dest_image = pack_dir / f"{base_name}.png"
                if item.image_path and Path(item.image_path).exists():
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
                                extracted_ok = True
                        except Exception as e:
                            logger.warning(f"Failed to auto-extract frame for clip #{item.index}: {e}")
                    if not extracted_ok:
                        self._create_fallback_image(dest_image, speaker_safe_name, item.index)
                item.image_path = dest_image

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
        pack_info_path = pack_dir / "_pack_info.ini"
        pack_info_path.write_text(self.build_pack_info(state.pack_info), encoding='utf-8')

        # Copy/repair backing track (_backing_track.mp3)
        dest_bg = pack_dir / "_backing_track.mp3"
        if hasattr(state, 'pack_backing_track_path') and state.pack_backing_track_path and Path(state.pack_backing_track_path).exists():
            if Path(state.pack_backing_track_path).resolve() != dest_bg.resolve():
                shutil.copy2(state.pack_backing_track_path, dest_bg)
        elif not dest_bg.exists():
            bg_src = getattr(state, 'separated_accompaniment_path', None) or state.work_audio_path or (state.video_path if (state.video_path and state.video_path.exists()) else None)
            if bg_src and Path(bg_src).exists():
                try:
                    from config import SUBPROCESS_FLAGS
                    cmd = [
                        "ffmpeg", "-y", "-i", str(bg_src),
                        "-vn", "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "44100",
                        str(dest_bg)
                    ]
                    subprocess.run(cmd, capture_output=True, timeout=60, creationflags=SUBPROCESS_FLAGS)
                except Exception as e:
                    logger.warning(f"Could not auto-generate backing track: {e}")
                    self._create_fallback_audio(dest_bg, max(1.0, state.video_duration))
            else:
                self._create_fallback_audio(dest_bg, max(1.0, state.video_duration))

        # Video Processing
        if has_video:
            # 1. Chunked stream copy of source video as dub_video.mp4
            dest_mp4 = pack_dir / "dub_video.mp4"
            if state.video_path.resolve() != dest_mp4.resolve():
                try:
                    self._copy_file_chunked(
                        state.video_path, dest_mp4,
                        vid_copy_base, vid_copy_span,
                        progress_cb=progress_cb,
                        msg_template=tr("exp_step_copying_source", cur="{cur}", total="{total}")
                    )
                except Exception as e:
                    logger.warning(f"Could not copy dub_video.mp4: {e}")
            else:
                if progress_cb:
                    progress_cb(vid_copy_base + vid_copy_span, tr("exp_step_copying_source", cur="0", total="0"))

            # 2. Maximum Quality OGV encode as dub_video.ogv
            dest_vid = pack_dir / "dub_video.ogv"
            if state.video_path.suffix.lower() == ".ogv":
                if state.video_path.resolve() != dest_vid.resolve():
                    self._copy_file_chunked(
                        state.video_path, dest_vid,
                        vid_enc_base, vid_enc_span,
                        progress_cb=progress_cb,
                        msg_template=tr("exp_step_copying_source", cur="{cur}", total="{total}")
                    )
            else:
                total_dur = state.video_duration if (state.video_duration and state.video_duration > 0) else 0.0
                if progress_cb:
                    progress_cb(vid_enc_base, tr("exp_step_encoding_ogv", cur="0.0", total=f"{total_dur:.1f}", pct="0"))
                try:
                    cmd = [
                        "ffmpeg", "-y", "-i", str(state.video_path),
                        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                        "-c:v", "libtheora", "-qscale:v", "10", "-b:v", "12M", "-maxrate", "16M", "-bufsize", "20M",
                        "-pix_fmt", "yuv420p", "-g", "15",
                        "-c:a", "libvorbis", "-qscale:a", "8",
                        "-progress", "pipe:1", "-nostats", "-v", "error",
                        str(dest_vid)
                    ]
                    from config import SUBPROCESS_FLAGS
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        text=True,
                        bufsize=1,
                        universal_newlines=True,
                        creationflags=SUBPROCESS_FLAGS
                    )

                    if proc.stdout:
                        try:
                            for line in proc.stdout:
                                line = line.strip()
                                if line.startswith("out_time_us="):
                                    try:
                                        us_val = int(line.split("=", 1)[1])
                                        cur_sec = us_val / 1_000_000.0
                                        if total_dur > 0:
                                            frac = min(1.0, max(0.0, cur_sec / total_dur))
                                            pct = vid_enc_base + vid_enc_span * frac
                                            if progress_cb:
                                                progress_cb(
                                                    pct,
                                                    tr("exp_step_encoding_ogv",
                                                       cur=f"{cur_sec:.1f}",
                                                       total=f"{total_dur:.1f}",
                                                       pct=int(frac * 100))
                                                )
                                    except (ValueError, IndexError):
                                        pass
                                elif line.startswith("progress=end"):
                                    if progress_cb:
                                        progress_cb(vid_enc_base + vid_enc_span, tr("exp_step_validating"))
                        except Exception:
                            proc.kill()
                            proc.wait()
                            if dest_vid.exists():
                                try:
                                    dest_vid.unlink()
                                except Exception:
                                    pass
                            raise

                    proc.wait()
                    if proc.returncode != 0 or not dest_vid.exists():
                        logger.error(f"FFmpeg OGV encoding failed (exit code {proc.returncode})")
                except Exception as e:
                    logger.error(f"Failed to encode dub_video.ogv: {e}")
                    raise

        if progress_cb:
            progress_cb(end_pct, tr("exp_step_validating"))
        return pack_dir

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
