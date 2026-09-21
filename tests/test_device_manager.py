"""
tests/test_device_manager.py
============================
Comprehensive automated unit tests for hardware compute detection,
dynamic multi-vendor GPU acceleration (NVIDIA, AMD, Intel, Apple, Qualcomm),
and multi-core/high-core CPU dynamic scaling.
"""

import os
import unittest
from unittest.mock import patch, MagicMock
from core.device_manager import (
    DeviceManager, DeviceBackend, HardwareTier, ComputeDevice,
    ConcurrencyConfig, device_manager
)


class TestDeviceManager(unittest.TestCase):

    def test_detect_available_devices_includes_cpu(self):
        """Multi-core CPU must always be discovered as an available compute processor."""
        devices = DeviceManager.detect_available_devices(force_refresh=True)
        self.assertTrue(len(devices) >= 1)
        backends = [d.backend for d in devices]
        self.assertIn(DeviceBackend.CPU, backends)

    def test_get_optimal_device_auto(self):
        """Auto resolution returns a valid ComputeDevice without errors."""
        dev = DeviceManager.get_optimal_device("auto")
        self.assertIsInstance(dev, ComputeDevice)
        self.assertTrue(bool(dev.name))
        self.assertTrue(bool(dev.display_title))

    def test_get_optimal_device_cpu_explicit(self):
        """Explicitly requesting CPU returns CPU backend."""
        dev = DeviceManager.get_optimal_device("cpu")
        self.assertEqual(dev.backend, DeviceBackend.CPU)
        self.assertFalse(dev.is_gpu)

    def test_get_whisper_kwargs_cpu_int8(self):
        """CPU compute must use INT8 quantization for optimal speed and memory footprint."""
        cpu_dev = ComputeDevice(
            backend=DeviceBackend.CPU,
            device_id="cpu",
            name="Test CPU",
            vendor="CPU",
            is_gpu=False
        )
        kwargs = DeviceManager.get_whisper_kwargs(cpu_dev)
        self.assertEqual(kwargs["device"], "cpu")
        self.assertEqual(kwargs["compute_type"], "int8")
        self.assertTrue(kwargs["cpu_threads"] >= 1)

    def test_get_demucs_device_args(self):
        """Demucs arguments should scale CPU jobs dynamically."""
        cpu_dev = ComputeDevice(
            backend=DeviceBackend.CPU,
            device_id="cpu",
            name="Test CPU",
            vendor="CPU",
            is_gpu=False
        )
        args = DeviceManager.get_demucs_device_args(cpu_dev)
        self.assertIn("-d", args)
        self.assertIn("cpu", args)
        self.assertIn("-j", args)

    @patch("os.cpu_count", return_value=32)
    @patch.object(DeviceManager, "get_system_ram_gb", return_value=64.0)
    def test_dynamic_concurrency_high_core_threadripper(self, mock_ram, mock_cpu):
        """High-core CPU (32 threads, 64GB RAM) should scale parallel workers up to ultra tier."""
        cfg_high = DeviceManager.get_optimal_concurrency_config(profile="high")
        self.assertEqual(cfg_high.tier, HardwareTier.ULTRA)
        self.assertTrue(cfg_high.clip_workers >= 16)
        self.assertTrue(cfg_high.whisper_threads >= 8)
        self.assertTrue(cfg_high.demucs_threads >= 8)

    @patch("os.cpu_count", return_value=4)
    @patch.object(DeviceManager, "get_system_ram_gb", return_value=8.0)
    def test_dynamic_concurrency_budget_laptop(self, mock_ram, mock_cpu):
        """Budget laptop (4 threads, 8GB RAM) should use balanced/safe resource limits."""
        cfg = DeviceManager.get_optimal_concurrency_config(profile="auto")
        self.assertEqual(cfg.tier, HardwareTier.BALANCED)
        self.assertTrue(cfg.clip_workers <= 6)
        self.assertTrue(cfg.whisper_threads <= 4)

    @patch("os.cpu_count", return_value=2)
    @patch.object(DeviceManager, "get_system_ram_gb", return_value=4.0)
    def test_dynamic_concurrency_eco_low_resource(self, mock_ram, mock_cpu):
        """Low resource system (2 threads, 4GB RAM) should use conservative single/dual workers."""
        cfg = DeviceManager.get_optimal_concurrency_config(profile="eco")
        self.assertEqual(cfg.tier, HardwareTier.LOW_RESOURCE)
        self.assertEqual(cfg.whisper_compute_type, "int8")
        self.assertEqual(cfg.batch_size, 1)

    def test_custom_concurrency_profile(self):
        """Custom profile respects user specified worker count."""
        cfg = DeviceManager.get_optimal_concurrency_config(profile="custom", custom_workers=12)
        self.assertEqual(cfg.clip_workers, 12)

    def test_ffmpeg_hwaccel_encoder_detection(self):
        """FFmpeg encoder detection should return a tuple with encoder string and arguments list."""
        encoder, flags = DeviceManager.get_ffmpeg_hwaccel_encoder()
        self.assertIsInstance(encoder, str)
        self.assertIsInstance(flags, list)
        self.assertTrue(len(flags) >= 1)

    def test_configure_runtime_environment_safe(self):
        """Configuring runtime environment should execute without throwing exceptions."""
        try:
            DeviceManager.configure_runtime_environment(profile="auto")
            DeviceManager.release_gpu_memory()
        except Exception as e:
            self.fail(f"configure_runtime_environment threw exception: {e}")


if __name__ == "__main__":
    unittest.main()
