"""Session persistence for BrowserApp."""
import base64
import json
import os
import re
import time

from PyQt6.QtNetwork import QLocalSocket

from .constants import SCHEME
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


def forward_to_running_instance(urls, private, app_id=None):
    """If another Null Browser is already running on this profile, hand it the URLs and return True."""
    sock = QLocalSocket()
    sock.connectToServer(ipc_name())
    if not sock.waitForConnected(400):
        return False
    sock.write(json.dumps({"urls": urls, "private": private, "app": app_id}).encode() + b"\n")
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


CLOSED_MAX = 25                       # entries in the "recently closed" list (tabs and whole windows)
HISTORY_MAX = 64_000                  # bytes of back/forward history kept per closed tab


def history_bytes(page):
    """The tab's back / forward list as bytes (QDataStream), so a reopened tab gets its history back. b"" on failure."""
    try:
        from PyQt6.QtCore import QByteArray, QDataStream, QIODevice
        buf = QByteArray()
        stream = QDataStream(buf, QIODevice.OpenModeFlag.WriteOnly)     # keep both alive while writing (QDataStream holds a raw pointer)
        stream << page.history()
        del stream
        data = bytes(buf)
        return data if len(data) <= HISTORY_MAX else b""
    except Exception:
        return b""


def load_history(page, data):
    """Inverse of history_bytes(); loading the history also navigates to its current entry. Returns True on success."""
    try:
        from PyQt6.QtCore import QByteArray, QDataStream, QIODevice
        buf = QByteArray(bytes(data))
        stream = QDataStream(buf, QIODevice.OpenModeFlag.ReadOnly)      # a temporary QByteArray here was freed mid-read (crash)
        stream >> page.history()
        ok = stream.status() == QDataStream.Status.Ok and page.history().count() > 0
        del stream
        return ok
    except Exception:
        return False


def _urls(tabs):
    return [t.get("url") for t in tabs]


def _worth_keeping(tabs):
    """A window that only had empty New Tab pages is not worth a "recently closed" entry."""
    return any(not str(t.get("url", "")).startswith(f"{SCHEME}://newtab") for t in tabs)


class SessionMixin:
    """Saving and restoring open windows / tabs, and the "recently closed" list behind Ctrl+Shift+T.

    The recently-closed list is shared by all windows and saved to closed.json, so Ctrl+Shift+T keeps working after the
    browser was closed and started again (the windows of the previous run come back first, like Chrome)."""

    # ------------------------------------------------------------------ recently closed (Ctrl+Shift+T)
    def _closed_file(self):
        return os.path.join(paths.data_dir(), "closed.json")

    def init_closed(self, previous_session=None):
        """Load the saved list; when the previous run's windows were not restored, they become the newest entries."""
        self.closed = []
        try:
            with open(self._closed_file(), encoding="utf-8") as f:
                self.closed = [e for e in json.load(f) if isinstance(e, dict) and e.get("kind") in ("tab", "window")]
        except (OSError, ValueError, TypeError):
            pass
        for ws in (previous_session or {}).get("windows", []):
            tabs = [t for t in ws.get("tabs", []) if isinstance(t, dict) and isinstance(t.get("url"), str) and t["url"]]
            if not tabs or not _worth_keeping(tabs):
                continue
            entry = {"kind": "window", "state": {**ws, "tabs": tabs}, "t": time.time()}
            if self.closed and self.closed[-1].get("kind") == "window" and _urls(self.closed[-1].get("state", {}).get("tabs", [])) == _urls(tabs):
                continue                                       # same window already on top (started twice without browsing)
            self.closed.append(entry)
        del self.closed[:-CLOSED_MAX]
        self._save_closed()

    def _save_closed(self):
        try:
            tmp = self._closed_file() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.closed[-CLOSED_MAX:], f)
            os.replace(tmp, self._closed_file())
        except OSError:
            pass

    @property
    def closed_tabs(self):                                     # older code / menus only ask "is there anything to reopen?"
        return getattr(self, "closed", [])

    def remember_closed_tab(self, tab, index):
        url = tab.real_url().toString()
        if tab.private or not url or url.startswith(f"{SCHEME}://newtab") or url.startswith("about:"):
            return
        hist = b"" if tab.lazy_url else history_bytes(tab.page)
        self.closed.append({"kind": "tab", "url": url, "title": tab.title(), "pinned": bool(tab.pinned), "index": int(index),
                            "history": base64.b64encode(hist).decode() if hist else "", "t": time.time()})
        del self.closed[:-CLOSED_MAX]
        self._save_closed()

    def remember_closed_window(self, win):
        if win.private or getattr(win, "_adopting", False):
            return
        state = win.session_state()
        if not state.get("tabs") or not _worth_keeping(state["tabs"]):
            return
        self.closed.append({"kind": "window", "state": state, "t": time.time(),
                            "title": f"{len(state['tabs'])} tab{'s' if len(state['tabs']) != 1 else ''}"})
        del self.closed[:-CLOSED_MAX]
        self._save_closed()

    def reopen_closed(self, win=None, entry_index=None):
        """Bring back the newest closed tab or window (or a specific entry from the menu). Returns the tab / window."""
        if not self.closed:
            return None
        i = len(self.closed) - 1 if entry_index is None else entry_index
        if not 0 <= i < len(self.closed):
            return None
        e = self.closed.pop(i)
        self._save_closed()
        if e["kind"] == "window":
            w = self.new_window(show=False)
            w.restore_state(e["state"])
            w.show_initial()
            w.raise_()
            w.activateWindow()
            return w
        if win is None or win.private or win not in self.windows:
            win = next((w for w in reversed(self.windows) if not w.private), None) or self.new_window()
        hist = b""
        try:
            hist = base64.b64decode(e.get("history") or "")
        except ValueError:
            pass
        return win.new_tab(e["url"], index=e.get("index"), pinned=bool(e.get("pinned")), history=hist or None)

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

    def read_session(self):
        try:
            with open(self._session_file(), encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def restore_session(self):
        data = self.read_session()
        if data is None:
            return False
        made = False
        for ws in data.get("windows", []):
            entries = [t for t in ws.get("tabs", []) if isinstance(t.get("url"), str)]
            if not entries:
                continue
            w = self.new_window(show=False)
            w.restore_state(ws)
            w.show_initial()
            made = True
            for k in range(len(getattr(self, "closed", [])) - 1, -1, -1):        # restored now: no need to offer it under Ctrl+Shift+T
                c = self.closed[k]
                if c.get("kind") == "window" and _urls(c.get("state", {}).get("tabs", [])) == _urls(entries):
                    del self.closed[k]
                    self._save_closed()
                    break
        return made
