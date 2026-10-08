"""Local, bounded diagnostics with a small setup/export interface; no telemetry."""
from __future__ import annotations

import atexit
from datetime import datetime, timezone
import faulthandler
import importlib.metadata
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import threading
import traceback
from uuid import uuid4
import zipfile

from config import APP_DIR, APP_VERSION, LOG_MAX_BYTES, LOG_BACKUP_COUNT, LOG_RETAIN_SESSIONS

_handler = None
_session = None
_root = None
_native_stream = None


def redact(text: str) -> str:
    text = re.sub(r'(?i)\b(Bearer|Basic)\s+[^\s"\',;]+', r'\1 <REDACTED>', str(text))
    text = re.sub(r'\b(?:hf_|gh[pousr]_|github_pat_|sk-)[A-Za-z0-9_-]{8,}', '<REDACTED>', text)
    text = re.sub(r'''(?ix)(["']?(?:hf_token|access_token|token|api[_-]?key|password|authorization)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;&]+)''', r'\1"<REDACTED>"', text)
    for name in ('HF_TOKEN', 'HUGGINGFACE_HUB_TOKEN', 'GITHUB_TOKEN', 'GH_TOKEN', 'OPENAI_API_KEY'):
        value = os.environ.get(name, '')
        if len(value) >= 4:
            text = text.replace(value, '<REDACTED>')
    for path, label in ((APP_DIR, '<APP_DIR>'), (Path.home(), '<USER_HOME>')):
        for spelling in {str(path), path.as_posix(), str(path).replace('\\', '\\\\')}:
            text = re.sub(re.escape(spelling), lambda match: label, text, flags=re.IGNORECASE if os.name == 'nt' else 0)
    return text


class _JsonFormatter(logging.Formatter):
    def format(self, record):
        data = {
            'time': datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            'level': record.levelname, 'module': record.name, 'function': record.funcName,
            'line': record.lineno, 'thread': record.threadName,
            'session': _session.name if _session else '', 'version': APP_VERSION,
            'message': redact(record.getMessage())[:16384],
        }
        if record.exc_info:
            data['exception'] = redact(''.join(traceback.format_exception(*record.exc_info)))[:32768]
        for key in ('operation', 'stage'):
            if hasattr(record, key):
                data[key] = redact(str(getattr(record, key)))
        return json.dumps(data, ensure_ascii=False)


def get_log_directory() -> Path:
    if _root is not None:
        return _root
    from core.platform_utils import get_appdata_dir
    return get_appdata_dir() / 'diagnostics'


def _pid_running(pid: int) -> bool:
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if handle:
            kernel.CloseHandle(handle)
            return True
        return ctypes.get_last_error() != 87
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _close_session():
    global _handler, _native_stream
    if _handler is not None:
        logging.getLogger().removeHandler(_handler)
        _handler.close()
        _handler = None
    if _native_stream is not None:
        faulthandler.disable()
        _native_stream.close()
        _native_stream = None
    if _session is not None:
        try:
            metadata = _session / 'session.json'
            data = json.loads(metadata.read_text(encoding='utf-8'))
            data['closed_at'] = datetime.now(timezone.utc).isoformat()
            metadata.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        except (OSError, ValueError, TypeError, AttributeError):
            pass


def _prune_sessions():
    sessions = sorted((_root / 'sessions').glob('session-*'), reverse=True)
    for session in sessions[LOG_RETAIN_SESSIONS:]:
        if session.is_symlink() or not session.is_dir():
            continue
        try:
            data = json.loads((session / 'session.json').read_text(encoding='utf-8'))
            if not data.get('closed_at') and _pid_running(int(data['pid'])):
                continue
            # Only our exact session directories, inside the configured log root.
            if session.resolve().parent == (_root / 'sessions').resolve():
                shutil.rmtree(session)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue


def configure_diagnostics(log_root: Path | None = None, *, install_hooks=True, native_crashes=True) -> Path | None:
    global _handler, _session, _root, _native_stream
    _close_session()
    try:
        _root = Path(log_root) if log_root is not None else get_log_directory()
        _session = _root / 'sessions' / f"session-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}-{os.getpid()}-{uuid4().hex[:8]}"
        _session.mkdir(parents=True)
        libraries = {}
        for name in ('PySide6', 'opencv-python', 'numpy', 'torch'):
            try:
                libraries[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                libraries[name] = 'not installed'
        metadata = {'schema': 1, 'session': _session.name, 'pid': os.getpid(), 'version': APP_VERSION,
                    'python': platform.python_version(), 'os': platform.system(), 'os_release': platform.release(),
                    'architecture': platform.machine(), 'libraries': libraries,
                    'ffmpeg_available': bool(shutil.which('ffmpeg'))}
        (_session / 'session.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        _handler = RotatingFileHandler(_session / 'app.jsonl', maxBytes=LOG_MAX_BYTES,
                                      backupCount=LOG_BACKUP_COUNT, encoding='utf-8')
        _handler.setFormatter(_JsonFormatter())
        root_logger = logging.getLogger()
        root_logger.addHandler(_handler)
        root_logger.setLevel(logging.INFO)
        if native_crashes:
            _native_stream = (_session / 'native-crash.log').open('a', encoding='utf-8')
            faulthandler.enable(file=_native_stream, all_threads=True)
        if install_hooks:
            sys.excepthook = _uncaught_exception
            threading.excepthook = lambda args: _uncaught_exception(args.exc_type, args.exc_value, args.exc_traceback)
        _prune_sessions()
        logging.getLogger(__name__).info('Application session started')
        _record_update_failures()
        return _session
    except OSError as exc:
        _close_session()
        if sys.stderr:
            sys.stderr.write(f'Diagnostics could not be initialized: {exc}\n')
        return None


def _uncaught_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.getLogger('application.uncaught').critical('Unhandled exception', exc_info=(exc_type, exc_value, exc_traceback))


def export_diagnostic_report(destination: Path) -> Path:
    """Export only whitelisted diagnostic files from the three newest sessions."""
    root = get_log_directory()
    sessions = sorted((session for session in (root / 'sessions').glob('session-*')
                       if session.is_dir() and not session.is_symlink()
                       and any((session / name).is_file() and not (session / name).is_symlink()
                               for name in ('session.json', 'app.jsonl', 'native-crash.log'))), reverse=True)[:3]
    if not sessions:
        raise RuntimeError('No diagnostic sessions are available yet')
    destination = Path(destination)
    part = destination.with_name(f'.{destination.name}.{uuid4().hex}.part')
    try:
        with zipfile.ZipFile(part, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('README.txt', 'Voicer Studio bug report. JSONL records identify module, function, line, time and thread.\nNo media, projects or settings are included. Native traces may contain local filenames; review before sharing.\n')
            for session in sessions:
                if session.is_symlink() or not session.is_dir():
                    continue
                files = [session / 'session.json', session / 'native-crash.log']
                files += [session / 'app.jsonl'] + [session / f'app.jsonl.{i}' for i in range(1, LOG_BACKUP_COUNT + 1)]
                for path in files:
                    if path.is_file() and not path.is_symlink():
                        handler = _handler
                        if handler is not None:
                            handler.acquire()
                        try:
                            if handler is not None:
                                handler.flush()
                            text = path.read_text(encoding='utf-8', errors='replace')
                        finally:
                            if handler is not None:
                                handler.release()
                        if path.name == 'session.json':
                            text = json.dumps(_redact_values(_read_json(text)), ensure_ascii=False, indent=2)
                        elif path.name.startswith('app.jsonl'):
                            # Scrub decoded strings, not JSON syntax (escaped quotes/paths).
                            text = '\n'.join(json.dumps(_redact_values(_read_json(line)), ensure_ascii=False)
                                             for line in text.splitlines() if line.strip()) + '\n'
                        else:
                            text = redact(text)
                        archive.writestr(f'sessions/{session.name}/{path.name}', text)
        part.replace(destination)
        return destination
    finally:
        part.unlink(missing_ok=True)


def _redact_values(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: '<REDACTED>' if re.fullmatch(r'(?i)(hf_token|access_token|token|api[_-]?key|password|authorization)', key)
                else _redact_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_values(item) for item in value]
    return value


def _read_json(text):
    try:
        return json.loads(text)
    except ValueError:
        # A crash can leave the final record incomplete; preserve its evidence.
        return {'level': 'WARNING', 'message': 'Incomplete diagnostic record: ' + redact(text)}


def _record_update_failures():
    # The detached installer outlives the GUI; collect its failures next launch.
    from config import TEMP_DIR
    try:
        jobs = sorted((job for job in TEMP_DIR.glob('voicer_update_*') if job.is_dir() and not job.is_symlink()),
                      key=lambda job: job.stat().st_mtime, reverse=True)[:10]
    except OSError:
        return
    for job in jobs:
        result = job / 'result.json'
        if job.is_symlink() or result.is_symlink() or not result.is_file():
            continue
        try:
            if result.stat().st_size > 65536:
                continue
            data = json.loads(result.read_text(encoding='utf-8'))
            if data.get('success') is False:
                logging.getLogger('core.updater').error('Previous update installer failed: %s', data.get('error', 'Unknown failure'), extra={'operation': 'update', 'stage': 'installer'})
        except (OSError, ValueError, AttributeError):
            continue


atexit.register(_close_session)
