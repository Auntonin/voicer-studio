"""Bounded local IPC client. Each request owns its Qt socket on one thread.

No model, widgets or SDK imports. This runs in the gateway worker pool, never
on the GUI owner thread. Disconnects never automatically replay writes.
"""
from __future__ import annotations

import json
import os
import re
import time
from threading import Lock
from uuid import uuid4

from core.agent_commands import MAX_MESSAGE_BYTES, CommandError, bounded_object


class AgentClient:
    def __init__(self, endpoint: str, credential: str, timeout_seconds: float = 3):
        self.endpoint = endpoint
        self._credential = credential
        self.timeout_seconds = timeout_seconds
        self._presence = None
        self._presence_lock = Lock()

    def request(self, request: dict, *, _keep_socket=False) -> dict | tuple[dict, object]:
        if not self.endpoint or not self._credential:
            raise CommandError('APP_NOT_READY')
        if os.name == 'nt' and not re.fullmatch(r'(?:\\\\\.\\pipe\\)?voicer-agent-[0-9a-f]{32}', self.endpoint):
            raise CommandError('APP_NOT_READY')
        if os.name != 'nt' and (not os.path.isabs(self.endpoint) or os.path.basename(self.endpoint) != 'socket'):
            raise CommandError('APP_NOT_READY')
        try:
            from PySide6.QtNetwork import QLocalSocket
        except ImportError:
            raise CommandError('DEPENDENCY_MISSING') from None
        payload = bounded_object(request)
        request_id = uuid4().hex
        payload['request_id'] = request_id
        socket = QLocalSocket()
        deadline = time.monotonic() + self.timeout_seconds
        buffer = bytearray()

        def remaining():
            return max(1, int((deadline - time.monotonic()) * 1000))

        def exchange(value):
            wire = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8') + b'\n'
            if len(wire) > MAX_MESSAGE_BYTES:
                raise CommandError('INVALID_ARGUMENT')
            socket.write(wire)
            while socket.bytesToWrite():
                if time.monotonic() >= deadline or not socket.waitForBytesWritten(remaining()):
                    raise CommandError('IPC_TIMEOUT')
            while b'\n' not in buffer:
                buffer.extend(bytes(socket.read(MAX_MESSAGE_BYTES + 1)))
                if len(buffer) > MAX_MESSAGE_BYTES:
                    raise CommandError('INVALID_RESPONSE')
                if b'\n' in buffer:
                    break
                if time.monotonic() >= deadline or not socket.waitForReadyRead(remaining()):
                    raise CommandError('IPC_TIMEOUT')
            raw, _, rest = buffer.partition(b'\n')
            buffer[:] = rest
            try:
                return bounded_object(json.loads(raw.decode('utf-8')))
            except (ValueError, UnicodeError):
                raise CommandError('INVALID_RESPONSE') from None

        kept = False
        try:
            socket.connectToServer(self.endpoint)
            if not socket.waitForConnected(remaining()):
                raise CommandError('APP_NOT_READY')
            auth = exchange({'auth': self._credential})
            if auth != {'ok': True}:
                raise CommandError('PERMISSION_DENIED')
            result = exchange(payload)
            if result.get('ok') is not True:
                code = result.get('code')
                if not isinstance(code, str) or not re.fullmatch('[A-Z_]{1,40}', code):
                    code = 'INVALID_RESPONSE'
                raise CommandError(code)
            if result.get('request_id') != request_id or not isinstance(result.get('result'), dict):
                raise CommandError('INVALID_RESPONSE')
            if _keep_socket:
                kept = True
                return result['result'], socket
            return result['result']
        finally:
            if not kept:
                socket.abort()

    def set_presence(self, name, version, protocol):
        with self._presence_lock:
            if self._presence is None:
                from core.agent_presence import AgentPresence
                self._presence = AgentPresence(self, name, version, protocol)
                self._presence.start()

    def close(self):
        with self._presence_lock:
            if self._presence is not None:
                self._presence.stop()
                self._presence = None
