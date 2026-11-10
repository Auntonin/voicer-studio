"""Update safety and real package installation regressions."""
import json
import subprocess
import sys
import zipfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.updater import UpdateDownloaderThread, UpdateInfo, apply_update_and_restart


def test_windows_update_does_not_launch_batch(tmp_path):
    archive = tmp_path / 'update.zip'
    archive.write_bytes(b'fixture')
    with patch('core.updater.sys.platform', 'win32'), patch('core.updater.subprocess.Popen') as launch:
        ok, message = apply_update_and_restart(archive, True, tmp_path / 'VoicerStudio.exe')
    assert ok, message
    command = launch.call_args.args[0]
    assert command[0].lower() != 'cmd.exe'
    assert not any(str(arg).lower().endswith('.bat') for arg in command)


def test_checksum_download_failure_is_not_ignored(tmp_path):
    info = UpdateInfo('1.1.2', 'v1.1.2', 'Patch', '', '', '', 'update.zip',
                      'https://example.test/update.zip', 7, True, 'https://example.test/update.zip.sha256')
    worker = UpdateDownloaderThread(info, tmp_path)
    errors, finished = [], []
    worker.error.connect(errors.append)
    worker.finished.connect(lambda *args: finished.append(args))
    response = MagicMock()
    response.__enter__.return_value = response
    response.headers = {'Content-Length': '7'}
    response.read.side_effect = [b'package', b'']
    with patch('urllib.request.urlopen', side_effect=[OSError('checksum unavailable'), response]):
        worker.run()
    assert errors
    assert not finished
    assert not (tmp_path / 'update.zip').exists()


def make_package(path, members):
    with zipfile.ZipFile(path, 'w') as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def test_mcp_manifest_update_preserves_projects_models_settings(tmp_path):
    from scripts.update_installer import install_update
    target = tmp_path / 'installed'
    target.mkdir()
    for filename, content in [('settings.json', 'user settings'), ('project.voicer', 'user project')]:
        (target / filename).write_text(content)
    (target / 'models').mkdir()
    (target / 'models' / 'model.bin').write_bytes(b'preserve weights')
    archive = tmp_path / 'update.zip'
    make_package(archive, {'main.py': 'new code', 'config.py': 'new config',
        'VoicerStudio.exe': 'fixture launcher', 'requirements-mcp.txt': 'mcp==2.3.0',
        'scripts/mcp_server.py': 'gateway code'})
    install_update(archive, True, target, target / 'VoicerStudio.exe')
    assert (target / 'requirements-mcp.txt').read_text() == 'mcp==2.3.0'
    assert (target / 'settings.json').read_text() == 'user settings'
    assert (target / 'project.voicer').read_text() == 'user project'
    assert (target / 'models' / 'model.bin').read_bytes() == b'preserve weights'


def test_nested_release_installs_and_preserves_user_data(tmp_path):
    from scripts.update_installer import install_update
    target = tmp_path / 'installed ภาษาไทย & space'
    target.mkdir()
    (target / 'settings.json').write_text('user settings')
    (target / 'main.py').write_text('old code')
    (target / 'models').mkdir()
    (target / 'models' / 'user-model.bin').write_bytes(b'model')
    package = tmp_path / 'release.zip'
    make_package(package, {'VoicerStudio-v1.1.2-win64/main.py': 'new code',
                           'VoicerStudio-v1.1.2-win64/config.py': 'APP_VERSION="1.1.2"',
                           'VoicerStudio-v1.1.2-win64/VoicerStudio.exe': 'new exe'})
    install_update(package, True, target, target / 'VoicerStudio.exe')
    assert (target / 'main.py').read_text() == 'new code'
    assert (target / 'settings.json').read_text() == 'user settings'
    assert (target / 'models' / 'user-model.bin').read_bytes() == b'model'
    assert not (target / 'VoicerStudio-v1.1.2-win64').exists()


