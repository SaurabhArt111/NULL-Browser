"""Built-in pages that live in one tab only: History, Bookmarks, Downloads, Settings, About, Version, Logs.

Opening one of them again (menu, shortcut, link on another built-in page, address bar) switches to the tab that already shows it
instead of opening a second copy. Settings sub-pages (settings/vpn, settings/apps...) reuse the Settings tab and navigate it."""
from PyQt6.QtCore import QUrl

from .constants import SCHEME

SINGLETON_HOSTS = ("history", "bookmarks", "downloads", "settings", "about", "version", "logs")


def _norm(url):
    return url.toString().rstrip("/")


class InternalPagesMixin:
    @staticmethod
    def singleton_host(url):
        """The page name when `url` is one of the one-tab-only built-in pages, else ""."""
        u = QUrl(url) if isinstance(url, str) else url
        if u.scheme().lower() == SCHEME and u.host().lower() in SINGLETON_HOSTS:
            return u.host().lower()
        return ""

    def find_internal_tab(self, url, private, exclude=None):
        """(window, tab) of an open tab that shows this page, or None. Private and normal windows never share tabs."""
        host = self.singleton_host(url)
        if not host:
            return None
        for w in list(self.windows):
            if w.private != private:
                continue
            for t in list(w.tabs):
                if t is exclude:
                    continue
                if t.real_url().scheme().lower() == SCHEME and t.real_url().host().lower() == host:
                    return w, t
        return None

    def focus_internal_page(self, url, private, exclude=None, background=False):
        """Switch to the tab that already shows `url`'s page (navigating it when the address differs, e.g. another Settings
        section). Returns that tab, or None when the page is not open anywhere."""
        found = self.find_internal_tab(url, private, exclude)
        if found is None:
            return None
        w, t = found
        target = QUrl(url) if isinstance(url, str) else url
        if _norm(target) != _norm(t.real_url()):
            t.load(target)
        if background:
            return t
        if w.isMinimized():
            w.showNormal()
        w.show()
        w.raise_()
        w.activateWindow()
        i = w.index_of(t)
        if i >= 0:
            w.tabbar.setCurrentIndex(i)
        return t
