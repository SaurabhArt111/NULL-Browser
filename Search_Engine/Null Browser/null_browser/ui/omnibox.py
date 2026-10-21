"""Address bar: smart input, inline autocomplete, history/bookmark/engine suggestions, security chip."""
import logging
import re

from PyQt6.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QToolButton, QWidget

from ..core.search import SuggestClient
from .tips import tip

log = logging.getLogger("null.omnibox")
KIND_ROLE = Qt.ItemDataRole.UserRole
TEXT_ROLE = Qt.ItemDataRole.UserRole + 1


class SuggestPopup(QListWidget):
    picked = pyqtSignal(str, bool)

    def __init__(self, owner):
        super().__init__(None)
        self.owner = owner
        self.setObjectName("suggest")
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setIconSize(QSize(18, 18))
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.itemClicked.connect(lambda it: self.picked.emit(it.data(TEXT_ROLE), bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier)))
        self.itemEntered.connect(lambda it: self.setCurrentItem(it))

    def show_for(self, widget):
        n = self.count()
        if n == 0:
            self.hide()
            return
        w = widget.width()
        self.setFixedSize(w, min(n, 9) * 36 + 16)
        self.move(widget.mapToGlobal(QPoint(0, widget.height() + 4)))
        if not self.isVisible():
            self.show()
        self.raise_()

    def move_selection(self, delta):
        if self.count() == 0:
            return None
        row = self.currentRow() + delta
        row = (row + self.count() + 1) % (self.count() + 1) if False else max(-1, min(self.count() - 1, row))
        if row < 0:
            row = self.count() - 1 if delta < 0 else 0
        self.setCurrentRow(row)
        return self.currentItem()


