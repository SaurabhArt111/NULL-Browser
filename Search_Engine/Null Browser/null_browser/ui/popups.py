"""Popups anchored to toolbar buttons: site information, downloads, bookmark editor, info bars."""
import logging

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton,
                             QScrollArea, QToolButton, QVBoxLayout, QWidget)

from ..constants import SCHEME
from ..core.permissions import BY_ID, origin_of
from . import tips

log = logging.getLogger("null.popups")
SITE_FEATURES = ["location", "camera", "microphone", "notifications", "clipboard", "javascript", "images", "cookies", "popups",
                 "sound", "automatic_downloads", "intrusive_ads", "insecure_content", "motion_sensors", "midi", "usb", "serial", "hid",
                 "file_editing", "fonts", "screen_capture", "background_sync", "payment_handlers"]


def fmt_bytes(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


class Anchored(QFrame):
    """Base for a card that pops under a widget and closes when focus is lost."""

    def __init__(self, parent):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("popup")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

    def show_under(self, widget, align_right=False):
        self.adjustSize()
        pt = widget.mapToGlobal(QPoint(widget.width() - self.width() if align_right else 0, widget.height() + 6))
        self.move(pt)
        self.show()


class SiteInfoPopup(Anchored):
    def __init__(self, win, tab):
        super().__init__(win)
        self.win, self.tab, self.app = win, tab, win.app
        url = tab.real_url()
        scheme = url.scheme()
        self.origin = origin_of(url.toString())
        host = url.host() or url.toString()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(8)
        self.setFixedWidth(380)
        title = QLabel(f"<b style='font-size:15px'>{host or 'This page'}</b>")
        if scheme == "https" and not tab.cert_failed:
            status, color, ic = "Connection is secure", self.win.pal["ok"], "lock"
        elif scheme == "http":
            status, color, ic = "Connection is not secure", self.win.pal["danger"], "alert"
        elif scheme == SCHEME:
            status, color, ic = "This is a Null Browser page", self.win.pal["muted"], "null"
        elif scheme == "file":
            status, color, ic = "This is a file on your device", self.win.pal["muted"], "file"
        else:
            status, color, ic = "Page information", self.win.pal["muted"], "info"
        if tab.cert_failed:
            status, color, ic = "Certificate is not valid", self.win.pal["danger"], "alert"
        head = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(self.win.icon(ic, color=color, size=22).pixmap(22, 22))
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(title)
        s = QLabel(status)
        s.setStyleSheet(f"color:{color};")
        col.addWidget(s)
        head.addWidget(icon)
        head.addLayout(col, 1)
        lay.addLayout(head)
        if scheme in ("http", "https") and self.origin:
            hr = QFrame()
            hr.setFrameShape(QFrame.Shape.HLine)
            hr.setStyleSheet(f"color:{self.win.pal['border']};")
            lay.addWidget(hr)
            self.blocked = QLabel(f"Ads and trackers blocked on this page: <b>{self.app.adblock.stats_for(url.host())}</b>")
            lay.addWidget(self.blocked)
            allow = QCheckBox("Allow ads on this site")
            allow.setChecked(self.app.adblock.is_allowed(url.host()))
            allow.toggled.connect(lambda v: self._set_ads(url.host(), v))
            lay.addWidget(allow)
            lay.addWidget(QLabel("<b>Permissions for this site</b>"))
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setFixedHeight(230)
            inner = QWidget()
            grid = QVBoxLayout(inner)
            grid.setContentsMargins(0, 0, 6, 0)
            grid.setSpacing(6)
            for fid in SITE_FEATURES:
                c = BY_ID.get(fid)
                if not c or not c["per_site"]:
                    continue
                row = QHBoxLayout()
                row.addWidget(QLabel(c["label"]), 1)
                combo = QComboBox()
                combo.setMinimumWidth(130)
                dflt = self.app.perms.default(fid)
                dl = next(o["label"] for o in c["options"] if o["value"] == dflt)
                combo.addItem(f"Default ({dl})", "default")
                for o in c["options"]:
                    combo.addItem(o["label"], o["value"])
                cur = self.app.perms.site(self.origin, fid) or "default"
                combo.setCurrentIndex(max(0, combo.findData(cur)))
                combo.activated.connect(lambda _i, f=fid, cb=combo: self._set(f, cb.currentData()))
                row.addWidget(combo)
                grid.addLayout(row)
            grid.addStretch(1)
            area.setWidget(inner)
            lay.addWidget(area)
            btns = QHBoxLayout()
            reset = QPushButton("Reset permissions")
            tips.tip(reset, "Reset permissions", "Forget every choice you made for this site")
            reset.clicked.connect(self._reset)
            more = QPushButton("Site settings")
            more.setObjectName("linkbtn")
            tips.tip(more, "Site settings", "Open the full list of permissions for all sites")
            more.clicked.connect(lambda: (self.close(), win.open_url(f"{SCHEME}://settings/content", new_tab=True)))
            btns.addWidget(reset)
            btns.addStretch(1)
            btns.addWidget(more)
            lay.addLayout(btns)
            self.note = QLabel("Reload the page for changes to take effect.")
            self.note.setStyleSheet(f"color:{self.win.pal['muted']};font-size:11px;")
            self.note.hide()
            lay.addWidget(self.note)

    def _set(self, feature, value):
        self.app.perms.set_site(self.origin, feature, value, self.tab.private)
        self.app.apply_site_policies()
        self.note.show()
        self.adjustSize()

    def _set_ads(self, host, allowed):
        self.app.adblock.set_allowed(host, allowed)
        self.app.refresh_shield()
        self.note.show()

    def _reset(self):
        self.app.perms.reset_site(self.origin)
        self.app.apply_site_policies()
        self.close()
        self.tab.reload()


class DownloadsPopup(Anchored):
    def __init__(self, win):
        super().__init__(win)
        self.win, self.app = win, win.app
        self.setFixedWidth(400)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(14, 12, 14, 10)
        self.lay.setSpacing(8)
        self.app.downloads.changed.connect(self.refresh)
        self.destroyed.connect(lambda *_: self._detach())
        self.refresh()

    def _detach(self):
        try:
            self.app.downloads.changed.disconnect(self.refresh)
        except Exception:
            pass

    def refresh(self):
        try:
            while self.lay.count():
                it = self.lay.takeAt(0)
                w = it.widget()
                if w:
                    w.deleteLater()
                elif it.layout():
                    self._clear(it.layout())
            head = QHBoxLayout()
            head.addWidget(QLabel("<b style='font-size:14px'>Downloads</b>"), 1)
            clear = QPushButton("Clear")
            clear.setObjectName("linkbtn")
            tips.tip(clear, "Clear list", "Remove finished downloads from this list (files stay on disk)")
            clear.clicked.connect(self.app.downloads.clear_finished)
            full = QPushButton("Show all")
            full.setObjectName("linkbtn")
            tips.tip(full, "Show all downloads", "Open the full downloads page", "Ctrl+J")
            full.clicked.connect(lambda: (self.close(), self.win.open_url(f"{SCHEME}://downloads", new_tab=True)))
            head.addWidget(clear)
            head.addWidget(full)
            hw = QWidget()
            hw.setLayout(head)
            self.lay.addWidget(hw)
            items = self.app.downloads.list()[:6]
            if not items:
                self.lay.addWidget(QLabel("No downloads yet"))
            for d in items:
                self.lay.addWidget(self._row(d))
            self.adjustSize()
        except Exception:
            log.exception("downloads popup refresh")

    def _clear(self, layout):
        while layout.count():
            w = layout.takeAt(0).widget()
            if w:
                w.deleteLater()

    def _row(self, d):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 2, 0, 2)
        ic = QLabel()
        ic.setPixmap(self.win.icon("file", size=22).pixmap(22, 22))
        col = QVBoxLayout()
        col.setSpacing(2)
        name = QLabel(d["filename"] or "download")
        name.setStyleSheet("font-weight:600;")
        col.addWidget(name)
        state = d["state"]
        if state == "in_progress":
            bar = QProgressBar()
            bar.setTextVisible(False)
            bar.setFixedHeight(5)
            bar.setRange(0, 100 if d["total"] > 0 else 0)
            bar.setValue(int(d["received"] * 100 / d["total"]) if d["total"] > 0 else 0)
            col.addWidget(bar)
            sub = f"{fmt_bytes(d['received'])}" + (f" of {fmt_bytes(d['total'])}" if d["total"] > 0 else "") + (" — paused" if d.get("paused") else "")
        else:
            sub = {"completed": fmt_bytes(d["total"] or d["received"]) + (" — file moved or deleted" if not d.get("exists") else ""), "cancelled": "Cancelled", "interrupted": "Failed"}.get(state, state)
        sl = QLabel(sub)
        sl.setStyleSheet(f"color:{self.win.pal['muted']};font-size:12px;")
        col.addWidget(sl)
        h.addWidget(ic)
        h.addLayout(col, 1)
        did = d["id"]

        def btn(icon, tip, fn, hint=""):
            b = QToolButton()
            b.setIcon(self.win.icon(icon, size=16))
            tips.tip(b, tip, hint)
            b.clicked.connect(lambda: fn(did))
            h.addWidget(b)
        dm = self.app.downloads
        if state == "in_progress":
            btn("stop", "Cancel download", dm.cancel, "Stop this download and discard the partial file")
        else:
            if state == "completed" and d.get("exists"):
                btn("external", "Open file", dm.open_file, "Open the downloaded file with its default app")
            if d.get("path"):
                btn("folder", "Show in folder", dm.show, "Reveal the file in your file manager")
        return w


