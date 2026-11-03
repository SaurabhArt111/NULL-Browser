"""Bookmarks bar of a browser window."""
from urllib.parse import urlsplit

import time

from PyQt6.QtCore import QMimeData, QObject, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QDrag, QIcon, QPixmap
from PyQt6.QtWidgets import (QApplication, QFrame, QInputDialog, QLabel, QMenu, QMessageBox, QToolButton)

from ..constants import SCHEME
from .popups import BookmarkEditor
from .tips import tip


BM_MIME = "application/x-null-bookmark"


class BookmarkButton(QToolButton):
    """A bookmark on the bar: click opens, middle-click / Ctrl+click opens a background tab, Shift+click a new window,
    and it can be dragged to a new place on the bar."""
    middleClicked = pyqtSignal()

    def __init__(self, bid=None, parent=None):
        super().__init__(parent)
        self.bid = bid
        self._press = None

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._press = ev.position().toPoint()
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._press is not None and self.bid is not None and (ev.buttons() & Qt.MouseButton.LeftButton) \
                and (ev.position().toPoint() - self._press).manhattanLength() > QApplication.startDragDistance() + 2:
            self._press = None
            self.setDown(False)
            drag = QDrag(self)
            md = QMimeData()
            md.setData(BM_MIME, str(self.bid).encode())
            md.setText(self.toolTip())
            drag.setMimeData(md)
            drag.setPixmap(self.grab())
            drag.setHotSpot(ev.position().toPoint())
            drag.exec(Qt.DropAction.MoveAction)
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        self._press = None
        if ev.button() == Qt.MouseButton.MiddleButton and self.rect().contains(ev.position().toPoint()):
            self.middleClicked.emit()
            return
        super().mouseReleaseEvent(ev)


class BookmarkMenu(QMenu):
    """Folder menu: a middle-click on an entry opens it in a background tab and keeps the menu open."""
    middleClickedAction = pyqtSignal(object)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.MiddleButton:
            a = self.actionAt(ev.position().toPoint())
            if a is not None and a.data():
                self.middleClickedAction.emit(a)
                ev.accept()
                return
        super().mouseReleaseEvent(ev)


