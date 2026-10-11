"""Download manager: policies, progress, persistence and native notifications."""
import logging
import os
import subprocess
import sys
import time

from PyQt6.QtCore import QObject, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest as DR
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from . import paths
from .permissions import origin_of

log = logging.getLogger("null.downloads")
DANGEROUS = {".exe", ".msi", ".bat", ".cmd", ".scr", ".ps1", ".vbs", ".js", ".jar", ".com", ".pif", ".reg",
             ".lnk", ".hta", ".dll", ".apk", ".dmg", ".pkg", ".sh", ".appimage"}
S = DR.DownloadState


def unique_path(directory, name):
    base, ext = os.path.splitext(name)
    path = os.path.join(directory, name)
    n = 1
    while os.path.exists(path):
        path = os.path.join(directory, f"{base} ({n}){ext}")
        n += 1
    return path


class Item:
    def __init__(self, req, row_id, private):
        self.req, self.id, self.private = req, row_id, private
        self.url = req.url().toString()
        self.path = ""
        self.name = ""
        self.mime = req.mimeType()
        self.started = time.time()
        self.finished = 0
        self.state = "in_progress"

    def to_dict(self):
        r = self.req
        return {"id": self.id, "url": self.url, "path": self.path, "filename": self.name, "mime": self.mime,
                "total": r.totalBytes() if r else 0, "received": r.receivedBytes() if r else 0,
                "state": self.state, "started": self.started, "finished": self.finished,
                "paused": bool(r and r.isPaused()), "private": self.private,
                "exists": os.path.exists(self.path) if self.path else False}


