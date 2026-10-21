"""Single-instance IPC for BrowserApp."""
import json
import logging
import re

from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from .core import crash, paths

log = logging.getLogger("null.app")


def ipc_name():
    import getpass
    import hashlib
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    tag = hashlib.sha1(paths.data_dir().encode()).hexdigest()[:8]
    return f"NullBrowser-{re.sub(r'[^A-Za-z0-9_-]', '_', user)}-{tag}"


def forward_to_running_instance(urls, private):
    """If another Null Browser is already running on this profile, hand it the URLs and return True."""
    sock = QLocalSocket()
    sock.connectToServer(ipc_name())
    if not sock.waitForConnected(400):
        return False
    sock.write(json.dumps({"urls": urls, "private": private}).encode() + b"\n")
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


class SingleInstanceMixin:
    """Hand URLs from a second launch to the running browser."""

    def listen_for_instances(self):
        name = self.ipc_name()
        QLocalServer.removeServer(name)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not self.server.listen(name):
            log.warning("single-instance server failed: %s", self.server.errorString())
            return
        self.server.newConnection.connect(self._ipc_connection)

    def _ipc_connection(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            sock.readyRead.connect(lambda s=sock: self._ipc_read(s))
            sock.disconnected.connect(sock.deleteLater)

    @crash.guarded
    def _ipc_read(self, sock):
        for line in bytes(sock.readAll()).splitlines():
            try:
                msg = json.loads(line.decode())
            except ValueError:
                continue
            urls = [u for u in msg.get("urls", []) if isinstance(u, str)][:20]
            self.open_urls(urls, bool(msg.get("private")))
