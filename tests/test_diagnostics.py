"""Offline tests for bounded, shareable local diagnostics."""
import json
import logging
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from core import diagnostics as d
from config import APP_DIR, APP_VERSION


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'diagnostics'
        self.old_root = d._root
        self.level = logging.getLogger().level
        self.hooks = sys.excepthook, threading.excepthook
        self.session = d.configure_diagnostics(self.root, install_hooks=False, native_crashes=False)

    def tearDown(self):
        d._close_session()
        d._root = self.old_root
        logging.getLogger().setLevel(self.level)
        sys.excepthook, threading.excepthook = self.hooks
        self.temp.cleanup()

    def records(self):
        d._handler.flush()
        return [json.loads(line) for line in (self.session / 'app.jsonl').read_text(encoding='utf-8').splitlines()]

    def test_exception_has_location_context_and_scrubs_credentials(self):
        try:
            raise ValueError('password="private value" hf_fakeToken123456')
        except ValueError:
            logging.getLogger('test.export').exception('Failed at %s', APP_DIR, extra={'operation': 'export', 'stage': 'ogv'})
        record = self.records()[-1]
        self.assertEqual(record['level'], 'ERROR')
        self.assertEqual(record['version'], APP_VERSION)
        self.assertEqual(record['operation'], 'export')
        self.assertEqual(record['stage'], 'ogv')
        self.assertIn('test_exception_has_location', record['function'])
        self.assertGreater(record['line'], 0)
        self.assertIn('ValueError', record['exception'])
        text = json.dumps(record)
        self.assertNotIn('private value', text)
        self.assertNotIn('hf_fakeToken123456', text)
        self.assertIn('<APP_DIR>', record['message'])

    def test_environment_token_and_bearer_scrubbed(self):
        with patch.dict('os.environ', {'HF_TOKEN': 'fake_secret_environment'}):
            value = d.redact('Bearer fake_bearer password=example fake_secret_environment')
        self.assertNotIn('fake_bearer', value)
        self.assertNotIn('example', value)
        self.assertNotIn('fake_secret_environment', value)

    def test_basic_authorization_is_scrubbed(self):
        self.assertNotIn('fake_encoded_credentials', d.redact('Authorization: Basic fake_encoded_credentials'))

    def test_native_trace_is_scrubbed_in_report(self):
        import faulthandler
        trace = self.session / 'native-crash.log'
        with trace.open('w', encoding='utf-8') as stream:
            faulthandler.dump_traceback(file=stream, all_threads=True)
        report = d.export_diagnostic_report(Path(self.temp.name) / 'native.zip')
        with zipfile.ZipFile(report) as archive:
            text = archive.read(f'sessions/{self.session.name}/native-crash.log').decode()
        self.assertIn('test_native_trace_is_scrubbed_in_report', text)
        self.assertNotIn(str(APP_DIR), text)

    def test_rotation_is_bounded(self):
        d._handler.maxBytes = 500
        for _ in range(50):
            logging.getLogger('test.rotation').error('X' * 200)
        files = list(self.session.glob('app.jsonl*'))
        self.assertEqual(len(files), 3)
        self.assertTrue(all(path.stat().st_size < 1000 for path in files))

    def test_report_whitelist_and_valid_json_after_scrubbing(self):
        logging.getLogger('test.report').error('token="fake private" quoted="hello"')
        (self.session / 'settings.json').write_text('private settings')
        (self.session / 'video.mp4').write_bytes(b'private media')
        (self.session / 'native-crash.log').write_text(str(Path.home() / 'example.py') + ' hf_fakeNative123456')
        output = d.export_diagnostic_report(Path(self.temp.name) / 'report.zip')
        with zipfile.ZipFile(output) as archive:
            names = archive.namelist()
            self.assertFalse(any('settings' in name or 'video' in name for name in names))
            for name in names:
                content = archive.read(name).decode('utf-8')
                self.assertNotIn('fake private', content)
                self.assertNotIn('hf_fakeNative123456', content)
                if name.endswith('.jsonl'):
                    for line in content.splitlines():
                        json.loads(line)
                elif name.endswith('.json'):
                    json.loads(content)
        self.assertFalse(list(output.parent.glob('*.part')))

    def test_incomplete_crash_record_does_not_block_report(self):
        d._handler.flush()
        with (self.session / 'app.jsonl').open('a', encoding='utf-8') as stream:
            stream.write('{"message":"hf_fakeBroken123456')
        output = d.export_diagnostic_report(Path(self.temp.name) / 'crash.zip')
        with zipfile.ZipFile(output) as archive:
            content = archive.read(f'sessions/{self.session.name}/app.jsonl').decode()
            self.assertNotIn('hf_fakeBroken123456', content)
            self.assertIn('Incomplete diagnostic record', content)

    def test_retention_protects_running_session(self):
        for index in range(4):
            old = self.root / 'sessions' / f'session-000{index}'
            old.mkdir()
            (old / 'session.json').write_text(json.dumps({'pid': 123, 'closed_at': 'done'}))
        active = self.root / 'sessions' / 'session-000active'
        active.mkdir()
        (active / 'session.json').write_text(json.dumps({'pid': 123}))
        with patch.object(d, 'LOG_RETAIN_SESSIONS', 2), patch.object(d, '_pid_running', return_value=True):
            d._prune_sessions()
        self.assertTrue(active.exists())
        self.assertFalse((self.root / 'sessions' / 'session-0000').exists())

    def test_hooks_capture_real_thread_failure(self):
        d.configure_diagnostics(self.root, native_crashes=False)
        self.session = d._session
        def fail():
            raise RuntimeError('fake thread failure')
        thread = threading.Thread(target=fail, name='test-failure-thread')
        thread.start()
        thread.join()
        record = self.records()[-1]
        self.assertEqual(record['level'], 'CRITICAL')
        self.assertEqual(record['thread'], 'test-failure-thread')
        self.assertIn('fake thread failure', record['exception'])

    def test_permission_failure_does_not_crash_startup(self):
        with patch.object(Path, 'mkdir', side_effect=PermissionError('test permission denied')):
            result = d.configure_diagnostics(self.root, install_hooks=False, native_crashes=False)
        self.assertIsNone(result)

    def test_detached_updater_failure_collected_on_next_start(self):
        jobs = Path(self.temp.name) / 'jobs'
        job = jobs / 'voicer_update_test'
        job.mkdir(parents=True)
        (job / 'result.json').write_text(json.dumps({'success': False, 'error': 'fake installer failure token=private'}))
        with patch('config.TEMP_DIR', jobs):
            d._record_update_failures()
        record = self.records()[-1]
        self.assertEqual(record['operation'], 'update')
        self.assertEqual(record['stage'], 'installer')
        self.assertNotIn('private', record['message'])

    def test_main_exception_hook_keeps_traceback(self):
        try:
            raise RuntimeError('fake main failure')
        except RuntimeError:
            d._uncaught_exception(*sys.exc_info())
        self.assertIn('fake main failure', self.records()[-1]['exception'])

    def test_report_preserves_destination_on_failure(self):
        destination = Path(self.temp.name) / 'previous.zip'
        destination.write_bytes(b'previous report')
        with patch.object(zipfile.ZipFile, 'writestr', side_effect=OSError('fake disk failure')):
            with self.assertRaises(OSError):
                d.export_diagnostic_report(destination)
        self.assertEqual(destination.read_bytes(), b'previous report')
        self.assertFalse(list(destination.parent.glob('.*.part')))

    def test_report_contains_latest_three_sessions(self):
        for _ in range(4):
            d.configure_diagnostics(self.root, install_hooks=False, native_crashes=False)
        output = d.export_diagnostic_report(Path(self.temp.name) / 'recent.zip')
        with zipfile.ZipFile(output) as archive:
            included = {name.split('/')[1] for name in archive.namelist() if name.startswith('sessions/')}
        self.assertEqual(len(included), 3)
        self.assertIn(d._session.name, included)
        self.assertNotIn(self.session.name, included)

    def test_empty_failed_sessions_do_not_hide_real_evidence(self):
        for index in range(4):
            (self.root / 'sessions' / f'session-999{index}').mkdir()
        report = d.export_diagnostic_report(Path(self.temp.name) / 'nonempty.zip')
        with zipfile.ZipFile(report) as archive:
            self.assertIn(f'sessions/{self.session.name}/app.jsonl', archive.namelist())
        d._close_session()
        isolated = Path(self.temp.name) / 'empty-root'
        (isolated / 'sessions' / 'session-empty').mkdir(parents=True)
        with patch.object(d, '_root', isolated):
            with self.assertRaisesRegex(RuntimeError, 'No diagnostic sessions'):
                d.export_diagnostic_report(Path(self.temp.name) / 'empty.zip')

    def test_recent_updater_jobs_use_time_not_random_names(self):
        import os
        jobs = Path(self.temp.name) / 'ordered-jobs'
        for index in range(11):
            job = jobs / f'voicer_update_z{index}'
            job.mkdir(parents=True)
            (job / 'result.json').write_text(json.dumps({'success': True}))
            os.utime(job, (1000, 1000))
        latest = jobs / 'voicer_update_a'
        latest.mkdir()
        (latest / 'result.json').write_text(json.dumps({'success': False, 'error': 'newest installer failure'}))
        with patch('config.TEMP_DIR', jobs):
            d._record_update_failures()
        self.assertIn('newest installer failure', self.records()[-1]['message'])

    def test_background_gui_export_and_translations(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
        from gui.main_window import MainWindow
        from core.i18n import STRINGS_EN, STRINGS_TH
        app = QApplication.instance() or QApplication([])
        destination = Path(self.temp.name) / 'gui-report.zip'
        with patch.object(MainWindow, '_load_settings', return_value={'check_updates_startup': False}):
            window = MainWindow()
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(destination), 'ZIP')), \
                patch.object(QMessageBox, 'information') as show_result:
            window._export_diagnostic_report()
            self.assertTrue(window._diagnostic_report_worker.wait(5000))
            app.processEvents()
            self.assertTrue(destination.is_file())
            show_result.assert_called_once()
            self.assertTrue(window._act_export_diagnostics.isEnabled())
        for key in ('menu_open_diagnostics', 'menu_export_diagnostics', 'diagnostics_done', 'diagnostics_failed'):
            self.assertIn(key, STRINGS_EN)
            self.assertIn(key, STRINGS_TH)
        # Do not persist settings or start playback/network activity during teardown.
        window.deleteLater()
        app.processEvents()

    def test_export_worker_failure_is_logged_with_traceback(self):
        from core.models import PipelineState
        from gui.export_dialog import FullExportWorker
        worker = FullExportWorker(PipelineState(), Path(self.temp.name) / 'pack', Path(self.temp.name) / 'pack.zip', {})
        errors = []
        worker.error.connect(errors.append)
        with patch('gui.export_dialog.PackBuilder.build_pack', side_effect=RuntimeError('fake export failure')):
            worker.run()
        self.assertTrue(errors)
        record = self.records()[-1]
        self.assertEqual(record['operation'], 'export')
        self.assertIn('fake export failure', record['exception'])