class DownloadManager(QObject):
    changed = pyqtSignal()
    started = pyqtSignal(object)
    completed = pyqtSignal(object)

    def __init__(self, db, settings, perms, notifier, parent=None):
        super().__init__(parent)
        self.db, self.settings, self.perms, self.notifier = db, settings, perms, notifier
        self.live = {}                   # id -> Item
        self._mem_id = -1
        self._recent = {}                # origin -> last start time (automatic download detection)
        self.parent_window = lambda: None
        try:                             # downloads in flight at last quit can never resume
            self.db.run("UPDATE downloads SET state='interrupted' WHERE state='in_progress'")
        except Exception:
            pass

    def target_dir(self):
        d = self.settings.get("download_dir") or paths.downloads_dir()
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            d = paths.downloads_dir()
        return d

    def handle(self, req, private=False):
        try:
            self._handle(req, private)
        except Exception:
            log.exception("download setup failed")
            try:
                req.cancel()
            except Exception:
                pass

    def _handle(self, req, private):
        win = self.parent_window()
        is_page_save = req.isSavePageDownload()
        origin = origin_of(req.url().toString()) or "download"
        now = time.time()
        if not is_page_save:
            last = self._recent.get(origin, 0)
            self._recent[origin] = now
            if now - last < 6:                                  # second download straight after the first
                policy = self.perms.effective(origin, "automatic_downloads", private)
                if policy == "block":
                    req.cancel()
                    self.notifier.notify("Download blocked", f"{origin} tried to download multiple files automatically.", force=True)
                    return
                if policy == "ask":
                    r = QMessageBox.question(win, "Automatic downloads", f"{origin} wants to download multiple files.\n\nAllow?")
                    if r != QMessageBox.StandardButton.Yes:
                        req.cancel()
                        return
        name = req.downloadFileName() or "download"
        directory = self.target_dir()
        ext = os.path.splitext(name)[1].lower()
        if not is_page_save and ext in DANGEROUS and self.settings.get("warn_dangerous_downloads"):
            box = QMessageBox(win)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Keep this file?")
            box.setText(f"“{name}” can harm your device.")
            box.setInformativeText(f"From: {req.url().host()}\nOnly keep files you trust.")
            keep = box.addButton("Keep", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Discard", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not keep:
                req.cancel()
                return
        if is_page_save:
            directory, name = req.downloadDirectory(), req.downloadFileName()
        elif self.settings.get("ask_download_location"):
            chosen, _ = QFileDialog.getSaveFileName(win, "Save file as", os.path.join(directory, name))
            if not chosen:
                req.cancel()
                return
            directory, name = os.path.dirname(chosen), os.path.basename(chosen)
        else:
            path = unique_path(directory, name)
            name = os.path.basename(path)
        req.setDownloadDirectory(directory)
        req.setDownloadFileName(name)

        if private:
            rid = self._mem_id
            self._mem_id -= 1
        else:
            rid = self.db.run(
                "INSERT INTO downloads(url,path,filename,mime,total,received,state,started) VALUES(?,?,?,?,?,?,?,?)",
                (req.url().toString(), os.path.join(directory, name), name, req.mimeType(), 0, 0, "in_progress", now)).lastrowid
        it = Item(req, rid, private)
        it.name, it.path = name, os.path.join(directory, name)
        self.live[rid] = it
        req.receivedBytesChanged.connect(self.changed)
        req.totalBytesChanged.connect(self.changed)
        req.isPausedChanged.connect(self.changed)
        req.stateChanged.connect(lambda st, i=it: self._state(i, st))
        req.accept()
        self.started.emit(it)
        self.changed.emit()

    def _state(self, it, st):
        mapping = {S.DownloadCompleted: "completed", S.DownloadCancelled: "cancelled",
                   S.DownloadInterrupted: "interrupted", S.DownloadInProgress: "in_progress"}
        it.state = mapping.get(st, "in_progress")
        if it.state != "in_progress":
            it.finished = time.time()
            r = it.req
            if not it.private:
                try:
                    self.db.run("UPDATE downloads SET state=?, finished=?, total=?, received=?, path=? WHERE id=?",
                                (it.state, it.finished, r.totalBytes(), r.receivedBytes(), it.path, it.id))
                except Exception:
                    log.exception("could not persist download state")
            if it.state == "completed":
                self.notifier.notify("Download complete", it.name, on_click=lambda p=it.path: self.show_in_folder(p))
                self.completed.emit(it)
            elif it.state == "interrupted":
                self.notifier.notify("Download failed", f"{it.name}: {r.interruptReasonString()}")
        self.changed.emit()

    # ---- queries / actions -----------------------------------------------------------
    def list(self):
        rows = {r["id"]: r for r in self.db.all("SELECT * FROM downloads ORDER BY started DESC LIMIT 500")}
        for it in self.live.values():
            rows[it.id] = {**rows.get(it.id, {}), **it.to_dict()}
        for r in rows.values():
            r.setdefault("paused", False)
            r["exists"] = os.path.exists(r.get("path") or "")
        return sorted(rows.values(), key=lambda r: -(r.get("started") or 0))

    def active_count(self):
        return sum(1 for i in self.live.values() if i.state == "in_progress")

    def _path_of(self, did):
        r = self.live.get(did)
        if r:
            return r.path
        row = self.db.one("SELECT path FROM downloads WHERE id=?", (did,))
        return (row or {}).get("path")

    def cancel(self, did):
        it = self.live.get(did)
        if it:
            it.req.cancel()

    def pause(self, did):
        it = self.live.get(did)
        if it:
            it.req.pause()

    def resume(self, did):
        it = self.live.get(did)
        if it:
            it.req.resume()

    def remove(self, did):
        it = self.live.pop(did, None)
        if it and it.state == "in_progress":
            it.req.cancel()
        if did >= 0:
            self.db.run("DELETE FROM downloads WHERE id=?", (did,))
        self.changed.emit()

    def clear_finished(self):
        for did in [d for d, i in self.live.items() if i.state != "in_progress"]:
            self.live.pop(did, None)
        self.db.run("DELETE FROM downloads WHERE state<>'in_progress'")
        self.changed.emit()

    def open_file(self, did):
        p = self._path_of(did)
        if p and os.path.exists(p):
            QDesktopServices.openUrl(QUrl.fromLocalFile(p))
            return True
        return False

    def show_in_folder(self, path):
        try:
            if not path:
                return False
            if sys.platform.startswith("win") and os.path.exists(path):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            elif sys.platform == "darwin" and os.path.exists(path):
                subprocess.Popen(["open", "-R", path])
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path) or self.target_dir()))
            return True
        except Exception:
            log.exception("show in folder failed")
            return False

    def show(self, did):
        return self.show_in_folder(self._path_of(did))
