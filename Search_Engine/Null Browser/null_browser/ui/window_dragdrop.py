"""Tab detach / adopt and drag-and-drop."""

from PyQt6.QtCore import QPoint


class TabTransferMixin:
    """Moving tabs between windows and dropping links / files on the window."""

    # ===================================================================== moving tabs between windows
    def detach_tab(self, i):
        """Take tab i out of this window WITHOUT destroying it (used when dragging a tab out / into another window)."""
        if not (0 <= i < len(self.tabs)):
            return None
        tab = self.tabs[i]
        was_current = i == self.tabbar.currentIndex()
        self.tabbar.blockSignals(True)
        self.tabs.pop(i)
        self.tabbar.removeTab(i)
        self.tabbar.blockSignals(False)
        self.stack.removeWidget(tab)
        for sig in (tab.titleChanged, tab.urlChanged, tab.iconChanged, tab.loadingChanged, tab.progressChanged, tab.audioChanged,
                    tab.securityChanged, tab.zoomChanged, tab.popupBlocked, tab.openTab, tab.openWindow, tab.closeRequested,
                    tab.fullscreenToggled, tab.focusOmnibox):
            try:
                sig.disconnect()
            except TypeError:
                pass
        tab.hide()
        self.tabbar.clear_loading()
        for t in self.tabs:
            if t.loading:
                self.tabbar.set_loading(self.index_of(t), True)
        if self.tabs and was_current:
            self._current_changed(self.tabbar.currentIndex())
        self._schedule_session()
        return tab

    def adopt_tab(self, tab, index=None, activate=True):
        """Insert a tab that was detached from another window."""
        i = len(self.tabs) if index is None else max(0, min(index, len(self.tabs)))
        self._wire_tab(tab)
        self.tabs.insert(i, tab)
        self.stack.insertWidget(i, tab)
        self.tabbar.blockSignals(True)
        self.tabbar.insertTab(i, self.icon("globe", size=16), tab.title())
        self.tabbar.blockSignals(False)
        self._decorate(tab)
        self._tab_title(tab)
        tab.loading and self.tabbar.set_loading(i, True)
        if not tab.loading:
            self._tab_icon(tab)
        if activate:
            self.tabbar.setCurrentIndex(i)
            self._current_changed(i)
        self._schedule_session()
        return tab

    def move_tab_to_new_window(self, i):
        if len(self.tabs) < 2 or not (0 <= i < len(self.tabs)):
            return
        tab = self.detach_tab(i)
        w = self.app.new_window(private=self.private, show=False, empty=True)
        w.resize(self.size() if not self.isMaximized() else self.normalGeometry().size())
        w.adopt_tab(tab)
        w.move(self.pos() + QPoint(40, 40))
        w.show()
        w.raise_()
        w.activateWindow()

    def drop_hint_index(self, global_pos):
        x = self.tabbar.mapFromGlobal(global_pos).x()
        for k in range(self.tabbar.count()):
            if x < self.tabbar.tabRect(k).center().x():
                return k
        return self.tabbar.count()

    def show_drop_hint(self, global_pos):
        k = self.drop_hint_index(global_pos)
        if k < self.tabbar.count():
            x = self.tabbar.tabRect(k).left()
        elif self.tabbar.count():
            x = self.tabbar.tabRect(self.tabbar.count() - 1).right()
        else:
            x = 0
        p = self.tabbar.mapTo(self.strip, QPoint(x, 0))
        self._drop_hint.setGeometry(p.x() - 1, 6, 3, self.strip.height() - 8)
        self._drop_hint.show()
        self._drop_hint.raise_()

    def clear_drop_hint(self):
        self._drop_hint.hide()

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls() or ev.mimeData().hasText():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        md = ev.mimeData()
        for u in md.urls():
            self.new_tab(u.toString())
        if not md.hasUrls() and md.hasText():
            self.navigate_text(md.text(), new_tab=True)
