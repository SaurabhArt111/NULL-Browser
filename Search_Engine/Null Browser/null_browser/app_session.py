"""Session persistence for BrowserApp."""
import json
import os
import re

from PyQt6.QtNetwork import QLocalSocket

from .core import crash, paths


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


class SessionMixin:
    """Saving and restoring open windows / tabs."""

    # ------------------------------------------------------------------ session
    def _session_file(self):
        return os.path.join(paths.data_dir(), "session.json")

    def _has_saved_session(self):
        try:
            with open(self._session_file(), encoding="utf-8") as f:
                return any(w.get("tabs") for w in json.load(f).get("windows", []))
        except (OSError, ValueError):
            return False

    @crash.guarded(quiet=True)
    def save_session(self):
        if self._shutting_down and not self.windows:
            return
        data = {"windows": [w.session_state() for w in self.windows if not w.private and w.tabs]}
        if not data["windows"]:
            return
        tmp = self._session_file() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, self._session_file())

    def restore_session(self):
        try:
            with open(self._session_file(), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return False
        made = False
        for ws in data.get("windows", []):
            entries = [t for t in ws.get("tabs", []) if isinstance(t.get("url"), str)]
            if not entries:
                continue
            w = self.new_window(show=False)
            w.restore_state(ws)
            w.show()
            made = True
        return made
