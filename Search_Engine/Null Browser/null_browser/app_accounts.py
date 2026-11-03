"""Google sign-in at browser level (see core/accounts.py) for BrowserApp."""
import logging
import os

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QPixmap
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWebEngineCore import QWebEnginePage

from .core import crash, paths
from .core.accounts import LIST_ACCOUNTS_URL, SIGN_IN_URL, AccountStore, parse_list_accounts
from .core.cookie_keeper import CookieKeeper

log = logging.getLogger("null.account")


class AccountsMixin:
    """Sign in with Google once; the browser remembers it across "Clear browsing data"."""

    def init_accounts(self):
        self.account = AccountStore(paths.data_dir())
        self.cookies = CookieKeeper(self.profile.cookieStore(), self)
        self.cookies.authCookieSeen.connect(self._auth_cookie_seen)
        self._signing_in = False
        self._identity_timer = QTimer(self, singleShot=True, interval=1800, timeout=self.refresh_identity)
        self._avatar_nam = None
        self.apply_google_compat()

    def apply_google_compat(self):
        """Sign-in compatibility (engine/google_compat.py): the Chrome brand in the request header for Google's own hosts."""
        from .engine import google_compat
        on = bool(self.settings.get("google_compat"))
        self.adblock.client_hints = google_compat.client_hints(self.profile.httpUserAgent()) if on else None

    # ---- state ---------------------------------------------------------------------------------
    def account_info(self):
        info = self.account.public()
        info["keep_on_clear"] = bool(self.settings.get("google_keep_signed_in"))
        info["avatar"] = os.path.isfile(self.avatar_path())
        info["has_cookies"] = self.cookies.has_auth()
        return info

    def avatar_path(self):
        return os.path.join(paths.data_dir(), "account-avatar.png")

    def keep_google_login(self):
        return self.account.signed_in() and bool(self.settings.get("google_keep_signed_in"))

    # ---- sign in / out ---------------------------------------------------------------------------
    def begin_sign_in(self):
        self._signing_in = True
        w = self.active_window()
        if w is None or w.private:
            w = self.new_window()
        w.open_url(SIGN_IN_URL, new_tab=True)
        w.show_toast("Sign in on the Google page. Null Browser will pick the account up when you are done.", 7000)

    def _auth_cookie_seen(self):
        if self._signing_in or (self.account.signed_in() and not os.path.isfile(self.avatar_path())):
            self._identity_timer.start()                        # wait for Google to finish setting its cookies, then ask who it is

    @crash.guarded(quiet=True)
    def refresh_identity(self, callback=None):
        """Ask Google who is signed in (the same ListAccounts call Chrome makes) using a hidden page on the normal profile."""
        page = QWebEnginePage(self.profile, self)
        done = {"v": False}

        def finish(text):
            if done["v"]:
                return
            done["v"] = True
            rec = parse_list_accounts(text)
            page.deleteLater()
            if rec:
                self._signing_in = False
                self.account.set(rec["email"], rec["name"], rec["picture"])
                self.fetch_avatar(rec["picture"])
                self.accountChanged.emit()
                w = self.active_window()
                if w:
                    w.show_toast(f"Signed in as {rec['email']}")
            if callback:
                callback(rec)

        page.loadFinished.connect(lambda ok: page.toPlainText(finish) if ok else finish(""))
        QTimer.singleShot(15000, lambda: finish(""))
        page.load(QUrl(LIST_ACCOUNTS_URL))

    def fetch_avatar(self, url):
        if not url or not url.startswith("https://"):
            return
        if self._avatar_nam is None:
            self._avatar_nam = QNetworkAccessManager(self)
        big = url.split("=")[0] + "=s96-c" if "googleusercontent.com" in url else url
        reply = self._avatar_nam.get(QNetworkRequest(QUrl(big)))

        def done():
            try:
                if reply.error() == QNetworkReply.NetworkError.NoError:
                    pm = QPixmap()
                    if pm.loadFromData(bytes(reply.readAll())) and not pm.isNull():
                        pm.scaled(96, 96).save(self.avatar_path(), "PNG")
                        self.accountChanged.emit()
            finally:
                reply.deleteLater()
        reply.finished.connect(done)

    def sign_out(self):
        """Remove the Google login from this browser: the saved identity and the sign-in cookies."""
        self._signing_in = False
        self.account.clear()
        self.cookies.remove_google_login()
        try:
            os.remove(self.avatar_path())
        except OSError:
            pass
        self.accountChanged.emit()
