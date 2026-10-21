"""Bookmarks bar of a browser window."""
from urllib.parse import urlsplit

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QPixmap
from PyQt6.QtWidgets import (QLabel, QMenu, QToolButton)

from ..constants import SCHEME
from .popups import BookmarkEditor
from .tips import tip


class BookmarkButton(QToolButton):
    middleClicked = pyqtSignal()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.MiddleButton and self.rect().contains(ev.position().toPoint()):
            self.middleClicked.emit()
            return
        super().mouseReleaseEvent(ev)


class BookmarksBarMixin:
    """Bookmark star, bookmarks bar and its buttons / folders."""

    # ===================================================================== bookmarks
    def toggle_bookmark(self):
        t = self.current()
        if not t:
            return
        u = t.real_url().toString()
        if not u.startswith(("http", "file")):
            return
        bm = self.app.db.bookmark_for(u)
        if not bm:
            bid = self.app.db.add_bookmark(t.title(), u, "Bookmarks bar")
            bm = self.app.db.one("SELECT * FROM bookmarks WHERE id=?", (bid,))
            self.app.bookmarks_changed()
        ed = BookmarkEditor(self, bm["title"], u, bm)
        ed.show_under(self.omni.star)

    def refresh_bookmarks(self):
        lay = self.bm_layout
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        db = self.app.db
        items = db.bookmarks()
        bar = [b for b in items if b["folder"] == "Bookmarks bar"]
        folders = {}
        for b in items:
            if b["folder"] not in ("Bookmarks bar", "Other bookmarks"):
                folders.setdefault(b["folder"], []).append(b)
        other = [b for b in items if b["folder"] == "Other bookmarks"]
        fm = self.fontMetrics()
        budget = max(300, self.width() - 220)
        used, overflow = 0, []
        for b in bar:
            label = (b["title"] or b["url"])[:24]
            w = fm.horizontalAdvance(label) + 44
            if used + w > budget:
                overflow.append(b)
                continue
            used += w
            lay.addWidget(self._bm_button(b, label))
        for name, bs in folders.items():
            w = fm.horizontalAdvance(name) + 44
            if used + w > budget:
                overflow.extend(bs)
                continue
            used += w
            lay.addWidget(self._folder_button(name, bs))
        if overflow:
            lay.addWidget(self._folder_button("»", overflow, icon_only=True))
        lay.addStretch(1)
        if other:
            lay.addWidget(self._folder_button("Other bookmarks", other))
        if not items:
            hint = QLabel("Bookmarks you add (Ctrl+D) show up here")
            hint.setStyleSheet(f"color:{self.pal['muted']};font-size:12px;padding-left:6px;")
            lay.insertWidget(0, hint)
        mgr = QToolButton()
        mgr.setObjectName("bm")
        mgr.setIcon(self.icon("bookmark", size=16))
        tip(mgr, "Bookmark manager", "Organize, import and export your bookmarks", "Ctrl+Shift+O")
        mgr.clicked.connect(lambda: self.open_url(f"{SCHEME}://bookmarks"))
        lay.addWidget(mgr)

    def _fav_icon(self, url):
        host = urlsplit(url).hostname
        png = self.app.db.favicon(host) if host else None
        if png:
            pm = QPixmap()
            if pm.loadFromData(bytes(png)):
                return QIcon(pm)
        return self.icon("globe", size=16)

    def _bm_button(self, b, label):
        btn = BookmarkButton()
        btn.setObjectName("bm")
        btn.setText(label)
        tip(btn, b["title"] or b["url"], b["url"])
        btn.setIcon(self._fav_icon(b["url"]))
        btn.setIconSize(QSize(16, 16))
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        btn.clicked.connect(lambda _=False, u=b["url"]: self.open_url(u, new_tab=False))
        btn.middleClicked.connect(lambda u=b["url"]: self.open_url(u, background=True))
        btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        btn.customContextMenuRequested.connect(lambda pos, b=b, w=btn: self._bm_menu(b, w.mapToGlobal(pos)))
        return btn

    def _folder_button(self, name, items, icon_only=False):
        btn = QToolButton()
        btn.setObjectName("bm")
        btn.setText("" if icon_only else name)
        if icon_only:
            btn.setText("»")
        else:
            btn.setIcon(self.icon("folder", size=16))
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        tip(btn, "More bookmarks" if icon_only else name, "Show the bookmarks that do not fit on the bar" if icon_only else f"{len(items)} bookmark{'s' if len(items) != 1 else ''} in this folder")
        m = QMenu(btn)
        for b in items:
            a = QAction(self._fav_icon(b["url"]), (b["title"] or b["url"])[:60], m)
            a.triggered.connect(lambda _=False, u=b["url"]: self.open_url(u, new_tab=False))
            m.addAction(a)
        btn.setMenu(m)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        return btn

    def _bm_menu(self, b, pos):
        m = QMenu(self)
        for text, fn in (("Open in new tab", lambda: self.open_url(b["url"])),
                         ("Open in new window", lambda: self.app.open_window(b["url"], False)),
                         ("Open in InPrivate window", lambda: self.app.open_window(b["url"], True)),
                         (None, None),
                         ("Edit…", lambda: BookmarkEditor(self, b["title"], b["url"], b).show_under(self.bmbar)),
                         ("Delete", lambda: (self.app.db.delete_bookmark(b["id"]), self.app.bookmarks_changed()))):
            if text is None:
                m.addSeparator()
            else:
                m.addAction(text, fn)
        m.exec(pos)

    def update_star(self):
        t = self.current()
        if not t:
            return
        u = t.real_url().toString()
        marked = bool(self.app.db.bookmark_for(u)) if u.startswith(("http", "file")) else False
        self.omni.star.setIcon(self.icon("star_fill" if marked else "star", color=self.accent if marked else None, size=18))
        self.omni.star.setVisible(u.startswith(("http", "file")))
