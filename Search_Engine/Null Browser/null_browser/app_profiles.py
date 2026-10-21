"""Profile creation for BrowserApp."""
import json
import re

from PyQt6.QtCore import QTimer
from PyQt6.QtNetwork import QLocalSocket
from PyQt6.QtWebEngineCore import QWebEngineProfile

from . import constants as C
from .core import paths
from .web.scheme import NullSchemeHandler


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


class ProfilesMixin:
    """Web profiles: the persistent one and the off-the-record one."""

    # ------------------------------------------------------------------ profiles
    def _make_profile(self, private):
        if private or self.settings.get("save_site_data") is False:
            # An unnamed profile is "off the record": cookies, logins, local storage, IndexedDB and the cache live in memory
            # only. Used for InPrivate windows, and for normal windows only if the user turned "Keep cookies and site data" OFF.
            prof = QWebEngineProfile(self)
            prof.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        else:
            prof = QWebEngineProfile("NullBrowser", self)
            prof.setPersistentStoragePath(paths.sub("profile", "storage"))
            prof.setCachePath(paths.sub("profile", "cache"))
            prof.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
            prof.setHttpCacheMaximumSize(300 * 1024 * 1024)
            prof.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
        try:
            prof.setPersistentPermissionsPolicy(QWebEngineProfile.PersistentPermissionsPolicy.AskEveryTime)
        except Exception:
            pass
        ua = re.sub(r"\s*QtWebEngine/[\d.]+", "", prof.httpUserAgent())
        prof.setHttpUserAgent(f"{ua} {C.UA_TOKEN}")
        prof.setHttpAcceptLanguage(self.settings.get("accept_languages") or "en-US,en")
        try:
            prof.setSpellCheckEnabled(bool(self.settings.get("spellcheck")))
        except Exception:
            pass
        handler = NullSchemeHandler(self, private=private, parent=prof)
        prof.installUrlSchemeHandler(C.SCHEME.encode(), handler)
        if not self.safe:
            prof.setUrlRequestInterceptor(self.adblock)
        prof.downloadRequested.connect(lambda req, p=private: self.downloads.handle(req, p))
        prof.setNotificationPresenter(self.notifier.present_web)
        prof.cookieStore().setCookieFilter(self.cookie_policy)
        self._install_shim(prof, private)
        self.video.install_script(prof)
        return prof

    @property
    def private_profile(self):
        if self._private_profile is None:
            self._private_profile = self._make_profile(private=True)
        return self._private_profile

    def maybe_drop_private_profile(self):
        if self._private_profile is None or any(w.private for w in self.windows):
            return
        prof, self._private_profile = self._private_profile, None
        self.perms.session.clear()
        QTimer.singleShot(800, lambda: prof.deleteLater())
