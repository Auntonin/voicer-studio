"""Regression coverage for missing export assets and importable pack references."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from types import SimpleNamespace
from unittest.mock import patch
import subprocess
import zipfile
import time

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage

from config import SUBPROCESS_FLAGS
from core.models import DialogueItem, PackInfo, PipelineState, SpeakerInfo
from core.pack_builder import PackBuilder
from core.project_manager import ProjectManager
from core.quality_checker import QualityChecker
from gui.export_dialog import ExportDialog, FullExportWorker

APP = QApplication.instance() or QApplication([])

@pytest.fixture
def source_state(tmp_path):
    video = tmp_path / 'source.mp4'
    subprocess.run(['ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=red:s=160x90:r=10',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                    '-t', '3', '-c:v', 'mpeg4', '-c:a', 'aac', str(video)],
                   check=True, capture_output=True, creationflags=SUBPROCESS_FLAGS)
    state = PipelineState(video_path=video, video_duration=3.0)
    state.pack_info = PackInfo(title='Regression', include_dub_video=False)
    state.speakers['hero'] = SpeakerInfo('hero', 'Hero')
    state.dialogues = [DialogueItem(1, 'hero', 0.2, 1.2, caption='Hello')]
    return state

def test_autofix_worker_zip_reimports_with_real_frame(source_state, tmp_path):
    worker = FullExportWorker(source_state, tmp_path / 'output', tmp_path / 'export.zip', {})
    errors, finished = [], []
    worker.error.connect(errors.append)
    worker.finished.connect(lambda *args: finished.append(args))
    worker.run()
    assert not errors, errors
    assert finished
    assert source_state.dialogues[0].image_path is None
    assert source_state.dialogues[0].audio_path is None
    unpacked = tmp_path / 'unpacked'
    with zipfile.ZipFile(tmp_path / 'export.zip') as archive:
        assert archive.testzip() is None
        archive.extractall(unpacked)
    imported = ProjectManager.load_from_pack_folder(next(unpacked.iterdir()))
    assert imported.dialogues[0].caption == 'Hello'
    with Image.open(imported.dialogues[0].image_path) as frame:
        red, green, blue = frame.convert('RGB').getpixel((50, 40))
        assert red > 150 and green < 80 and blue < 80

def test_backing_repair_uses_separated_background(source_state, tmp_path):
    background = tmp_path / 'background.wav'
    subprocess.run(['ffmpeg', '-y', '-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=48000',
                    '-t', '3', str(background)], check=True, capture_output=True, creationflags=SUBPROCESS_FLAGS)
    source_state.separated_bg_path = background
    with patch('core.pack_builder.subprocess.run', wraps=subprocess.run) as calls:
        PackBuilder().build_pack(source_state, tmp_path / 'output', {})
    backing_calls = [call.args[0] for call in calls.call_args_list if '-i' in call.args[0] and str(call.args[0][-1]).endswith('_backing_track.mp3')]
    assert backing_calls
    assert str(background) == backing_calls[-1][backing_calls[-1].index('-i') + 1]

def test_missing_backing_is_detected_even_without_path(source_state):
    app = QApplication.instance() or QApplication([])
    assert ExportDialog._detect_missing_assets(SimpleNamespace(state=source_state))['backing']

def test_corrupt_cue_reference_fails_validation(source_state, tmp_path):
    pack = PackBuilder().build_pack(source_state, tmp_path / 'output', {})
    cue = source_state.dialogues[0].txt_path
    cue.write_text(cue.read_text(encoding='utf-8').replace('001_Hero.png', 'missing.png'), encoding='utf-8')
    assert QualityChecker().has_errors(QualityChecker().check_all(source_state, pack))

def test_repaired_icon_follows_renamed_image(source_state, tmp_path):
    image = tmp_path / 'old_image.png'
    Image.new('RGB', (20, 20), 'blue').save(image)
    source_state.dialogues[0].image_path = image
    source_state.pack_info.icon = image.name
    pack = PackBuilder().build_pack(source_state, tmp_path / 'output', {})
    imported = ProjectManager.load_from_pack_folder(pack)
    assert (pack / imported.pack_info.icon).is_file()
    second = PackBuilder().build_pack(source_state, tmp_path / 'output', {})
    assert not QualityChecker().has_errors(QualityChecker().check_all(source_state, second))

def test_corrupt_image_is_repaired_from_video(source_state, tmp_path):
    image = tmp_path / 'broken.png'
    image.write_bytes(b'not an image')
    source_state.dialogues[0].image_path = image
    pack = PackBuilder().build_pack(source_state, tmp_path / 'output', {})
    assert not QualityChecker().has_errors(QualityChecker().check_all(source_state, pack))
    assert image.read_bytes() == b'not an image'

def test_export_failure_leaves_source_untouched(source_state, tmp_path):
    worker = FullExportWorker(source_state, tmp_path / 'output', tmp_path / 'export.zip', {})
    errors = []
    worker.error.connect(errors.append)
    with patch('core.pack_builder.PackBuilder._create_fallback_image', side_effect=RuntimeError('write failed')), \
         patch('core.frame_extractor.FrameExtractor.find_best_frame', return_value=None):
        worker.run()
    assert errors
    assert not (tmp_path / 'export.zip').exists()
    assert source_state.dialogues[0].audio_path is None

def test_non_mp4_video_is_remuxed_to_real_mp4(source_state, tmp_path):
    mkv = tmp_path / 'source.mkv'
    subprocess.run(['ffmpeg', '-y', '-i', str(source_state.video_path), '-c', 'copy', str(mkv)],
                   check=True, capture_output=True, creationflags=SUBPROCESS_FLAGS)
    source_state.video_path = mkv
    source_state.pack_info.include_dub_video = True
    pack = PackBuilder().build_pack(source_state, tmp_path / 'output', {'include_dub_video': True})
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=format_name',
                             '-of', 'default=nw=1', str(pack / 'dub_video.mp4')],
                            check=True, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
    assert 'mp4' in result.stdout
    assert not QualityChecker().has_errors(QualityChecker().check_all(source_state, pack))

def test_failed_backing_encoder_does_not_report_success(source_state, tmp_path):
    real_run = subprocess.run
    def fail_backing(command, *args, **kwargs):
        if str(command[-1]).endswith('_backing_track.mp3'):
            return subprocess.CompletedProcess(command, 1, stderr=b'encoder failed')
        return real_run(command, *args, **kwargs)
    with patch('core.pack_builder.subprocess.run', side_effect=fail_backing):
        with pytest.raises(RuntimeError):
            PackBuilder().build_pack(source_state, tmp_path / 'output', {})

def test_new_clip_preview_persists_image(source_state):
    from gui.clip_editor import ClipEditor
    app = QApplication.instance() or QApplication([])
    editor = ClipEditor()
    editor.load_item(source_state.dialogues[0], source_state)
    deadline = time.monotonic() + 5
    while not source_state.dialogues[0].image_path and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    try:
        assert source_state.dialogues[0].image_path
        assert QualityChecker()._check_png_readable(source_state.dialogues[0].image_path)
        assert source_state.dialogues[0].image_path.parent == source_state.video_path.parent / 'output' / 'frames'
    finally:
        editor.close()
        if source_state.dialogues[0].image_path:
            source_state.dialogues[0].image_path.unlink(missing_ok=True)

@pytest.mark.parametrize('method', ['_on_split', '_on_split_at_playhead'])
def test_split_invalidates_original_audio(source_state, tmp_path, method):
    from gui.main_window import MainWindow
    item = source_state.dialogues[0]
    item.audio_path = tmp_path / 'old.mp3'
    window = SimpleNamespace(_state=source_state,
                             _timeline=SimpleNamespace(current_time=0.7, _get_clip_at_time=lambda t: item),
                             _push_undo=lambda: None, _mark_dirty=lambda *args: None,
                             _refresh_all_views=lambda: None, _log_message=lambda *args: None)
    getattr(MainWindow, method)(window, *([1] if method == '_on_split' else []))
    assert item.audio_path is None

def test_stale_preview_cannot_change_another_clip(source_state, tmp_path):
    from gui.clip_editor import ClipEditor
    editor = ClipEditor()
    original = source_state.dialogues[0]
    editor.load_item(original, source_state)
    request_id = editor._frame_preview_req_id
    other = DialogueItem(2, 'hero', 1.5, 2.0)
    editor.load_item(other, source_state)
    editor._frame_preview_timer.stop()
    stale = tmp_path / 'stale.png'
    Image.new('RGB', (10, 10), 'red').save(stale)
    editor._on_frame_qimage_ready(request_id, QImage(str(stale)), original, str(stale))
    assert other.image_path is None
    assert original.image_path is None
    assert not stale.exists()
    editor.close()

def test_cancelled_export_creates_no_zip(source_state, tmp_path):
    worker = FullExportWorker(source_state, tmp_path / 'output', tmp_path / 'export.zip', {})
    errors, finished = [], []
    worker.error.connect(errors.append)
    worker.finished.connect(lambda *args: finished.append(args))
    worker.cancel()
    worker.run()
    assert not errors  # User cancellation is deliberately not reported as an export error.
    assert not finished
    assert not (tmp_path / 'export.zip').exists()
    assert source_state.dialogues[0].image_path is None

def test_ogv_source_still_exports_compatible_videos(source_state, tmp_path):
    ogv = tmp_path / 'source.ogv'
    subprocess.run(['ffmpeg', '-y', '-i', str(source_state.video_path), '-c:v', 'libtheora',
                    '-c:a', 'libvorbis', str(ogv)], check=True, capture_output=True,
                   creationflags=SUBPROCESS_FLAGS)
    source_state.video_path = ogv
    source_state.pack_info.include_dub_video = True
    pack = PackBuilder().build_pack(source_state, tmp_path / 'output', {'include_dub_video': True})
    assert (pack / 'dub_video.ogv').read_bytes() == ogv.read_bytes()
    assert not QualityChecker().has_errors(QualityChecker().check_all(source_state, pack))
