import logging
import subprocess
import shutil
import sys
import time
from pathlib import Path
from typing import Tuple, Optional, Callable

from core.models import PipelineState, DialogueItem
from config import TEMP_DIR, PACK_BACKING_TRACK_NAME, VoiceSepMode, ROFORMER_MODEL_DEFAULT

logger = logging.getLogger(__name__)

class VoiceSeparator:
    def __init__(self, mode: str = VoiceSepMode.ROFORMER, device: str = 'auto'):
        self.mode = mode
        self.device = device
        self.has_audio_separator = False
        self.has_demucs = False

        try:
            import audio_separator
            self.has_audio_separator = True
        except ImportError:
            pass

        try:
            import demucs
            self.has_demucs = True
        except ImportError:
            pass

        self.available = self.has_audio_separator or self.has_demucs

    def separate(self, audio_path: Path, output_dir: Path, cancel_check: Optional[Callable[[], bool]] = None) -> Tuple[Path, Path]:
        if self.mode == VoiceSepMode.ORIGINAL or not self.available:
            if self.mode != VoiceSepMode.ORIGINAL:
                logger.warning("No AI separation library available, falling back to original audio.")
            return audio_path, audio_path

        # 1. Prefer audio-separator + BS-RoFormer if available
        if self.has_audio_separator and self.mode in [VoiceSepMode.ROFORMER, VoiceSepMode.HIGH_QUALITY, VoiceSepMode.VOICE_ISOLATION, 'roformer']:
            try:
                return self._separate_audio_separator(audio_path, output_dir, cancel_check=cancel_check)
            except Exception as e:
                logger.error(f"audio-separator RoFormer failed ({e}), falling back to Demucs...")

        # 2. Fallback to Demucs if available
        if self.has_demucs:
            try:
                return self._separate_demucs(audio_path, output_dir, cancel_check=cancel_check)
            except Exception as e:
                logger.error(f"Demucs separation failed ({e})")

        return audio_path, audio_path

    def _separate_audio_separator(self, audio_path: Path, output_dir: Path, cancel_check: Optional[Callable[[], bool]] = None) -> Tuple[Path, Path]:
        from audio_separator.separator import Separator
        from core.device_manager import device_manager, DeviceBackend
        
        dev_info = device_manager.get_optimal_device(self.device)
        use_cuda = (dev_info.backend == DeviceBackend.CUDA)
        logger.info(f"Running audio-separator (Model: {ROFORMER_MODEL_DEFAULT}) on {dev_info.name} (use_cuda={use_cuda})")

        out_sep_dir = output_dir / "roformer"
        out_sep_dir.mkdir(parents=True, exist_ok=True)

        try:
            if cancel_check and cancel_check():
                raise RuntimeError("Voice separation cancelled before RoFormer start")

            separator = Separator(
                output_dir=str(out_sep_dir),
                output_format="WAV",
                use_cuda=use_cuda,
                log_level=10
            )
            separator.load_model(model_filename=ROFORMER_MODEL_DEFAULT)
            if cancel_check and cancel_check():
                raise RuntimeError("Voice separation cancelled after RoFormer model load")
            output_files = separator.separate(str(audio_path))
        except Exception as e:
            if cancel_check and cancel_check():
                raise RuntimeError("Voice separation cancelled") from e
            if use_cuda:
                logger.warning(f"CUDA RoFormer failed ({e}), falling back to CPU multi-threaded...")
                device_manager.release_gpu_memory()
                device_manager.configure_runtime_environment(dev_info)
                separator = Separator(
                    output_dir=str(out_sep_dir),
                    output_format="WAV",
                    use_cuda=False,
                    log_level=10
                )
                separator.load_model(model_filename=ROFORMER_MODEL_DEFAULT)
                if cancel_check and cancel_check():
                    raise RuntimeError("Voice separation cancelled")
                output_files = separator.separate(str(audio_path))
            else:
                raise
        finally:
            device_manager.release_gpu_memory()

        vocals_path = None
        bg_path = None

        for fname in output_files:
            full_p = out_sep_dir / fname
            fname_lower = fname.lower()
            if "vocal" in fname_lower:
                vocals_path = full_p
            elif "instrumental" in fname_lower or "no_vocals" in fname_lower:
                bg_path = full_p

        if not vocals_path and output_files:
            vocals_path = out_sep_dir / output_files[0]
        elif not vocals_path:
            vocals_path = audio_path

        if not bg_path and len(output_files) > 1:
            bg_path = out_sep_dir / output_files[1]
        elif not bg_path:
            bg_path = audio_path

        logger.info(f"RoFormer separation complete! Vocals: {vocals_path.name}, Backing Track: {bg_path.name}")
        return vocals_path, bg_path

    def _run_subprocess_with_cancel(self, cmd: list, timeout: int = 1800, cancel_check: Optional[Callable[[], bool]] = None):
        from config import SUBPROCESS_FLAGS
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=SUBPROCESS_FLAGS
        )
        start_t = time.time()
        while proc.poll() is None:
            if cancel_check and cancel_check():
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise RuntimeError("Voice separation cancelled by user")
            if time.time() - start_t > timeout:
                proc.kill()
                raise subprocess.TimeoutExpired(cmd, timeout)
            time.sleep(0.2)

        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, cmd)

    def _separate_demucs(self, audio_path: Path, output_dir: Path, cancel_check: Optional[Callable[[], bool]] = None) -> Tuple[Path, Path]:
        from core.device_manager import device_manager
        dev_info = device_manager.get_optimal_device(self.device)
        model = "htdemucs_6s" if self.mode == VoiceSepMode.HIGH_QUALITY else "htdemucs"
        logger.info(f"Running demucs ({model}) on {dev_info.name}")

        cmd = [
            sys.executable, "-m", "demucs.separate", "-n", model,
            "--two-stems", "vocals",
            "--shifts", "2",
            "--overlap", "0.5",
            "--out", str(output_dir),
        ]
        cmd.extend(device_manager.get_demucs_device_args(dev_info))
        cmd.append(str(audio_path))

        try:
            self._run_subprocess_with_cancel(cmd, timeout=1800, cancel_check=cancel_check)
        except Exception as e:
            if cancel_check and cancel_check():
                raise
            if dev_info.is_gpu:
                logger.warning(f"Demucs on {dev_info.name} failed ({e}), retrying on multi-threaded CPU...")
                device_manager.release_gpu_memory()
                cmd_cpu = [
                    sys.executable, "-m", "demucs.separate", "-n", model,
                    "--two-stems", "vocals",
                    "--shifts", "2",
                    "--overlap", "0.5",
                    "--out", str(output_dir),
                    "-d", "cpu", "-j", str(device_manager.get_optimal_concurrency_config().demucs_threads),
                    str(audio_path)
                ]
                self._run_subprocess_with_cancel(cmd_cpu, timeout=1800, cancel_check=cancel_check)
            else:
                raise
        finally:
            device_manager.release_gpu_memory()

        track_name = audio_path.stem
        model_dir = output_dir / model / track_name

        vocals_path = model_dir / "vocals.wav"
        bg_path = model_dir / "no_vocals.wav"

        if not vocals_path.exists():
            vocals_path = audio_path
        if not bg_path.exists():
            bg_path = audio_path

        return vocals_path, bg_path

    def get_clip_audio(self, item: DialogueItem, state: PipelineState) -> Path:
        if self.mode != VoiceSepMode.ORIGINAL and state.separated_vocals_path:
            return state.separated_vocals_path
        return state.work_audio_path

    def generate_backing_track(self, state: PipelineState, output_path: Path, bitrate: str = "320k", cancel_check: Optional[Callable[[], bool]] = None) -> Path:
        if not state.separated_bg_path and self.available and state.work_audio_path and state.work_audio_path.exists():
            sep_dir = TEMP_DIR / "separated"
            sep_dir.mkdir(exist_ok=True)
            logger.info("Running AI stem separation for backing track...")
            vocals, bg = self.separate(state.work_audio_path, sep_dir, cancel_check=cancel_check)
            state.separated_vocals_path = vocals
            state.separated_bg_path = bg

        bg_audio = state.separated_bg_path if state.separated_bg_path else state.work_audio_path

        logger.info(f"Generating MP3 backing track ({bitrate}) at {output_path}")
        cmd = [
            "ffmpeg", "-y", "-i", str(bg_audio),
            "-vn", "-c:a", "libmp3lame", "-b:a", bitrate, "-ar", "44100",
            "-af", "volume=1.0",
            str(output_path)
        ]
        try:
            self._run_subprocess_with_cancel(cmd, timeout=300, cancel_check=cancel_check)
            return output_path
        except FileNotFoundError:
            logger.error("FFmpeg not found in PATH when generating backing track.")
            return bg_audio
        except Exception as e:
            logger.error(f"Failed to generate backing track: {e}")
            return bg_audio
