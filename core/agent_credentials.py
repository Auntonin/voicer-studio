"""Ephemeral bridge tickets in an explicitly trusted OS credential backend.

Public references go into client configs; credentials never go into settings,
argv or discovery files. No plaintext/chained/third-party backend fallback.
"""
from __future__ import annotations

import json
import re
import sys
from uuid import uuid4

from core.agent_commands import CommandError, bounded_object

SERVICE = 'VoicerStudio.MCP.Session'
BACKENDS = {'win32': ('keyring.backends.Windows', 'WinVaultKeyring'),
            'darwin': ('keyring.backends.macOS', 'Keyring'),
            'linux': ('keyring.backends.SecretService', 'Keyring')}


def _backend():
    try:
        import keyring
        backend = keyring.get_keyring()
        if (type(backend).__module__, type(backend).__name__) != BACKENDS.get(sys.platform):
            raise CommandError('PERMISSION_DENIED')
        return backend
    except ImportError:
        raise CommandError('DEPENDENCY_MISSING') from None
    except CommandError:
        raise
    except Exception:
        raise CommandError('PERMISSION_DENIED') from None


def _reference(reference):
    if not isinstance(reference, str) or not re.fullmatch('[0-9a-f]{32}', reference):
        raise CommandError('INVALID_ARGUMENT')


def publish(ticket, *, reference=None):
    reference = reference or uuid4().hex
    _reference(reference)
    backend = _backend()
    try:
        existing = backend.get_password(SERVICE, reference)
    except Exception:
        raise CommandError('PERMISSION_DENIED') from None
    if existing is not None:
        # Another open app instance may own this remembered public reference.
        raise CommandError('REFERENCE_IN_USE')
    value = json.dumps({'endpoint': ticket.endpoint, 'session_id': ticket.session_id,
                        'credential': ticket.credential})
    try:
        backend.set_password(SERVICE, reference, value)
        if backend.get_password(SERVICE, reference) != value:
            raise CommandError('PERMISSION_DENIED')
    except Exception:
        try:
            backend.delete_password(SERVICE, reference)
        except Exception:
            pass
        raise CommandError('PERMISSION_DENIED') from None
    return reference


def resolve(reference):
    _reference(reference)
    try:
        value = _backend().get_password(SERVICE, reference)
        if not value:
            raise CommandError('APP_NOT_READY')
        ticket = bounded_object(json.loads(value))
        if set(ticket) != {'endpoint', 'session_id', 'credential'}:
            raise CommandError('INVALID_ARGUMENT')
        _reference(ticket['session_id'])
        if not isinstance(ticket['credential'], str) or not re.fullmatch('[0-9a-f]{64}', ticket['credential']):
            raise CommandError('INVALID_ARGUMENT')
        if not isinstance(ticket['endpoint'], str) or len(ticket['endpoint']) > 1024:
            raise CommandError('INVALID_ARGUMENT')
        return ticket
    except CommandError:
        raise
    except Exception:
        raise CommandError('PERMISSION_DENIED') from None


def remove(reference):
    _reference(reference)
    try:
        backend = _backend()
        if backend.get_password(SERVICE, reference) is not None:
            backend.delete_password(SERVICE, reference)
    except CommandError:
        raise
    except Exception:
        raise CommandError('PERMISSION_DENIED') from None
