import io
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from core.models import PipelineState, PipelineStep, DialogueItem
from core.pipeline import PipelineWorker
from core.clip_generator import ClipGenerator

def test_analyze_does_not_time_out_active_ogv_encoding(tmp_path):
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'source')
    state = PipelineState(video_path=source, video_duration=3600)
    worker = PipelineWorker(state, {})
    worker._output_dir = tmp_path / 'pack'
    worker._output_dir.mkdir()
    def run(command, **kwargs):
        if 'libtheora' in command:
            assert 'timeout' not in kwargs, 'Active encoding is killed after 600 seconds'
            Path(command[-1]).write_bytes(b'encoded')
        return SimpleNamespace(returncode=0, stdout='libtheora', stderr='')
    def popen(command, **kwargs):
        Path(command[-1]).write_bytes(b'encoded')
        return SimpleNamespace(stdout=io.StringIO('out_time_us=3600000000\nprogress=end\n'),
                               returncode=0, wait=lambda **kw: 0, kill=lambda: None)
    with patch('subprocess.run', side_effect=run), patch('subprocess.Popen', side_effect=popen):
        worker._step_pack_build()
    assert state.is_step_done(PipelineStep.PACK_BUILD)
    assert (worker.output_dir / 'dub_video.ogv').read_bytes() == b'encoded'

def test_completed_retry_clears_previous_error():
    state = PipelineState()
    state.step_errors[PipelineStep.PACK_BUILD] = 'timeout'
    PipelineWorker(state, {})._complete_step(PipelineStep.PACK_BUILD)
    assert PipelineStep.PACK_BUILD not in state.step_errors

def test_cached_clip_generation_restores_output_directory(tmp_path):
    state = PipelineState(video_path=tmp_path / 'source.mp4')
    state.step_completed[PipelineStep.CLIP_GENERATION] = True
    state.dialogues = [DialogueItem(1, 'speaker', 0, 1, audio_path=tmp_path / 'pack' / '001.mp3')]
    state.dialogues[0].audio_path.parent.mkdir()
    state.dialogues[0].audio_path.write_bytes(b'clip')
    worker = PipelineWorker(state, {})
    worker._step_clip_generation()
    assert worker.output_dir == tmp_path / 'pack'

def test_clip_worker_failure_is_fatal(tmp_path):
    state = PipelineState(dialogues=[DialogueItem(1, 'speaker', 0, 1)])
    with patch.object(ClipGenerator, 'generate_clip', side_effect=RuntimeError('encoder failed')):
        with pytest.raises(RuntimeError, match='encoder failed'):
            ClipGenerator().generate_all_clips(state, tmp_path / 'audio.wav', tmp_path, max_workers=1)

def test_validation_failure_propagates(tmp_path):
    worker = PipelineWorker(PipelineState(video_path=tmp_path / 'source.mp4'), {'output_dir': str(tmp_path)})
    with patch('core.quality_checker.QualityChecker.check_all',
               return_value=[SimpleNamespace(level='error', message='Missing backing track')]):
        with pytest.raises(RuntimeError, match='Pack validation failed'):
            worker._step_validation()

from core.pack_builder import PackBuilder


def test_encoder_continues_beyond_600_seconds_when_progress_advances(tmp_path):
    destination = tmp_path / 'dub_video.ogv'
    clock = [0]
    def monotonic():
        clock[0] += 200
        return clock[0]
    def popen(command, **kwargs):
        Path(command[-1]).write_bytes(b'complete')
        return SimpleNamespace(stdout=io.StringIO(''.join(f'out_time_us={n * 1000000}\n' for n in range(1, 10))),
                               returncode=0, wait=lambda **kw: 0, kill=lambda: None)
    progress = []
    with patch('core.pack_builder.subprocess.Popen', side_effect=popen), \
         patch('core.pack_builder.time.monotonic', side_effect=monotonic):
        PackBuilder._encode_video(['-i', 'source.mp4'], destination, progress.append)
    assert clock[0] > 600
    assert progress == list(range(1, 10))
    assert destination.read_bytes() == b'complete'
    assert list(tmp_path.iterdir()) == [destination]


@pytest.mark.parametrize('failure', ['encoder', 'cancel', 'stall', 'callback'])
def test_failed_encoding_preserves_previous_video_and_removes_partial(tmp_path, failure):
    destination = tmp_path / 'dub_video.ogv'
    destination.write_bytes(b'previous valid video')
    killed = []
    def popen(command, **kwargs):
        Path(command[-1]).write_bytes(b'partial')
        proc = SimpleNamespace(stdout=io.StringIO('out_time_us=1000000\n'),
                               returncode=1 if failure == 'encoder' else None)
        def kill():
            killed.append(True)
            proc.returncode = -9
        def wait(**kwargs):
            proc.returncode = proc.returncode if proc.returncode is not None else 0
        proc.kill, proc.wait = kill, wait
        return proc
    def report(seconds):
        if failure == 'callback':
            raise RuntimeError('callback failed')
    clock = [0]
    def monotonic():
        clock[0] += 601
        return clock[0]
    expected = {'encoder': RuntimeError, 'cancel': InterruptedError,
                'stall': TimeoutError, 'callback': RuntimeError}[failure]
    with patch('core.pack_builder.subprocess.Popen', side_effect=popen):
        if failure == 'stall':
            with patch('core.pack_builder.time.monotonic', side_effect=monotonic), pytest.raises(expected):
                PackBuilder._encode_video([], destination)
        else:
            with pytest.raises(expected):
                PackBuilder._encode_video([], destination, report, cancel_check=lambda: failure == 'cancel')
    assert destination.read_bytes() == b'previous valid video'
    assert list(tmp_path.iterdir()) == [destination]
    if failure != 'encoder':
        assert killed


