"""Exercise the user-facing ZIP entry points, not only the pack parser."""
from pathlib import Path
from unittest.mock import patch
import zipfile

from core.models import PipelineState
from test_agent_bridge import window, pump


def test_zip_dropped_on_video_panel_opens_pack_instead_of_video_warning(window, tmp_path):
    win, _ = window
    archive = tmp_path / 'pack.zip'
    archive.write_bytes(b'ZIP entry point test')
    with patch.object(win, 'load_pack_zip') as load_pack, \
         patch.object(win, '_check_unsaved_changes', return_value=True), \
         patch('gui.main_window.QMessageBox.warning') as warning:
        win._video_panel.video_dropped.emit(archive)
        load_pack.assert_called_once_with(archive)
        warning.assert_not_called()


def test_import_button_accepts_zip_and_uses_pack_workflow(window, tmp_path):
    win, _ = window
    archive = tmp_path / 'pack.zip'
    with patch('gui.main_window.QFileDialog.getOpenFileName', return_value=(str(archive), '')), \
         patch.object(win, 'load_pack_zip') as load_pack, \
         patch.object(win, '_check_unsaved_changes', return_value=True), \
         patch.object(win, '_prompt_active_project_action', return_value='cancel') as video_prompt:
        win.on_import_video()
        load_pack.assert_called_once_with(archive)
        video_prompt.assert_not_called()


def test_open_project_zip_populates_real_dialogue_table(window, tmp_path):
    win, app = window
    win._state = PipelineState()
    archive = tmp_path / 'pack.zip'
    with zipfile.ZipFile(archive, 'w') as pack:
        pack.writestr('voice pack/_pack_info.ini', '[data]\ntitle="Imported pack"\nauthors=["Test"]\n')
        pack.writestr('voice pack/001_CHARACTER.txt', '[data]\ncaption="Imported dialogue"\ndub_timestamps=[1.000, 2.000]\ndub_characters=["Hero"]\n')
    with patch('gui.main_window.QFileDialog.getOpenFileName', return_value=(str(archive), '')), \
         patch('gui.main_window.QStandardPaths.writableLocation', return_value=str(tmp_path)), \
         patch('gui.main_window.QFileDialog.getExistingDirectory') as choose_folder, \
         patch('gui.main_window.QMessageBox.critical') as error:
        win.on_open_project()
        pump(app, lambda: getattr(win, '_pack_import_worker', None) is None, timeout=10)
        app.processEvents()
        error.assert_not_called()
        choose_folder.assert_not_called()
        assert len(win._state.dialogues) == 1
        assert win._state.dialogues[0].caption == 'Imported dialogue'
        assert win._dialogue_table.table.rowCount() == 1
        assert win._state.pack_info.title == 'Imported pack'
        assert win._current_project_path is None and win._is_dirty
        assert win._settings['recent_projects'][0] == str(archive.resolve())


def test_zip_import_does_not_discard_unsaved_project_when_cancelled(window, tmp_path):
    win, _ = window
    previous = win._state
    with patch.object(win, '_check_unsaved_changes', return_value=False), \
         patch.object(win, 'load_pack_zip') as load_pack:
        win._video_panel.video_dropped.emit(tmp_path / 'pack.zip')
        load_pack.assert_not_called()
        assert win._state is previous


def test_video_drop_still_uses_existing_import_confirmation(window, tmp_path):
    win, _ = window
    path = tmp_path / 'sample.mp4'
    with patch.object(win, 'on_import_video_file') as import_video:
        win._video_panel.video_dropped.emit(path)
        import_video.assert_called_once_with(path)


def test_invalid_zip_shows_error_and_clears_worker_without_changing_project(window, tmp_path):
    win, app = window
    previous = win._state
    archive = tmp_path / 'invalid.zip'
    archive.write_text('This is not a ZIP')
    with patch.object(win, '_check_unsaved_changes', return_value=True), \
         patch('gui.main_window.QStandardPaths.writableLocation', return_value=str(tmp_path)), \
         patch('gui.main_window.QMessageBox.critical') as error:
        win.on_open_file(archive)
        pump(app, lambda: getattr(win, '_pack_import_worker', None) is None)
        error.assert_called_once()
        assert win._pack_import_progress is None
        assert win._state is previous

