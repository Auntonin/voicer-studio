"""Client setup never changes sandbox settings or unrelated MCP entries."""
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.agent_commands import CommandError
from core.agent_setup import find_codex_cli, find_gateway_python, register_codex, register_claude_desktop

ROOT = Path(__file__).resolve().parents[1]


def test_registration_finds_desktop_codex_without_path(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr('core.agent_setup.sys', SimpleNamespace(platform='win32'))
    cli = tmp_path / 'OpenAI/Codex/bin/test-build/codex.exe'
    cli.parent.mkdir(parents=True)
    cli.touch()
    python = tmp_path / 'python.exe'
    entry = ROOT / 'scripts/mcp_server.py'
    reference = 'a' * 32
    checked = {'transport': {'command': str(python), 'args': [str(entry), '--session', reference]}}
    responses = [SimpleNamespace(returncode=1, stdout=b''), SimpleNamespace(returncode=0, stdout=b''),
                 SimpleNamespace(returncode=0, stdout=json.dumps(checked).encode())]
    with patch('core.agent_setup.find_gateway_python', return_value=python), \
         patch('core.agent_setup.shutil.which', return_value=None), \
         patch('core.agent_setup.subprocess.run', side_effect=responses) as run:
        assert register_codex(ROOT, reference) == str(python)
        assert Path(run.call_args_list[0].args[0][0]) == cli


def test_gateway_selection_rejects_launcher_and_missing_dependencies(tmp_path):
    launcher = tmp_path / 'VoicerStudio.exe'
    launcher.touch()
    with patch('core.agent_setup.subprocess.run', return_value=SimpleNamespace(returncode=1)) as probe:
        with pytest.raises(CommandError, match='DEPENDENCY_MISSING'):
            find_gateway_python(tmp_path, launcher)
        assert all('VoicerStudio.exe' not in str(call.args[0]) for call in probe.call_args_list)


def test_registration_refuses_another_servers_name(tmp_path):
    result = SimpleNamespace(returncode=0, stdout=json.dumps({'transport': {
        'type': 'stdio', 'args': [str(tmp_path / 'other_server.py')]}}).encode())
    with patch('core.agent_setup.find_gateway_python', return_value=Path('python')), \
         patch('core.agent_setup.shutil.which', return_value='codex'), \
         patch('core.agent_setup.subprocess.run', return_value=result) as run:
        with pytest.raises(CommandError, match='MCP_NAME_CONFLICT'):
            register_codex(tmp_path, 'a' * 32)
        assert run.call_count == 1


def test_real_codex_cli_registration_in_disposable_home(tmp_path, monkeypatch):
    import os
    try:
        cli = find_codex_cli()
    except CommandError:
        pytest.skip('Optional local Codex CLI is not installed')
    gateway = ROOT / '.temp/mcp-sdk-env/Scripts/python.exe'
    if not gateway.is_file():
        pytest.skip('Local gateway fixture unavailable; no dependency installation during tests')
    monkeypatch.setenv('CODEX_HOME', str(tmp_path))
    (tmp_path / 'config.toml').write_text('model = "test-preserved-model"\n', encoding='utf-8')
    interpreter = register_codex(ROOT, 'a' * 32, gateway)
    registered = subprocess.run([cli, 'mcp', 'get', 'voicer-studio', '--json'], cwd=ROOT,
                                capture_output=True, timeout=15)
    assert registered.returncode == 0
    entry = json.loads(registered.stdout)
    assert entry['transport']['command'] == interpreter
    assert entry['transport']['args'][-1] == 'a' * 32
    assert 'test-preserved-model' in (tmp_path / 'config.toml').read_text()
    register_codex(ROOT, 'b' * 32, gateway)
    assert 'b' * 32 in (tmp_path / 'config.toml').read_text()
    assert 'a' * 32 not in (tmp_path / 'config.toml').read_text()
    assert 'sandbox_mode' not in (tmp_path / 'config.toml').read_text()
    config = tmp_path / 'config.toml'
    config.write_text(config.read_text() + '\ndefault_tools_approval_mode = "prompt"\n', encoding='utf-8')
    with pytest.raises(CommandError, match='MCP_CONFIG_CUSTOMIZED'):
        register_codex(ROOT, 'c' * 32, gateway)
    assert 'default_tools_approval_mode = "prompt"' in config.read_text()
    assert 'b' * 32 in config.read_text()


@pytest.mark.parametrize('scenario', ['new', 'update', 'custom', 'conflict', 'invalid'])
def test_claude_config_merge_preserves_preferences_and_refuses_custom_entries(tmp_path, monkeypatch, scenario):
    monkeypatch.setenv('APPDATA', str(tmp_path))
    monkeypatch.setattr('core.agent_setup.sys', SimpleNamespace(platform='win32'))
    directory = tmp_path / 'Claude'
    directory.mkdir()
    config = directory / 'claude_desktop_config.json'
    entrypoint = str((ROOT / 'scripts/mcp_server.py').resolve())
    data = {'preferences': {'theme': 'dark'}, 'mcpServers': {'unrelated': {'command': 'keep-me'}}}
    if scenario != 'new':
        data['mcpServers']['voicer-studio'] = {'command': 'old-python', 'args': [entrypoint, '--session', 'b' * 32]}
    if scenario == 'custom':
        data['mcpServers']['voicer-studio']['env'] = {'PRIVATE_VALUE': 'not-for-output'}
    if scenario == 'conflict':
        data['mcpServers']['voicer-studio']['args'][0] = str(tmp_path / 'different.py')
    previous = 'not-json' if scenario == 'invalid' else json.dumps(data)
    config.write_text(previous, encoding='utf-8')
    with patch('core.agent_setup.find_gateway_python', return_value=tmp_path / 'python.exe'):
        if scenario in ('custom', 'conflict', 'invalid'):
            with pytest.raises(CommandError):
                register_claude_desktop(ROOT, 'a' * 32)
            assert config.read_text(encoding='utf-8') == previous
        else:
            register_claude_desktop(ROOT, 'a' * 32)
            updated = json.loads(config.read_text(encoding='utf-8'))
            assert updated['preferences'] == data['preferences']
            assert updated['mcpServers']['unrelated'] == data['mcpServers']['unrelated']
            assert updated['mcpServers']['voicer-studio']['args'][-1] == 'a' * 32
            assert (directory / 'claude_desktop_config.voicer-studio.bak').read_text(encoding='utf-8') == previous
    assert not list(directory.glob('.voicer-*.tmp'))
