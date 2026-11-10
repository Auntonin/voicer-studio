"""Authenticated QLocalSocket round trips and real owner-thread GUI commands."""
import json
import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtNetwork import QLocalSocket

from core.agent_commands import CommandError, MAX_MESSAGE_BYTES
from core.models import DialogueItem, PipelineState, SpeakerInfo
from gui.agent_bridge import AgentBridge
from gui.main_window import MainWindow


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    with patch.object(MainWindow, '_load_settings', return_value={'check_updates_startup': False}), \
            patch('core.device_manager.device_manager.prewarm_async'):
        window = MainWindow()
    # Fixture sessions must never overwrite the user's real settings.json.
    window._save_settings = MagicMock(return_value=True)
    window._state = PipelineState(video_duration=10,
        speakers={'one': SpeakerInfo('one', 'private speaker'), 'two': SpeakerInfo('two', 'second')},
        dialogues=[DialogueItem(1, 'one', 1, 3, 'original caption')])
    yield window, app
    window._autosave_timer.stop()
    window._state = PipelineState()
    window._is_dirty = False
    window.deleteLater()
    app.processEvents()


def pump(app, condition, timeout=3):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.001)
    assert condition(), 'Qt event loop deadline exceeded'


def connect(app, endpoint):
    socket = QLocalSocket()
    socket.connectToServer(endpoint)
    pump(app, lambda: socket.state() == QLocalSocket.LocalSocketState.ConnectedState)
    return socket


def receive(app, socket, count=1):
    data = bytearray()
    def received():
        data.extend(bytes(socket.readAll()))
        return data.count(b'\n') >= count
    pump(app, received)
    return [json.loads(line) for line in data.splitlines()]


def send(app, socket, value):
    socket.write(json.dumps(value).encode() + b'\n')
    return receive(app, socket)[0]


def test_presence_counts_clients_not_tool_requests_and_disconnects(window):
    win, app = window
    bridge = AgentBridge(win.agent_commands(), win)
    ticket = bridge.open_session({'read_project'})
    sockets = []
    try:
        for name in ('Synthetic Codex', 'Synthetic Claude'):
            socket = connect(app, ticket.endpoint)
            sockets.append(socket)
            assert send(app, socket, {'auth': ticket.credential}) == {'ok': True}
            assert send(app, socket, {'method': 'client_presence', 'name': name, 'version': '1',
                                     'protocol': '2025-11-25', 'request_id': 'a' * 32})['ok']
        assert [client['name'] for client in bridge.connected_clients()] == ['Synthetic Codex', 'Synthetic Claude']
        transient = connect(app, ticket.endpoint)
        sockets.append(transient)
        assert send(app, transient, {'auth': ticket.credential})['ok']
        assert send(app, transient, {'method': 'describe'})['ok']
        assert len(bridge.connected_clients()) == 2
        bridge._rate[ticket.session_id] = (time.monotonic(), 128)
        assert send(app, sockets[0], {'method': 'client_presence', 'name': 'changed', 'version': '1',
                                    'protocol': '2025-11-25', 'request_id': 'a' * 32})['code'] == 'RATE_LIMITED'
        assert bridge.connected_clients()[0]['name'] == 'Synthetic Codex'
        sockets[0].abort()
        pump(app, lambda: len(bridge.connected_clients()) == 1)
        bridge.revoke(ticket.session_id)
        pump(app, lambda: not bridge.connected_clients())
    finally:
        for socket in sockets:
            socket.abort()
        bridge.close()


@pytest.mark.parametrize('field,value', [('request_id', '../bad'), ('name', 'bad\nname'),
                                        ('version', 'x' * 101), ('protocol', 1)])
def test_presence_rejects_invalid_metadata(window, field, value):
    win, app = window
    bridge = AgentBridge(win.agent_commands(), win)
    ticket = bridge.open_session({'read_project'})
    socket = connect(app, ticket.endpoint)
    try:
        assert send(app, socket, {'auth': ticket.credential})['ok']
        payload = {'method': 'client_presence', 'name': 'test', 'version': '1',
                   'protocol': '2025-11-25', 'request_id': 'a' * 32}
        payload[field] = value
        socket.write(json.dumps(payload).encode() + b'\n')
        pump(app, lambda: socket.state() == QLocalSocket.LocalSocketState.UnconnectedState)
        assert not bridge.connected_clients()
    finally:
        socket.abort()
        bridge.close()


