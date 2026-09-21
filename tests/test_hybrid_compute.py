"""
tests/test_hybrid_compute.py
=============================
Unit tests for DeviceManager dynamic performance scoring, universal multi-vendor GPU detection,
and hybrid CPU+GPU work partitioning plans.
"""

import unittest
from core.device_manager import DeviceManager, ComputeDevice, DeviceBackend


class TestHybridCompute(unittest.TestCase):

    def test_rtx3070_gpu_outperforms_standard_cpu(self):
        """RTX 3070 GPU score should significantly exceed standard CPU score."""
        gpu = ComputeDevice(
            backend=DeviceBackend.CUDA,
            device_id="cuda:0",
            name="NVIDIA GeForce RTX 3070",
            vendor="NVIDIA",
            vram_bytes=8 * (1024 ** 3),
            is_gpu=True,
            fp16_supported=True
        )
        cpu = ComputeDevice(
            backend=DeviceBackend.CPU,
            device_id="cpu",
            name="8-Core CPU",
            vendor="CPU",
            is_gpu=False
        )

        gpu_score = DeviceManager.calculate_performance_score(gpu)
        cpu_score = DeviceManager.calculate_performance_score(cpu)

        self.assertGreater(gpu_score, 1000.0)
        self.assertGreater(gpu_score, cpu_score)

    def test_high_core_threadripper_outperforms_weak_gpu(self):
        """A 64-thread CPU score should exceed a weak integrated / GT 1030 GPU score."""
        weak_gpu = ComputeDevice(
            backend=DeviceBackend.CUDA,
            device_id="cuda:0",
            name="NVIDIA GeForce GT 1030",
            vendor="NVIDIA",
            vram_bytes=2 * (1024 ** 3),
            is_gpu=True,
            fp16_supported=False
        )
        monster_cpu = ComputeDevice(
            backend=DeviceBackend.CPU,
            device_id="cpu",
            name="AMD Ryzen Threadripper 3990X (64 Threads)",
            vendor="AMD",
            is_gpu=False
        )

        weak_gpu_score = DeviceManager.calculate_performance_score(weak_gpu)
        cpu_score = DeviceManager.calculate_performance_score(monster_cpu)

        # 64-thread CPU score should comfortably beat weak GT 1030 GPU
        self.assertGreater(cpu_score, weak_gpu_score)

    def test_hybrid_execution_plan_generation(self):
        """get_hybrid_execution_plan returns a valid plan with Thai summary and workload distribution."""
        plan = DeviceManager.get_hybrid_execution_plan(preference="auto")
        self.assertIsNotNone(plan.primary_device)
        self.assertGreater(plan.cpu_score, 0.0)
        self.assertIn(plan.selected_mode, ["HYBRID_GPU_PRIMARY", "CPU_VECTORIZED_PRIMARY", "DUAL_COOPERATIVE"])
        self.assertTrue(len(plan.summary_th) > 10)


if __name__ == "__main__":
    unittest.main()
