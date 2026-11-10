"""Repeatable offscreen IPC/UI microbenchmark, not a media/desktop release gate.

Prints raw measurements only. No settings, credentials or user files are saved.
AI prewarm/update checks are disabled; run each mode in a fresh process.
"""
import time
_started = time.perf_counter()
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication
from core.models import DialogueItem, PipelineState, SpeakerInfo
from gui.main_window import MainWindow


def memory_bytes():
    if os.name != 'nt':
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return value if sys.platform == 'darwin' else value * 1024
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [(name, ctypes.c_size_t) for name in
            ('peak', 'working', 'paged_peak', 'paged', 'nonpaged_peak', 'nonpaged', 'pagefile', 'pagefile_peak')]
    info = Counters()
    info.cb = ctypes.sizeof(info)
    kernel = ctypes.WinDLL('kernel32')
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL('psapi')
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(info), info.cb):
        raise OSError('Memory measurement unavailable')
    return info.working


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('off', 'on'), required=True)
    args = parser.parse_args()
    app = QApplication([])
    constructor = time.perf_counter()
    with patch.object(MainWindow, '_load_settings', return_value={'check_updates_startup': False}), \
         patch('core.device_manager.device_manager.prewarm_async'):
        window = MainWindow()
    result = {'mode': args.mode, 'python': sys.version.split()[0], 'platform': sys.platform,
        'constructor_ms': (time.perf_counter() - constructor) * 1000,
        'imports_and_constructor_ms': (time.perf_counter() - _started) * 1000,
        'fixture_clips': 10000, 'page_size': 50, 'samples': 50,
        'cpu_cores': os.cpu_count(), 'memory_kind': 'working_set' if os.name == 'nt' else 'peak_rss'}
    window._state = PipelineState(video_duration=20000, speakers={'one': SpeakerInfo('one', 'fixture')},
        dialogues=[DialogueItem(i + 1, 'one', i * 2, i * 2 + 1, 'fixture caption') for i in range(10000)])
    if args.mode == 'on':
        window._enable_agent_bridge()
    result['sdk_imported'] = 'mcp' in sys.modules
    result['listener'] = window._agent_bridge is not None
    result['memory_idle_bytes'] = memory_bytes()
    gaps = []
    last = [time.perf_counter()]
    def tick():
        now = time.perf_counter()
        gaps.append(max(0, (now - last[0]) * 1000 - 10))
        last[0] = now
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(tick)
    timer.start()
    idle_cpu, idle_wall = time.process_time(), time.perf_counter()
    while time.perf_counter() - idle_wall < 1.5:
        app.processEvents()
        time.sleep(.001)
    timer.stop()
    elapsed = time.perf_counter() - idle_wall
    cpu = time.process_time() - idle_cpu
    result.update(idle_wall_seconds=elapsed, idle_cpu_seconds=cpu,
        idle_cpu_percent_normalized=cpu / elapsed / (os.cpu_count() or 1) * 100,
        idle_cpu_percent_one_core=cpu / elapsed * 100,
        event_loop_excess_p95_ms=sorted(gaps)[int(len(gaps) * .95)])
    if args.mode == 'on':
        ticket = window._agent_bridge.open_session({'read_project'})
        # Qt's synchronous socket waits must not share the GUI's Python GIL.
        # This models the actual separate gateway process, not a same-process thread.
        code = '''import json, os, time
from PySide6.QtCore import QCoreApplication
from core.agent_client import AgentClient
app = QCoreApplication([])
client = AgentClient(os.environ.pop('VOICER_AGENT_ENDPOINT'), os.environ.pop('VOICER_AGENT_CREDENTIAL'))
times = []
for _ in range(50):
    start = time.perf_counter()
    client.request({'method': 'snapshot', 'limit': 50})
    times.append((time.perf_counter() - start) * 1000)
print(json.dumps(times))
'''
        from config import SUBPROCESS_FLAGS
        process = subprocess.Popen([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, 'VOICER_AGENT_ENDPOINT': ticket.endpoint, 'VOICER_AGENT_CREDENTIAL': ticket.credential},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=SUBPROCESS_FLAGS)
        while process.poll() is None:
            app.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            time.sleep(.001)
        stdout, stderr = process.communicate()
        if process.returncode:
            window._disable_agent_bridge()
            raise RuntimeError('IPC benchmark failed in separate process')
        times = json.loads(stdout)
        result.update(ipc_page_raw_ms=times, ipc_page_p95_ms=sorted(times)[47])
        window._disable_agent_bridge()
        before = memory_bytes()
        for _ in range(50):
            window._enable_agent_bridge()
            window._disable_agent_bridge()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
        result.update(toggle_cycles=50, memory_before_toggles_bytes=before, memory_after_toggles_bytes=memory_bytes())
    window._autosave_timer.stop()
    window._state = PipelineState()
    window._is_dirty = False
    window.deleteLater()
    print(json.dumps(result))


if __name__ == '__main__':
    main()