def test_fragmented_auth_multiple_packets_edit_and_gui_undo(window):
    win, app = window
    assert win._agent_commands is None
    commands = win.agent_commands()
    bridge = AgentBridge(commands, win)
    ticket = bridge.open_session({'read_project', 'read_transcript', 'edit_caption'})
    socket = connect(app, ticket.endpoint)
    try:
        wire = json.dumps({'auth': ticket.credential}).encode() + b'\n'
        socket.write(wire[:10])
        app.processEvents()
        socket.write(wire[10:] + b'{"method":"describe"}\n')
        replies = receive(app, socket, 2)
        assert replies[0] == {'ok': True}
        assert replies[1]['result']['app_version']
        snapshot = send(app, socket, {'method': 'snapshot', 'limit': 1})['result']
        request = {'operation': 'caption', 'project_epoch': snapshot['project_epoch'],
                   'expected_revision': snapshot['revision'],
                   'clip_ref': snapshot['dialogues'][0]['clip_ref'], 'caption': 'changed caption'}
        proposal = send(app, socket, {'method': 'submit', 'command': request})['result']
        assert win._state.dialogues[0].caption == 'original caption'
        assert not send(app, socket, {'method': 'approve', 'job_id': proposal['job_id']})['ok']
        commands.approve(proposal['job_id'])  # Trusted harness, never the peer.
        assert win._state.dialogues[0].caption == 'changed caption'
        win.on_undo()
        assert win._state.dialogues[0].caption == 'original caption'
        win.on_redo()
        assert win._state.dialogues[0].caption == 'changed caption'
        assert win._is_dirty
        assert send(app, socket, {'method': 'submit', 'command': request})['code'] == 'REVISION_CONFLICT'
    finally:
        socket.abort()
        bridge.close()


@pytest.mark.parametrize('attack', ['wrong_token', 'unicode_token', 'unauthenticated', 'oversized', 'malformed'])
def test_invalid_connections_are_closed(window, attack):
    win, app = window
    bridge = AgentBridge(win.agent_commands(), win)
    ticket = bridge.open_session({'read_project'})
    socket = connect(app, ticket.endpoint)
    payload = {'wrong_token': json.dumps({'auth': 'f' * 64}).encode() + b'\n',
               'unicode_token': json.dumps({'auth': 'ก' * 64}).encode() + b'\n',
               'unauthenticated': b'{"method":"snapshot"}\n',
               'oversized': b'x' * (MAX_MESSAGE_BYTES + 1), 'malformed': b'{broken}\n'}[attack]
    try:
        socket.write(payload)
        pump(app, lambda: socket.state() == QLocalSocket.LocalSocketState.UnconnectedState)
        assert not socket.bytesAvailable()
    finally:
        bridge.close()


def test_permission_revoke_expired_credential_restart_and_cleanup(window):
    win, app = window
    commands = win.agent_commands()
    bridge = AgentBridge(commands, win)
    ticket = bridge.open_session({'read_project'})
    socket = connect(app, ticket.endpoint)
    assert send(app, socket, {'auth': ticket.credential})['ok']
    bridge.revoke(ticket.session_id)
    pump(app, lambda: socket.state() == QLocalSocket.LocalSocketState.UnconnectedState)
    endpoint = bridge.endpoint
    bridge.close()
    other = AgentBridge(commands, win)
    try:
        assert other.endpoint != endpoint
        socket = connect(app, other.endpoint)
        socket.write(json.dumps({'auth': ticket.credential}).encode() + b'\n')
        pump(app, lambda: socket.state() == QLocalSocket.LocalSocketState.UnconnectedState)
        if os.name != 'nt':
            assert not Path(endpoint).exists()
    finally:
        other.close()


@pytest.mark.parametrize('mutation', ['caption', 'speaker', 'split', 'undo', 'reload'])
def test_gui_mutations_invalidate_snapshot(window, mutation):
    win, _ = window
    commands = win.agent_commands()
    session = commands.grant({'read_project', 'edit_caption'})
    snapshot = commands.snapshot(session, limit=1)
    request = {'operation': 'caption', 'project_epoch': snapshot['project_epoch'],
               'expected_revision': snapshot['revision'],
               'clip_ref': snapshot['dialogues'][0]['clip_ref'], 'caption': 'stale'}
    if mutation == 'caption':
        win._on_caption_changed(1, 'GUI edit')
    elif mutation == 'speaker':
        win._on_speaker_changed(1, 'two')
    elif mutation == 'split':
        win._timeline.current_time = 2
        win._on_split(1)
    elif mutation == 'undo':
        win._on_caption_changed(1, 'GUI edit')
        win.on_undo()
    else:
        win.load_dialogues(win._state)
    with pytest.raises(CommandError, match='PERMISSION_DENIED|REVISION_CONFLICT'):
        commands.submit(session, request)


