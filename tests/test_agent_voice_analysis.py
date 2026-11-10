"""Read-only local voice analysis and owner-thread lifecycle regressions."""
from threading import Event
from unittest.mock import patch

import numpy as np
import pytest

from core.agent_commands import CommandError
from core.speaker_matcher import SpeakerMatcher
from test_agent_bridge import window, pump


@pytest.mark.parametrize('ambiguous,short,single', [(False, False, False), (True, False, False),
                                                  (False, True, False), (False, False, True)])
def test_rankings_do_not_mutate_or_claim_calibrated_confidence(window, ambiguous, short, single):
    win, _ = window
    state = win._state
    state.speakers['one'].embedding = [1., 0.]
    if not single:
        state.speakers['two'].embedding = [1., 0.] if ambiguous else [0., 1.]
    before = state.to_dict()
    with patch.object(SpeakerMatcher, 'extract_segment_features', return_value=np.array([1., 0.])):
        result = SpeakerMatcher.analyze_segment(state, None, 1., 1.5 if short else 3.)
    assert result['needs_review'] == (ambiguous or short or single)
    assert result['score_is_probability'] is False
    assert state.to_dict() == before


@pytest.mark.parametrize('outcome', ['success', 'cancel', 'stale', 'error'])
def test_background_analysis_lifecycle_and_private_result(window, tmp_path, outcome):
    win, app = window
    state = win._state
    source = tmp_path / 'private audio.wav'
    source.touch()
    state.work_audio_path = source
    state.speakers['one'].embedding = [1., 0.]
    commands = win.agent_commands()
    session = commands.grant({'read_project', 'analyze_speakers'})
    page = commands.snapshot(session, limit=1)
    job = commands.submit(session, {'operation': 'analyze_voice', 'project_epoch': page['project_epoch'],
        'expected_revision': page['revision'], 'clip_ref': page['dialogues'][0]['clip_ref']})['job_id']
    entered, release = Event(), Event()
    def analyze(*_args):
        entered.set()
        assert release.wait(5)
        if outcome == 'error':
            raise ValueError('AUDIO_ANALYSIS_FAILED')
        return {'method': 'acoustic_features_52', 'score_is_probability': False, 'needs_review': True,
                'margin': 0., 'candidates': [{'speaker_id': 'one', 'score': .5}]}
    with patch.object(SpeakerMatcher, 'analyze_segment', side_effect=analyze):
        try:
            commands.approve(job)
            pump(app, entered.is_set)
            assert win._agent_busy()
            if outcome == 'cancel':
                commands.cancel(session, job)
            elif outcome == 'stale':
                win._mark_dirty(True)
            release.set()
            assert win._agent_audio_worker.wait(5000)
            assert not win._agent_audio_worker.isRunning()
            assert win._agent_busy()  # GUI has not consumed the queued result yet.
            pump(app, lambda: commands._jobs[job].state in ('succeeded', 'failed', 'cancelled'))
            pump(app, lambda: not win._agent_audio_worker.isRunning())
        finally:
            release.set()
            win._agent_audio_worker.wait(5000)
    status = commands.job_status(session, job)
    assert status['state'] == {'success': 'succeeded', 'cancel': 'cancelled', 'stale': 'failed', 'error': 'failed'}[outcome]
    assert state.dialogues[0].speaker_id == 'one'
    if outcome == 'success':
        import json
        assert status['result']['needs_review']
        assert status['result']['candidates'][0]['speaker_ref'] == page['speakers'][0]['speaker_ref']
        encoded = json.dumps(status)
        assert 'private speaker' not in encoded and 'private audio' not in encoded and 'embedding' not in encoded
        other = commands.grant({'read_project', 'analyze_speakers'})
        with pytest.raises(CommandError, match='JOB_NOT_FOUND'):
            commands.job_status(other, job)


def test_analysis_requires_scope_and_reference_and_does_not_mutate(window):
    win, _ = window
    commands = win.agent_commands()
    session = commands.grant({'read_project'})
    page = commands.snapshot(session, limit=1)
    command = {'operation': 'analyze_voice', 'project_epoch': page['project_epoch'],
               'expected_revision': page['revision'], 'clip_ref': page['dialogues'][0]['clip_ref']}
    with pytest.raises(CommandError, match='PERMISSION_DENIED'):
        commands.submit(session, command)
    assert win._state.dialogues[0].speaker_id == 'one'


@pytest.mark.parametrize('vector', [np.zeros(2), np.array([float('nan'), 1.])])
def test_invalid_features_cannot_enroll_or_produce_confident_result(window, vector):
    win, _ = window
    with patch.object(SpeakerMatcher, 'extract_segment_features', return_value=vector):
        assert not SpeakerMatcher.enroll_speaker_sample(win._state, 'one', None, 1., 3.)
        with pytest.raises(ValueError, match='AUDIO_ANALYSIS_FAILED'):
            SpeakerMatcher.analyze_segment(win._state, None, 1., 3.)
    assert not win._state.speakers['one'].has_voiceprint()
