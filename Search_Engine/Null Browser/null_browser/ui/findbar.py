"""The find-in-page bar that floats over a tab."""

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QToolButton)

from .tips import tip


class FindBar(QFrame):
    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab
        self.setObjectName("findbar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 6, 6)
        lay.setSpacing(4)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Find in page")
        self.edit.setFixedWidth(220)
        self.count = QLabel("")
        self.count.setMinimumWidth(52)
        self.prev, self.next, self.close_btn = QToolButton(), QToolButton(), QToolButton()
        for b, name, (t, hint, key) in ((self.prev, "up", ("Previous match", "Jump to the match before this one", "Shift+Enter")),
                                        (self.next, "down", ("Next match", "Jump to the next match", "Enter")),
                                        (self.close_btn, "close", ("Close find bar", "Stop searching this page", "Esc"))):
            tip(b, t, hint, key)
            b.setProperty("iconname", name)
        for w in (self.edit, self.count, self.prev, self.next, self.close_btn):
            lay.addWidget(w)
        self.edit.textChanged.connect(self.search)
        self.edit.returnPressed.connect(lambda: self.search(self.edit.text(), True))
        self.next.clicked.connect(lambda: self.search(self.edit.text(), True))
        self.prev.clicked.connect(lambda: self.search(self.edit.text(), False))
        self.close_btn.clicked.connect(self.close_bar)
        self.edit.installEventFilter(self)
        self.restyle()
        self.adjustSize()

    def restyle(self):
        for b in (self.prev, self.next, self.close_btn):
            b.setIcon(self.tab.app.icon(b.property("iconname"), private=self.tab.private))
            b.setIconSize(QSize(16, 16))

    def open(self):
        self.restyle()
        self.show()
        self.raise_()
        self.adjustSize()
        self.tab._place_overlays()
        sel = self.tab.page.selectedText()
        if sel:
            self.edit.setText(sel.splitlines()[0][:100])
        self.edit.setFocus()
        self.edit.selectAll()
        if self.edit.text():
            self.search(self.edit.text())

    def close_bar(self):
        self.hide()
        self.tab.page.findText("")
        self.tab.view.setFocus()

    def search(self, text, forward=True):
        self.tab.page.findText(text, QWebEnginePage.FindFlag(0) if forward else QWebEnginePage.FindFlag.FindBackward)
        if not text:
            self.count.setText("")

    def on_result(self, res):
        if not self.edit.text():
            return
        n = res.numberOfMatches()
        self.count.setText(f"{res.activeMatchOrdinal()}/{n}" if n else "0/0")
        self.edit.setStyleSheet("" if n else "QLineEdit { color: #d93a4a; }")

    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() == ev.Type.KeyPress:
            if ev.key() == Qt.Key.Key_Escape:
                self.close_bar()
                return True
            if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.search(self.edit.text(), False)
                return True
        return super().eventFilter(obj, ev)