class _BarDrops(QObject):
    """Drag-and-drop on the bar: moves a bookmark to the spot under the pointer (an accent line shows where it will land) and
    turns a link or an address dragged from a page into a new bookmark."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.line = QFrame(win.bmbar)
        self.line.setFixedWidth(2)
        self.line.hide()

    def _slot(self, x):
        """(index among the bar's bookmarks, x position of the insertion line)"""
        lay = self.win.bm_layout
        buttons = [lay.itemAt(i).widget() for i in range(lay.count())]
        buttons = [w for w in buttons if isinstance(w, BookmarkButton) and w.bid is not None]
        n = sum(1 for w in buttons if x > w.geometry().center().x())
        if n < len(buttons):
            edge = buttons[n].geometry().left() - 1
        elif buttons:
            edge = buttons[-1].geometry().right() + 1
        else:
            edge = 6
        return n, max(2, edge)

    def eventFilter(self, obj, ev):
        t = ev.type()
        name = {60: "enter", 61: "move", 62: "leave", 63: "drop"}.get(int(t))
        if name is None or obj is not self.win.bmbar:
            return False
        if name == "leave":
            self.line.hide()
            return False
        md = ev.mimeData()
        ok = md.hasFormat(BM_MIME) or md.hasUrls()
        if not ok:
            return False
        if name in ("enter", "move"):
            ev.acceptProposedAction()
            _, edge = self._slot(int(ev.position().x()))
            self.line.setGeometry(edge, 3, 2, self.win.bmbar.height() - 6)
            self.line.setStyleSheet(f"background:{self.win.accent};border-radius:1px;")
            self.line.show()
            self.line.raise_()
            return True
        if name == "drop":
            self.line.hide()
            idx, _ = self._slot(int(ev.position().x()))
            db = self.win.app.db
            if md.hasFormat(BM_MIME):
                db.move_bookmark(int(bytes(md.data(BM_MIME)).decode()), "Bookmarks bar", idx)
            else:
                url = md.urls()[0].toString()
                if url.startswith(("http", "file")) and not db.bookmark_for(url):
                    bid = db.add_bookmark((md.text() or url).strip()[:120], url, "Bookmarks bar")
                    db.move_bookmark(bid, "Bookmarks bar", idx)
            ev.acceptProposedAction()
            self.win.app.bookmarks_changed()
            return True
        return False


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
        if not getattr(self, "_bm_wired", False):
            self._bm_wired = True
            self.bmbar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.bmbar.customContextMenuRequested.connect(self._bar_menu)
            self.bmbar.setAcceptDrops(True)
            self._bm_drops = _BarDrops(self)
            self.bmbar.installEventFilter(self._bm_drops)
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

    def _open_bm(self, url):
        """Click on a bookmark: Ctrl = background tab, Shift = new window, otherwise this tab (Chrome's behaviour)."""
        mods = QApplication.keyboardModifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            self.open_url(url, background=True)
        elif mods & Qt.KeyboardModifier.ShiftModifier:
            self.app.open_window(url, False)
        else:
            self.open_url(url, new_tab=False)

    def _bar_menu(self, pos):
        m = QMenu(self)
        m.addAction("Add this page…", self.toggle_bookmark)
        m.addAction("Bookmark all tabs…", self.bookmark_all_tabs)
        m.addSeparator()
        m.addAction("Bookmark manager", lambda: self.open_url(f"{SCHEME}://bookmarks"))
        m.addAction("Hide bookmarks bar", lambda: self.app.settings.set("show_bookmarks_bar", False))
        m.exec(self.bmbar.mapToGlobal(pos))
        m.deleteLater()

    def bookmark_all_tabs(self):
        urls = [(t.title(), t.real_url().toString()) for t in self.tabs if t.real_url().toString().startswith(("http", "file"))]
        if not urls:
            return
        name, ok = QInputDialog.getText(self, "Bookmark all tabs", "Folder name:", text="Tabs " + time.strftime("%Y-%m-%d"))
        if not ok or not name.strip():
            return
        for title, u in urls:
            if not self.app.db.bookmark_for(u):
                self.app.db.add_bookmark(title or u, u, name.strip())
        self.app.bookmarks_changed()
        self.show_toast(f"Saved {len(urls)} tab{'s' if len(urls) != 1 else ''} to “{name.strip()}”")

    def _fav_icon(self, url):
        host = urlsplit(url).hostname
        png = self.app.db.favicon(host) if host else None
        if png:
            pm = QPixmap()
            if pm.loadFromData(bytes(png)):
                return QIcon(pm)
        return self.icon("globe", size=16)

    def _bm_button(self, b, label):
        btn = BookmarkButton(b["id"])
        btn.setObjectName("bm")
        btn.setText(label)
        tip(btn, b["title"] or b["url"], b["url"])
        btn.setIcon(self._fav_icon(b["url"]))
        btn.setIconSize(QSize(16, 16))
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        btn.clicked.connect(lambda _=False, u=b["url"]: self._open_bm(u))
        btn.middleClicked.connect(lambda u=b["url"]: self.open_url(u, background=True))
        btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        btn.customContextMenuRequested.connect(lambda pos, b=b, w=btn: self._bm_menu(b, w.mapToGlobal(pos)))
        return btn

    def _folder_button(self, name, items, icon_only=False):
        btn = QToolButton()
        btn.setObjectName("bm")
        if icon_only:
            btn.setText("»")
        else:
            btn.setText(name)
            btn.setIcon(self.icon("folder", size=16))
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        tip(btn, "More bookmarks" if icon_only else name, "Show the bookmarks that do not fit on the bar" if icon_only else f"{len(items)} bookmark{'s' if len(items) != 1 else ''} in this folder")
        m = BookmarkMenu(btn)
        for b in items:
            a = QAction(self._fav_icon(b["url"]), (b["title"] or b["url"])[:60], m)
            a.setData(b["url"])
            a.triggered.connect(lambda _=False, u=b["url"]: self._open_bm(u))
            m.addAction(a)
        if len(items) > 1:
            m.addSeparator()
            m.addAction(f"Open all ({len(items)})", lambda urls=[b["url"] for b in items]: [self.open_url(u, background=True) for u in urls])
        m.middleClickedAction.connect(lambda a: self.open_url(a.data(), background=True))
        btn.setMenu(m)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        if not icon_only and name not in ("Other bookmarks", "Bookmarks bar"):
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(lambda pos, n=name, w=btn: self._folder_menu(n, w.mapToGlobal(pos)))
        return btn

    def _folder_menu(self, name, pos):
        m = QMenu(self)
        m.addAction("Rename folder…", lambda: self._rename_folder(name))
        m.addAction("Delete folder…", lambda: self._delete_folder(name))
        m.exec(pos)
        m.deleteLater()

    def _rename_folder(self, name):
        new, ok = QInputDialog.getText(self, "Rename folder", "Folder name:", text=name)
        if ok and new.strip() and new.strip() != name:
            self.app.db.rename_folder(name, new.strip())
            self.app.bookmarks_changed()

    def _delete_folder(self, name):
        items = self.app.db.bookmarks(name)
        if QMessageBox.question(self, "Delete folder", f"Delete “{name}” and its {len(items)} bookmark{'s' if len(items) != 1 else ''}?") == QMessageBox.StandardButton.Yes:
            for b in items:
                self.app.db.delete_bookmark(b["id"])
            self.app.bookmarks_changed()

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
