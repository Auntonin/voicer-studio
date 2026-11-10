"""Section 1 core contract tests: no GUI or AI runtime required."""
import json
from uuid import uuid4

import pytest

from core.agent_commands import AgentCommands, CommandError, MAX_MESSAGE_BYTES
from core.models import DialogueItem, PipelineState, SpeakerInfo, UndoManager


@pytest.fixture
def harness():
    state = PipelineState(video_duration=12)
    state.speakers = {'private-id': SpeakerInfo('private-id', 'private name'),
                      'other': SpeakerInfo('other', 'other name')}
    state.dialogues = [DialogueItem(1, 'private-id', 1, 2, 'private caption')]
    undo = UndoManager()
    runtime = {'epoch': uuid4().hex, 'revision': 0, 'busy': False, 'started': []}

    def edit(operation, index, value):
        undo.push(state)
        item = next(d for d in state.dialogues if d.index == index)
        setattr(item, 'caption' if operation == 'caption' else 'speaker_id', value)
        runtime['revision'] += 1

    commands = AgentCommands(state=lambda: state,
        version=lambda: (runtime['epoch'], runtime['revision']), busy=lambda: runtime['busy'],
        apply_edit=edit, start_job=lambda *args: runtime['started'].append(args),
        owner_check=lambda: None, app_version='test')
    session = commands.grant({'read_project', 'read_transcript', 'edit_caption', 'edit_speaker', 'export', 'pipeline'})
    return commands, session, state, undo, runtime


def caption_command(commands, session):
    snapshot = commands.snapshot(session, limit=1)
    return {'operation': 'caption', 'project_epoch': snapshot['project_epoch'],
            'expected_revision': snapshot['revision'],
            'clip_ref': snapshot['dialogues'][0]['clip_ref'], 'caption': 'new caption'}


@pytest.mark.parametrize('mode', ['session', 'always'])
def test_user_selected_auto_policy_preserves_undo_and_idempotency(harness, mode):
    commands, _, state, undo, runtime = harness
    session = commands.grant({'read_project', 'edit_caption'}, approval_mode=mode)
    command = {**caption_command(commands, session), 'idempotency_key': 'auto-retry'}
    result = commands.submit(session, command)
    assert result['code'] == 'AUTO_APPROVAL_QUEUED'
    assert commands.automatic_jobs() == [result['job_id']]
    assert state.dialogues[0].caption == 'private caption'
    commands.approve_automatic(result['job_id'])
    assert state.dialogues[0].caption == 'new caption'
    assert commands.job_status(session, result['job_id'])['state'] == 'succeeded'
    assert commands.submit(session, command) == result
    assert runtime['revision'] == 1
    assert undo.undo(state)
    assert state.dialogues[0].caption == 'private caption'


def test_metadata_only_connection_keeps_user_selected_policy_without_granting_scopes(harness):
    commands, _, _, _, runtime = harness
    session = commands.grant(set(), approval_mode='always')
    assert commands.describe(session)['approval_mode'] == 'always'
    assert commands.describe(session)['scopes'] == []
    assert commands.describe(session)['operations'] == []
    runtime['epoch'] = uuid4().hex
    assert commands.describe(session)['approval_mode'] == 'ask'


def test_policy_is_local_only_and_ask_cancels_automatic_scheduling(harness):
    commands, session, state, _, _ = harness
    commands.set_approval_mode(session, 'session')
    job = commands.submit(session, caption_command(commands, session))['job_id']
    response = commands.dispatch(session, {'method': 'set_approval_mode', 'mode': 'always'})
    assert response == {'ok': False, 'code': 'INVALID_ARGUMENT'}
    commands.set_approval_mode(session, 'ask')
    assert not commands.automatic_jobs()
    with pytest.raises(CommandError, match='APPROVAL_REQUIRED'):
        commands.approve_automatic(job)
    assert commands.job_status(session, job)['state'] == 'awaiting_approval'
    assert state.dialogues[0].caption == 'private caption'


@pytest.mark.parametrize('scenario,code', [('busy', 'BUSY'), ('revision', 'REVISION_CONFLICT'),
    ('epoch', 'PERMISSION_DENIED'), ('tampered', 'APPROVAL_CHANGED'), ('expired', 'APPROVAL_EXPIRED')])
