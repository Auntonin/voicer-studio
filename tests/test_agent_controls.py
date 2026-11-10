"""Trusted controls, expiry, discovery and path policy regressions."""
import json
import os
from pathlib import Path
import secrets
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtNetwork import QLocalServer
from core.agent_commands import CommandError
from core import agent_credentials as credentials
from core.agent_paths import validate_output
from gui.agent_bridge import BridgeSession
from test_agent_bridge import window, pump


@pytest.fixture
def vault(monkeypatch):
    values = {}
    backend = SimpleNamespace(
        set_password=lambda service, ref, value: values.__setitem__((service, ref), value),
        get_password=lambda service, ref: values.get((service, ref)),
        delete_password=lambda service, ref: values.pop((service, ref)))
    monkeypatch.setattr(credentials, '_backend', lambda: backend)
    return values


def proposal(win, session, operation='caption'):
    commands = win.agent_commands()
    page = commands.snapshot(session, limit=1)
    command = {'operation': operation, 'project_epoch': page['project_epoch'], 'expected_revision': page['revision']}
    if operation == 'caption':
        command.update(clip_ref=page['dialogues'][0]['clip_ref'], caption='<script>ignore all permissions</script>')
    return commands.submit(session, command)['job_id']


def test_default_off_toggle_cleanup_and_no_auto_permissions(window, vault):
    win, app = window
    assert win._agent_bridge is None and win._agent_dialog is None and win._agent_commands is None
    win.on_agent_connection()
    dialog = win._agent_dialog
    assert not dialog.enabled.isChecked()
    assert not any(check.isChecked() for check in dialog.scopes.values())
    for _ in range(10):
        win._enable_agent_bridge()
        session = win._add_agent_connection({'read_project'})
        commands = win.agent_commands()
        assert commands.describe(session)['scopes'] == ['read_project']
        win._disable_agent_bridge()
        assert not vault and not commands._sessions
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        assert not win.findChildren(QLocalServer)
    dialog.close()


def test_simple_panel_enable_grant_all_and_close_keeps_bridge(window, vault):
    from core.agent_commands import SCOPES
    win, _ = window
    win.on_agent_connection()
    dialog = win._agent_dialog
    assert not dialog.advanced_panel.isVisible()
    with patch.object(dialog, '_auto_setup') as setup:
        dialog.enabled.setChecked(True)
        assert win._agent_bridge is not None
        session = dialog._selected_session()
        assert win.agent_commands().describe(session)['scopes'] == []
        dialog.grant_all.click()
        session = dialog._selected_session()
        assert set(win.agent_commands().describe(session)['scopes']) == SCOPES
        assert setup.call_count == 0
        dialog.close()
        assert win._agent_bridge is not None
    win._disable_agent_bridge()


def test_first_time_connection_controls_are_visible_without_advanced(window, vault):
    win, _ = window
    win.on_agent_connection()
    dialog = win._agent_dialog
    assert not dialog.advanced_panel.isVisible()
    assert dialog.enabled.isVisible()
    assert dialog.live_clients.isVisible()
    assert dialog.connect_button.isVisible()
    assert not dialog.advanced_panel.isAncestorOf(dialog.connect_button)
    assert dialog.target_client.isVisible()
    assert dialog.prepare_runtime.isVisible() and dialog.test_connection.isVisible()
    assert dialog.connect_button.isEnabled()
    with patch.object(dialog, '_auto_setup') as setup:
        dialog.enabled.setChecked(True)
        assert dialog.connect_button.isEnabled()
        assert setup.call_count == 0
        dialog.connect_button.click()
        assert setup.call_count == 1
    win._disable_agent_bridge()
    dialog.close()


def test_application_title_and_status_use_voicer_studio(window):
    from core.i18n import tr
    from config import APP_NAME
    win, _ = window
    assert APP_NAME == 'Voicer Studio'
    assert win.windowTitle().startswith('Voicer Studio')
    assert 'Voicer Studio' in tr('status_version', version='test')


