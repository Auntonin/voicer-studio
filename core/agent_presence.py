"""Gateway-only event-driven presence socket. Never imports models or widgets."""
from threading import Event
from PySide6.QtCore import QThread, QTimer, Qt
from core.agent_commands import CommandError


class AgentPresence(QThread):
    def __init__(self, client, name, version, protocol):
        super().__init__()
        self.client = client
        self.metadata = {key: ''.join(c for c in str(value) if c.isprintable())[:100] or 'unknown'
                         for key, value in [('name', name), ('version', version), ('protocol', protocol)]}
        self.stopping = Event()

    def run(self):
        socket = None
        try:
            _, socket = self.client.request({'method': 'client_presence', **self.metadata}, _keep_socket=True)
            socket.disconnected.connect(self.quit, Qt.ConnectionType.DirectConnection)
            QTimer.singleShot(0, lambda: self.quit() if self.stopping.is_set() else None)
            self.exec()
        except CommandError:
            pass  # Tool requests still return their own fixed connection errors.
        finally:
            if socket is not None:
                socket.abort()

    def stop(self):
        self.stopping.set()
        self.quit()
        if not self.wait(5000):
            raise CommandError('IPC_TIMEOUT')