def test_speaker_editor_snapshots_before_mutation(window):
    win, _ = window
    item = win._state.dialogues[0]
    win._clip_editor.load_item(item, win._state)
    index = win._clip_editor.combo_speaker.findData('two')
    win._clip_editor.combo_speaker.setCurrentIndex(index)
    assert item.speaker_id == 'two'
    win.on_undo()
    assert win._state.dialogues[0].speaker_id == 'one'


def test_busy_covers_dialog_asset_workers_and_transcription(window):
    from types import SimpleNamespace
    win, _ = window
    commands = win.agent_commands()
    session = commands.grant({'read_project'})
    for name, value in [('_export_dialog', object()),
                        ('_clip_transcribe_worker', SimpleNamespace(isRunning=lambda: True)),
                        ('_asset_jobs', {'work': object()})]:
        before = getattr(win, name)
        setattr(win, name, value)
        with pytest.raises(CommandError, match='BUSY'):
            commands.snapshot(session)
        setattr(win, name, before)


def test_partial_packet_timeout(window, monkeypatch):
    import gui.agent_bridge as bridge_module
    win, app = window
    monkeypatch.setattr(bridge_module, 'REQUEST_TIMEOUT_MS', 30)
    bridge = AgentBridge(win.agent_commands(), win)
    ticket = bridge.open_session({'read_project'})
    socket = connect(app, ticket.endpoint)
    try:
        socket.write(b'{')
        pump(app, lambda: socket.state() == QLocalSocket.LocalSocketState.UnconnectedState)
    finally:
        bridge.close()


def test_endpoint_access_restricted_to_current_user(window):
    import stat
    win, app = window
    bridge = AgentBridge(win.agent_commands(), win)
    try:
        if os.name != 'nt':
            info = Path(bridge.endpoint).lstat()
            assert info.st_uid == os.getuid()
            assert stat.S_IMODE(info.st_mode) == 0o600
            assert stat.S_IMODE(Path(bridge.endpoint).parent.stat().st_mode) == 0o700
            return
        import ctypes
        from ctypes import wintypes
        socket = connect(app, bridge.endpoint)
        adv = ctypes.WinDLL('advapi32', use_last_error=True)
        adv.GetSecurityInfo.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        adv.GetSecurityInfo.restype = wintypes.DWORD
        owner, acl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        error = adv.GetSecurityInfo(socket.socketDescriptor(), 6, 1 | 4,
            ctypes.byref(owner), None, ctypes.byref(acl), None, ctypes.byref(descriptor))
        assert error == 0 and acl.value
        try:
            class ACLInfo(ctypes.Structure):
                _fields_ = [('count', wintypes.DWORD), ('used', wintypes.DWORD), ('free', wintypes.DWORD)]
            info = ACLInfo()
            adv.GetAclInformation.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_int]
            assert adv.GetAclInformation(acl, ctypes.byref(info), ctypes.sizeof(info), 2)
            assert info.count == 1
            adv.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
            ace = ctypes.c_void_p()
            assert adv.GetAce(acl, 0, ctypes.byref(ace))
            assert ctypes.string_at(ace, 1) == b'\x00'
            adv.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
            token = wintypes.HANDLE()
            assert adv.OpenProcessToken(wintypes.HANDLE(-1), 8, ctypes.byref(token))
            try:
                size = wintypes.DWORD()
                adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
                adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
                buffer = ctypes.create_string_buffer(size.value)
                assert adv.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size))
                user_sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
                assert adv.EqualSid(user_sid, ace.value + 8)
            finally:
                ctypes.windll.kernel32.CloseHandle(token)
        finally:
            ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
            ctypes.windll.kernel32.LocalFree(descriptor)
            socket.abort()
    finally:
        bridge.close()


@pytest.mark.parametrize('outcome', ['cancelled', 'failed', 'succeeded'])
def test_real_export_thread_job_outcome_is_not_thread_exit(window, tmp_path, outcome):
    import zipfile
    from gui.export_dialog import FullExportWorker
    win, app = window
    commands = win.agent_commands()
    session = commands.grant({'read_project', 'export'})
    snapshot = commands.snapshot(session)
    job = commands.submit(session, {'operation': 'export', 'project_epoch': snapshot['project_epoch'],
                                   'expected_revision': snapshot['revision']})['job_id']
    worker = FullExportWorker(win._state, tmp_path, tmp_path / 'pack.zip', {})
    win._agent_pending_job = job
    win._bind_agent_worker(worker, 'export')
    win._agent_pending_job = None

    def build(*args, **kwargs):
        if outcome == 'failed':
            raise RuntimeError('private/path/fixture_failure')
        return tmp_path

    def export(*args, **kwargs):
        with zipfile.ZipFile(worker.zip_path, 'w') as archive:
            archive.writestr('fixture/test.txt', 'test')

    with patch('gui.export_dialog.PackBuilder.build_pack', side_effect=build), \
            patch('gui.export_dialog.QualityChecker.check_all', return_value=[]), \
            patch('gui.export_dialog.PackBuilder.export_zip', side_effect=export):
        if outcome == 'cancelled':
            commands.cancel(session, job)
        worker.start()
        pump(app, lambda: commands.job_status(session, job)['state'] in {'cancelled', 'failed', 'succeeded'})
        pump(app, lambda: not worker.isRunning())
    status = commands.job_status(session, job)
    assert status['state'] == outcome
    assert 'private/path' not in json.dumps(status)
    assert (tmp_path / 'pack.zip').exists() == (outcome == 'succeeded')


