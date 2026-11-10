"""Project edit commands reuse trusted GUI mutations and project Undo."""
from pathlib import Path
from unittest.mock import patch

import pytest

from core.agent_commands import CommandError, SCOPES
from core.models import DialogueItem
from test_agent_bridge import window, pump


def command(win, session, operation, **arguments):
    snapshot = win.agent_commands().snapshot(session, limit=100)
    return {'operation': operation, 'project_epoch': snapshot['project_epoch'],
            'expected_revision': snapshot['revision'], **arguments}


def apply(win, session, operation, **arguments):
    commands = win.agent_commands()
    job = commands.submit(session, command(win, session, operation, **arguments))['job_id']
    commands.approve(job)
    assert commands.job_status(session, job)['state'] == 'succeeded'


@pytest.mark.parametrize('operation', ['split', 'merge', 'timing', 'delete_clip', 'add_clip',
                                      'add_character', 'rename_character', 'delete_character', 'clear_voiceprint'])
def test_edits_are_one_project_undo_action(window, operation):
    win, _ = window
    state = win._state
    state.dialogues.append(DialogueItem(2, 'one', 4, 5, 'next caption'))
    state.speakers['two'].embedding = [1., 0.]
    state.speakers['two'].voiceprint_samples = ['reference']
    commands = win.agent_commands()
    session = commands.grant(SCOPES)
    page = commands.snapshot(session, limit=100)
    clip = page['dialogues'][0]['clip_ref']
    speaker = page['speakers'][1]['speaker_ref']
    args = {
        'split': {'clip_ref': clip, 'time': 2.}, 'merge': {'clip_ref': clip},
        'timing': {'clip_ref': clip, 'start': 1.2, 'end': 2.7}, 'delete_clip': {'clip_ref': clip},
        'add_clip': {'speaker_ref': speaker, 'start': 6., 'end': 7., 'caption': 'new'},
        'add_character': {'name': 'New character'}, 'rename_character': {'speaker_ref': speaker, 'name': 'Renamed'},
        'delete_character': {'speaker_ref': speaker}, 'clear_voiceprint': {'speaker_ref': speaker}}
    before = state.to_dict()
    apply(win, session, operation, **args[operation])
    assert state.to_dict() != before
    assert win._undo_manager.undo(state)
    assert state.to_dict() == before
    assert not win._undo_manager.undo(state)
    assert win._undo_manager.redo(state)
    assert state.to_dict() != before


@pytest.mark.parametrize('operation,args', [('timing', {'start': float('nan'), 'end': 4}),
    ('timing', {'start': 2, 'end': 1}), ('timing', {'start': 1, 'end': 11}),
    ('split', {'time': True}), ('split', {'time': 1.01}), ('split', {'time': 4})])
def test_invalid_boundaries_have_no_side_effects(window, operation, args):
    win, _ = window
    commands = win.agent_commands()
    session = commands.grant({'read_project', 'edit_clips'})
    clip = commands.snapshot(session, limit=1)['dialogues'][0]['clip_ref']
    before = win._state.to_dict()
    with pytest.raises(CommandError, match='INVALID_ARGUMENT'):
        commands.submit(session, command(win, session, operation, clip_ref=clip, **args))
    assert win._state.to_dict() == before


def test_stale_clip_after_split_and_character_in_use_are_rejected(window):
    win, _ = window
    commands = win.agent_commands()
    session = commands.grant(SCOPES)
    page = commands.snapshot(session, limit=1)
    old = command(win, session, 'delete_clip', clip_ref=page['dialogues'][0]['clip_ref'])
    apply(win, session, 'split', clip_ref=page['dialogues'][0]['clip_ref'], time=2.)
    with pytest.raises(CommandError, match='REVISION_CONFLICT'):
        commands.submit(session, old)
    page = commands.snapshot(session, limit=1)
    with pytest.raises(CommandError, match='CHARACTER_IN_USE'):
        commands.submit(session, command(win, session, 'delete_character', speaker_ref=page['speakers'][0]['speaker_ref']))


