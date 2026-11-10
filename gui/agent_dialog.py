"""Modeless trusted MCP controls. No SDK/model imports or background polling."""
from __future__ import annotations

import json
from pathlib import Path
import sys

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QLabel, QListWidget, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget)
from core.agent_commands import CommandError, TERMINAL, SCOPES
from core.i18n import tr
from gui.ui_utils import apply_dark_title_bar


class AgentDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self._interpreter = None
        self._copied_session = None
        self._connect_requested = False
        self.setWindowTitle(tr('mcp_title'))
        self.resize(720, 520)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        layout = QVBoxLayout(self)
        warning = QLabel(tr('mcp_warning'))
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self.enabled = QCheckBox(tr('mcp_enable'))
        self.enabled.setChecked(owner._agent_bridge is not None)
        self.enabled.toggled.connect(self._toggle)
        layout.addWidget(self.enabled)
        steps = QLabel(tr('mcp_live_hint'))
        steps.setWordWrap(True)
        layout.addWidget(steps)
        connect_row = QHBoxLayout()
        self.target_client = QComboBox()
        for client in ('codex', 'claude', 'manual'):
            self.target_client.addItem(tr('mcp_target_' + client), client)
        self.target_client.currentIndexChanged.connect(self._client_changed)
        connect_row.addWidget(self.target_client, 1)
        self.connect_button = QPushButton(tr('mcp_connect_app'))
        self.connect_button.clicked.connect(self._connect_selected)
        connect_row.addWidget(self.connect_button)
        self.choose_python = QPushButton(tr('mcp_choose_python'))
        self.choose_python.clicked.connect(self._choose_interpreter)
        connect_row.addWidget(self.choose_python)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.live_clients = QListWidget()
        self.live_clients.setMaximumHeight(80)
        layout.addWidget(self.live_clients)
        self.always = QCheckBox(tr('mcp_simple_always'))
        self.always.setChecked(owner._settings.get('mcp_approval_mode') == 'always')
        self.always.toggled.connect(self._set_always)
        layout.addWidget(self.always)
        self.grant_all = QPushButton(tr('mcp_grant_all_scopes'))
        self.grant_all.clicked.connect(self._grant_all_scopes)
        layout.addWidget(self.grant_all)
        consent = QLabel(tr('mcp_simple_consent'))
        consent.setWordWrap(True)
        layout.addWidget(consent)
        self.connection_status = QLabel(tr('mcp_live_hint') if owner._agent_bridge else tr('mcp_simple_off'))
        self.connection_status.setWordWrap(True)
        self.connection_status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.connection_status)
        advanced_toggle = QPushButton(tr('mcp_advanced_connection'))
        self.advanced_toggle = advanced_toggle
        advanced_toggle.setCheckable(True)
        self.advanced_panel = QWidget()
        advanced_toggle.toggled.connect(self.advanced_panel.setVisible)
        layout.addWidget(advanced_toggle)
        layout.addWidget(self.advanced_panel)
        root_layout = layout
        layout = QVBoxLayout(self.advanced_panel)
        layout.addLayout(connect_row)
        self.approval_mode = QComboBox()
        for mode in ('ask', 'session', 'always'):
            self.approval_mode.addItem(tr('mcp_mode_' + mode), mode)
        remembered = 'always' if owner._settings.get('mcp_approval_mode') == 'always' else 'ask'
        self.approval_mode.setCurrentIndex(self.approval_mode.findData(remembered))
        self._last_approval_mode = remembered
        self.approval_mode.currentIndexChanged.connect(self._approval_mode_changed)
        layout.addWidget(self.approval_mode)
        mode_hint = QLabel(tr('mcp_mode_hint'))
        mode_hint.setWordWrap(True)
        layout.addWidget(mode_hint)
        presets = QHBoxLayout()
        for key, scopes in [('mcp_preset_read', {'read_project'}),
                            ('mcp_preset_captions', {'read_project', 'read_transcript', 'edit_caption'})]:
            button = QPushButton(tr(key))
            button.clicked.connect(lambda _checked=False, selected=scopes: self._set_scopes(selected))
            presets.addWidget(button)
        layout.addLayout(presets)
        self.scopes = {}
        permissions = QWidget()
        permission_layout = QVBoxLayout(permissions)
        permission_layout.setContentsMargins(0, 0, 0, 0)
        advanced = QPushButton(tr('mcp_permissions'))
        advanced.setCheckable(True)
        advanced.toggled.connect(permissions.setVisible)
        layout.addWidget(advanced)
        for scope in ('read_project', 'read_transcript', 'read_speaker_names', 'edit_caption',
                      'edit_speaker', 'save_project', 'export', 'pipeline', 'analyze_speakers', 'edit_clips', 'manage_speakers'):
            check = QCheckBox(tr('mcp_scope_' + scope))
            self.scopes[scope] = check
            permission_layout.addWidget(check)
        layout.addWidget(permissions)
        permissions.hide()
        self.clients = QListWidget()
        self.clients.setMaximumHeight(95)
        self.clients.currentItemChanged.connect(self._sync_approval_mode)
        layout.addWidget(self.clients)
        self.config_format = QComboBox()
        self.config_format.addItem(tr('mcp_format_json'), 'json')
        self.config_format.addItem(tr('mcp_format_codex'), 'codex')
        self.config_format.currentIndexChanged.connect(self._clear_config)
        format_row = QHBoxLayout()
        format_row.addWidget(self.config_format)
        layout.addLayout(format_row)
        controls = QHBoxLayout()
        for key, action in [('mcp_copy', self._copy)]:
            button = QPushButton(tr(key))
            button.clicked.connect(action)
            controls.addWidget(button)
        layout.addLayout(controls)
        interpreter_hint = QLabel(tr('mcp_interpreter_hint'))
        interpreter_hint.setWordWrap(True)
        layout.addWidget(interpreter_hint)
        self.copy_feedback = QLabel(tr('mcp_not_copied'))
        self.copy_feedback.setTextFormat(Qt.TextFormat.PlainText)
        self.copy_feedback.setWordWrap(True)
        layout.addWidget(self.copy_feedback)
        self.connection_config = QPlainTextEdit()
        self.connection_config.setReadOnly(True)
        self.connection_config.setPlaceholderText(tr('mcp_config_placeholder'))
        self.connection_config.setMaximumHeight(100)
        layout.addWidget(self.connection_config)
        self.advanced_panel.hide()
        layout = root_layout
        self.jobs = QTableWidget(0, 5)
        self.jobs.setHorizontalHeaderLabels([tr(k) for k in ('mcp_job', 'mcp_client', 'mcp_operation', 'mcp_state', 'mcp_progress')])
        self.jobs.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.jobs.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.jobs.itemSelectionChanged.connect(self._preview)
        layout.addWidget(self.jobs)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(170)
        layout.addWidget(self.details)
        actions = QHBoxLayout()
        self.approve = QPushButton(tr('mcp_approve'))
        self.approve.clicked.connect(self._approve)
        self.approve_all = QPushButton(tr('mcp_approve_all'))
        self.approve_all.clicked.connect(self._approve_all)
        self.cancel = QPushButton(tr('mcp_cancel'))
        self.cancel.clicked.connect(self._cancel)
        actions.addWidget(self.approve)
        actions.addWidget(self.approve_all)
        actions.addWidget(self.cancel)
        layout.addLayout(actions)
        # Single-shot coalescing only after state events; never a polling timer.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh)
        self._preview_signature = None
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        apply_dark_title_bar(self)
        self.refresh()

    def schedule_refresh(self):
        if self.isVisible() and not self._refresh_timer.isActive():
            self._refresh_timer.start(100)

    def _error(self, code):
        message = tr('mcp_error_dependency') if code == 'DEPENDENCY_MISSING' else tr('mcp_error', code=code)
        QMessageBox.warning(self, tr('mcp_title'), message)

    def _clear_config(self, _index=None):
        self._copied_session = None
        self.connection_config.clear()
        self.copy_feedback.setText(tr('mcp_not_copied'))

    def _toggle(self, enabled):
        was_enabled = self.owner._agent_bridge is not None
        try:
            if enabled:
                self.owner._enable_agent_bridge()
                if not self.owner._agent_connections:
                    if self._add() is None:
                        raise CommandError('APP_NOT_READY')
                self.refresh()
                self.connection_status.setText(tr('mcp_live_hint'))
            elif not self.owner._disable_agent_bridge(ask=True):
                enabled = True
            else:
                self._connect_requested = False
                self.connection_status.setText(tr('mcp_simple_off'))
        except CommandError as exc:
            if not was_enabled and self.owner._agent_bridge is not None:
                self.owner._disable_agent_bridge()
            self._error(exc.code)
            enabled = False
        self.enabled.blockSignals(True)
        self.enabled.setChecked(enabled)
        self.enabled.blockSignals(False)
        self.refresh()

    def _client_changed(self, _index):
        self._connect_requested = False
        self.config_format.setCurrentIndex(1 if self.target_client.currentData() == 'codex' else 0)
        self._clear_config()
        self.connection_status.setText(tr('mcp_connect_hint'))

    def _connect_selected(self):
        if self.owner._agent_bridge is None:
            self._error('APP_NOT_READY')
            return
        session = self._selected_session()
        selected = {key for key, check in self.scopes.items() if check.isChecked()}
        if not session or set(self.owner.agent_commands().describe(session)['scopes']) != selected:
            if session:
                self.owner._revoke_agent_connection(session)
            if self._add() is None:
                return
        if self.target_client.currentData() == 'manual':
            self._copy()
            if self.connection_config.toPlainText():
                self.connection_status.setText(tr('mcp_manual_ready'))
                self.advanced_toggle.setChecked(True)
            return
        self._connect_requested = True
        self._auto_setup()

    def _set_always(self, checked):
        self.approval_mode.setCurrentIndex(self.approval_mode.findData('always' if checked else 'ask'))
        self.always.blockSignals(True)
        self.always.setChecked(self.approval_mode.currentData() == 'always')
        self.always.blockSignals(False)

    def _grant_all_scopes(self):
        if not (self.owner._state.video_path or self.owner._state.dialogues):
            self._error('NO_PROJECT')
            return
        self._set_scopes(SCOPES)
        session = self._selected_session()
        if session:
            self.owner._revoke_agent_connection(session)
        self.owner._enable_agent_bridge()
        if self._add() is not None:
            self.enabled.blockSignals(True)
            self.enabled.setChecked(True)
            self.enabled.blockSignals(False)
            if self._connect_requested:
                self._auto_setup()

    def _auto_setup(self):
        from gui.agent_setup_worker import AgentSetupWorker
        worker = getattr(self.owner, '_agent_setup_worker', None)
        if worker is not None:
            self.connection_status.setText(tr('mcp_client_setup_busy', client=self.target_client.currentText()))
            return
        session = self._selected_session()
        if not session:
            return
        reference = self.owner._agent_connections[session]['reference']
        worker = AgentSetupWorker(Path(__file__).resolve().parents[1], reference, self._interpreter, self.owner,
                                  client=self.target_client.currentData())
        self.owner._agent_setup_worker = worker
        self.connection_status.setText(tr('mcp_client_setup_busy', client=self.target_client.currentText()))
        self.connect_button.setEnabled(False)
        worker.ready.connect(self._setup_done)
        worker.finished.connect(self._setup_finished)
        worker.start()

    def _setup_finished(self):
        worker = self.owner._agent_setup_worker
        self.owner._agent_setup_worker = None
        reference = worker.reference
        worker.deleteLater()
        session = self._selected_session()
        if (self._connect_requested and worker.client == self.target_client.currentData() and
                self.owner._agent_bridge and session and self.owner._agent_connections[session]['reference'] != reference):
            self._auto_setup()  # Coalesce permission changes during setup.
        self.refresh()

    def _setup_done(self, interpreter, error):
        worker = self.owner._agent_setup_worker
        if worker and worker.client != self.target_client.currentData():
            self.connection_status.setText(tr('mcp_connect_hint'))
            return
        if not self.owner._agent_bridge:
            self.connection_status.setText(tr('mcp_simple_off'))
        elif error:
            reason = tr('mcp_setup_reason_' + error) if error in ('CODEX_CLI_MISSING', 'DEPENDENCY_MISSING',
                'CLIENT_NOT_INSTALLED', 'MCP_CONFIG_CUSTOMIZED', 'MCP_NAME_CONFLICT') else tr('mcp_setup_reason_default')
            self.connection_status.setText(tr('mcp_client_setup_error', code=error, reason=reason))
        else:
            self._interpreter = interpreter
            self.connection_status.setText(tr('mcp_client_ready_' + self.target_client.currentData()))

    def _selected_session(self):
        item = self.clients.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _set_scopes(self, selected):
        for key, check in self.scopes.items():
            check.setChecked(key in selected)

    def _sync_approval_mode(self, *_args):
        session = self._selected_session()
        if session:
            mode = self.owner.agent_commands().describe(session)['approval_mode']
            self._last_approval_mode = mode
            self._restore_approval_mode()

    def _restore_approval_mode(self):
        self.approval_mode.blockSignals(True)
        self.approval_mode.setCurrentIndex(self.approval_mode.findData(self._last_approval_mode))
        self.approval_mode.blockSignals(False)
        self.always.blockSignals(True)
        self.always.setChecked(self.approval_mode.currentData() == 'always')
        self.always.blockSignals(False)

    def _approval_mode_changed(self, _index):
        mode = self.approval_mode.currentData()
        if mode != 'ask' and QMessageBox.question(self, tr('mcp_title'), tr('mcp_auto_confirm'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            self._restore_approval_mode()
            return
        previous = self.owner._settings.get('mcp_approval_mode', 'ask')
        persisted = 'always' if mode == 'always' else 'ask'
        if previous != persisted:
            self.owner._settings['mcp_approval_mode'] = persisted
            if not self.owner._save_settings(self.owner._settings):
                self.owner._settings['mcp_approval_mode'] = previous
                self._restore_approval_mode()
                self._error('SETTINGS_SAVE_FAILED')
                return
        self._last_approval_mode = mode
        session = self._selected_session()
        if session:
            try:
                self.owner.agent_commands().set_approval_mode(session, mode)
            except CommandError as exc:
                self._error(exc.code)
        self.refresh()

    def _connect_copy(self):
        scopes = {key for key, check in self.scopes.items() if check.isChecked()}
        description = (', '.join(tr('mcp_scope_' + key) for key in sorted(scopes)) or tr('mcp_metadata_only'))
        description += '\n' + tr('mcp_mode_' + self.approval_mode.currentData())
        if QMessageBox.question(self, tr('mcp_title'), tr('mcp_connect_confirm', scopes=description),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.owner._enable_agent_bridge()
            self.enabled.blockSignals(True)
            self.enabled.setChecked(True)
            self.enabled.blockSignals(False)
            if self._add() is not None:
                self._copy()
        except CommandError as exc:
            self._error(exc.code)

    def _add(self):
        try:
            session = self.owner._add_agent_connection({key for key, check in self.scopes.items() if check.isChecked()},
                                                      approval_mode=self.approval_mode.currentData())
            self.refresh()
            self.clients.setCurrentRow(self.clients.count() - 1)
            return session
        except CommandError as exc:
            self._error(exc.code)

    def _choose_interpreter(self):
        interpreter, _ = QFileDialog.getOpenFileName(self, tr('mcp_interpreter'), self._interpreter or sys.executable)
        if not interpreter:
            self.copy_feedback.setText(tr('mcp_copy_cancelled'))
            return None
        self._interpreter = str(Path(interpreter).resolve())
        self._clear_config()
        self.copy_feedback.setText(tr('mcp_python_selected', path=self._interpreter))
        return self._interpreter

    def _copy(self):
        session = self._selected_session()
        if not session and self.clients.count() == 1:
            self.clients.setCurrentRow(0)
            session = self._selected_session()
        if not session:
            QMessageBox.information(self, tr('mcp_title'), tr('mcp_copy_no_connection'))
            return
        interpreter = self._interpreter
        if not interpreter:
            interpreter = self._choose_interpreter()
        if not interpreter:
            self.copy_feedback.setText(tr('mcp_copy_cancelled'))
            return
        connection = self.owner._agent_connections.get(session)
        if not connection:
            self._error('APP_NOT_READY')
            return
        config = {'mcpServers': {'voicer-studio': {
            'command': str(Path(interpreter).resolve()),
            'args': [str(Path(__file__).resolve().parents[1] / 'scripts' / 'mcp_server.py'),
                     '--session', connection['reference']]}}}
        entry = config['mcpServers']['voicer-studio']
        if self.config_format.currentData() == 'codex':
            encoded = ('[mcp_servers.voicer-studio]\ncommand = ' + json.dumps(entry['command'], ensure_ascii=False)
                       + '\nargs = ' + json.dumps(entry['args'], ensure_ascii=False) + '\n')
        else:
            encoded = json.dumps(config, indent=2, ensure_ascii=False)
        self._copied_session = session
        self.connection_config.setPlainText(encoded)
        QApplication.clipboard().setText(encoded)
        self.copy_feedback.setText(tr('mcp_copied') if QApplication.clipboard().text() == encoded
                                   else tr('mcp_clipboard_failed'))

    def _revoke(self):
        session = self._selected_session()
        if session:
            try:
                commands = self.owner.agent_commands()
                running = [jid for jid, job in commands._jobs.items()
                           if job.owner == session and job.state in ('running', 'cancelling')]
                if running:
                    choice = QMessageBox.question(self, tr('mcp_title'), tr('mcp_disable_jobs'),
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                        QMessageBox.StandardButton.Cancel)
                    if choice == QMessageBox.StandardButton.Cancel:
                        return
                    if choice == QMessageBox.StandardButton.Yes:
                        for job_id in running:
                            commands.cancel_trusted(job_id)
                self.owner._revoke_agent_connection(session)
            except CommandError as exc:
                self._error(exc.code)
            self.refresh()

    def _selected_job(self):
        row = self.jobs.currentRow()
        item = self.jobs.item(row, 0) if row >= 0 else None
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def refresh(self):
        bridge = self.owner._agent_bridge
        self.connect_button.setEnabled(bool(bridge and self.owner._agent_setup_worker is None))
        self.grant_all.setEnabled(bool(bridge))
        connected = bridge.connected_clients() if bridge else []
        self.status.setText(tr('mcp_live_status', count=len(connected)) if bridge else tr('mcp_live_off'))
        self.live_clients.clear()
        for client in connected:
            # Handshake names are peer-reported labels, never authentication.
            self.live_clients.addItem(f"{client['name']} | {client['version']} | {client['protocol']}")
        session = self._selected_session()
        self.clients.blockSignals(True)
        self.clients.clear()
        for sid, connection in self.owner._agent_connections.items():
            status = self.owner.agent_commands().describe(sid)
            scopes = status['scopes']
            self.clients.addItem(tr('mcp_client_scopes', client=connection['reference'][:8],
                                    scopes=(', '.join(tr('mcp_scope_' + scope) for scope in scopes) or tr('mcp_metadata_only'))
                                    + ' | ' + tr('mcp_mode_' + status['approval_mode'])))
            item = self.clients.item(self.clients.count() - 1)
            item.setData(Qt.ItemDataRole.UserRole, sid)
            if sid == session:
                self.clients.setCurrentItem(item)
        if self.clients.count() == 1 and self.clients.currentRow() < 0:
            self.clients.setCurrentRow(0)
        self.clients.blockSignals(False)
        self._sync_approval_mode()
        if self._copied_session not in self.owner._agent_connections:
            self._clear_config()
        job_id = self._selected_job()
        commands = self.owner._agent_commands
        jobs = list(commands._jobs.items()) if commands else []
        self.approve_all.setEnabled(bool(bridge and any(job.state == 'awaiting_approval' for _, job in jobs)))
        self.jobs.blockSignals(True)
        self.jobs.setRowCount(len(jobs))
        for row, (jid, job) in enumerate(jobs):
            connection = self.owner._agent_connections.get(job.owner, {})
            values = [jid[:8], connection.get('reference', job.owner)[:8],
                      tr('mcp_op_' + job.command['operation']), tr('mcp_state_' + job.state), f'{job.progress:.0f}%']
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, jid)
                self.jobs.setItem(row, column, item)
            if jid == job_id:
                self.jobs.selectRow(row)
        self.jobs.blockSignals(False)
        self._preview()

    def _preview(self):
        commands = self.owner._agent_commands
        job_id = self._selected_job()
        job = commands._jobs.get(job_id) if commands else None
        self.approve.setEnabled(bool(job and job.state == 'awaiting_approval' and self.owner._agent_bridge))
        self.cancel.setEnabled(bool(job and job.state not in TERMINAL))
        if not job:
            self.details.clear()
            self._preview_signature = None
            return
        payload = dict(job.command)
        if job.command['operation'] in ('caption', 'speaker'):
            item = commands._clips.get(job.command['clip_ref'])
            payload['before'] = (item.caption if job.command['operation'] == 'caption' else item.speaker_id) if item else None
        elif job.command['operation'] in ('save', 'pipeline', 'export', 'analyze_voice'):
            payload['workflow'] = tr('mcp_workflow_' + job.command['operation'])
            payload['options'] = self._options()
        payload['error'] = job.error
        if job.result is not None:
            payload['result'] = job.result
        self.details.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))
        self._preview_signature = (job_id, job.fingerprint, json.dumps(self._options(), sort_keys=True))

    def _options(self):
        from core.pipeline import build_options_from_settings
        options = build_options_from_settings(self.owner._settings)
        return {key: options[key] for key in ('whisper_model', 'voice_sep_mode', 'compute_device',
            'output_dir', 'include_dub_video', 'timestamp_mode', 'audio_bitrate', 'image_quality')}

    def _confirm_all(self, pending):
        review = QDialog(self)
        review.setWindowTitle(tr('mcp_approve_all'))
        review.resize(700, 500)
        layout = QVBoxLayout(review)
        notice = QLabel(tr('mcp_approve_all_review', count=len(pending)))
        notice.setWordWrap(True)
        layout.addWidget(notice)
        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        records = []
        commands = self.owner.agent_commands()
        for job_id, _fingerprint in pending:
            job = commands._jobs[job_id]
            record = {'job': job_id[:8], 'command': dict(job.command)}
            if job.command['operation'] in ('caption', 'speaker'):
                item = commands._clips.get(job.command['clip_ref'])
                record['before'] = (item.caption if job.command['operation'] == 'caption' else item.speaker_id) if item else None
            elif job.command['operation'] in ('save', 'pipeline', 'export', 'analyze_voice'):
                record['workflow'] = tr('mcp_workflow_' + job.command['operation'])
                record['options'] = self._options()
            records.append(record)
        preview.setPlainText(json.dumps(records, ensure_ascii=False, indent=2))
        layout.addWidget(preview)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr('mcp_approve_all'))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        buttons.accepted.connect(review.accept)
        buttons.rejected.connect(review.reject)
        layout.addWidget(buttons)
        try:
            return review.exec() == QDialog.DialogCode.Accepted
        finally:
            review.deleteLater()

    def _approve_all(self):
        if self.owner._agent_bridge is None:
            self._error('APP_NOT_READY')
            return
        commands = self.owner.agent_commands()
        pending = [(job_id, job.fingerprint) for job_id, job in commands._jobs.items()
                   if job.state == 'awaiting_approval']
        if not pending:
            return
        options = json.dumps(self._options(), sort_keys=True)
        if not self._confirm_all(pending):
            return
        accepted, rejected = 0, 0
        for job_id, fingerprint in pending:
            job = commands._jobs.get(job_id)
            if (self.owner._agent_bridge is None or job is None or job.state != 'awaiting_approval'
                    or job.fingerprint != fingerprint or options != json.dumps(self._options(), sort_keys=True)):
                rejected += 1
                continue
            try:
                # Never rebase revisions or authorize new requests that appeared
                # during the review. The normal owner-thread guards still apply.
                commands.approve(job_id)
                accepted += 1
            except CommandError:
                rejected += 1
            except Exception:
                self._error('OPERATION_FAILED')
                break
        self.refresh()
        QMessageBox.information(self, tr('mcp_title'),
                                tr('mcp_approve_all_result', accepted=accepted, rejected=rejected))

    def _approve(self):
        job_id = self._selected_job()
        if not job_id:
            return
        commands = self.owner.agent_commands()
        job = commands._jobs[job_id]
        signature = (job_id, job.fingerprint, json.dumps(self._options(), sort_keys=True))
        if self._preview_signature != signature:
            self._error('APPROVAL_CHANGED')
            self._preview()
            return
        try:
            commands.approve(job_id)
        except CommandError as exc:
            self._error(exc.code)
        except Exception:
            self._error('OPERATION_FAILED')
        self.refresh()

    def _cancel(self):
        job_id = self._selected_job()
        if job_id:
            self.owner.agent_commands().cancel_trusted(job_id)
            self.refresh()
