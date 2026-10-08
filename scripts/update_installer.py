"""Detached, standard-library update installer; never runs a shell or kills apps."""
import ctypes
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile


def wait_for_exit(pid: int, timeout: float = 120.0):
    if pid <= 0:
        return
    if os.name == 'nt':
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:  # Process already exited.
                return
            raise OSError('Cannot wait for the running application to exit')
        try:
            if kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
                raise TimeoutError('Application is still running; update not installed')
        finally:
            kernel.CloseHandle(handle)
    else:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.2)
        raise TimeoutError('Application is still running; update not installed')


def install_update(package: Path, is_zip: bool, target_dir: Path, target_exe: Path):
    """Stage first, replace only runtime files, and roll back on any copy failure."""
    target_dir = target_dir.resolve()
    if target_exe.resolve().parent != target_dir or not target_dir.is_dir():
        raise ValueError('Invalid application installation directory')
    job = Path(tempfile.mkdtemp(prefix='voicer_install_'))
    stage, backup = job / 'stage', job / 'backup'
    stage.mkdir()
    backup.mkdir()
    changed = []
    preserve_backup = False
    try:
        if is_zip:
            with zipfile.ZipFile(package) as archive:
                for entry in archive.infolist():
                    name = PurePosixPath(entry.filename)
                    if (name.is_absolute() or '..' in name.parts or '\\' in entry.filename
                            or ':' in entry.filename or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                        raise ValueError(f'Unsafe update archive entry: {entry.filename}')
                archive.extractall(stage)
            children = list(stage.iterdir())
            source = children[0] if len(children) == 1 and children[0].is_dir() else stage
            if not (source / 'main.py').is_file() or not (source / 'config.py').is_file():
                raise ValueError('Update package is missing application code')
            if target_exe.suffix.lower() == '.exe' and not (source / target_exe.name).is_file():
                raise ValueError('Update package is missing the application launcher')
            allowed = {'VoicerStudio.exe', 'VoicerStudio', 'main.py', 'config.py', 'requirements.txt',
                       'settings.example.json', 'README.md', 'LICENSE', 'assets', 'core', 'gui', 'locales', 'scripts'}
            files = []
            for path in source.rglob('*'):
                if path.is_file():
                    relative = path.relative_to(source)
                    if relative.parts[0] not in allowed:
                        raise ValueError(f'Unexpected update file: {relative}')
                    files.append((path, relative))
        else:
            files = [(package, Path(target_exe.name))]

        for source_file, relative in files:
            destination = target_dir / relative
            # Existing junctions/symlinks must not redirect writes outside the app.
            if destination.resolve() != destination:
                raise ValueError(f'Unsafe installation path: {relative}')
            saved = backup / relative
            existed = destination.exists()
            if existed:
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, saved)
            destination.parent.mkdir(parents=True, exist_ok=True)
            changed.append((destination, saved, existed))
            shutil.copy2(source_file, destination)
    except Exception:
        for destination, saved, existed in reversed(changed):
            try:
                if existed:
                    shutil.copy2(saved, destination)
                else:
                    destination.unlink(missing_ok=True)
            except OSError:
                preserve_backup = True
        if preserve_backup:
            raise RuntimeError(f'Update rollback needs manual recovery; backups kept at {backup}')
        raise
    finally:
        if not preserve_backup:
            shutil.rmtree(job)


def launch_application(target_dir: Path, target_exe: Path):
    if target_exe.is_file():
        command = [str(target_exe)]
    else:
        command = [sys.executable, str(target_dir / 'main.py')]
    subprocess.Popen(command, cwd=str(target_dir), close_fds=True,
                     creationflags=0x08000000 if os.name == 'nt' else 0)


def run_manifest(manifest_path: Path):
    data = json.loads(manifest_path.read_text(encoding='utf-8'))
    target_dir, target_exe = Path(data['target_dir']), Path(data['target_exe'])
    wait_for_exit(data['pid'])
    if data.get('package'):
        install_update(Path(data['package']), data['is_zip'], target_dir, target_exe)
    if data.get('restart', True):
        launch_application(target_dir, target_exe)


if __name__ == '__main__':
    manifest = Path(sys.argv[1])
    try:
        run_manifest(manifest)
        (manifest.parent / 'result.json').write_text(json.dumps({'success': True}), encoding='utf-8')
    except Exception as exc:
        (manifest.parent / 'result.json').write_text(json.dumps({'success': False, 'error': str(exc)}), encoding='utf-8')
        if os.name == 'nt':
            ctypes.windll.user32.MessageBoxW(None, str(exc), 'Voicer Studio Update Failed', 0x10)
        sys.exit(1)