@pytest.mark.parametrize('checksum,expected_error', [('0' * 64, 'mismatch'), ('invalid', 'valid SHA-256')])
def test_bad_checksum_never_replaces_existing_download(tmp_path, checksum, expected_error):
    info = UpdateInfo('1.1.2', 'v1.1.2', 'Patch', '', '', '', 'update.zip',
                      'https://example.test/update.zip', 7, True, 'https://example.test/update.zip.sha256')
    destination = tmp_path / 'update.zip'
    destination.write_bytes(b'previous valid download')
    worker = UpdateDownloaderThread(info, tmp_path)
    errors, finished = [], []
    worker.error.connect(errors.append)
    worker.finished.connect(lambda *args: finished.append(args))
    checksum_response = MagicMock()
    checksum_response.__enter__.return_value = checksum_response
    checksum_response.read.return_value = checksum.encode()
    package_response = MagicMock()
    package_response.__enter__.return_value = package_response
    package_response.headers = {'Content-Length': '7'}
    package_response.read.side_effect = [b'package', b'']
    with patch('urllib.request.urlopen', side_effect=[checksum_response, package_response]):
        worker.run()
    assert errors and expected_error in errors[0]
    assert not finished
    assert destination.read_bytes() == b'previous valid download'
    assert not (tmp_path / '.update.zip.part').exists()


def test_release_prefers_full_zip_even_when_exe_is_first():
    from core.updater import check_for_updates
    response = MagicMock()
    response.status = 200
    response.__enter__.return_value = response
    response.read.return_value = json.dumps({'tag_name': 'v1.1.2', 'assets': [
        {'name': 'VoicerStudio-win64.exe', 'browser_download_url': 'https://example.test/launcher.exe'},
        {'name': 'VoicerStudio-v1.1.2-win64.zip', 'browser_download_url': 'https://example.test/package.zip'},
        {'name': 'VoicerStudio-v1.1.2-win64.zip.sha256', 'browser_download_url': 'https://example.test/package.zip.sha256'},
    ]}).encode()
    with patch('urllib.request.urlopen', return_value=response), patch('core.updater.sys.platform', 'win32'):
        has_update, info, error = check_for_updates('1.1.1')
    assert has_update and not error
    assert info.is_zip


def test_release_does_not_offer_windows_package_to_linux():
    from core.updater import check_for_updates
    response = MagicMock()
    response.status = 200
    response.__enter__.return_value = response
    response.read.return_value = json.dumps({'tag_name': 'v1.1.2', 'assets': [
        {'name': 'VoicerStudio-v1.1.2-win64.zip', 'browser_download_url': 'https://example.test/package.zip'},
    ]}).encode()
    with patch('urllib.request.urlopen', return_value=response), patch('core.updater.sys.platform', 'linux'):
        has_update, info, error = check_for_updates('1.1.1')
    assert not has_update and info is None and error


def test_unsafe_archive_leaves_installation_unchanged(tmp_path):
    import pytest
    from scripts.update_installer import install_update
    target = tmp_path / 'installed'
    target.mkdir()
    (target / 'main.py').write_text('old code')
    package = tmp_path / 'unsafe.zip'
    make_package(package, {'../escape.txt': 'unsafe', 'main.py': 'new code'})
    with pytest.raises(ValueError):
        install_update(package, True, target, target / 'VoicerStudio.exe')
    assert (target / 'main.py').read_text() == 'old code'
    assert not (tmp_path / 'escape.txt').exists()


def test_copy_failure_rolls_back_all_changed_files(tmp_path):
    from scripts.update_installer import install_update
    target = tmp_path / 'installed'
    target.mkdir()
    (target / 'main.py').write_text('old code')
    package = tmp_path / 'release.zip'
    make_package(package, {'main.py': 'new code', 'config.py': 'new config', 'VoicerStudio.exe': 'new exe'})
    import shutil
    real_copy = shutil.copy2
    def fail_config(source, destination, *args, **kwargs):
        if Path(source).name == 'config.py' and Path(destination) == target / 'config.py':
            raise OSError('simulated write failure')
        return real_copy(source, destination, *args, **kwargs)
    with patch('scripts.update_installer.shutil.copy2', side_effect=fail_config):
        with pytest.raises(OSError):
            install_update(package, True, target, target / 'VoicerStudio.exe')
    assert (target / 'main.py').read_text() == 'old code'
    assert not (target / 'config.py').exists()
    assert not (target / 'VoicerStudio.exe').exists()