class Omnibox(QWidget):
    """Rounded field: [security chip][text........][chips...][star]"""
    navigate = pyqtSignal(str, bool)       # text, open in new tab
    focusChanged = pyqtSignal(bool)
    securityClicked = pyqtSignal()
    starClicked = pyqtSignal()

    def __init__(self, win):
        super().__init__()
        self.win, self.app = win, win.app
        self.setObjectName("omniwrap")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("focused", False)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(2)
        self.sec = QToolButton()
        self.sec.setObjectName("chip")
        self.sec.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        tip(self.sec, "Site information", "See the connection security and what this site is allowed to do")
        self.sec.clicked.connect(self.securityClicked)
        self.edit = _Edit(self)
        self.chips = QWidget()
        cl = QHBoxLayout(self.chips)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(2)
        self.popup_chip, self.zoom_chip, self.shield_chip = QToolButton(), QToolButton(), QToolButton()
        for b, (t, hint) in ((self.popup_chip, ("Pop-ups blocked", "This page tried to open pop-up windows. Click to allow them")),
                             (self.zoom_chip, ("Zoom level", "Click to zoom in, zoom out or reset")),
                             (self.shield_chip, ("Ads and trackers blocked", "Click to see details or allow ads on this site"))):
            b.setObjectName("chip")
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            tip(b, t, hint)
            b.hide()
            cl.addWidget(b)
        self.star = QToolButton()
        tip(self.star, "Bookmark this tab", "Save this page so you can find it again", "Ctrl+D")
        self.star.clicked.connect(self.starClicked)
        for w in (self.sec, self.edit, self.chips, self.star):
            lay.addWidget(w)
        lay.setStretch(1, 1)
        self.setMinimumHeight(38)
        self.popup = SuggestPopup(self)
        self.popup.picked.connect(self._picked)
        self.client = SuggestClient(self.app.search, self.app.settings, self)
        self.client.ready.connect(self._remote)
        self.local_items, self.remote_items, self.query = [], [], ""
        self._autocompleted = False
        self.restyle()

    def restyle(self):
        for b in (self.popup_chip, self.zoom_chip, self.shield_chip, self.sec):
            b.setIconSize(QSize(15, 15))
        self.popup_chip.setIcon(self.win.icon("popup", size=16))
        self.zoom_chip.setIcon(self.win.icon("zoom", size=16))
        self.star.setIconSize(QSize(18, 18))

    # ---- text helpers ----------------------------------------------------------------
    def text(self):
        return self.edit.text()

    def set_display(self, text):
        if not self.edit.hasFocus():
            self.edit.setText(text)
            self.edit.setCursorPosition(0)

    def focus_and_select(self):
        self.edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.edit.selectAll()

    def has_focus(self):
        return self.edit.hasFocus()

    def focus_changed(self, focused):
        try:
            self.setProperty("focused", focused)
            self.style().unpolish(self)
            self.style().polish(self)
            if not focused:
                self.popup.hide()
            self.focusChanged.emit(focused)
        except RuntimeError:
            pass                                    # focus-out during window teardown: the popup is already gone

    # ---- suggestions ---------------------------------------------------------------------
    def edited(self, text):
        self.query = text
        t = text.strip()
        if not t:
            self.popup.hide()
            self.client.cancel()
            return
        self.local_items = self._local(t)
        self.remote_items = []
        self.client.request(t)
        self._rebuild()

    def _local(self, t):
        search = self.app.search
        out, seen = [], set()
        url, is_search = search.to_url(t)
        engine = search.current()["name"]
        if is_search:
            out.append(("search", t, f"{t}", f"{engine} Search"))
        else:
            out.append(("nav", t, t, "Open"))
        low = t.lower()
        n = 0
        for b in self.app.db.bookmarks():
            if low in (b["title"] or "").lower() or low in b["url"].lower():
                if b["url"] not in seen:
                    seen.add(b["url"])
                    out.append(("bookmark", b["url"], b["title"] or b["url"], b["url"]))
                    n += 1
                if n >= 3:
                    break
        for r in self.app.db.omnibox_history(t, 6):
            if r["url"] in seen:
                continue
            seen.add(r["url"])
            out.append(("history", r["url"], r["title"] or r["url"], re.sub(r"^https?://", "", r["url"]).rstrip("/")))
        for e in search.engines().values():
            if t.startswith("@") and e["keyword"].startswith(low.split(" ")[0]) and " " not in t:
                out.append(("engine", e["keyword"] + " ", f"Search {e['name']}", e["keyword"]))
        return out[:8]

    def _remote(self, q, items):
        if q.strip() != self.query.strip() or not self.edit.hasFocus():
            return
        self.remote_items = items
        self._rebuild()

    def _rebuild(self):
        p = self.popup
        cur = p.currentRow()
        p.clear()
        icon_for = {"search": "search", "nav": "globe", "bookmark": "star", "history": "history", "engine": "search", "suggest": "search"}
        items = list(self.local_items)
        have = {i[1] for i in items}
        for s in self.remote_items:
            if s not in have:
                items.append(("suggest", s, s, ""))
        for kind, text, title, sub in items[:9]:
            it = QListWidgetItem(self.win.icon(icon_for.get(kind, "globe"), size=18), f"{title}" + (f"  —  {sub}" if sub and kind not in ("search",) else (f"  —  {sub}" if sub else "")))
            it.setData(KIND_ROLE, kind)
            it.setData(TEXT_ROLE, text)
            p.addItem(it)
        p.setCurrentRow(-1 if cur < 0 else min(cur, p.count() - 1))
        p.show_for(self)

    def _picked(self, text, new_tab):
        self.popup.hide()
        self.navigate.emit(text, new_tab)

    # ---- key handling (called by the inner edit) -----------------------------------------------
    def handle_key(self, ev):
        k = ev.key()
        if k in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            if not self.popup.isVisible() and self.edit.text().strip():
                self.edited(self.edit.text())
                return True
            it = self.popup.move_selection(1 if k == Qt.Key.Key_Down else -1)
            if it is not None and self.popup.currentRow() >= 0:
                kind = it.data(KIND_ROLE)
                self.edit.blockSignals(True)
                self.edit.setText(it.data(TEXT_ROLE) if kind != "search" else it.data(TEXT_ROLE))
                self.edit.blockSignals(False)
            return True
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            text = self.edit.text().strip()
            if self.popup.isVisible() and self.popup.currentRow() >= 0:
                text = self.popup.currentItem().data(TEXT_ROLE)
            self.popup.hide()
            if text:
                mods = ev.modifiers()
                self.navigate.emit(text, bool(mods & Qt.KeyboardModifier.AltModifier))
            return True
        if k == Qt.Key.Key_Escape:
            if self.popup.isVisible():
                self.popup.hide()
            else:
                self.win.revert_omnibox()
            return True
        return False

    def autocomplete(self, text):
        """Inline completion of a host from history (Chrome style)."""
        if " " in text or "/" in text or len(text) < 2 or text.startswith(("@", "?", "null:")):
            return
        low = text.lower()
        for r in self.app.db.omnibox_history(low, 12):
            host = re.sub(r"^https?://(www\.)?", "", r["url"]).split("/")[0].lower()
            if host.startswith(low) and host != low:
                self.edit.blockSignals(True)
                self.edit.setText(text + host[len(low):])
                self.edit.setSelection(len(host), -(len(host) - len(text)))
                self.edit.blockSignals(False)
                return


class _Edit(QLineEdit):
    def __init__(self, box):
        super().__init__()
        self.box = box
        self.setObjectName("omnibox")
        self.setPlaceholderText("Search or enter address")
        self.setClearButtonEnabled(False)
        self._click_select = False
        self._last_key = None
        self.textEdited.connect(self._edited)

    def _edited(self, text):
        deleting = self._last_key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete)
        self.box.edited(text)
        if not deleting:
            self.box.autocomplete(text)

    def focusInEvent(self, ev):
        super().focusInEvent(ev)
        self.box.focus_changed(True)
        if ev.reason() == Qt.FocusReason.MouseFocusReason:
            self._click_select = True
        else:
            self.selectAll()

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        self.box.focus_changed(False)
        if ev.reason() != Qt.FocusReason.PopupFocusReason:
            self.deselect()

    def mouseReleaseEvent(self, ev):
        super().mouseReleaseEvent(ev)
        if self._click_select:
            self._click_select = False
            if not self.hasSelectedText():
                self.selectAll()

    def keyPressEvent(self, ev):
        self._last_key = ev.key()
        if self.box.handle_key(ev):
            ev.accept()
            return
        super().keyPressEvent(ev)
