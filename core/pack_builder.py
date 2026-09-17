import logging
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Callable, Optional

from core.models import PipelineState, DialogueItem, PackInfo
from config import FILENAME_ALLOWED_CHARS

logger = logging.getLogger(__name__)

class PackBuilder:
    @staticmethod
    def sanitize_pack_name(title: str) -> str:
        name = title.strip().replace(" ", "_")
        name = "".join(c for c in name if c in FILENAME_ALLOWED_CHARS)
        return name if name else "Untitled_Pack"

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
        # Escape quotes in caption
        caption = item.caption.replace('"', '\\"')
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
        if speaker_display_names:
            chars = speaker_display_names
        else:
            chars = [state.speakers[item.speaker_id].display_name
                     if item.speaker_id in state.speakers
                     else state.get_speaker_safe_name(item.speaker_id)]
        chars_str = ", ".join(f'"{c}"' for c in chars)
        lines.append(f"dub_characters=[{chars_str}]")

        return "\n".join(lines) + "\n"

    def build_pack_info(self, pack_info: PackInfo) -> str:
        return pack_info.to_ini_string()

    @staticmethod
    def get_unique_pack_dir(output_dir: Path, title: str) -> Path:
        sanitized = PackBuilder.sanitize_pack_name(title)
        target = output_dir / sanitized
        if not target.exists() or not any(target.iterdir()):
            return target
            
        counter = 1
        while True:
            candidate = output_dir / f"{sanitized}_{counter}"
            if not candidate.exists() or not any(candidate.iterdir()):
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

    def build_pack(self, state: PipelineState, output_dir: Path, options: dict, progress_cb: Optional[Callable[[int, str], None]] = None) -> Path:
        pack_dir = self.get_unique_pack_dir(output_dir, state.pack_info.title)
        pack_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Building pack in {pack_dir}")
        if progress_cb:
            progress_cb(5, "Preparing pack directory and assets...")
        
        timestamp_mode = options.get('timestamp_mode', 'start_only')
        active_items = state.active_dialogues()
        total_items = max(1, len(active_items))
        
        for idx, item in enumerate(active_items):
            speaker_safe_name = state.get_speaker_safe_name(item.speaker_id)
            base_name = item.filename_base(speaker_safe_name)
            
            # Copy/rename audio (.mp3)
            if item.audio_path and item.audio_path.exists():
                dest_audio = pack_dir / f"{base_name}.mp3"
                if item.audio_path.resolve() != dest_audio.resolve():
                    shutil.copy2(item.audio_path, dest_audio)
                
            # Copy/rename image (.png)
            if item.image_path and item.image_path.exists():
                dest_image = pack_dir / f"{base_name}.png"
                if item.image_path.resolve() != dest_image.resolve():
                    shutil.copy2(item.image_path, dest_image)
                
            # Write txt
            txt_path = pack_dir / f"{base_name}.txt"
            txt_content = self.build_txt(item, state, timestamp_mode, speaker_display_names=options.get('speaker_display_names'))
            txt_path.write_text(txt_content, encoding='utf-8')
            item.txt_path = txt_path

            if progress_cb and (idx % 2 == 0 or idx == total_items - 1):
                item_pct = 5 + int(30 * (idx + 1) / total_items)
                progress_cb(item_pct, f"Exporting dialogue cues [{idx+1}/{total_items}]...")
            
        # Write pack info
        if progress_cb:
            progress_cb(38, "Writing _pack_info.ini...")
        pack_info_path = pack_dir / "_pack_info.ini"
        pack_info_path.write_text(self.build_pack_info(state.pack_info), encoding='utf-8')
        
        # Copy backing track if generated (_backing_track.mp3)
        if hasattr(state, 'pack_backing_track_path') and state.pack_backing_track_path:
            if state.pack_backing_track_path.exists():
                if progress_cb:
                    progress_cb(42, "Copying backing track (_backing_track.mp3)...")
                dest_bg = pack_dir / "_backing_track.mp3"
                if state.pack_backing_track_path.resolve() != dest_bg.resolve():
                    shutil.copy2(state.pack_backing_track_path, dest_bg)
                
        # Copy/convert dub video if asked (dub_video.ogv & dub_video.mp4)
        if options.get('include_dub_video', False) and state.video_path and state.video_path.exists():
            # 1. Untouched original copy as dub_video.mp4
            if progress_cb:
                progress_cb(45, "Copying full source video (dub_video.mp4)...")
            dest_mp4 = pack_dir / "dub_video.mp4"
            if state.video_path.resolve() != dest_mp4.resolve():
                try:
                    shutil.copy2(state.video_path, dest_mp4)
                except Exception as e:
                    logger.warning(f"Could not copy dub_video.mp4: {e}")

            # 2. Maximum Quality OGV encode as dub_video.ogv
            dest_vid = pack_dir / "dub_video.ogv"
            if state.video_path.suffix.lower() == ".ogv":
                if state.video_path.resolve() != dest_vid.resolve():
                    shutil.copy2(state.video_path, dest_vid)
            else:
                if progress_cb:
                    progress_cb(50, "Encoding game video dub_video.ogv (Theora/Vorbis)...")
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
                        stderr=subprocess.PIPE,
                        text=True,
                        bufsize=1,
                        universal_newlines=True,
                        creationflags=SUBPROCESS_FLAGS
                    )

                    total_dur = state.video_duration if (state.video_duration and state.video_duration > 0) else 0.0
                    last_pct = 50

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
                                            pct = 50 + int(22 * frac)
                                            if pct != last_pct:
                                                last_pct = pct
                                                if progress_cb:
                                                    progress_cb(pct, f"Encoding game video dub_video.ogv: {int(frac * 100)}% ({cur_sec:.1f}s / {total_dur:.1f}s)...")
                                        else:
                                            if progress_cb:
                                                progress_cb(50, f"Encoding game video dub_video.ogv: {cur_sec:.1f}s rendered...")
                                    except (ValueError, IndexError):
                                        pass
                                elif line.startswith("progress=end"):
                                    if progress_cb:
                                        progress_cb(72, "Finished encoding dub_video.ogv.")
                        except Exception:
                            # Cancellation requested via progress_cb
                            proc.kill()
                            proc.wait()
                            if dest_vid.exists():
                                try:
                                    dest_vid.unlink()
                                except Exception:
                                    pass
                            raise

                    _, stderr_data = proc.communicate()
                    if proc.returncode != 0 or not dest_vid.exists():
                        logger.error(f"FFmpeg OGV encoding failed (exit code {proc.returncode}): {stderr_data}")
                except Exception as e:
                    logger.error(f"Failed to encode dub_video.ogv: {e}")
                    raise

        if progress_cb:
            progress_cb(72, "Pack assets assembled.")
        return pack_dir

    @staticmethod
    def export_zip(pack_dir: Path, zip_path: Path, progress_cb: Optional[Callable[[int, str], None]] = None) -> Path:
        logger.info(f"Exporting ZIP to {zip_path}")
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        files = [f for f in sorted(pack_dir.iterdir()) if f.is_file()]
        total_files = max(1, len(files))

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for idx, file_path in enumerate(files):
                arcname = f"{pack_dir.name}/{file_path.name}"
                zipf.write(file_path, arcname)
                if progress_cb:
                    pct = 75 + int(24 * (idx + 1) / total_files)
                    progress_cb(pct, f"Compressing ZIP: {file_path.name} [{idx+1}/{total_files}]...")

        if progress_cb:
            progress_cb(100, "ZIP archive ready.")
        return zip_path