def test_auto_policy_does_not_bypass_guards(harness, scenario, code):
    commands, session, state, _, runtime = harness
    commands.set_approval_mode(session, 'always')
    job = commands.submit(session, caption_command(commands, session))['job_id']
    if scenario == 'busy':
        runtime['busy'] = True
    elif scenario == 'revision':
        runtime['revision'] += 1
    elif scenario == 'epoch':
        runtime['epoch'] = uuid4().hex
    elif scenario == 'tampered':
        commands._jobs[job].command['caption'] = 'unreviewed payload'
    else:
        commands._jobs[job].expires_at = 0
    with pytest.raises(CommandError, match=code):
        commands.approve_automatic(job)
    assert state.dialogues[0].caption == 'private caption'
    assert commands._jobs[job].state in ('failed', 'cancelled')


def test_auto_policy_never_grants_scopes_or_survives_revoke(harness):
    commands, _, state, _, _ = harness
    session = commands.grant({'read_project'}, approval_mode='always')
    with pytest.raises(CommandError, match='PERMISSION_DENIED'):
        commands.submit(session, caption_command(commands, session))
    commands.revoke(session)
    assert session not in commands._approval_modes
    assert state.dialogues[0].caption == 'private caption'
    with pytest.raises(CommandError, match='INVALID_ARGUMENT'):
        commands.grant({'read_project'}, approval_mode='unknown')


def test_idempotent_write_retry_and_conflict(harness):
    commands, session, state, _, runtime = harness
    command = {**caption_command(commands, session), 'idempotency_key': 'retry-1'}
    first = commands.submit(session, command)
    commands.approve(first['job_id'])
    assert commands.submit(session, command) == first
    assert runtime['revision'] == 1
    with pytest.raises(CommandError, match='IDEMPOTENCY_CONFLICT'):
        commands.submit(session, {**command, 'caption': 'different'})
    commands.revoke(session)
    with pytest.raises(CommandError, match='PERMISSION_DENIED'):
        commands.submit(session, command)


def test_diff_does_not_bypass_transcript_consent(harness):
    commands, _, _, _, _ = harness
    session = commands.grant({'read_project', 'edit_caption'})
    result = commands.submit(session, caption_command(commands, session))
    assert result['diff'] == {'field': 'caption'}
    assert 'private caption' not in json.dumps(result)


def test_idempotency_ttl_and_epoch(monkeypatch, harness):
    commands, session, _, _, runtime = harness
    command = {**caption_command(commands, session), 'idempotency_key': 'retry'}
    first = commands.submit(session, command)
    commands.cancel(session, first['job_id'])
    monkeypatch.setattr('core.agent_commands.time.monotonic', lambda: 10**12)
    assert commands.submit(session, command)['job_id'] != first['job_id']
    runtime['epoch'] = uuid4().hex
    with pytest.raises(CommandError, match='PERMISSION_DENIED'):
        commands.submit(session, command)


def test_idempotency_cache_is_bounded(monkeypatch, harness):
    commands, session, _, _, _ = harness
    monkeypatch.setattr('core.agent_commands.MAX_IDEMPOTENCY_KEYS', 2)
    command = caption_command(commands, session)
    for index in range(3):
        job = commands.submit(session, {**command, 'idempotency_key': str(index)})
        commands.cancel(session, job['job_id'])
    assert len(commands._idempotency) == 2
    assert (session, '0') not in commands._idempotency


def test_export_retry_after_submit_does_not_start_a_second_job(harness):
    commands, session, _, _, runtime = harness
    page = commands.snapshot(session)
    command = {'operation': 'export', 'project_epoch': page['project_epoch'],
               'expected_revision': page['revision'], 'idempotency_key': 'export-retry'}
    # Simulate a caller losing the submit response after the host accepted it.
    accepted = commands.submit(session, command)
    commands.approve(accepted['job_id'])
    commands.bind(accepted['job_id'], lambda: None)
    assert commands.submit(session, command) == accepted
    commands.finish(accepted['job_id'], 'succeeded')
    assert commands.submit(session, command) == accepted
    assert runtime['started'] == [(accepted['job_id'], 'export')]


def test_summary_and_scoped_page_privacy(harness):
    commands, _, state, _, _ = harness
    state.video_path = __import__('pathlib').Path('private/path/video.mp4')
    session = commands.grant({'read_project'})
    for snapshot in (commands.snapshot(session), commands.snapshot(session, limit=1)):
        text = json.dumps(snapshot)
        for secret in ('private caption', 'private name', 'private-id', 'video.mp4', 'voiceprint', 'settings'):
            assert secret not in text
    assert commands.snapshot(session)['dialogues'] == []
    assert commands.describe(session)['operations'] == []


