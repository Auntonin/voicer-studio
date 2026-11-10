"""Trusted local MCP setup; client configuration never changes AI policies."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from core.agent_commands import CommandError


def find_codex_cli():
    cli = shutil.which('codex.exe' if os.name == 'nt' else 'codex')
    if cli:
        return cli
    if sys.platform == 'win32':
        local = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local')
        bundled = local / 'OpenAI/Codex/bin'
        try:
            candidates = [p for p in bundled.glob('*/codex.exe') if p.is_file()]
            if candidates:
                return str(max(candidates, key=lambda p: p.stat().st_mtime).resolve())
        except OSError:
            pass
    raise CommandError('CODEX_CLI_MISSING')


def _protect_custom_configuration(root):
    # CLI get intentionally omits some tool-policy fields. Inspect config keys
    # without logging their values before allowing CLI add to reconstruct entry.
    try:
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # Optional Python 3.10 fallback; otherwise fail closed.
        project_config = root / '.codex/config.toml'
        if project_config.is_file() and 'voicer-studio' in tomllib.loads(project_config.read_text(encoding='utf-8')).get('mcp_servers', {}):
            raise CommandError('MCP_CONFIG_CUSTOMIZED')
        config_dir = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')
        data = tomllib.loads((config_dir / 'config.toml').read_text(encoding='utf-8'))
        entry = data.get('mcp_servers', {}).get('voicer-studio')
        if not isinstance(entry, dict) or set(entry) != {'command', 'args'}:
            raise CommandError('MCP_CONFIG_CUSTOMIZED')
    except CommandError:
        raise
    except (ImportError, OSError, ValueError, TypeError):
        raise CommandError('MCP_CONFIG_CUSTOMIZED') from None


def find_gateway_python(root, preferred=None):
    suffix = Path('Scripts/python.exe') if os.name == 'nt' else Path('bin/python')
    candidates = [preferred, root / '.venv-mcp' / suffix, root / '.venv' / suffix,
                  root / '.temp/mcp-sdk-env' / suffix, sys.executable]
    from config import SUBPROCESS_FLAGS
    for candidate in candidates:
        if not candidate or not Path(candidate).is_file() or Path(candidate).name.lower() not in ('python', 'python.exe', 'python3'):
            continue
        try:
            checked = subprocess.run([str(candidate), '-c',
                "from importlib.metadata import version; import PySide6.QtNetwork, keyring, anyio, jsonschema; "
                "from mcp.server.lowlevel import Server; from mcp.client.stdio import stdio_client; "
                "assert version('mcp') == '2.3.0'"],
                capture_output=True, timeout=8, creationflags=SUBPROCESS_FLAGS)
            if checked.returncode == 0:
                return Path(candidate).resolve()
        except (OSError, subprocess.TimeoutExpired):
            continue
    raise CommandError('DEPENDENCY_MISSING')


def install_gateway(root, preferred=None):
    """Explicit user action only: prepare a separate, persistent gateway venv."""
    root = Path(root).resolve()
    suffix = Path('Scripts/python.exe') if os.name == 'nt' else Path('bin/python')
    requirements = root / 'requirements-mcp.txt'
    if not requirements.is_file():
        raise CommandError('DEPENDENCY_MISSING')
    from config import SUBPROCESS_FLAGS
    for candidate in (preferred, root / '.venv' / suffix, sys.executable):
        if not candidate or not Path(candidate).is_file() or Path(candidate).name.lower() not in ('python.exe', 'python', 'python3'):
            continue
        try:
            probe = subprocess.run([str(candidate), '-I', '-c',
                'import sys, venv; assert (3, 10) <= sys.version_info[:2] < (3, 14)'],
                capture_output=True, timeout=10, creationflags=SUBPROCESS_FLAGS)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode == 0:
            break
    else:
        raise CommandError('PYTHON_MISSING')
    directory = root / '.venv-mcp'
    if directory.is_symlink():
        raise CommandError('PATH_DENIED')
    interpreter = directory / suffix
    try:
        for command in ([str(candidate), '-m', 'venv', str(directory)],
                        [str(interpreter), '-m', 'pip', 'install', '--disable-pip-version-check', '-r', str(requirements)]):
            result = subprocess.run(command, cwd=root, capture_output=True, timeout=600,
                                    creationflags=SUBPROCESS_FLAGS)
            if result.returncode:
                raise CommandError('RUNTIME_INSTALL_FAILED')
    except (OSError, subprocess.TimeoutExpired):
        raise CommandError('RUNTIME_INSTALL_FAILED') from None
    return find_gateway_python(root, interpreter)


def connection_config(root, reference, interpreter, format='json'):
    """Produce client-specific text from one authoritative stdio entry."""
    from core.agent_credentials import _reference
    _reference(reference)
    entry = {'command': str(Path(interpreter).resolve()),
             'args': [str((Path(root) / 'scripts/mcp_server.py').resolve()), '--session', reference]}
    if format == 'codex':
        return ('[mcp_servers.voicer-studio]\ncommand = ' + json.dumps(entry['command'], ensure_ascii=False)
                + '\nargs = ' + json.dumps(entry['args'], ensure_ascii=False) + '\n')
    if format not in ('json', 'vscode'):
        raise CommandError('INVALID_ARGUMENT')
    if format == 'vscode':
        entry = {'type': 'stdio', **entry}
    return json.dumps({'servers' if format == 'vscode' else 'mcpServers': {'voicer-studio': entry}},
                      indent=2, ensure_ascii=False)


def check_gateway(root, reference, preferred=None):
    """Run a real stdio initialize/list/call round trip, without reading media."""
    from core.agent_credentials import _reference
    _reference(reference)
    interpreter = find_gateway_python(root, preferred)
    from config import SUBPROCESS_FLAGS
    try:
        result = subprocess.run([str(interpreter), str(Path(root) / 'scripts/mcp_server.py'),
                                 '--session', reference, '--check'], cwd=root, capture_output=True,
                                timeout=30, creationflags=SUBPROCESS_FLAGS)
        data = json.loads(result.stdout)
        if result.returncode or data.get('ok') is not True:
            code = data.get('code')
            raise CommandError(code if code in ('APP_NOT_READY', 'PERMISSION_DENIED', 'DEPENDENCY_MISSING',
                                                'IPC_TIMEOUT', 'PROTOCOL_FAILURE') else 'CONNECTION_CHECK_FAILED')
    except CommandError:
        raise
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise CommandError('CONNECTION_CHECK_FAILED') from None
    return str(interpreter)


def register_codex(root, reference, preferred=None):
    """Use the supported CLI; replace only this app's matching named entry.

    Changes the local voicer-studio MCP entry, never client approval/sandbox
    settings. CLI output can contain configuration data and is not logged.
    """
    from core.agent_credentials import _reference
    _reference(reference)
    interpreter = find_gateway_python(root, preferred)
    cli = find_codex_cli()
    entrypoint = (root / 'scripts/mcp_server.py').resolve()
    from config import SUBPROCESS_FLAGS
    def invoke(args):
        try:
            return subprocess.run([cli, 'mcp', *args], cwd=root, capture_output=True,
                                  timeout=15, creationflags=SUBPROCESS_FLAGS)
        except (OSError, subprocess.TimeoutExpired):
            raise CommandError('CLIENT_SETUP_FAILED') from None
    existing = invoke(['get', 'voicer-studio', '--json'])
    if existing.returncode == 0:
        try:
            existing_entry = json.loads(existing.stdout)
            transport = existing_entry['transport']
            args = transport.get('args', [])
            if transport.get('type') != 'stdio' or not args or Path(args[0]).resolve() != entrypoint:
                raise CommandError('MCP_NAME_CONFLICT')
            # mcp add reconstructs this entry. Do not erase hand-tuned tool policy.
            if any(existing_entry.get(key) not in (None, {}, []) for key in (
                    'enabled_tools', 'disabled_tools', 'default_tools_approval_mode', 'tools',
                    'startup_timeout_sec', 'tool_timeout_sec')) or existing_entry.get('enabled') is False:
                raise CommandError('MCP_CONFIG_CUSTOMIZED')
            if transport.get('env') or transport.get('env_vars') or transport.get('cwd'):
                raise CommandError('MCP_CONFIG_CUSTOMIZED')
        except (ValueError, KeyError, TypeError):
            raise CommandError('MCP_NAME_CONFLICT') from None
        _protect_custom_configuration(root)
    added = invoke(['add', 'voicer-studio', '--', str(interpreter), str(entrypoint), '--session', reference])
    if added.returncode:
        raise CommandError('CLIENT_SETUP_FAILED')
    checked = invoke(['get', 'voicer-studio', '--json'])
    try:
        transport = json.loads(checked.stdout)['transport']
        if checked.returncode or transport['command'] != str(interpreter) or transport['args'] != [str(entrypoint), '--session', reference]:
            raise CommandError('CLIENT_SETUP_FAILED')
    except (ValueError, KeyError, TypeError):
        raise CommandError('CLIENT_SETUP_FAILED') from None
    return str(interpreter)


def register_claude_desktop(root, reference, preferred=None):
    """Merge only this app's entry, preserving other client preferences/servers."""
    from core.agent_credentials import _reference
    _reference(reference)
    interpreter = find_gateway_python(root, preferred)
    if sys.platform == 'win32' and os.environ.get('APPDATA'):
        directory = Path(os.environ['APPDATA']) / 'Claude'
    elif sys.platform == 'darwin':
        directory = Path.home() / 'Library/Application Support/Claude'
    else:
        raise CommandError('CLIENT_NOT_INSTALLED')
    if not directory.is_dir() or directory.is_symlink():
        raise CommandError('CLIENT_NOT_INSTALLED')
    config = directory / 'claude_desktop_config.json'
    _merge_client_config(config, json.loads(connection_config(root, reference, interpreter))['mcpServers']['voicer-studio'])
    return str(interpreter)


