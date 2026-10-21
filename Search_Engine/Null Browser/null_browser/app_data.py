"""Browsing-data clearing and memory saver for BrowserApp."""
import json
import logging
import os
import re
import shutil
import time

from PyQt6.QtNetwork import QLocalSocket

from .core import crash, paths

log = logging.getLogger("null.app")
STORAGE_DIRS = ("Local Storage", "IndexedDB", "Session Storage", "Service Worker", "File System", "databases", "shared_proto_db")


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


class BrowsingDataMixin:
    """Clearing browsing data and discarding idle tabs."""

    # ------------------------------------------------------------------ privacy
    def _pending_file(self):
        return os.path.join(paths.data_dir(), "pending-clear.json")

    def _apply_pending_clear(self):
        """Runs before any WebEngine profile exists, so site storage dirs are unlocked."""
        try:
            from .core.settings import peek
            if peek().get("save_site_data", True) is False:
                # Only when the user explicitly switched "Keep cookies and site data" OFF: remove what an earlier run left on disk.
                shutil.rmtree(os.path.join(paths.data_dir(), "profile"), ignore_errors=True)
            if os.path.exists(self._pending_file()):
                os.remove(self._pending_file())
                base = paths.sub("profile", "storage")
                for d in STORAGE_DIRS:
                    shutil.rmtree(os.path.join(base, d), ignore_errors=True)
                log.info("Cleared local site storage")
        except Exception:
            log.exception("pending clear failed")

    def clear_data(self, types, rng="all"):
        seconds = {"15min": 900, "hour": 3600, "day": 86400, "week": 7 * 86400, "month": 28 * 86400}.get(rng)
        start = time.time() - seconds if seconds else 0
        if "history" in types:
            self.db.delete_history_range(start)
            self.profile.clearAllVisitedLinks()
        if "downloads" in types:
            self.db.run("DELETE FROM downloads WHERE state<>'in_progress' AND started>=?", (start,))
            self.downloads.clear_finished() if not seconds else None
            self.downloads.changed.emit()
        if "cache" in types:
            self.profile.clearHttpCache()
            if self._private_profile:
                self._private_profile.clearHttpCache()
        if "cookies" in types:
            self.profile.cookieStore().deleteAllCookies()
            if self._private_profile:
                self._private_profile.cookieStore().deleteAllCookies()
            try:
                with open(self._pending_file(), "w") as f:
                    f.write("1")
            except OSError:
                pass
        if "site_perms" in types:
            self.perms.reset_all_sites()
            self.apply_site_policies()
        log.info("Cleared browsing data: %s (%s)", sorted(types), rng)

    # ------------------------------------------------------------------ memory saver
    @crash.guarded(quiet=True)
    def memory_saver_tick(self):
        if not self.settings.get("memory_saver"):
            return
        limit = max(1, int(self.settings.get("memory_saver_minutes") or 15)) * 60
        now = time.time()
        for t in self.all_tabs():
            if (now - t.last_active > limit and not t.pinned and not t.loading and not t.discarded
                    and not t.page.recentlyAudible() and t.devtools is None and not t.is_internal()):
                t.discard()