class BookmarkEditor(QDialog):
    removed = pyqtSignal()

    def __init__(self, win, title, url, bookmark=None):
        super().__init__(win, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("popup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.win, self.app, self.bookmark, self.url = win, win.app, bookmark, url
        from PyQt6.QtWidgets import QFormLayout
        self.setFixedWidth(340)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.addWidget(QLabel(f"<b style='font-size:15px'>{'Edit bookmark' if bookmark else 'Bookmark added'}</b>"))
        form = QFormLayout()
        self.name = QLineEdit(title)
        self.folder = QComboBox()
        self.folder.setEditable(True)
        for f in self.app.db.bookmark_folders():
            self.folder.addItem(f)
        self.folder.setCurrentText(bookmark["folder"] if bookmark else "Bookmarks bar")
        form.addRow("Name", self.name)
        form.addRow("Folder", self.folder)
        lay.addLayout(form)
        row = QHBoxLayout()
        rm = QPushButton("Remove")
        tips.tip(rm, "Remove bookmark", "Delete this bookmark")
        rm.clicked.connect(self._remove)
        done = QPushButton("Done")
        done.setDefault(True)
        tips.tip(done, "Done", "Save the name and folder")
        done.clicked.connect(self._done)
        row.addWidget(rm)
        row.addStretch(1)
        row.addWidget(done)
        lay.addLayout(row)

    def _done(self):
        db = self.app.db
        folder = self.folder.currentText().strip() or "Bookmarks bar"
        if self.bookmark:
            db.update_bookmark(self.bookmark["id"], self.name.text(), None, folder)
        self.accept()
        self.app.bookmarks_changed()

    def _remove(self):
        if self.bookmark:
            self.app.db.delete_bookmark(self.bookmark["id"])
        self.accept()
        self.app.bookmarks_changed()
        self.removed.emit()

    def show_under(self, widget):
        self.adjustSize()
        self.move(widget.mapToGlobal(QPoint(widget.width() - self.width(), widget.height() + 6)))
        self.show()
        self.name.setFocus()
        self.name.selectAll()


class InfoBar(QFrame):
    def __init__(self, text, buttons, on_close=None, kind="info"):
        super().__init__()
        self.setObjectName("infobar")
        h = QHBoxLayout(self)
        h.setContentsMargins(16, 6, 8, 6)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        h.addWidget(self.label, 1)
        for label, fn in buttons:
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, f=fn: (f(), self.dismiss()))
            h.addWidget(b)
        x = QToolButton()
        x.setText("×")
        tips.tip(x, "Dismiss", "Hide this message")
        x.clicked.connect(self.dismiss)
        h.addWidget(x)
        self._on_close = on_close

    def dismiss(self):
        self.hide()
        self.deleteLater()
        if self._on_close:
            self._on_close()