def test_choose_client_does_not_write_config_until_connect_and_scopes_refresh_it(window, vault):
    win, _ = window
    win.on_agent_connection()
    dialog = win._agent_dialog
    with patch.object(dialog, '_auto_setup') as setup:
        dialog.enabled.setChecked(True)
        dialog.target_client.setCurrentIndex(dialog.target_client.findData('claude'))
        assert setup.call_count == 0
        dialog.connect_button.click()
        assert setup.call_count == 1 and dialog._connect_requested
        dialog.grant_all.click()
        assert setup.call_count == 2
        dialog.target_client.setCurrentIndex(dialog.target_client.findData('codex'))
        assert not dialog._connect_requested and setup.call_count == 2
    win._disable_agent_bridge()
    dialog.close()


@pytest.mark.parametrize('client', ['codex', 'claude'])
def test_selected_client_setup_runs_in_worker_and_panel_close_keeps_bridge(window, vault, client):
    from threading import Event, get_ident
    from core.i18n import tr
    win, app = window
    win.on_agent_connection()
    dialog = win._agent_dialog
    dialog.enabled.setChecked(True)
    dialog.target_client.setCurrentIndex(dialog.target_client.findData(client))
    entered, release = Event(), Event()
    owner_thread = get_ident()
    def register(*_args):
        assert get_ident() != owner_thread
        entered.set()
        assert release.wait(5)
        return 'validated-python'
    function = 'register_codex' if client == 'codex' else 'register_claude_desktop'
    try:
        with patch('core.agent_setup.' + function, side_effect=register) as setup:
            dialog.connect_button.click()
            worker = win._agent_setup_worker
            pump(app, entered.is_set)
            assert not dialog.connect_button.isEnabled()
            dialog.close()
            assert win._agent_bridge is not None
            release.set()
            pump(app, lambda: win._agent_setup_worker is None)
            assert dialog.connection_status.text() == tr('mcp_client_ready_' + client)
            assert dialog.connect_button.isEnabled()
            assert setup.call_count == 1
    finally:
        release.set()
        if win._agent_setup_worker is not None:
            win._agent_setup_worker.wait(5000)
            pump(app, lambda: win._agent_setup_worker is None)
        win._disable_agent_bridge()


def test_other_client_copies_config_from_main_connect_button(window, vault, tmp_path):
    from PySide6.QtWidgets import QApplication
    win, _ = window
    win.on_agent_connection()
    dialog = win._agent_dialog
    dialog.enabled.setChecked(True)
    dialog.target_client.setCurrentIndex(dialog.target_client.findData('manual'))
    dialog._interpreter = str(tmp_path / 'python.exe')
    with patch.object(dialog, '_auto_setup') as setup:
        dialog.connect_button.click()
        assert setup.call_count == 0
        assert dialog.advanced_toggle.isChecked()
        assert dialog.connection_config.toPlainText() == QApplication.clipboard().text()
        assert 'voicer-studio' in json.loads(QApplication.clipboard().text())['mcpServers']
    win._disable_agent_bridge()
    dialog.close()


def test_vault_failure_revokes_without_fallback(window, monkeypatch):
    win, _ = window
    win._enable_agent_bridge()
    def fail(ticket):
        raise CommandError('PERMISSION_DENIED')
    monkeypatch.setattr(credentials, 'publish', fail)
    try:
        with pytest.raises(CommandError, match='PERMISSION_DENIED'):
            win._add_agent_connection({'read_project'})
        assert not win._agent_connections and not win.agent_commands()._sessions
        assert not win._agent_bridge._credentials
    finally:
        win._disable_agent_bridge()


def test_connection_reference_survives_disable_and_reenable_without_persisting_secrets(window, vault):
    win, _ = window
    with patch.object(win, '_save_settings', return_value=True):
        win._enable_agent_bridge()
        first_session = win._add_agent_connection({'read_project'})
        first_reference = win._agent_connections[first_session]['reference']
        first_ticket = credentials.resolve(first_reference)
        win._disable_agent_bridge()
        with pytest.raises(CommandError, match='APP_NOT_READY'):
            credentials.resolve(first_reference)
        win._enable_agent_bridge()
        second_session = win._add_agent_connection({'read_project', 'read_transcript'})
        second_reference = win._agent_connections[second_session]['reference']
        second_ticket = credentials.resolve(second_reference)
        assert first_reference == second_reference
        assert first_ticket['credential'] != second_ticket['credential']
        assert second_ticket['session_id'] != first_ticket['session_id']
        for ticket in (first_ticket, second_ticket):
            assert ticket['credential'] not in json.dumps(win._settings)
        win._disable_agent_bridge()