def register_client(root, reference, preferred=None, *, client='codex'):
    if client == 'codex':
        return register_codex(root, reference, preferred)
    if client == 'claude':
        return register_claude_desktop(root, reference, preferred)
    interpreter = find_gateway_python(root, preferred)
    container = 'mcpServers'
    if client == 'cursor':
        config = Path.home() / '.cursor/mcp.json'
    elif client == 'claude-code':
        base = Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude')
        if not base.is_dir():
            raise CommandError('CLIENT_NOT_INSTALLED')
        config = base / '.claude.json' if os.environ.get('CLAUDE_CONFIG_DIR') else Path.home() / '.claude.json'
    elif client == 'vscode':
        container = 'servers'
        if sys.platform == 'win32':
            base = Path(os.environ.get('APPDATA') or Path.home() / 'AppData/Roaming')
        elif sys.platform == 'darwin':
            base = Path.home() / 'Library/Application Support'
        else:
            base = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
        config = base / 'Code/User/mcp.json'
    else:
        raise CommandError('INVALID_ARGUMENT')
    if not config.parent.is_dir():
        raise CommandError('CLIENT_NOT_INSTALLED')
    entry = json.loads(connection_config(root, reference, interpreter,
                                        'vscode' if client == 'vscode' else 'json'))[container]['voicer-studio']
    _merge_client_config(config, entry, container)
    return str(interpreter)


