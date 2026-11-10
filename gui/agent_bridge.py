"""Opt-in local IPC proof of concept, not an MCP server.

Only trusted test/GUI code may instantiate this bridge and grant a session.
Credentials remain in memory: there is intentionally no external discovery or
credential file until platform ACLs/discovery have been independently verified.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hmac
import json
import os
import re
from pathlib import Path
import secrets
import stat
import tempfile
import time
from uuid import uuid4

from PySide6.QtCore import QObject, QStandardPaths, QTimer, Signal
from PySide6.QtNetwork import QLocalServer
from core.agent_commands import MAX_MESSAGE_BYTES, CommandError, bounded_object

MAX_CONNECTIONS = 8
REQUEST_TIMEOUT_MS = 5000


@dataclass(frozen=True)
class BridgeSession:
    endpoint: str
    session_id: str
    credential: str = field(repr=False)


class AgentBridge(QObject):
    changed = Signal()

    def __init__(self, commands, parent=None):
        super().__init__(parent)
        commands._owner_check()
        self.commands = commands
        self._credentials = {}
        self._connections = {}
        self._rate = {}
        self._directory = None
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.setMaxPendingConnections(MAX_CONNECTIONS)
        endpoint = 'voicer-agent-' + uuid4().hex
        if os.name != 'nt':
            base = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
            base.mkdir(parents=True, exist_ok=True)
            directory = Path(tempfile.mkdtemp(prefix='agent-', dir=base))
            os.chmod(directory, 0o700)
            info = directory.stat()
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                directory.rmdir()
                raise CommandError('PERMISSION_DENIED')
            self._directory = directory
            endpoint = str(directory / 'socket')
        if not self.server.listen(endpoint):
            if self._directory:
                self._directory.rmdir()
            raise CommandError('APP_NOT_READY')
        if self._directory:
            try:
                os.chmod(endpoint, 0o600)
                info = Path(endpoint).lstat()
                if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                    raise CommandError('PERMISSION_DENIED')
            except (OSError, CommandError):
                self.server.close()
                self._directory.rmdir()
                raise CommandError('PERMISSION_DENIED') from None
        self.endpoint = self.server.fullServerName()
        self.server.newConnection.connect(self._accept)
        self._approval_timer = QTimer(self)
        self._approval_timer.setSingleShot(True)
        self._approval_timer.timeout.connect(self._expire)
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._approve_automatic)
        self.commands.change_notify = self._changed

    def _changed(self):
        import time
        pending = [job.expires_at for job in self.commands._jobs.values() if job.state == 'awaiting_approval']
        self._approval_timer.stop()
        self._auto_timer.stop()
        if pending:
            self._approval_timer.start(max(1, int((min(pending) - time.monotonic()) * 1000)))
        if self.commands.automatic_jobs():
            # Dispatch returns its job handle before opening GUI workflows.
            self._auto_timer.start(0)
        self.changed.emit()

    def _approve_automatic(self):
        for job_id in self.commands.automatic_jobs():
            try:
                self.commands.approve_automatic(job_id)
            except CommandError:
                pass  # The ordinary approval path records the fixed failure code.
            except Exception:
                self.commands.finish(job_id, 'failed', 'OPERATION_FAILED')

    def _expire(self):
        self.commands.expire_approvals()
        self._changed()

    def open_session(self, scopes, *, approval_mode='ask'):
        """Local permission grant; never dispatched to the socket peer."""
        self.commands._owner_check()
        if not self.server.isListening():
            raise CommandError('APP_NOT_READY')
        session_id = self.commands.grant(scopes, approval_mode=approval_mode)
        credential = secrets.token_hex(32)
        self._credentials[credential] = session_id
        return BridgeSession(self.endpoint, session_id, credential)

    def revoke(self, session_id):
        self.commands.revoke(session_id)
        self._rate.pop(session_id, None)
        self._credentials = {key: value for key, value in self._credentials.items() if value != session_id}
        for socket, connection in list(self._connections.items()):
            if connection['session'] == session_id:
                socket.abort()

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if len(self._connections) >= MAX_CONNECTIONS:
                socket.abort()
                socket.deleteLater()
                continue
            socket.setReadBufferSize(MAX_MESSAGE_BYTES + 1)
            timer = QTimer(socket)
            timer.setSingleShot(True)
            timer.timeout.connect(socket.abort)
            timer.start(REQUEST_TIMEOUT_MS)
            self._connections[socket] = {'buffer': bytearray(), 'session': None, 'timer': timer}
            socket.readyRead.connect(lambda socket=socket: self._read(socket))
            socket.disconnected.connect(lambda socket=socket: self._drop(socket))
            if socket.bytesAvailable():
                self._read(socket)

    def _drop(self, socket):
        connection = self._connections.pop(socket, None)
        from shiboken6 import isValid
        if isValid(socket):
            socket.deleteLater()
        if connection is not None and isValid(self):
            self.changed.emit()

    def _send(self, socket, response):
        data = json.dumps(response, ensure_ascii=False, allow_nan=False).encode('utf-8') + b'\n'
        if len(data) > MAX_MESSAGE_BYTES or socket.bytesToWrite() > MAX_MESSAGE_BYTES:
            socket.abort()
            return
        socket.write(data)

    def connected_clients(self):
        """Authenticated persistent MCP connections, not transient tool requests."""
        return [dict(connection['client']) for connection in self._connections.values()
                if connection.get('client') is not None]

    def _read(self, socket):
        connection = self._connections.get(socket)
        if connection is None:
            return
        if not connection['timer'].isActive():
            connection['timer'].start(REQUEST_TIMEOUT_MS)
        connection['buffer'].extend(bytes(socket.read(MAX_MESSAGE_BYTES + 1)))
        if len(connection['buffer']) > MAX_MESSAGE_BYTES:
            socket.abort()
            return
        frames = 0
        while b'\n' in connection['buffer']:
            frames += 1
            if frames > 32:
                socket.abort()
                return
            raw, _, remaining = connection['buffer'].partition(b'\n')
            connection['buffer'] = bytearray(remaining)
            try:
                request = bounded_object(json.loads(raw.decode('utf-8')))
                if connection['session'] is None:
                    if set(request) != {'auth'} or not isinstance(request['auth'], str):
                        raise CommandError('PERMISSION_DENIED')
                    token = request['auth']
                    if len(token) != 64 or not token.isascii():
                        raise CommandError('PERMISSION_DENIED')
                    session = next((sid for key, sid in self._credentials.items()
                                    if hmac.compare_digest(key, token)), None)
                    if session is None:
                        raise CommandError('PERMISSION_DENIED')
                    self.commands._permission(session)
                    connection['session'] = session
                    self.changed.emit()
                    response = {'ok': True}
                else:
                    session = connection['session']
                    started, count = self._rate.get(session, (time.monotonic(), 0))
                    if time.monotonic() - started >= 1:
                        started, count = time.monotonic(), 0
                    self._rate[session] = (started, count + 1)
                    if count >= 128:
                        response = {'ok': False, 'code': 'RATE_LIMITED'}
                    elif request.get('method') == 'client_presence':
                        self.commands._permission(session)
                        if set(request) != {'method', 'name', 'version', 'protocol', 'request_id'}:
                            raise CommandError('INVALID_ARGUMENT')
                        if not isinstance(request['request_id'], str) or not re.fullmatch('[0-9a-f]{32}', request['request_id']):
                            raise CommandError('INVALID_ARGUMENT')
                        metadata = {key: request[key] for key in ('name', 'version', 'protocol')}
                        if any(not isinstance(value, str) or len(value) > 100 or not value.isprintable()
                               for value in metadata.values()) or not metadata['name']:
                            raise CommandError('INVALID_ARGUMENT')
                        # Reserve sockets for tool requests, not only idle clients.
                        if not connection.get('client') and len(self.connected_clients()) >= MAX_CONNECTIONS // 2:
                            raise CommandError('BUSY')
                        connection['client'] = metadata
                        response = {'ok': True, 'request_id': request['request_id'], 'result': {}}
                        self.changed.emit()
                    else:
                        response = self.commands.dispatch(session, request)
                self._send(socket, response)
            except (CommandError, ValueError, UnicodeError, RecursionError):
                # Untrusted packets never enter diagnostics or echo back to peers.
                socket.abort()
                return
        if not connection['buffer']:
            connection['timer'].stop()

    def close(self):
        self.commands._owner_check()
        self._approval_timer.stop()
        for socket in list(self._connections):
            socket.abort()
        for session in list(self._credentials.values()):
            self.commands.revoke(session)
        self._credentials.clear()
        self._rate.clear()
        self.commands.change_notify = lambda: None
        self._auto_timer.stop()
        self.server.close()  # QLocalServer owns its endpoint; no removeServer on arbitrary names.
        if self._directory:
            self._directory.rmdir()
            self._directory = None