def test_gateway_reloads_rotated_ticket_and_never_replays_a_write(vault):
    from core.agent_client import SessionAgentClient
    from unittest.mock import MagicMock
    reference = 'a' * 32
    first = BridgeSession('voicer-agent-' + '1' * 32, '1' * 32, '1' * 64)
    second = BridgeSession('voicer-agent-' + '2' * 32, '2' * 32, '2' * 64)
    credentials.publish(first, reference=reference)
    with patch('core.agent_client.AgentClient') as factory:
        clients = [MagicMock(), MagicMock()]
        factory.side_effect = clients
        client = SessionAgentClient(reference)
        client.request({'method': 'submit', 'command': {'test': 'one'}})
        credentials.remove(reference)
        with pytest.raises(CommandError, match='APP_NOT_READY'):
            client.request({'method': 'describe'})
        credentials.publish(second, reference=reference)
        client.request({'method': 'describe'})
        assert clients[0].request.call_count == 1
        assert clients[1].request.call_args.args[0] == {'method': 'describe'}
        clients[0].close.assert_called_once()
        client.close()


def test_remembered_reference_never_overwrites_another_open_instance(vault):
    reference = 'a' * 32
    first = BridgeSession('voicer-agent-' + '1' * 32, '1' * 32, '1' * 64)
    second = BridgeSession('voicer-agent-' + '2' * 32, '2' * 32, '2' * 64)
    credentials.publish(first, reference=reference)
    with pytest.raises(CommandError, match='REFERENCE_IN_USE'):
        credentials.publish(second, reference=reference)
    assert credentials.resolve(reference)['session_id'] == first.session_id


def test_public_config_contains_no_credential(window, vault, tmp_path):
    win, _ = window
    win.on_agent_connection()
    dialog = win._agent_dialog
    win._enable_agent_bridge()
    try:
        win._add_agent_connection({'read_project'})
        dialog.refresh()
        dialog.clients.setCurrentRow(0)
        with patch('gui.agent_dialog.QFileDialog.getOpenFileName', return_value=(str(tmp_path / 'ภาษาไทย space' / 'python.exe'), '')):
            dialog._copy()
        from PySide6.QtWidgets import QApplication
        config = json.loads(QApplication.clipboard().text())
        entry = config['mcpServers']['voicer-studio']
        assert Path(entry['command']).is_absolute() and Path(entry['args'][0]).is_absolute()
        assert entry['args'][1] == '--session'
        ticket = credentials.resolve(entry['args'][2])
        assert ticket['credential'] not in json.dumps(config)
        assert ticket['credential'] not in json.dumps(win._settings)
    finally:
        win._disable_agent_bridge()
        dialog.close()


def test_copy_without_connection_is_not_silent(window):
    win, _ = window
    win.on_agent_connection()
    dialog = win._agent_dialog
    with patch('gui.agent_dialog.QMessageBox.information') as notice:
        dialog._copy()
    notice.assert_called_once()
    assert not win._agent_connections
    dialog.close()


