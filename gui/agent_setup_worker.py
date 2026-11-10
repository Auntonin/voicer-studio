"""Client setup stays off the GUI thread and is never exposed as an MCP tool."""
from PySide6.QtCore import QThread, Signal
from core.agent_commands import CommandError


class AgentSetupWorker(QThread):
    ready = Signal(str, str)

    def __init__(self, root, reference, preferred=None, parent=None, *, client='codex'):
        super().__init__(parent)
        self.root, self.reference, self.preferred = root, reference, preferred
        self.client = client

    def run(self):
        from core.agent_setup import register_codex, register_claude_desktop
        try:
            if self.client not in ('codex', 'claude'):
                raise CommandError('INVALID_ARGUMENT')
            register = register_codex if self.client == 'codex' else register_claude_desktop
            self.ready.emit(register(self.root, self.reference, self.preferred), '')
        except CommandError as exc:
            self.ready.emit('', exc.code)
        except Exception:
            self.ready.emit('', 'CLIENT_SETUP_FAILED')