def test_pipeline_terminal_outcomes_and_cancel_at_last_step(window, tmp_path):
    from contextlib import ExitStack
    from types import SimpleNamespace
    from core.device_manager import device_manager
    from core.pipeline import PipelineWorker
    win, app = window
    win._state.video_path = tmp_path / 'fixture.mp4'
    steps = ('_step_audio_extract', '_step_voice_separation', '_step_vad', '_step_transcription',
             '_step_diarization', '_step_clip_generation', '_step_frame_extraction',
             '_step_backing_track', '_step_pack_build', '_step_validation')
    for expected in ('succeeded', 'failed', 'cancelled'):
        worker = PipelineWorker(win._state, {})
        results = []
        worker.signals.settled.connect(results.append)
        with ExitStack() as stack:
            stack.enter_context(patch.object(device_manager, 'get_optimal_device',
                return_value=SimpleNamespace(display_title='test')))
            stack.enter_context(patch.object(device_manager, 'get_optimal_concurrency_config',
                return_value=SimpleNamespace(tier=SimpleNamespace(value='test'), clip_workers=1,
                                             whisper_threads=1, ram_gb=1)))
            stack.enter_context(patch.object(device_manager, 'configure_runtime_environment'))
            stack.enter_context(patch.object(device_manager, 'release_gpu_memory'))
            stack.enter_context(patch('core.project_manager.ProjectManager.cleanup_stale_temp_files'))
            for step in steps:
                stack.enter_context(patch.object(worker, step))
            if expected == 'failed':
                worker._step_audio_extract.side_effect = RuntimeError('fixture_failure')
            elif expected == 'cancelled':
                worker._step_validation.side_effect = worker.cancel
            worker.start()
            pump(app, lambda: bool(results))
            pump(app, lambda: not worker.isRunning())
        assert results == [expected]
        assert worker.outcome == expected


def test_asset_worker_commits_on_owner_thread_and_ignores_reloaded_project(window, tmp_path):
    from threading import Event
    win, app = window
    win._output_dir = tmp_path
    started, release = Event(), Event()
    original = win._state.dialogues[0]
    def regenerate(item, state, output):
        assert item is not original
        assert state is not win._state
        started.set()
        assert release.wait(3)
        item.audio_path = tmp_path / 'audio.mp3'
    with patch('core.clip_generator.ClipGenerator.regenerate_clip', side_effect=regenerate):
        win._on_regen_audio(1)
        pump(app, started.is_set)
        assert win._is_busy()
        assert original.audio_path is None
        win.load_dialogues(PipelineState(dialogues=[DialogueItem(1, 'one', 1, 3, 'new project')]))
        release.set()
        pump(app, lambda: not win._asset_jobs)
    assert win._state.dialogues[0].audio_path is None
    assert original.audio_path is None


def test_export_dialog_escape_waits_cooperatively_without_blocking(window, tmp_path):
    from threading import Event
    from gui.export_dialog import ExportDialog, FullExportWorker
    win, app = window
    dialog = ExportDialog(win, win._state, {})
    worker = FullExportWorker(win._state, tmp_path, tmp_path / 'cancel.zip', {})
    dialog.worker = worker
    entered, release = Event(), Event()
    closed = []
    dialog.finished.connect(lambda _result: closed.append(True))
    def build(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return tmp_path
    with patch('gui.export_dialog.PackBuilder.build_pack', side_effect=build):
        worker.start()
        pump(app, entered.is_set)
        start = time.monotonic()
        dialog.reject()
        assert time.monotonic() - start < .2
        assert not closed and worker._is_cancelled
        release.set()
        pump(app, lambda: bool(closed))
        pump(app, lambda: not worker.isRunning())
    assert worker.outcome == 'cancelled'
    dialog.deleteLater()
