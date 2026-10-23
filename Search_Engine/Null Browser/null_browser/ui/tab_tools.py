"""Page tools: view source, save as, PDF, print, zoom."""
import logging
import os
import re

from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineCore import QWebEnginePage

from ..core import crash

log = logging.getLogger("null.tab")
ZOOMS = [0.25, 0.33, 0.5, 0.67, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0, 5.0]


class PageToolsMixin:
    """View source, save, print, zoom."""

    # ---- tools --------------------------------------------------------------------------------------
    def view_source(self):
        """Ctrl+U: the page's real source (as the server sent it) in a new tab, like Chrome's view-source:."""
        url = self.real_url()
        if url.scheme() in ("http", "https", "file"):
            self.openTab.emit("view-source:" + url.toString(QUrl.ComponentFormattingOption.FullyEncoded), False, None)

    def _default_name(self):
        return re.sub(r"[^\w\- .]", "_", self.title())[:80] or "page"

    def save_page(self):
        from PyQt6.QtWidgets import QFileDialog
        path, flt = QFileDialog.getSaveFileName(self.window(), "Save page as", os.path.join(self.app.downloads.target_dir(), self._default_name()),
                                                "Web page, complete (*.html);;Web page, HTML only (*.html);;Web archive MHTML (*.mhtml)")
        if not path:
            return
        fmt = QWebEnginePage.SavePageFormat
        self.page.save(path, fmt.CompleteHtmlSaveFormat if "complete" in flt else fmt.SingleHtmlSaveFormat if "only" in flt else fmt.MimeHtmlSaveFormat)

    def save_pdf(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self.window(), "Save as PDF", os.path.join(self.app.downloads.target_dir(), self._default_name() + ".pdf"), "PDF (*.pdf)")
        if path:
            self.page.printToPdf(path)
            self.app.notifier.notify("PDF saved", os.path.basename(path), on_click=lambda: self.app.downloads.show_in_folder(path))

    def print_page(self, *_):
        try:
            from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
            printer = QPrinter()
            if QPrintDialog(printer, self.window()).exec():
                self.page.print(printer, lambda ok: None if ok else self.app.notifier.notify("Print failed", self.title(), force=True))
        except Exception:
            crash.log.exception("print")
            self.save_pdf()

    # ---- zoom -------------------------------------------------------------------------------------
    def zoom_step(self, direction):
        cur = self.page.zoomFactor()
        idx = min(range(len(ZOOMS)), key=lambda i: abs(ZOOMS[i] - cur))
        self.set_zoom(ZOOMS[max(0, min(len(ZOOMS) - 1, idx + direction))])

    def set_zoom(self, z):
        self.page.setZoomFactor(z)
        host = self.page.url().host()
        if host and not self.private and self.page.url().scheme() in ("http", "https"):
            self.app.db.set_zoom(host, z)
        self.zoomChanged.emit()

    def show_find(self):
        self.find.open()
