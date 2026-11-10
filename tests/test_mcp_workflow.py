"""Real stdio and media workflow; AI inference stages explicitly use cached manual cues."""
import asyncio
from threading import Event
import queue
import subprocess
import time
from unittest.mock import patch

from test_mcp_adapter import (window, exercise, parameters, ClientSession, stdio_client)
from gui.agent_bridge import AgentBridge
from core.models import PipelineState, PipelineStep
from core.agent_commands import SCOPES
from config import SUBPROCESS_FLAGS, VoiceSepMode


def test_stdio_empty_import_edit_tracks_pipeline_and_save(window, tmp_path):
    win, app = window
    source = tmp_path / 'source.mp4'
    subprocess.run(['ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=red:s=160x120:r=10',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '3',
                    '-c:v', 'libx264', '-c:a', 'aac', str(source)], check=True,
                   capture_output=True, creationflags=SUBPROCESS_FLAGS)
    win._state = PipelineState()
    win._settings.update(preview_proxy_enabled=False, output_dir=str(tmp_path / 'out'),
                         voice_sep_mode=VoiceSepMode.ORIGINAL, include_dub_video=False)
    win._refresh_all_views()
    bridge = AgentBridge(win.agent_commands(), win)
    ticket = bridge.open_session(SCOPES, approval_mode='session')
    actions = queue.Queue()

    async def owner(action):
        ready = Event()
        actions.put((action, ready))
        while not ready.is_set():
            await asyncio.sleep(.005)

    async def run():
        async with stdio_client(parameters(ticket)) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=10) as session:
                await session.initialize()
                async def page():
                    for _ in range(300):
                        result = await session.call_tool('list_dialogues', {'limit': 100})
                        if not result.is_error:
                            return result.structured_content
                        assert result.structured_content['code'] == 'BUSY', result.structured_content
                        await asyncio.sleep(.01)
                    raise AssertionError('Project stayed busy')
                count = 0
                async def edit(tool, **fields):
                    nonlocal count
                    current = await page()
                    count += 1
                    result = await session.call_tool(tool, {'project_epoch': current['project_epoch'],
                        'expected_revision': current['revision'], 'idempotency_key': 'workflow-' + str(count), **fields})
                    assert not result.is_error, result.structured_content
                    deadline = time.monotonic() + 180
                    while time.monotonic() < deadline:
                        status = await session.call_tool('get_job_status', {'job_id': result.structured_content['job_id']})
                        assert not status.is_error, status.structured_content
                        if status.structured_content['state'] in ('succeeded', 'failed', 'cancelled'):
                            assert status.structured_content['state'] == 'succeeded', status.structured_content
                            return
                        await asyncio.sleep(.05)
                    raise AssertionError('Job did not settle')
                assert (await page())['clip_count'] == 0
                await edit('request_import_media')
                assert (await page())['duration'] >= 3
                await edit('create_character', name='Hero')
                await edit('create_character', name='Extra')
                current = await page()
                extra = next(s['speaker_ref'] for s in current['speakers'] if s['name'] == 'Extra')
                await edit('rename_character', speaker_ref=extra, name='Renamed')
                current = await page()
                hero = next(s['speaker_ref'] for s in current['speakers'] if s['name'] == 'Hero')
                await edit('create_clip', speaker_ref=hero, start=.2, end=1.8, caption='Incorrect')
                current = await page()
                await edit('propose_dialogue_edits', operation='caption', clip_ref=current['dialogues'][0]['clip_ref'], caption='Corrected caption')
                current = await page()
                await edit('create_clip', speaker_ref=current['dialogues'][0]['speaker_ref'], start=2., end=2.7, caption='Previously missing words')
                current = await page()
                await edit('delete_clip', clip_ref=current['dialogues'][1]['clip_ref'])
                await edit('undo_project')
                assert (await page())['clip_count'] == 2
                current = await page()
                extra = next(s['speaker_ref'] for s in current['speakers'] if s['name'] == 'Renamed')
                await edit('remove_character', speaker_ref=extra)
                # No model downloads: manually supplied cues are existing cache.
                await owner(lambda: win._state.step_completed.update({step: True for step in
                    (PipelineStep.VAD, PipelineStep.TRANSCRIPTION, PipelineStep.DIARIZATION)}))
                await edit('request_pipeline')
                await edit('request_save_project')
                assert (await page())['clip_count'] == 2
    try:
        with patch('gui.main_window.QMessageBox.warning', side_effect=AssertionError('Unexpected warning dialog')), patch('gui.main_window.QMessageBox.critical', side_effect=AssertionError('Unexpected error dialog')), patch('gui.main_window.QFileDialog.getOpenFileName', return_value=(str(source), '')), \
             patch('gui.main_window.QFileDialog.getSaveFileName', return_value=(str(tmp_path / 'saved.voicer'), '')):
            exercise(app, run, actions=actions, timeout=180)
        assert (tmp_path / 'saved.voicer').is_file()
        assert all(d.audio_path.is_file() and d.image_path.is_file() for d in win._state.active_dialogues())
        assert win._state.dialogues[0].caption == 'Corrected caption'
    finally:
        if win._worker is not None:
            win._worker.wait(30000)
        bridge.close()
