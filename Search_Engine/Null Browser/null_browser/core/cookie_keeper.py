"""Mirror of the persistent profile's cookie jar, so "clear cookies" can delete everything except the Google sign-in."""
import logging

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QNetworkCookie

from .accounts import is_auth_cookie

log = logging.getLogger("null.cookies")


def _key(c):
    return (c.domain(), c.path(), bytes(c.name()).decode("latin-1"))


class CookieKeeper(QObject):
    authCookieSeen = pyqtSignal()                       # a Google sign-in cookie was just set (the sign-in flow listens)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.jar = {}
        store.cookieAdded.connect(self._added)
        store.cookieRemoved.connect(self._removed)
        store.loadAllCookies()                          # replays every stored cookie through cookieAdded

    def _added(self, c):
        c = QNetworkCookie(c)                           # the signal's object is only valid during the call: keep our own copy
        self.jar[_key(c)] = c
        if is_auth_cookie(bytes(c.name()).decode("latin-1"), c.domain()):
            self.authCookieSeen.emit()

    def _removed(self, c):
        self.jar.pop(_key(c), None)

    def has_auth(self):
        return any(is_auth_cookie(k[2], k[0]) for k in self.jar)

    def clear(self, keep_google_login):
        """Delete cookies. With keep_google_login the cookies that make up the Google sign-in survive (everything else goes)."""
        if not keep_google_login:
            self.store.deleteAllCookies()
            return 0
        kept = 0
        for k, c in list(self.jar.items()):
            if is_auth_cookie(k[2], k[0]):
                kept += 1
                continue
            self.store.deleteCookie(c)
        return kept

    def remove_google_login(self):
        n = 0
        for k, c in list(self.jar.items()):
            if is_auth_cookie(k[2], k[0]):
                self.store.deleteCookie(c)
                n += 1
        return n
