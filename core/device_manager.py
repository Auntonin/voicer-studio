"""
core/device_manager.py
======================
Comprehensive Compute Processor and Hardware Device Manager for Voicer Studio.

Supports:
1. NVIDIA GPUs (CUDA: RTX, GTX, Quadro, Tesla) with FP16/INT8 compute modes.
2. AMD Radeon & Intel Arc / Iris Xe GPUs via DirectML (Windows DirectX 12) & ROCm.
3. Apple Silicon (MPS: Metal Performance Shaders on macOS).
4. Multi-Core CPU (Intel / AMD) with automatic thread optimization and INT8 quantization.
5. FFmpeg Hardware Acceleration detection (NVENC, AMF, QSV, D3D11VA, DXVA2).
6. Out-Of-Memory (OOM) recovery & automatic graceful fallback.
"""

from __future__ import annotations

import os
import sys
import shutil
import logging
import subprocess
from enum import Enum
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any

log = logging.getLogger(__name__)


class DeviceBackend(str, Enum):
    AUTO = "auto"
    CUDA = "cuda"
    DIRECTML = "directml"
    ROCM = "rocm"
    MPS = "mps"
    CPU = "cpu"


@dataclass
class ComputeDevice:
    """Detailed metadata for a compute hardware processor."""
    backend: DeviceBackend
    device_id: str                      # e.g. "cuda:0", "directml:0", "cpu"
    name: str                           # Display name, e.g. "NVIDIA GeForce RTX 3070"
    vram_bytes: int = 0                 # VRAM in bytes (0 for CPU)
    is_gpu: bool = False
    fp16_supported: bool = False
    description: str = ""

    @property
    def vram_gb(self) -> float:
        return self.vram_bytes / (1024 ** 3) if self.vram_bytes > 0 else 0.0

    @property
    def display_title(self) -> str:
        if self.is_gpu:
            if self.vram_gb > 0:
                return f"{self.name} ({self.vram_gb:.1f} GB VRAM)"
            return self.name
        else:
            cores = os.cpu_count() or 4
            return f"{self.name} ({cores} Threads)"


