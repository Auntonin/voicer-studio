"""Client setup stays off the GUI thread and is never exposed as an MCP tool."""
from PySide6.QtCore import QThread, Signal
from core.agent_commands import CommandError


class AgentSetupWorker(QThread):
    ready = Signal(str, str)

    def __init__(self, root, reference, preferred=None, parent=None, *, client='codex', mode='connect'):
        super().__init__(parent)
        self.root, self.reference, self.preferred = root, reference, preferred
        self.client = client
        self.mode = mode

    def run(self):
        from core.agent_setup import register_client, install_gateway, check_gateway
        try:
            if self.mode == 'prepare':
                result = str(install_gateway(self.root, self.preferred))
            elif self.mode == 'check':
                result = check_gateway(self.root, self.reference, self.preferred)
            elif self.mode == 'connect':
                try:
                    result = register_client(self.root, self.reference, self.preferred, client=self.client)
                except CommandError as exc:
                    if exc.code != 'DEPENDENCY_MISSING':
                        raise
                    interpreter = install_gateway(self.root, self.preferred)
                    result = register_client(self.root, self.reference, interpreter, client=self.client)
            else:
                raise CommandError('INVALID_ARGUMENT')
            self.ready.emit(result, '')
        except CommandError as exc:
            self.ready.emit('', exc.code)
        except Exception:
            self.ready.emit('', 'CLIENT_SETUP_FAILED')