def test_quick_connect_copy_presets_and_consent(window, vault, tmp_path):
    from PySide6.QtWidgets import QApplication, QMessageBox
    win, _ = window
    win.on_agent_connection()
    dialog = win._agent_dialog
    dialog._set_scopes({'read_project', 'read_transcript', 'edit_caption'})
    with patch('gui.agent_dialog.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
        dialog._connect_copy()
    assert not win._agent_connections and win._agent_bridge is None
    try:
        with patch('gui.agent_dialog.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), \
             patch('gui.agent_dialog.QFileDialog.getOpenFileName', return_value=(str(tmp_path / 'python.exe'), '')) as picker:
            dialog._connect_copy()
            dialog._copy()
        assert picker.call_count == 1
        assert dialog.enabled.isChecked() and len(win._agent_connections) == 1
        session = dialog._selected_session()
        assert set(win.agent_commands().describe(session)['scopes']) == {'read_project', 'read_transcript', 'edit_caption'}
        assert dialog.connection_config.toPlainText() == QApplication.clipboard().text()
        assert dialog.copy_feedback.text() != ''
        dialog._revoke()
        assert not dialog.connection_config.toPlainText()
    finally:
        win._disable_agent_bridge()
        dialog.close()


def test_codex_copy_format_is_valid_and_has_no_credential(window, vault, tmp_path):
    import sys
    from PySide6.QtWidgets import QApplication
    win, _ = window
    win.on_agent_connection()
    dialog = win._agent_dialog
    win._enable_agent_bridge()
    try:
        win._add_agent_connection({'read_project'})
        dialog.refresh()
        dialog.config_format.setCurrentIndex(1)
        with patch('gui.agent_dialog.QFileDialog.getOpenFileName', return_value=(str(tmp_path / 'ภาษาไทย space' / 'python.exe'), '')):
            dialog._copy()
        encoded = QApplication.clipboard().text()
        assert encoded == dialog.connection_config.toPlainText()
        lines = encoded.splitlines()
        assert lines[0] == '[mcp_servers.voicer-studio]'
        command = json.loads(lines[1].split(' = ', 1)[1])
        args = json.loads(lines[2].split(' = ', 1)[1])
        assert Path(command).is_absolute() and args[1] == '--session'
        assert credentials.resolve(args[2])['credential'] not in encoded
        if sys.version_info >= (3, 11):
            import tomllib
            assert tomllib.loads(encoded)['mcp_servers']['voicer-studio'] == {'command': command, 'args': args}
    finally:
        win._disable_agent_bridge()
        dialog.close()


@pytest.mark.parametrize('confirm', [False, True])
def test_approve_all_is_once_reviewed_and_undoable(window, vault, confirm):
    win, _ = window
    win.on_agent_connection()
    dialog = win._agent_dialog
    win._enable_agent_bridge()
    try:
        session = win._add_agent_connection({'read_project', 'edit_caption'})
        job = proposal(win, session)
        with patch.object(dialog, '_confirm_all', return_value=confirm) as review, \
             patch('gui.agent_dialog.QMessageBox.information'):
            dialog._approve_all()
        review.assert_called_once()
        assert win.agent_commands()._jobs[job].state == ('succeeded' if confirm else 'awaiting_approval')
        if confirm:
            win.on_undo()
        assert win._state.dialogues[0].caption == 'original caption'
    finally:
        win._disable_agent_bridge()
        dialog.close()


def test_approve_all_preserves_revision_conflicts(window, vault):
    win, _ = window
    win.on_agent_connection()
    dialog = win._agent_dialog
    win._enable_agent_bridge()
    try:
        sessions = [win._add_agent_connection({'read_project', 'edit_caption'}) for _ in range(2)]
        first, second = [proposal(win, session) for session in sessions]
        with patch.object(dialog, '_confirm_all', return_value=True), \
             patch('gui.agent_dialog.QMessageBox.information'):
            dialog._approve_all()
        commands = win.agent_commands()
        assert commands._jobs[first].state == 'succeeded'
        assert commands._jobs[second].error == 'REVISION_CONFLICT'
        win.on_undo()
        assert win._state.dialogues[0].caption == 'original caption'
    finally:
        win._disable_agent_bridge()
        dialog.close()


@pytest.mark.parametrize('scenario', ['expired', 'tampered', 'options', 'revoked', 'new_request'])
def test_approve_all_rechecks_after_review_and_never_includes_future_requests(window, vault, scenario):
    win, _ = window
    win.on_agent_connection()
    dialog = win._agent_dialog
    win._enable_agent_bridge()
    commands = win.agent_commands()
    session = win._add_agent_connection({'read_project', 'edit_caption'})
    job_id = proposal(win, session)
    added = []
    def review(pending):
        assert len(pending) == 1
        if scenario == 'expired':
            commands._jobs[job_id].expires_at = 0
        elif scenario == 'tampered':
            commands._jobs[job_id].command['caption'] = 'not reviewed'
        elif scenario == 'options':
            win._settings['whisper_model'] = 'changed-during-review'
        elif scenario == 'revoked':
            win._disable_agent_bridge()
        else:
            other = win._add_agent_connection({'read_project', 'edit_caption'})
            added.append(proposal(win, other))
        return True
    try:
        with patch.object(dialog, '_confirm_all', side_effect=review), \
             patch('gui.agent_dialog.QMessageBox.information'):
            dialog._approve_all()
        if scenario == 'new_request':
            assert commands._jobs[job_id].state == 'succeeded'
            assert commands._jobs[added[0]].state == 'awaiting_approval'
            win.on_undo()
        else:
            assert commands._jobs[job_id].state != 'succeeded'
        assert win._state.dialogues[0].caption == 'original caption'
    finally:
        win._disable_agent_bridge()
        dialog.close()


def test_approve_all_review_shows_plain_diff_and_cancel_is_default(window, vault):
    from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit
    win, _ = window
    win.on_agent_connection()
    dialog = win._agent_dialog
    win._enable_agent_bridge()
    try:
        session = win._add_agent_connection({'read_project', 'edit_caption'})
        job_id = proposal(win, session)
        def inspect_review(review):
            encoded = review.findChild(QPlainTextEdit).toPlainText()
            assert 'original caption' in encoded and '<script>' in encoded
            buttons = review.findChild(QDialogButtonBox)
            assert buttons.button(QDialogButtonBox.StandardButton.Cancel).isDefault()
            return QDialog.DialogCode.Rejected
        with patch.object(QDialog, 'exec', new=inspect_review):
            assert not dialog._confirm_all([(job_id, win.agent_commands()._jobs[job_id].fingerprint)])
        assert win.agent_commands()._jobs[job_id].state == 'awaiting_approval'
    finally:
        win._disable_agent_bridge()
        dialog.close()


@pytest.mark.parametrize('mode', ['session', 'always'])
def test_auto_policy_runs_deferred_on_owner_thread_and_is_undoable(window, vault, mode):
    win, app = window
    win._enable_agent_bridge()
    try:
        session = win._add_agent_connection({'read_project', 'edit_caption'}, approval_mode=mode)
        job_id = proposal(win, session)
        commands = win.agent_commands()
        assert commands._jobs[job_id].state == 'awaiting_approval'
        assert win._state.dialogues[0].caption == 'original caption'
        pump(app, lambda: commands._jobs[job_id].state == 'succeeded')
        win.on_undo()
        assert win._state.dialogues[0].caption == 'original caption'
    finally:
        win._disable_agent_bridge()


@pytest.mark.parametrize('stop', ['ask', 'revoke', 'disable'])
def test_user_can_stop_queued_auto_approval_before_event_loop(window, vault, stop):
    win, app = window
    win._enable_agent_bridge()
    commands = win.agent_commands()
    try:
        session = win._add_agent_connection({'read_project', 'edit_caption'}, approval_mode='session')
        job_id = proposal(win, session)
        if stop == 'ask':
            commands.set_approval_mode(session, 'ask')
        elif stop == 'revoke':
            win._revoke_agent_connection(session)
        else:
            win._disable_agent_bridge()
        app.processEvents()
        assert commands._jobs[job_id].state != 'succeeded'
        assert win._state.dialogues[0].caption == 'original caption'
    finally:
        win._disable_agent_bridge()


def test_approval_mode_ui_consent_persistence_and_existing_connection(window, vault):
    from gui.agent_dialog import AgentDialog
    from PySide6.QtWidgets import QMessageBox
    win, app = window
    win.on_agent_connection()
    dialog = win._agent_dialog
    assert dialog.approval_mode.currentData() == 'ask'
    win._enable_agent_bridge()
    try:
        session = win._add_agent_connection({'read_project', 'edit_caption'})
        dialog.refresh()
        with patch('gui.agent_dialog.QMessageBox.question', return_value=QMessageBox.StandardButton.No):
            dialog.approval_mode.setCurrentIndex(1)
        assert dialog.approval_mode.currentData() == 'ask'
        with patch('gui.agent_dialog.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), \
             patch.object(win, '_save_settings', return_value=True) as save:
            dialog.approval_mode.setCurrentIndex(2)
        assert win._settings['mcp_approval_mode'] == 'always'
        assert win.agent_commands().describe(session)['approval_mode'] == 'always'
        save.assert_called_once()
        reopened = AgentDialog(win)
        assert reopened.approval_mode.currentData() == 'always'
        reopened.deleteLater()
        with patch.object(win, '_save_settings', return_value=True):
            dialog.approval_mode.setCurrentIndex(0)
        assert win._settings['mcp_approval_mode'] == 'ask'
        assert win.agent_commands().describe(session)['approval_mode'] == 'ask'
        app.processEvents()
    finally:
        win._disable_agent_bridge()
        dialog.close()


def test_selected_connection_shows_its_own_policy_without_changing_permissions(window, vault):
    win, _ = window
    win.on_agent_connection()
    dialog = win._agent_dialog
    win._enable_agent_bridge()
    try:
        first = win._add_agent_connection({'read_project'}, approval_mode='session')
        second = win._add_agent_connection({'read_project'}, approval_mode='ask')
        with patch('gui.agent_dialog.QMessageBox.question') as confirm, \
             patch.object(win, '_save_settings') as save:
            dialog.refresh()
            dialog.clients.setCurrentRow(0)
            assert dialog.approval_mode.currentData() == 'session'
            dialog.clients.setCurrentRow(1)
            assert dialog.approval_mode.currentData() == 'ask'
            dialog.refresh()
            assert dialog.approval_mode.currentData() == 'ask'
            confirm.assert_not_called()
            save.assert_not_called()
        assert win.agent_commands().describe(first)['approval_mode'] == 'session'
        assert win.agent_commands().describe(second)['approval_mode'] == 'ask'
    finally:
        win._disable_agent_bridge()
        dialog.close()


def test_always_mode_does_not_apply_when_settings_save_fails(window):
    from PySide6.QtWidgets import QMessageBox
    win, _ = window
    win.on_agent_connection()
    dialog = win._agent_dialog
    with patch('gui.agent_dialog.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), \
         patch('gui.agent_dialog.QMessageBox.warning') as warning, \
         patch.object(win, '_save_settings', return_value=False):
        dialog.approval_mode.setCurrentIndex(2)
    warning.assert_called_once()
    assert dialog.approval_mode.currentData() == 'ask'
    assert win._settings.get('mcp_approval_mode') == 'ask'
    assert win._agent_bridge is None
    dialog.close()


def test_gui_diff_approval_and_undo(window, vault):
    win, _ = window
    win.on_agent_connection()
    win._enable_agent_bridge()
    dialog = win._agent_dialog
    try:
        session = win._add_agent_connection({'read_project', 'edit_caption'})
        job_id = proposal(win, session)
        dialog.refresh()
        dialog.jobs.selectRow(0)
        assert 'original caption' in dialog.details.toPlainText()
        assert '<script>' in dialog.details.toPlainText()  # Plain text, never executable rich content.
        dialog._approve()
        assert win.agent_commands()._jobs[job_id].state == 'succeeded'
        win.on_undo()
        assert win._state.dialogues[0].caption == 'original caption'
    finally:
        win._disable_agent_bridge()
        dialog.close()


def test_approval_expired_and_payload_changed_do_not_mutate(window):
    win, _ = window
    commands = win.agent_commands()
    session = commands.grant({'read_project', 'edit_caption'})
    job = proposal(win, session)
    commands._jobs[job].expires_at = 0
    with pytest.raises(CommandError, match='APPROVAL_EXPIRED'):
        commands.approve(job)
    other = proposal(win, session)
    commands._jobs[other].command['caption'] = 'tampered'
    with pytest.raises(CommandError, match='APPROVAL_CHANGED'):
        commands.approve(other)
    assert win._state.dialogues[0].caption == 'original caption'


def test_bridge_expires_pending_without_polling(window, vault, monkeypatch):
    win, app = window
    monkeypatch.setattr('core.agent_commands.APPROVAL_TTL_SECONDS', .03)
    win._enable_agent_bridge()
    try:
        session = win._add_agent_connection({'read_project', 'edit_caption'})
        job = proposal(win, session)
        pump(app, lambda: win.agent_commands()._jobs[job].state == 'cancelled')
        assert win.agent_commands()._jobs[job].error == 'APPROVAL_EXPIRED'
        assert not win._agent_bridge._approval_timer.isActive()
    finally:
        win._disable_agent_bridge()


@pytest.mark.parametrize('cancel', [False, True])
def test_disable_revokes_pending_and_preserves_running_control(window, vault, cancel):
    win, _ = window
    win._enable_agent_bridge()
    commands = win.agent_commands()
    session = win._add_agent_connection({'read_project', 'export'})
    job = proposal(win, session, 'export')
    calls = []
    commands.bind(job, lambda: calls.append(True))
    win._disable_agent_bridge(cancel_running=cancel)
    assert not commands._sessions and not vault
    assert calls == ([True] if cancel else [])
    if not cancel:
        commands.cancel_trusted(job)
        assert calls == [True]
    commands.finish(job, 'cancelled')
    assert commands._jobs[job].state == 'cancelled'


def test_secure_reference_roundtrip_and_invalid_ids(vault):
    ticket = BridgeSession('voicer-agent-' + secrets.token_hex(16), secrets.token_hex(16), secrets.token_hex(32))
    reference = credentials.publish(ticket)
    assert credentials.resolve(reference)['credential'] == ticket.credential
    for bad in ('../x', 'a' * 33, '\\\\network', None):
        with pytest.raises(CommandError, match='INVALID_ARGUMENT'):
            credentials.resolve(bad)
    credentials.remove(reference)
    assert not vault
    with pytest.raises(CommandError, match='APP_NOT_READY'):
        credentials.resolve(reference)


def test_untrusted_keyring_backend_is_rejected(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, 'keyring', SimpleNamespace(get_keyring=lambda: SimpleNamespace()))
    with pytest.raises(CommandError, match='PERMISSION_DENIED'):
        credentials._backend()


def test_path_traversal_network_extension_and_links(tmp_path):
    valid = tmp_path / 'project.voicer'
    assert validate_output(valid, '.voicer') == valid
    for path in (tmp_path / '..' / 'outside.voicer', Path('relative.voicer'), Path('//server/share/project.voicer'), tmp_path / 'wrong.txt'):
        with pytest.raises(CommandError, match='PATH_DENIED'):
            validate_output(path, '.voicer')
    target = tmp_path / 'target'
    target.mkdir()
    link = tmp_path / 'redirect'
    if os.name == 'nt':
        import subprocess
        # Explicit test-only junction within tmp_path; never targets user directories.
        result = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True)
        assert result.returncode == 0
    else:
        link.symlink_to(target, target_is_directory=True)
    with pytest.raises(CommandError, match='PATH_DENIED'):
        validate_output(link / 'project.voicer', '.voicer')


@pytest.mark.parametrize('scenario', ['overwrite_denied', 'repair_denied', 'redirected'])
def test_agent_export_never_inherits_blanket_repair_or_overwrite(window, tmp_path, scenario):
    from PySide6.QtWidgets import QDialog, QMessageBox
    from gui.export_dialog import ExportDialog
    win, _ = window
    commands = win.agent_commands()
    session = commands.grant({'read_project', 'export'})
    job = proposal(win, session, 'export')
    commands.bind(job, lambda: None)
    win._agent_pending_job = job
    dialog = ExportDialog(win, win._state, {'auto_repair_missing_export_assets': True})
    dialog.target_zip_path = tmp_path / ('wrong.txt' if scenario == 'redirected' else 'output.zip')
    if scenario == 'overwrite_denied':
        dialog.target_zip_path.write_bytes(b'preserve existing output')
    try:
        with patch('gui.export_dialog.QMessageBox.question', return_value=QMessageBox.StandardButton.No), \
             patch('gui.export_dialog.QMessageBox.warning'), \
             patch('gui.export_dialog.ExportRepairConfirmDialog.exec', return_value=QDialog.DialogCode.Rejected) as repair, \
             patch('gui.export_dialog.FullExportWorker') as worker:
            dialog._start_export()
            worker.assert_not_called()
            assert repair.call_count == (1 if scenario == 'repair_denied' else 0)
            assert dialog.settings['auto_repair_missing_export_assets'] is True
        if scenario == 'overwrite_denied':
            assert dialog.target_zip_path.read_bytes() == b'preserve existing output'
    finally:
        win._agent_pending_job = None
        commands.finish(job, 'cancelled')
        dialog.deleteLater()


def test_path_recheck_is_not_a_race_safe_write(tmp_path):
    """Release-gate evidence: a post-validation redirect still escapes selection.

    This test reproduces a known limitation, not a security pass. Both the
    selected directory and redirected destination are disposable test fixtures.
    """
    from core.models import PipelineState
    from core.project_manager import ProjectManager
    import subprocess
    selected = tmp_path / 'selected'
    selected.mkdir()
    redirected = tmp_path / 'redirected'
    redirected.mkdir()
    destination = validate_output(selected / 'race.voicer', '.voicer')
    selected.rename(tmp_path / 'original_selection')
    if os.name == 'nt':
        result = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(selected), str(redirected)],
                                capture_output=True)
        assert result.returncode == 0
    else:
        selected.symlink_to(redirected, target_is_directory=True)
    # A later recheck detects the redirect, but there remains a gap after any
    # final recheck and before ProjectManager resolves/opens its destination.
    with pytest.raises(CommandError, match='PATH_DENIED'):
        validate_output(destination, '.voicer')
    assert ProjectManager.save_project(PipelineState(), destination)
    assert (redirected / 'race.voicer').is_file()
    assert not (tmp_path / 'original_selection' / 'race.voicer').exists()


def test_diagnostics_only_accepts_opaque_correlation_ids():
    import logging
    from core.diagnostics import _JsonFormatter
    record = logging.LogRecord('agent', logging.INFO, __file__, 1, 'Safe event', (), None)
    record.request_id = secrets.token_hex(16)
    record.job_id = 'private caption or credential'
    record.session_id = secrets.token_hex(16)
    record.code = 'APPROVAL_EXPIRED'
    record.arguments = {'caption': 'private caption'}
    result = json.loads(_JsonFormatter().format(record))
    assert result['request_id'] == record.request_id and result['code'] == 'APPROVAL_EXPIRED'
    assert 'job_id' not in result and 'arguments' not in result
    assert 'private caption' not in json.dumps(result)


def test_old_enabled_setting_does_not_auto_open_listener(window):
    from gui.main_window import MainWindow
    from core.models import PipelineState
    _, app = window
    with patch.object(MainWindow, '_load_settings', return_value={'check_updates_startup': False, 'mcp_enabled': True}), \
         patch('core.device_manager.device_manager.prewarm_async'):
        other = MainWindow()
    try:
        assert other._agent_bridge is None and other._agent_commands is None
        assert other._settings['mcp_enabled'] is False
    finally:
        other._autosave_timer.stop()
        other._state = PipelineState()
        other.deleteLater()
        app.processEvents()


def test_close_cancels_real_export_thread_without_destroying_it(window, vault, tmp_path):
    import time
    from threading import Event
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox
    from gui.export_dialog import ExportDialog, FullExportWorker
    win, app = window
    win._enable_agent_bridge()
    session = win._add_agent_connection({'read_project', 'export'})
    commands = win.agent_commands()
    job = proposal(win, session, 'export')
    win._current_project_path = tmp_path / 'current.voicer'
    dialog = ExportDialog(win, win._state, {})
    worker = FullExportWorker(win._state, tmp_path, tmp_path / 'cancel.zip', {})
    dialog.worker = worker
    win._export_dialog = dialog
    dialog.finished.connect(lambda _result: setattr(win, '_export_dialog', None))
    worker.settled.connect(dialog._on_worker_settled)
    win._agent_pending_job = job
    win._bind_agent_worker(worker, 'export')
    win._agent_pending_job = None
    entered, release = Event(), Event()
    def build(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return tmp_path
    try:
        with patch('gui.export_dialog.PackBuilder.build_pack', side_effect=build), \
             patch('gui.main_window.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
            worker.start()
            pump(app, entered.is_set)
            event = QCloseEvent()
            start = time.monotonic()
            win.closeEvent(event)
            assert not event.isAccepted() and time.monotonic() - start < .2
            assert worker.isRunning() and worker._is_cancelled
            release.set()
            pump(app, lambda: not worker.isRunning() and win._export_dialog is None)
            pump(app, lambda: win._agent_bridge is None)
        assert commands._jobs[job].state == 'cancelled'
        assert not vault
    finally:
        release.set()
        worker.wait(5000)
        win._export_dialog = None
        win._disable_agent_bridge()
        dialog.deleteLater()