def test_delete_after_merge_and_add_targets_active_clip_not_old_deleted_index(window):
    win, app = window
    win._state.dialogues.append(DialogueItem(2, 'one', 4., 5., 'merged'))
    commands = win.agent_commands()
    session = commands.grant(SCOPES)
    page = commands.snapshot(session, limit=1)
    apply(win, session, 'merge', clip_ref=page['dialogues'][0]['clip_ref'])
    page = commands.snapshot(session, limit=100)
    apply(win, session, 'add_clip', speaker_ref=page['speakers'][0]['speaker_ref'], start=6., end=7., caption='new')
    pump(app, lambda: not win._agent_busy())
    page = commands.snapshot(session, limit=100)
    apply(win, session, 'delete_clip', clip_ref=page['dialogues'][1]['clip_ref'])
    assert len(win._state.active_dialogues()) == 1
    assert win._undo_manager.undo(win._state)
    assert len(win._state.active_dialogues()) == 2
    assert win._undo_manager.redo(win._state)
    assert len(win._state.active_dialogues()) == 1


@pytest.mark.parametrize('needs_review', [True, False])
def test_only_confident_current_owned_analysis_can_be_applied(window, needs_review):
    win, _ = window
    commands = win.agent_commands()
    session = commands.grant(SCOPES)
    page = commands.snapshot(session, limit=1)
    job = commands.submit(session, command(win, session, 'analyze_voice', clip_ref=page['dialogues'][0]['clip_ref']))['job_id']
    commands._jobs[job].result = {'needs_review': needs_review, 'clip_ref': page['dialogues'][0]['clip_ref'],
                                 'candidates': [{'speaker_ref': page['speakers'][1]['speaker_ref'], 'score': .95}]}
    commands.finish(job, 'succeeded')
    if needs_review:
        with pytest.raises(CommandError, match='UNCERTAIN_MATCH'):
            commands.submit(session, command(win, session, 'apply_voice_match', analysis_job_id=job))
        assert win._state.dialogues[0].speaker_id == 'one'
    else:
        apply(win, session, 'apply_voice_match', analysis_job_id=job)
        assert win._state.dialogues[0].speaker_id == 'two'
        assert win._state.dialogues[0].speaker_confidence == .95
        assert win._undo_manager.undo(win._state)
        assert win._state.dialogues[0].speaker_id == 'one'


def test_reference_enrollment_runs_on_copy_and_is_undoable(window, tmp_path):
    import numpy as np
    from core.speaker_matcher import SpeakerMatcher
    win, app = window
    source = tmp_path / 'reference.wav'
    source.touch()
    win._state.work_audio_path = source
    commands = win.agent_commands()
    session = commands.grant(SCOPES)
    page = commands.snapshot(session, limit=1)
    job = commands.submit(session, command(win, session, 'enroll_voice',
        clip_ref=page['dialogues'][0]['clip_ref'], speaker_ref=page['speakers'][1]['speaker_ref']))['job_id']
    with patch.object(SpeakerMatcher, 'extract_segment_features', return_value=np.array([1., 0.])):
        commands.approve(job)
        pump(app, lambda: commands._jobs[job].state == 'succeeded')
        win._agent_audio_worker.wait(5000)
    assert win._state.speakers['two'].has_voiceprint()
    assert win._state.dialogues[0].speaker_id == 'two'
    assert commands.job_status(session, job)['result'] == {'enrolled': True}
    assert win._undo_manager.undo(win._state)
    assert not win._state.speakers['two'].has_voiceprint()
    assert win._state.dialogues[0].speaker_id == 'one'


@pytest.mark.parametrize('cancel', [False, True])
def test_asset_job_has_real_terminal_state_and_undo(window, tmp_path, cancel):
    from threading import Event
    from core.clip_generator import ClipGenerator
    win, app = window
    win._output_dir = tmp_path
    commands = win.agent_commands()
    session = commands.grant(SCOPES)
    clip = commands.snapshot(session, limit=1)['dialogues'][0]['clip_ref']
    job = commands.submit(session, command(win, session, 'regenerate_audio', clip_ref=clip))['job_id']
    entered, release = Event(), Event()
    def regenerate(item, *_args):
        entered.set()
        assert release.wait(5)
        item.audio_path = tmp_path / 'generated.mp3'
    with patch.object(ClipGenerator, 'regenerate_clip', side_effect=regenerate):
        try:
            commands.approve(job)
            pump(app, entered.is_set)
            if cancel:
                commands.cancel(session, job)
            release.set()
            pump(app, lambda: commands._jobs[job].state in ('succeeded', 'cancelled'))
        finally:
            release.set()
            pump(app, lambda: not win._asset_jobs)
    if cancel:
        assert win._state.dialogues[0].audio_path is None
    else:
        assert win._state.dialogues[0].audio_path is not None
        assert win._undo_manager.undo(win._state)
        assert win._state.dialogues[0].audio_path is None