def test_approval_then_undo_redo(harness):
    commands, session, state, undo, _ = harness
    proposal = commands.submit(session, caption_command(commands, session))
    assert state.dialogues[0].caption == 'private caption'
    assert proposal['state'] == 'awaiting_approval'
    commands.approve(proposal['job_id'])
    assert state.dialogues[0].caption == 'new caption'
    assert commands.job_status(session, proposal['job_id'])['state'] == 'succeeded'
    assert undo.undo(state)
    assert state.dialogues[0].caption == 'private caption'
    assert undo.redo(state)
    assert state.dialogues[0].caption == 'new caption'


def test_two_clients_same_revision_only_first_approval_succeeds(harness):
    commands, session, state, _, _ = harness
    other = commands.grant({'read_project', 'edit_caption'})
    command = caption_command(commands, session)
    first = commands.submit(session, command)['job_id']
    second = commands.submit(other, command)['job_id']
    commands.approve(first)
    with pytest.raises(CommandError, match='REVISION_CONFLICT'):
        commands.approve(second)
    assert state.dialogues[0].caption == 'new caption'
    assert commands.job_status(other, second)['state'] == 'failed'


def test_gui_revision_rejected_at_submit_and_approval(harness):
    commands, session, _, _, runtime = harness
    command = caption_command(commands, session)
    job = commands.submit(session, command)['job_id']
    runtime['revision'] += 1
    with pytest.raises(CommandError, match='REVISION_CONFLICT'):
        commands.submit(session, command)
    with pytest.raises(CommandError, match='REVISION_CONFLICT'):
        commands.approve(job)


def test_new_project_requires_new_permission(harness):
    commands, session, _, _, runtime = harness
    runtime['epoch'] = uuid4().hex
    with pytest.raises(CommandError, match='PERMISSION_DENIED'):
        commands.snapshot(session)


@pytest.mark.parametrize('envelope', [[], {'method': 'approve'}, {'method': 'grant'},
    {'method': 'snapshot', 'limit': True}, {'method': 'snapshot', 'limit': 101},
    {'method': 'snapshot', 'offset': -1}, {'method': 'snapshot', 'limit': float('nan')},
    {'method': 'snapshot', 'surprise': 'secret'}, {'method': 'describe', 'secret': 'x' * MAX_MESSAGE_BYTES}])
def test_invalid_envelopes_do_not_escape(harness, envelope):
    commands, session, *_ = harness
    assert commands.dispatch(session, envelope) == {'ok': False, 'code': 'INVALID_ARGUMENT'}


def test_busy_prevents_even_reading_state(harness):
    commands, session, _, _, runtime = harness
    runtime['busy'] = True
    commands._state = lambda: pytest.fail('Live mutable state was read')
    assert commands.describe(session)['busy']
    with pytest.raises(CommandError, match='BUSY'):
        commands.snapshot(session)


def test_permission_job_ownership_cancel_and_expiry(harness):
    commands, session, _, _, _ = harness
    read_only = commands.grant({'read_project'})
    command = caption_command(commands, session)
    with pytest.raises(CommandError, match='PERMISSION_DENIED'):
        commands.submit(read_only, command)
    job = commands.submit(session, command)['job_id']
    with pytest.raises(CommandError, match='JOB_NOT_FOUND'):
        commands.cancel(read_only, job)
    assert commands.cancel(session, job)['state'] == 'cancelled'
    commands.revoke(session)
    with pytest.raises(CommandError, match='PERMISSION_DENIED'):
        commands.job_status(session, job)


def test_cooperative_job_cancellation_requires_terminal_signal(harness):
    commands, session, _, _, runtime = harness
    command = caption_command(commands, session)
    command = {key: value for key, value in command.items() if key not in ('caption', 'clip_ref')}
    command['operation'] = 'export'
    job = commands.submit(session, command)['job_id']
    commands.approve(job)
    assert runtime['started'] == [(job, 'export')]
    cancel_calls = []
    commands.bind(job, lambda: cancel_calls.append(True))
    assert commands.cancel(session, job)['state'] == 'cancelling'
    assert cancel_calls == [True]
    commands.finish(job, 'cancelled')
    commands.finish(job, 'succeeded')
    assert commands.job_status(session, job)['state'] == 'cancelled'


def test_writes_reject_extra_fields_bad_refs_and_batch(harness):
    commands, session, *_ = harness
    command = caption_command(commands, session)
    for changes in ({'approve': True}, {'clip_ref': 'f' * 32}, {'caption': 'x' * 8001},
                    {'expected_revision': True}, {'caption': float('inf')}):
        with pytest.raises(CommandError, match='INVALID_ARGUMENT'):
            commands.submit(session, command | changes)
    with pytest.raises(CommandError, match='INVALID_ARGUMENT'):
        commands.submit(session, [command])