def test_analyze_retry_replaces_stale_ogv_and_creates_real_mp4(tmp_path):
    import subprocess
    from config import SUBPROCESS_FLAGS
    if not PackBuilder.check_theora_encoder_available():
        pytest.skip('FFmpeg libtheora unavailable')
    source = tmp_path / 'source.mkv'
    subprocess.run(['ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=red:s=160x90:r=10',
                    '-t', '2', '-c:v', 'mpeg4', str(source)], check=True,
                   capture_output=True, creationflags=SUBPROCESS_FLAGS)
    pack = tmp_path / 'pack'
    pack.mkdir()
    (pack / 'dub_video.ogv').write_bytes(b'leftover from timeout')
    (pack / 'dub_video.mp4').write_bytes(b'wrong container')
    state = PipelineState(video_path=source, video_duration=2)
    worker = PipelineWorker(state, {})
    worker._output_dir = pack
    state.step_errors[PipelineStep.PACK_BUILD] = 'old timeout'
    worker._step_pack_build()
    for name, container in [('dub_video.mp4', 'mp4'), ('dub_video.ogv', 'ogg')]:
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=format_name,duration',
                                 '-of', 'json', str(pack / name)], check=True,
                                capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
        import json
        metadata = json.loads(result.stdout)['format']
        assert container in metadata['format_name']
        assert abs(float(metadata['duration']) - 2) < 0.2
    assert state.is_step_done(PipelineStep.PACK_BUILD)
    assert PipelineStep.PACK_BUILD not in state.step_errors
    assert not list(pack.glob('.*.part*'))


def test_cancelled_pack_is_not_marked_complete(tmp_path):
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'source')
    state = PipelineState(video_path=source)
    worker = PipelineWorker(state, {'output_dir': str(tmp_path)})
    worker.cancel()
    worker._step_pack_build()
    assert worker.outcome == 'cancelled'
    assert not state.is_step_done(PipelineStep.PACK_BUILD)
    assert PipelineStep.PACK_BUILD not in state.step_errors


def test_new_analyze_does_not_overwrite_existing_pack(tmp_path):
    existing = tmp_path / 'Untitled_Pack'
    existing.mkdir()
    (existing / '001.mp3').write_bytes(b'user clip')
    worker = PipelineWorker(PipelineState(video_path=tmp_path / 'source.mp4'), {'output_dir': str(tmp_path)})
    assert worker._resolve_output_dir() == tmp_path / 'Untitled_Pack_1'
    assert (existing / '001.mp3').read_bytes() == b'user clip'


def test_backing_failure_stops_before_video_encoding(tmp_path):
    worker = PipelineWorker(PipelineState(video_path=tmp_path / 'source.mp4'), {'output_dir': str(tmp_path)})
    with patch('core.separator.VoiceSeparator.generate_backing_track', side_effect=RuntimeError('disk full')):
        with pytest.raises(RuntimeError, match='disk full'):
            worker._step_backing_track()
    assert not worker.state.is_step_done(PipelineStep.BACKING_TRACK)


def test_validation_failure_never_emits_pack_ready(tmp_path):
    from contextlib import ExitStack
    worker = PipelineWorker(PipelineState(video_path=tmp_path / 'source.mp4'), {'output_dir': str(tmp_path)})
    ready, finished, settled = [], [], []
    worker.signals.pack_ready.connect(ready.append)
    worker.signals.finished.connect(lambda: finished.append(True))
    worker.signals.settled.connect(settled.append)
    with ExitStack() as stack:
        for method in ['_step_audio_extract', '_step_voice_separation', '_step_vad', '_step_transcription',
                       '_step_diarization', '_step_clip_generation', '_step_frame_extraction',
                       '_step_backing_track', '_step_pack_build']:
            stack.enter_context(patch.object(worker, method))
        stack.enter_context(patch('core.device_manager.device_manager.get_optimal_device',
                                 return_value=SimpleNamespace(display_title='Test CPU')))
        stack.enter_context(patch('core.device_manager.device_manager.configure_runtime_environment'))
        stack.enter_context(patch('core.device_manager.device_manager.get_optimal_concurrency_config',
                                 return_value=SimpleNamespace(tier=SimpleNamespace(value='test'),
                                 clip_workers=1, whisper_threads=1, ram_gb=1)))
        stack.enter_context(patch('core.device_manager.device_manager.release_gpu_memory'))
        stack.enter_context(patch('core.project_manager.ProjectManager.cleanup_stale_temp_files'))
        stack.enter_context(patch('core.quality_checker.QualityChecker.check_all',
                                 return_value=[SimpleNamespace(level='error', message='Missing backing track')]))
        worker.run()
    assert worker.outcome == 'failed'
    assert worker.state.current_step == PipelineStep.ERROR
    assert not ready and not finished
    assert settled == ['failed']


def test_cancel_stops_encoder_even_without_stdout_progress(tmp_path):
    from threading import Event
    release = Event()
    killed = []
    class SilentOutput:
        def __iter__(self):
            release.wait(timeout=5)
            return iter(())
        def close(self):
            pass
    def popen(command, **kwargs):
        Path(command[-1]).write_bytes(b'partial')
        proc = SimpleNamespace(stdout=SilentOutput(), returncode=None)
        def kill():
            killed.append(True)
            proc.returncode = -9
            release.set()
        proc.kill = kill
        proc.wait = lambda **kwargs: None
        return proc
    checks = [0]
    def cancelled():
        checks[0] += 1
        return checks[0] >= 2
    with patch('core.pack_builder.subprocess.Popen', side_effect=popen), pytest.raises(InterruptedError):
        PackBuilder._encode_video([], tmp_path / 'dub_video.ogv', cancel_check=cancelled)
    assert killed
    assert not list(tmp_path.iterdir())
