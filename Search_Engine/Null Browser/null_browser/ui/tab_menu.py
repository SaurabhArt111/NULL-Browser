"""Context menu for page content."""

from PyQt6.QtGui import QAction
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWidgets import QMenu

from ..core import crash


class ContextMenuMixin:
    """Right-click menu of a tab."""

    # ---- context menu -----------------------------------------------------------------------------
    def show_context_menu(self, global_pos):
        d = self.view.lastContextMenuRequest()
        if d is None:
            return
        WAct = QWebEnginePage.WebAction
        T = d.MediaType
        m = QMenu(self)
        act = lambda text, fn, ic=None, enabled=True: self._add(m, text, fn, ic, enabled)
        link, media, sel = d.linkUrl(), d.mediaUrl(), d.selectedText()
        if link.isValid():
            act("Open link in new tab", lambda: self.openTab.emit(link.toString(), False, None), "plus")
            act("Open link in new window", lambda: self.openWindow.emit(link.toString(), False), "external")
            act("Open link in InPrivate window", lambda: self.openWindow.emit(link.toString(), True), "eye_off")
            m.addSeparator()
            act("Save link as…", lambda: self.page.triggerAction(WAct.DownloadLinkToDisk), "download")
            act("Copy link address", lambda: self.page.triggerAction(WAct.CopyLinkToClipboard), "copy")
            m.addSeparator()
        if media.isValid() and d.mediaType() == T.MediaTypeImage:
            act("Open image in new tab", lambda: self.openTab.emit(media.toString(), False, None), "plus")
            act("Save image as…", lambda: self.page.triggerAction(WAct.DownloadImageToDisk), "download")
            act("Copy image", lambda: self.page.triggerAction(WAct.CopyImageToClipboard), "copy")
            act("Copy image address", lambda: self.page.triggerAction(WAct.CopyImageUrlToClipboard))
            m.addSeparator()
        elif media.isValid() and d.mediaType() in (T.MediaTypeVideo, T.MediaTypeAudio):
            act("Save media as…", lambda: self.page.triggerAction(WAct.DownloadMediaToDisk), "download")
            act("Copy media address", lambda: self.page.triggerAction(WAct.CopyMediaUrlToClipboard))
            m.addSeparator()
        if d.isContentEditable():
            f, E = d.editFlags(), d.EditFlag
            act("Undo", lambda: self.page.triggerAction(WAct.Undo), enabled=bool(f & E.CanUndo))
            act("Redo", lambda: self.page.triggerAction(WAct.Redo), enabled=bool(f & E.CanRedo))
            m.addSeparator()
            act("Cut", lambda: self.page.triggerAction(WAct.Cut), enabled=bool(f & E.CanCut))
            act("Copy", lambda: self.page.triggerAction(WAct.Copy), "copy", bool(f & E.CanCopy))
            act("Paste", lambda: self.page.triggerAction(WAct.Paste), enabled=bool(f & E.CanPaste))
            act("Select all", lambda: self.page.triggerAction(WAct.SelectAll), enabled=bool(f & E.CanSelectAll))
            m.addSeparator()
        elif sel:
            act("Copy", lambda: self.page.triggerAction(WAct.Copy), "copy")
            short = sel.strip()[:30] + ("…" if len(sel.strip()) > 30 else "")
            act(f"Search {self.app.search.current()['name']} for “{short}”",
                lambda: self.openTab.emit(self.app.search.search_url(sel.strip()), False, None), "search")
            m.addSeparator()
        if not link.isValid() and not d.isContentEditable() and not sel:
            h = self.page.history()
            act("Back", lambda: self.page.triggerAction(WAct.Back), "back", h.canGoBack())
            act("Forward", lambda: self.page.triggerAction(WAct.Forward), "forward", h.canGoForward())
            act("Reload", self.reload, "reload")
            m.addSeparator()
            act("Save as…", self.save_page, "download")
            act("Print…", self.print_page, "print")
            act("Find in page", self.show_find, "search")
            m.addSeparator()
        act("View page source", self.view_source, "code")
        act("Inspect", lambda: self.toggle_devtools(inspect=True), "tool")
        m.exec(global_pos)
        m.deleteLater()

    def _add(self, menu, text, fn, icon_name=None, enabled=True):
        a = QAction(text, menu)
        if icon_name:
            a.setIcon(self.app.icon(icon_name, private=self.private))
        a.setEnabled(enabled)
        a.triggered.connect(lambda *_: crash.guarded(fn)())
        menu.addAction(a)
        return a