def _merge_client_config(config, entry, container='mcpServers'):
    """Preserve unrelated settings and reject customized/redirected entries."""
    directory = config.parent
    temporary = None
    try:
        from core.agent_paths import validate_output
        validate_output(config.absolute())
        if config.is_symlink():
            raise CommandError('MCP_CONFIG_CUSTOMIZED')
        previous = config.read_bytes() if config.exists() else None
        data = json.loads(previous) if previous is not None else {}
        if not isinstance(data, dict) or not isinstance(data.get(container, {}), dict):
            raise CommandError('MCP_CONFIG_CUSTOMIZED')
        servers = data.setdefault(container, {})
        old = servers.get('voicer-studio')
        entrypoint = Path(entry['args'][0])
        if old is not None:
            if not isinstance(old, dict) or not isinstance(old.get('args'), list) or not old['args'] or Path(old['args'][0]).resolve() != entrypoint:
                raise CommandError('MCP_NAME_CONFLICT')
            if set(old) - {'command', 'args', 'type'} or old.get('type', 'stdio') != 'stdio':
                raise CommandError('MCP_CONFIG_CUSTOMIZED')
            if len(old['args']) != 3 or old['args'][1] != '--session':
                raise CommandError('MCP_CONFIG_CUSTOMIZED')
        servers['voicer-studio'] = entry
        # Same-directory atomic replacement; refuse a concurrently changed config.
        with tempfile.NamedTemporaryFile(dir=directory, prefix='.voicer-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8'))
        if (config.read_bytes() if config.exists() else None) != previous:
            raise CommandError('MCP_CONFIG_CUSTOMIZED')
        if previous is not None:
            backup = directory / (config.stem + '.voicer-studio.bak')
            try:
                with backup.open('xb') as stream:
                    stream.write(previous)
                if os.name != 'nt':
                    backup.chmod(0o600)
            except FileExistsError:
                pass  # Keep the first pre-integration backup; never overwrite it.
        os.replace(temporary, config)
        temporary = None
    except CommandError:
        raise
    except (OSError, ValueError, TypeError):
        raise CommandError('CLIENT_SETUP_FAILED') from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
