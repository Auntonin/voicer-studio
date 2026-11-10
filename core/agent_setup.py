"""Optional local Codex registration. Never installs dependencies or models."""
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
    candidates = [preferred, root / '.venv' / suffix, root / '.temp/mcp-sdk-env' / suffix, sys.executable]
    from config import SUBPROCESS_FLAGS
    for candidate in candidates:
        if not candidate or not Path(candidate).is_file() or Path(candidate).name.lower() not in ('python', 'python.exe', 'python3'):
            continue
        try:
            checked = subprocess.run([str(candidate), '-c',
                "from importlib.metadata import version; import PySide6.QtNetwork, keyring; assert version('mcp') == '2.3.0'"],
                capture_output=True, timeout=8, creationflags=SUBPROCESS_FLAGS)
            if checked.returncode == 0:
                return Path(candidate).resolve()
        except (OSError, subprocess.TimeoutExpired):
            continue
    raise CommandError('DEPENDENCY_MISSING')


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
    temporary = None
    try:
        if config.is_symlink():
            raise CommandError('MCP_CONFIG_CUSTOMIZED')
        previous = config.read_bytes() if config.exists() else None
        data = json.loads(previous) if previous is not None else {}
        if not isinstance(data, dict) or not isinstance(data.get('mcpServers', {}), dict):
            raise CommandError('MCP_CONFIG_CUSTOMIZED')
        servers = data.setdefault('mcpServers', {})
        old = servers.get('voicer-studio')
        entrypoint = (root / 'scripts/mcp_server.py').resolve()
        if old is not None:
            if not isinstance(old, dict) or not isinstance(old.get('args'), list) or not old['args'] or Path(old['args'][0]).resolve() != entrypoint:
                raise CommandError('MCP_NAME_CONFLICT')
            if set(old) != {'command', 'args'}:
                raise CommandError('MCP_CONFIG_CUSTOMIZED')
        servers['voicer-studio'] = {'command': str(interpreter), 'args': [str(entrypoint), '--session', reference]}
        # Same-directory atomic replacement; refuse a concurrently changed config.
        with tempfile.NamedTemporaryFile(dir=directory, prefix='.voicer-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8'))
        if (config.read_bytes() if config.exists() else None) != previous:
            raise CommandError('MCP_CONFIG_CUSTOMIZED')
        if previous is not None:
            backup = directory / 'claude_desktop_config.voicer-studio.bak'
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
    return str(interpreter)