def test_source_rollback_to_git_head_preserves_new_settings_and_project(tmp_path):
    """Run the actual previous source loader in an isolated installation.

    No running application is downgraded; HEAD is the explicit rollback target.
    This validates source/settings compatibility, not a native installer smoke.
    """
    import io
    from core.models import DialogueItem, PipelineState, SpeakerInfo
    from core.project_manager import ProjectManager
    from scripts.update_installer import install_update
    from config import SUBPROCESS_FLAGS
    repository = Path(__file__).resolve().parents[1]
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repository, check=True,
                              capture_output=True, text=True).stdout.strip()
    snapshot = subprocess.run(['git', 'archive', '--format=zip', revision], cwd=repository,
                              check=True, capture_output=True).stdout
    allowed = {'main.py', 'config.py', 'VoicerStudio.exe', 'requirements.txt',
               'settings.example.json', 'README.md', 'LICENSE', 'core', 'gui',
               'scripts', 'locales', 'assets'}
    package = tmp_path / 'previous-source.zip'
    with zipfile.ZipFile(io.BytesIO(snapshot)) as source, zipfile.ZipFile(package, 'w') as archive:
        for item in source.infolist():
            if not item.is_dir() and Path(item.filename).parts[0] in allowed:
                archive.writestr(item, source.read(item))
    target = tmp_path / 'isolated rollback ภาษาไทย'
    target.mkdir()
    settings = {'mcp_enabled': True, 'check_updates_startup': False,
                'language': 'th', 'user_preference_fixture': 'preserved'}
    (target / 'settings.json').write_text(json.dumps(settings), encoding='utf-8')
    (target / 'models').mkdir()
    (target / 'models' / 'fixture.bin').write_bytes(b'preserved synthetic weights')
    (target / 'media').mkdir()
    (target / 'media' / 'fixture.bin').write_bytes(b'preserved synthetic media')
    project = target / 'fixture.voicer'
    state = PipelineState(video_duration=3, speakers={'one': SpeakerInfo('one', 'Fixture')},
                          dialogues=[DialogueItem(1, 'one', .2, 1.2, 'ทดสอบ rollback')])
    assert ProjectManager.save_project(state, project)
    before = {path.relative_to(target): path.read_bytes() for path in target.rglob('*') if path.is_file()}
    install_update(package, True, target, target / 'VoicerStudio.exe')
    # Orphaned optional source files are not removed by the updater: old startup
    # must not import or activate them merely because the new setting remains.
    (target / 'requirements-mcp.txt').write_text('mcp==2.3.0')
    code = '''
import json, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path.cwd()))
from core.project_manager import ProjectManager
from gui.main_window import MainWindow
with patch('core.credentials.get_huggingface_token', return_value=''):
    settings = MainWindow._load_settings(None)
assert settings['mcp_enabled'] is True
assert settings['user_preference_fixture'] == 'preserved'
state = ProjectManager.load_project(Path('fixture.voicer'))
assert state.dialogues[0].caption == 'ทดสอบ rollback'
assert state.dialogues[0].start == .2 and state.dialogues[0].end == 1.2
assert 'mcp' not in sys.modules and 'gui.agent_bridge' not in sys.modules
print(json.dumps({'rollback_loader': 'passed'}))
'''
    result = subprocess.run([sys.executable, '-c', code], cwd=target, capture_output=True,
                            text=True, encoding='utf-8', timeout=30, creationflags=SUBPROCESS_FLAGS)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['rollback_loader'] == 'passed'
    for relative, content in before.items():
        assert (target / relative).read_bytes() == content


def test_installer_runs_as_real_isolated_python_process(tmp_path):
    target = tmp_path / 'installed ภาษาไทย & space'
    target.mkdir()
    package = tmp_path / 'release.zip'
    make_package(package, {'VoicerStudio-v1.1.2-win64/main.py': 'new code',
                           'VoicerStudio-v1.1.2-win64/config.py': 'APP_VERSION="1.1.2"',
                           'VoicerStudio-v1.1.2-win64/VoicerStudio.exe': 'new exe'})
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'pid': 0, 'target_dir': str(target), 'target_exe': str(target / 'VoicerStudio.exe'),
                                    'package': str(package), 'is_zip': True, 'restart': False}), encoding='utf-8')
    helper = Path(__file__).resolve().parent.parent / 'scripts' / 'update_installer.py'
    from config import SUBPROCESS_FLAGS
    subprocess.run([sys.executable, '-I', str(helper), str(manifest)], check=True, timeout=15,
                   capture_output=True, creationflags=SUBPROCESS_FLAGS)
    assert json.loads((tmp_path / 'result.json').read_text())['success']
    assert (target / 'main.py').read_text() == 'new code'