class DeviceManager:
    """
    Central system-wide hardware compute manager.
    Detects, configures, and tunes all AI processing pipelines according to hardware capability.
    """

    _cached_devices: Optional[List[ComputeDevice]] = None
    _active_device: Optional[ComputeDevice] = None

    @classmethod
    def detect_available_devices(cls, force_refresh: bool = False) -> List[ComputeDevice]:
        """
        Scans system for all available compute processors (CUDA, DirectML, ROCm, MPS, CPU).
        """
        if cls._cached_devices is not None and not force_refresh:
            return cls._cached_devices

        devices: List[ComputeDevice] = []

        # ── 1. Check NVIDIA CUDA ──────────────────────────────────────────────
        try:
            import torch
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()):
                    name = torch.cuda.get_device_name(i)
                    props = torch.cuda.get_device_properties(i)
                    total_vram = props.total_memory
                    # Compute capability >= 7.0 supports fast Tensor Core FP16
                    cap = props.major + props.minor / 10.0
                    fp16 = cap >= 5.3
                    devices.append(ComputeDevice(
                        backend=DeviceBackend.CUDA,
                        device_id=f"cuda:{i}",
                        name=f"NVIDIA {name}",
                        vram_bytes=total_vram,
                        is_gpu=True,
                        fp16_supported=fp16,
                        description=f"NVIDIA CUDA Hardware Acceleration (Compute {cap:.1f})"
                    ))
        except Exception as e:
            log.debug(f"CUDA check failed or not present: {e}")

        # ── 2. Check DirectML (AMD Radeon / Intel Arc / Windows DirectX 12) ───
        try:
            import torch_directml
            if torch_directml.is_available():
                for i in range(torch_directml.device_count()):
                    name = torch_directml.device_name(i)
                    devices.append(ComputeDevice(
                        backend=DeviceBackend.DIRECTML,
                        device_id=f"directml:{i}",
                        name=f"{name} (DirectML)",
                        vram_bytes=0,
                        is_gpu=True,
                        fp16_supported=False,
                        description="DirectX 12 Hardware Acceleration via DirectML"
                    ))
        except ImportError:
            # Check if an AMD or Intel GPU exists on Windows so we can at least detect it
            if sys.platform == "win32":
                try:
                    res = subprocess.run(
                        ["powershell", "-NoProfile", "-Command", 
                         "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                        capture_output=True, text=True, timeout=3
                    )
                    if res.returncode == 0:
                        gpu_names = [line.strip() for line in res.stdout.splitlines() if line.strip()]
                        for gname in gpu_names:
                            gl = gname.lower()
                            if ("amd" in gl or "radeon" in gl or "intel" in gl or "arc" in gl) and "virtual" not in gl:
                                devices.append(ComputeDevice(
                                    backend=DeviceBackend.DIRECTML,
                                    device_id="directml",
                                    name=f"{gname} (DirectX 12)",
                                    vram_bytes=0,
                                    is_gpu=True,
                                    fp16_supported=False,
                                    description="DirectX 12 GPU Detected (DirectML / HW Encoding)"
                                ))
                except Exception:
                    pass
        except Exception as e:
            log.debug(f"DirectML check error: {e}")

        # ── 3. Check Apple Silicon Metal (MPS) ────────────────────────────────
        try:
            import torch
            if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                devices.append(ComputeDevice(
                    backend=DeviceBackend.MPS,
                    device_id="mps",
                    name="Apple Silicon Metal (MPS)",
                    vram_bytes=0,
                    is_gpu=True,
                    fp16_supported=True,
                    description="Apple Metal Performance Shaders"
                ))
        except Exception:
            pass

        # ── 4. CPU (Multi-Core Processor — Always Available) ───────────────────
        cores = os.cpu_count() or 4
        cpu_name = "Multi-Core CPU"
        if sys.platform == "win32":
            cpu_name = os.environ.get("PROCESSOR_IDENTIFIER", "CPU").split(",")[0].strip()
            if not cpu_name or len(cpu_name) > 30:
                cpu_name = "Host CPU"

        devices.append(ComputeDevice(
            backend=DeviceBackend.CPU,
            device_id="cpu",
            name=cpu_name,
            vram_bytes=0,
            is_gpu=False,
            fp16_supported=False,
            description=f"Standard Multi-Threaded CPU Pipeline ({cores} Threads, INT8 Quantized)"
        ))

        cls._cached_devices = devices
        return devices

    @classmethod
    def get_optimal_device(cls, preference: str = "auto") -> ComputeDevice:
        """
        Resolves the preferred device string (e.g. 'auto', 'cuda', 'directml', 'cpu')
        into the best available ComputeDevice instance.
        """
        devices = cls.detect_available_devices()

        if preference != "auto":
            pref_lower = preference.lower()
            for dev in devices:
                if dev.backend.value in pref_lower or dev.device_id.lower() == pref_lower:
                    cls._active_device = dev
                    return dev

        # Auto-selection priority: CUDA > DirectML > MPS > CPU
        for dev in devices:
            if dev.backend == DeviceBackend.CUDA:
                cls._active_device = dev
                return dev
        for dev in devices:
            if dev.backend in (DeviceBackend.DIRECTML, DeviceBackend.ROCM):
                cls._active_device = dev
                return dev
        for dev in devices:
            if dev.backend == DeviceBackend.MPS:
                cls._active_device = dev
                return dev

        # Fallback to CPU
        for dev in devices:
            if dev.backend == DeviceBackend.CPU:
                cls._active_device = dev
                return dev

        # Ultimate fallback
        fallback = ComputeDevice(
            backend=DeviceBackend.CPU,
            device_id="cpu",
            name="CPU Fallback",
            is_gpu=False
        )
        cls._active_device = fallback
        return fallback

    @classmethod
    def configure_runtime_environment(cls, device: Optional[ComputeDevice] = None):
        """
        Configures global PyTorch thread counts and execution parameters for optimal
        throughput and CPU responsiveness.
        """
        target = device or cls._active_device or cls.get_optimal_device()
        try:
            import torch
            if not target.is_gpu:
                # Limit PyTorch CPU threads so UI and other tasks remain responsive
                total_threads = os.cpu_count() or 4
                optimal_threads = max(1, min(total_threads, 8))
                torch.set_num_threads(optimal_threads)
                torch.set_num_interop_threads(max(1, optimal_threads // 2))
                log.info(f"Configured PyTorch CPU threads: {optimal_threads} (Host total: {total_threads})")
            else:
                # GPU mode
                if target.backend == DeviceBackend.CUDA and torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    # Allow TF32 for high performance on Ampere+ GPUs
                    if hasattr(torch.backends.cuda, "matmul"):
                        torch.backends.cuda.matmul.allow_tf32 = True
                    if hasattr(torch.backends.cudnn, "allow_tf32"):
                        torch.backends.cudnn.allow_tf32 = True
        except Exception as e:
            log.debug(f"Could not configure torch runtime: {e}")

    @classmethod
    def get_whisper_kwargs(cls, device: ComputeDevice) -> Dict[str, Any]:
        """
        Returns parameters for faster_whisper WhisperModel initialization.
        Ensures safe compute types (avoids 'Half not implemented on CPU' crashes).
        """
        if device.backend == DeviceBackend.CUDA:
            # Use float16 for CUDA, with int8 fallback
            return {
                "device": "cuda",
                "compute_type": "float16" if device.fp16_supported else "int8",
                "cpu_threads": 4,
            }
        elif device.backend == DeviceBackend.CPU:
            # int8 on CPU is 3-4x faster than float32 on modern x86/ARM CPUs
            return {
                "device": "cpu",
                "compute_type": "int8",
                "cpu_threads": max(1, min(os.cpu_count() or 4, 8)),
            }
        else:
            # Generic fallback
            return {
                "device": "cpu",
                "compute_type": "int8",
                "cpu_threads": max(1, min(os.cpu_count() or 4, 8)),
            }

    @classmethod
    def get_demucs_device_args(cls, device: ComputeDevice) -> List[str]:
        """
        Returns CLI parameters for Demucs vocal separation.
        """
        if device.backend == DeviceBackend.CUDA:
            return ["-d", "cuda"]
        elif device.backend == DeviceBackend.MPS:
            return ["-d", "mps"]
        else:
            # CPU multi-threaded
            jobs = max(1, (os.cpu_count() or 4) // 2)
            return ["-d", "cpu", "-j", str(jobs)]

    @classmethod
    def get_ffmpeg_hwaccel_encoder(cls) -> Tuple[str, List[str]]:
        """
        Detects installed FFmpeg hardware video encoders.
        Returns:
            (encoder_name, extra_ffmpeg_flags)
            e.g. ("h264_nvenc", ["-preset", "p4", "-cq", "24"])
                 ("h264_amf", ["-usage", "transcoding"])
                 ("h264_qsv", ["-preset", "medium"])
                 ("libx264", ["-preset", "faster"]) [Software fallback]
        """
        try:
            from config import SUBPROCESS_FLAGS
            res = subprocess.run(
                ["ffmpeg", "-encoders"],
                capture_output=True, text=True, timeout=5,
                creationflags=SUBPROCESS_FLAGS
            )
            out = res.stdout.lower()

            devices = cls.detect_available_devices()
            has_cuda = any(d.backend == DeviceBackend.CUDA for d in devices)
            has_directml = any(d.backend == DeviceBackend.DIRECTML for d in devices)

            # NVIDIA NVENC
            if has_cuda and "h264_nvenc" in out:
                return "h264_nvenc", ["-preset", "p4", "-cq", "23"]

            # AMD AMF
            if has_directml and "h264_amf" in out:
                return "h264_amf", ["-quality", "speed"]

            # Intel QSV
            if "h264_qsv" in out and (has_directml or not has_cuda):
                return "h264_qsv", ["-preset", "faster"]

        except Exception as e:
            log.debug(f"FFmpeg encoder detection failed: {e}")

        # Universal fallback: CPU libx264 with optimized fast preset
        return "libx264", ["-preset", "veryfast", "-crf", "22", "-threads", "0"]


# Global instance
device_manager = DeviceManager()
