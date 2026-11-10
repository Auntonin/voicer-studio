"""Bounded internal commands; no Qt, file access, AI engines or serialization.

The host calls this interface on its owner thread. Approval and permission grants
are trusted local operations, deliberately absent from the IPC dispatch table.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections import OrderedDict
import hashlib
import json
import logging
import math
import time
from typing import Callable
from uuid import uuid4

MAX_MESSAGE_BYTES = 64 * 1024
MAX_PAGE_SIZE = 100
MAX_CAPTION_LENGTH = 8000
MAX_JOBS = 128
MAX_IDEMPOTENCY_KEYS = 256
IDEMPOTENCY_TTL_SECONDS = 600
APPROVAL_TTL_SECONDS = 300
APPROVAL_MODES = frozenset({'ask', 'session', 'always'})
SCOPES = frozenset({'read_project', 'read_transcript', 'read_speaker_names',
                    'edit_caption', 'edit_speaker', 'pipeline', 'export', 'save_project', 'analyze_speakers',
                    'edit_clips', 'manage_speakers', 'import_project'})
EXTENDED_FIELDS = {
    'add_character': {'name'}, 'rename_character': {'speaker_ref', 'name'},
    'delete_character': {'speaker_ref'}, 'clear_voiceprint': {'speaker_ref'},
    'enroll_voice': {'speaker_ref', 'clip_ref'}, 'apply_voice_match': {'analysis_job_id'},
    'split': {'clip_ref', 'time'}, 'merge': {'clip_ref'}, 'timing': {'clip_ref', 'start', 'end'},
    'add_clip': {'speaker_ref', 'start', 'end', 'caption'}, 'delete_clip': {'clip_ref'},
    'regenerate_audio': {'clip_ref'}, 'regenerate_frame': {'clip_ref'}, 'undo': set(), 'redo': set(),
}


def operation_scope(operation):
    if operation in ('caption', 'speaker'):
        return 'edit_' + operation
    if operation in ('add_character', 'rename_character', 'delete_character', 'clear_voiceprint', 'enroll_voice'):
        return 'manage_speakers'
    if operation in ('analyze_voice', 'apply_voice_match'):
        return 'analyze_speakers'
    if operation in EXTENDED_FIELDS:
        return 'edit_clips'
    return 'save_project' if operation == 'save' else operation
TERMINAL = frozenset({'cancelled', 'failed', 'succeeded'})


class CommandError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class Job:
    owner: str
    command: dict = field(repr=False)
    state: str = 'awaiting_approval'
    stage: str = 'approval'
    progress: float = 0.0
    error: str | None = None
    cancel_callback: Callable | None = field(default=None, repr=False)
    expires_at: float = field(default_factory=lambda: time.monotonic() + APPROVAL_TTL_SECONDS)
    fingerprint: str = ''
    result: dict | None = field(default=None, repr=False)


def bounded_object(value: object) -> dict:
    if not isinstance(value, dict):
        raise CommandError('INVALID_ARGUMENT')
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(encoded) > MAX_MESSAGE_BYTES:
            raise CommandError('INVALID_ARGUMENT')
        return json.loads(encoded)
    except (TypeError, ValueError, RecursionError, UnicodeError):
        raise CommandError('INVALID_ARGUMENT') from None


class AgentCommands:
    def __init__(self, *, state, version, busy, apply_edit, start_job, owner_check, app_version):
        self._state, self._version, self._busy = state, version, busy
        self._apply_edit, self._start_job = apply_edit, start_job
        self._owner_check, self._app_version = owner_check, app_version
        self._sessions: dict[str, frozenset[str]] = {}
        self._session_epochs = {}
        self._approval_modes = {}
        self._jobs: dict[str, Job] = {}
        self._reference_version = None
        self._clips, self._speakers = {}, {}
        self._idempotency = OrderedDict()
        self.change_notify = lambda: None

    @staticmethod
    def _fingerprint(command):
        return hashlib.sha256(json.dumps(command, sort_keys=True,
            ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()

    def expire_approvals(self):
        self._owner_check()
        for job_id, job in self._jobs.items():
            if job.state == 'awaiting_approval' and time.monotonic() >= job.expires_at:
                self.finish(job_id, 'cancelled', 'APPROVAL_EXPIRED')

    def grant(self, scopes, *, approval_mode='ask') -> str:
        self._owner_check()
        scopes = frozenset(scopes)
        if not scopes <= SCOPES or len(self._sessions) >= 16 or approval_mode not in APPROVAL_MODES:
            raise CommandError('INVALID_ARGUMENT')
        session = uuid4().hex
        self._sessions[session] = scopes
        self._session_epochs[session] = self._version()[0]
        self._approval_modes[session] = approval_mode
        self.change_notify()
        return session

    def set_approval_mode(self, session, mode):
        """Trusted local user choice only; deliberately not a transport method."""
        self._permission(session)
        if mode not in APPROVAL_MODES:
            raise CommandError('INVALID_ARGUMENT')
        self._approval_modes[session] = mode
        self.change_notify()

    def automatic_jobs(self):
        self._owner_check()
        return [job_id for job_id, job in self._jobs.items()
                if job.state == 'awaiting_approval' and
                self._approval_modes.get(job.owner, 'ask') in ('session', 'always')]

    def approve_automatic(self, job_id):
        """Host event-loop callback; never skips the ordinary approval guards."""
        self._owner_check()
        job = self._jobs.get(job_id)
        if job is None or self._approval_modes.get(job.owner, 'ask') == 'ask':
            raise CommandError('APPROVAL_REQUIRED')
        self.approve(job_id)

    def revoke(self, session):
        self._owner_check()
        self._sessions.pop(session, None)
        self._session_epochs.pop(session, None)
        self._approval_modes.pop(session, None)
        for key in list(self._idempotency):
            if key[0] == session:
                del self._idempotency[key]
        for job in self._jobs.values():
            if job.owner == session and job.state == 'awaiting_approval':
                job.state = 'cancelled'
        self.change_notify()

    def _permission(self, session, *scopes):
        self._owner_check()
        if session not in self._sessions or not set(scopes) <= self._sessions[session]:
            raise CommandError('PERMISSION_DENIED')
        if scopes and self._session_epochs[session] != self._version()[0]:
            raise CommandError('PERMISSION_DENIED')

    def _project(self, session, *, allow_empty=False):
        self._permission(session, 'read_project')
        if self._busy():
            raise CommandError('BUSY')
        state = self._state()
        if not allow_empty and not (state.video_path or state.dialogues or state.speakers):
            raise CommandError('NO_PROJECT')
        return state

    def _check_revision(self, command):
        if (command['project_epoch'], command['expected_revision']) != self._version():
            raise CommandError('REVISION_CONFLICT')

    def _references(self, state):
        version = self._version()
        if version != self._reference_version:
            self._clips = {uuid4().hex: item for item in state.active_dialogues()}
            self._speakers = {uuid4().hex: sid for sid in state.speakers}
            self._reference_version = version

    def describe(self, session):
        self._permission(session)
        scopes = self._sessions[session] if self._session_epochs[session] == self._version()[0] else frozenset()
        return {'app_version': self._app_version, 'busy': bool(self._busy()),
                'approval_mode': self._approval_modes[session] if self._session_epochs[session] == self._version()[0] else 'ask',
                'scopes': sorted(scopes), 'batch_edits': False,
                'operations': [op for op, scope in [('caption', 'edit_caption'),
                    ('speaker', 'edit_speaker'), ('save', 'save_project'),
                    ('pipeline', 'pipeline'), ('export', 'export'), ('analyze_voice', 'analyze_speakers'),
                    ('import_project', 'import_project')]
                    if scope in scopes] + [op for op in EXTENDED_FIELDS if operation_scope(op) in scopes
                                         and (op != 'apply_voice_match' or 'edit_speaker' in scopes)],
                'max_page_size': MAX_PAGE_SIZE}

    def snapshot(self, session, *, offset=0, limit=0):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 0 <= limit <= MAX_PAGE_SIZE:
            raise CommandError('INVALID_ARGUMENT')
        state = self._project(session, allow_empty=True)
        self._references(state)
        epoch, revision = self._version()
        if not math.isfinite(state.video_duration) or state.video_duration < 0:
            raise CommandError('INVALID_ARGUMENT')
        result = {'project_epoch': epoch, 'revision': revision, 'clip_count': len(self._clips),
                  'speaker_count': len(self._speakers), 'duration': state.video_duration,
                  'dialogues': [], 'speakers': []}
        if limit:
            reverse = {sid: ref for ref, sid in self._speakers.items()}
            for ref, item in list(self._clips.items())[offset:offset + limit]:
                if not math.isfinite(item.start) or not math.isfinite(item.end) or item.end <= item.start or item.start < 0:
                    raise CommandError('INVALID_ARGUMENT')
                entry = {'clip_ref': ref, 'start': item.start, 'end': item.end,
                         'speaker_ref': reverse.get(item.speaker_id), 'needs_review': item.needs_review}
                if 'read_transcript' in self._sessions[session]:
                    entry['caption'] = item.caption[:MAX_CAPTION_LENGTH]
                    entry['caption_truncated'] = len(item.caption) > MAX_CAPTION_LENGTH
                result['dialogues'].append(entry)
            for ref, sid in self._speakers.items():
                entry = {'speaker_ref': ref, 'has_reference_voice': state.speakers[sid].has_voiceprint()}
                if 'read_speaker_names' in self._sessions[session]:
                    entry['name'] = state.speakers[sid].display_name[:MAX_CAPTION_LENGTH]
                result['speakers'].append(entry)
        return bounded_object(result)

    def submit(self, session, command):
        self.expire_approvals()
        command = bounded_object(command)
        idempotency_key = command.pop('idempotency_key', None)
        if idempotency_key is not None and (not isinstance(idempotency_key, str) or
                not 1 <= len(idempotency_key) <= 128 or not idempotency_key.isascii() or
                any(not (char.isalnum() or char in '_-') for char in idempotency_key)):
            raise CommandError('INVALID_ARGUMENT')
        operation = command.get('operation')
        required = {'operation', 'project_epoch', 'expected_revision'}
        if operation == 'caption':
            required |= {'clip_ref', 'caption'}
            scope = 'edit_caption'
            if not isinstance(command.get('caption'), str) or len(command['caption']) > MAX_CAPTION_LENGTH:
                raise CommandError('INVALID_ARGUMENT')
        elif operation == 'speaker':
            required |= {'clip_ref', 'speaker_ref'}
            scope = 'edit_speaker'
        elif operation in ('pipeline', 'export', 'import_project'):
            scope = operation
        elif operation == 'save':
            scope = 'save_project'
        elif operation == 'analyze_voice':
            required |= {'clip_ref'}
            scope = 'analyze_speakers'
        elif operation in EXTENDED_FIELDS:
            required |= EXTENDED_FIELDS[operation]
            scope = operation_scope(operation)
        else:
            raise CommandError('INVALID_ARGUMENT')
        if set(command) != required or type(command.get('expected_revision')) is not int or command['expected_revision'] < 0:
            raise CommandError('INVALID_ARGUMENT')
        if not all(isinstance(command[key], str) and len(command[key]) == 32
                   and all(c in '0123456789abcdef' for c in command[key])
                   for key in required & {'project_epoch', 'clip_ref', 'speaker_ref', 'analysis_job_id'}):
            raise CommandError('INVALID_ARGUMENT')
        if operation in EXTENDED_FIELDS:
            for key in ('time', 'start', 'end'):
                if key in command and (type(command[key]) not in (int, float) or not math.isfinite(command[key]) or command[key] < 0):
                    raise CommandError('INVALID_ARGUMENT')
            if 'start' in command and command['end'] - command['start'] < .05:
                raise CommandError('INVALID_ARGUMENT')
            if 'name' in command and (not isinstance(command['name'], str) or not command['name'].strip() or len(command['name']) > 128):
                raise CommandError('INVALID_ARGUMENT')
            if 'caption' in command and (not isinstance(command['caption'], str) or len(command['caption']) > MAX_CAPTION_LENGTH):
                raise CommandError('INVALID_ARGUMENT')
            if operation == 'apply_voice_match':
                self._permission(session, 'edit_speaker')
        self._permission(session, 'read_project', scope)
        fingerprint = hashlib.sha256(json.dumps(command, sort_keys=True,
            ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()
        cache_key = (session, idempotency_key)
        now = time.monotonic()
        for key, entry in list(self._idempotency.items()):
            if now - entry[0] >= IDEMPOTENCY_TTL_SECONDS:
                del self._idempotency[key]
        if idempotency_key is not None and cache_key in self._idempotency:
            _, old_fingerprint, old_result = self._idempotency[cache_key]
            if old_fingerprint != fingerprint:
                raise CommandError('IDEMPOTENCY_CONFLICT')
            if old_result['job_id'] not in self._jobs:
                raise CommandError('JOB_NOT_FOUND')
            return bounded_object(old_result)
        state = self._project(session, allow_empty=operation in ('import_project', 'add_character'))
        self._check_revision(command)
        self._references(state)
        self._validate_extended(session, command, state)
        if operation in ('caption', 'speaker', 'analyze_voice'):
            if command['clip_ref'] not in self._clips:
                raise CommandError('INVALID_ARGUMENT')
            if operation == 'speaker' and command['speaker_ref'] not in self._speakers:
                raise CommandError('INVALID_ARGUMENT')
        if any(job.owner == session and job.state == 'awaiting_approval' for job in self._jobs.values()):
            raise CommandError('BUSY')
        if len(self._jobs) >= MAX_JOBS:
            oldest = next((key for key, job in self._jobs.items() if job.state in TERMINAL), None)
            if oldest is None:
                raise CommandError('BUSY')
            del self._jobs[oldest]
        job_id = uuid4().hex
        self._jobs[job_id] = Job(session, command, fingerprint=self._fingerprint(command))
        result = {'job_id': job_id, 'state': 'awaiting_approval', 'code': 'APPROVAL_REQUIRED'}
        if self._approval_modes.get(session, 'ask') != 'ask':
            result['code'] = 'AUTO_APPROVAL_QUEUED'
        if operation == 'caption':
            result['diff'] = {'field': 'caption'}
            if 'read_transcript' in self._sessions[session]:
                result['diff'].update(before=self._clips[command['clip_ref']].caption[:MAX_CAPTION_LENGTH],
                                      after=command['caption'])
        elif operation == 'speaker':
            before = next((ref for ref, sid in self._speakers.items()
                           if sid == self._clips[command['clip_ref']].speaker_id), None)
            result['diff'] = {'field': 'speaker', 'before': before, 'after': command['speaker_ref']}
        if idempotency_key is not None:
            self._idempotency[cache_key] = (now, fingerprint, bounded_object(result))
            while len(self._idempotency) > MAX_IDEMPOTENCY_KEYS:
                self._idempotency.popitem(last=False)
        self.change_notify()
        logging.getLogger(__name__).info('Agent request awaiting approval', extra={
            'operation': 'agent', 'stage': 'submit', 'job_id': job_id, 'session_id': session})
        return result

    def _validate_extended(self, session, command, state):
        operation = command['operation']
        if operation not in EXTENDED_FIELDS:
            return
        if 'clip_ref' in command and command['clip_ref'] not in self._clips:
            raise CommandError('INVALID_ARGUMENT')
        if 'speaker_ref' in command and command['speaker_ref'] not in self._speakers:
            raise CommandError('INVALID_ARGUMENT')
        if 'end' in command and state.video_duration > 0 and command['end'] > state.video_duration:
            raise CommandError('INVALID_ARGUMENT')
        if operation == 'split':
            item = self._clips[command['clip_ref']]
            if not item.start + .05 < round(command['time'], 3) < item.end - .05:
                raise CommandError('INVALID_ARGUMENT')
        if operation == 'merge':
            item = self._clips[command['clip_ref']]
            if not any(d is not item and d.speaker_id == item.speaker_id and d.start >= item.start for d in state.active_dialogues()):
                raise CommandError('INVALID_ARGUMENT')
        if operation == 'delete_character' and any(d.speaker_id == self._speakers[command['speaker_ref']] for d in state.active_dialogues()):
            raise CommandError('CHARACTER_IN_USE')
        if operation == 'delete_character':
            if len(state.speakers) <= 1:
                raise CommandError('LAST_CHARACTER')
            if any(self._speakers[command['speaker_ref']] in d.extra_speakers for d in state.active_dialogues()):
                raise CommandError('CHARACTER_IN_USE')
        if operation == 'enroll_voice':
            if self._clips[command['clip_ref']].duration < 1.:
                raise CommandError('REFERENCE_TOO_SHORT')
            if len(state.speakers[self._speakers[command['speaker_ref']]].voiceprint_samples) >= 64:
                raise CommandError('REFERENCE_LIMIT')
        if operation == 'apply_voice_match':
            self._permission(session, 'edit_speaker')
            analysis = self._job(session, command['analysis_job_id'])
            if analysis.command['operation'] != 'analyze_voice' or analysis.state != 'succeeded' or not analysis.result:
                raise CommandError('INVALID_ARGUMENT')
            if (analysis.command['project_epoch'], analysis.command['expected_revision']) != self._version():
                raise CommandError('REVISION_CONFLICT')
            candidates = analysis.result.get('candidates', [])
            if analysis.result.get('needs_review', True) or not candidates:
                raise CommandError('UNCERTAIN_MATCH')
            if candidates[0]['speaker_ref'] not in self._speakers or analysis.result['clip_ref'] not in self._clips:
                raise CommandError('REVISION_CONFLICT')

    def approve(self, job_id):
        """Trusted GUI/harness only; revalidate immediately before mutation."""
        self._owner_check()
        job = self._jobs.get(job_id)
        if job is None:
            raise CommandError('JOB_NOT_FOUND')
        if job.state == 'awaiting_approval' and time.monotonic() >= job.expires_at:
            self.finish(job_id, 'cancelled', 'APPROVAL_EXPIRED')
            raise CommandError('APPROVAL_EXPIRED')
        if job.state != 'awaiting_approval':
            raise CommandError('INVALID_ARGUMENT')
        try:
            if self._fingerprint(job.command) != job.fingerprint:
                raise CommandError('APPROVAL_CHANGED')
            operation = job.command['operation']
            scope = operation_scope(operation)
            self._permission(job.owner, scope)
            state = self._project(job.owner, allow_empty=operation in ('import_project', 'add_character'))
            self._check_revision(job.command)
            self._references(state)
            self._validate_extended(job.owner, job.command, state)
            if operation in ('caption', 'speaker'):
                item = self._clips[job.command['clip_ref']]
                value = job.command['caption'] if operation == 'caption' else self._speakers[job.command['speaker_ref']]
                self._apply_edit(operation, item.index, value)
                self.finish(job_id, 'succeeded')
            else:
                job.state, job.stage = 'running', 'configuration'
                self.change_notify()
                self._start_job(job_id, operation)
        except CommandError as exc:
            self.finish(job_id, 'failed', exc.code)
            raise
        except Exception:
            self.finish(job_id, 'failed', 'OPERATION_FAILED')
            raise

    def bind(self, job_id, cancel_callback):
        self._owner_check()
        job = self._jobs[job_id]
        job.state, job.stage = 'running', 'processing'
        job.cancel_callback = cancel_callback
        self.change_notify()

    def progress(self, job_id, stage, progress):
        self._owner_check()
        job = self._jobs[job_id]
        if job.state in TERMINAL or not math.isfinite(progress):
            return
        job.stage = stage  # Only fixed identifiers, never worker log text.
        job.progress = max(0.0, min(100.0, float(progress)))
        self.change_notify()

    def finish(self, job_id, state, error=None):
        self._owner_check()
        job = self._jobs[job_id]
        if job.state in TERMINAL:
            return
        if state not in TERMINAL:
            raise CommandError('INVALID_ARGUMENT')
        job.state, job.stage, job.error = state, 'complete', error
        job.cancel_callback = None
        if state == 'succeeded':
            job.progress = 100.0
        self.change_notify()
        logging.getLogger(__name__).info('Agent job reached terminal state', extra={
            'operation': 'agent', 'stage': state, 'job_id': job_id, 'code': error or 'OK'})

    def _job(self, session, job_id):
        self._permission(session)
        job = self._jobs.get(job_id)
        if job is None or job.owner != session:
            raise CommandError('JOB_NOT_FOUND')
        operation = job.command['operation']
        scope = operation_scope(operation)
        self._permission(session, scope)
        return job

    def job_status(self, session, job_id):
        self.expire_approvals()
        job = self._job(session, job_id)
        result = {'job_id': job_id, 'state': job.state, 'stage': job.stage,
                  'progress': job.progress, 'error': job.error}
        if job.result is not None:
            result['result'] = bounded_object(job.result)
        return result

    def cancel(self, session, job_id):
        job = self._job(session, job_id)
        self._cancel_job(job_id, job)
        return self.job_status(session, job_id)

    def cancel_trusted(self, job_id):
        """Local user control, including jobs whose connection was revoked."""
        self._owner_check()
        job = self._jobs.get(job_id)
        if job is None:
            raise CommandError('JOB_NOT_FOUND')
        self._cancel_job(job_id, job)

    def _cancel_job(self, job_id, job):
        if job.state == 'awaiting_approval':
            self.finish(job_id, 'cancelled')
        elif job.state == 'running':
            job.state = 'cancelling'
            if job.cancel_callback:
                job.cancel_callback()
            self.change_notify()

    def dispatch(self, session, request):
        """Internal IPC envelope, not an MCP/JSON-RPC implementation."""
        try:
            request = bounded_object(request)
            request_id = request.pop('request_id', None)
            if request_id is not None and (not isinstance(request_id, str) or len(request_id) != 32 or
                    any(char not in '0123456789abcdef' for char in request_id)):
                raise CommandError('INVALID_ARGUMENT')
            method = request.get('method')
            if method == 'describe' and set(request) == {'method'}:
                result = self.describe(session)
            elif method == 'snapshot' and set(request) <= {'method', 'offset', 'limit'}:
                result = self.snapshot(session, offset=request.get('offset', 0), limit=request.get('limit', 0))
            elif method == 'submit' and set(request) == {'method', 'command'}:
                result = self.submit(session, request['command'])
            elif method in ('job_status', 'cancel') and set(request) == {'method', 'job_id'} and isinstance(request['job_id'], str):
                result = getattr(self, method)(session, request['job_id'])
            else:
                raise CommandError('INVALID_ARGUMENT')
            response = {'ok': True, 'result': result}
            if method in ('submit', 'cancel'):
                logging.getLogger(__name__).info('Agent write request handled', extra={
                    'operation': 'agent', 'stage': method, 'request_id': request_id,
                    'session_id': session, 'job_id': result.get('job_id')})
            if request_id:
                response['request_id'] = request_id
            return response
        except CommandError as exc:
            return {'ok': False, 'code': exc.code}
