"""Runs / monitors the bundled Null Search Engine (FastAPI) so the browser is linked to it.

 * start()  launches `python Null Search Engine/src/main.py` as a child process
 * state   stopped | starting | running | external | unavailable | error
 * The browser keeps working with any state - search falls back to Google.
"""
import json
import logging
import os
import sys

from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

from . import paths

log = logging.getLogger("null.engine")


class EngineService(QObject):
    state_changed = pyqtSignal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.state = "stopped"
        self.detail = ""
        self.stats = {}
        self.proc = None
        self.nam = QNetworkAccessManager(self)
        self.timer = QTimer(self, interval=4000)
        self.timer.timeout.connect(self.check)
        self.engine_dir = paths.project_engine_dir()
        self._tail = []

    @property
    def port(self):
        return int(self.settings.get("null_search_port") or 8000)

    def _set(self, state, detail=""):
        if state != self.state or detail != self.detail:
            self.state, self.detail = state, detail
            self.state_changed.emit(state)

    def start(self):
        if self.proc and self.proc.state() != QProcess.ProcessState.NotRunning:
            return
        if not self.engine_dir:
            self._set("unavailable", "The 'Null Search Engine' folder was not found next to the browser.")
            return
        self.timer.start()
        self._probe(first=True)

    def _spawn(self):
        self._set("starting", "Starting local search server…")
        self.proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("NULL_SEARCH_PORT", str(self.port))
        env.insert("PYTHONUNBUFFERED", "1")
        engine_python = os.path.join(self.engine_dir, "..", "..", ".venv", "Scripts", "python.exe")
        if sys.platform.startswith("win") and os.path.isfile(engine_python):
            executable = engine_python
        else:
            executable = sys.executable
        self.proc.setProcessEnvironment(env)
        self.proc.setWorkingDirectory(self.engine_dir)
        self.proc.readyReadStandardOutput.connect(lambda: self._read(self.proc.readAllStandardOutput()))
        self.proc.readyReadStandardError.connect(lambda: self._read(self.proc.readAllStandardError()))
        self.proc.finished.connect(self._exited)
        self._stopping = False
        self.proc.errorOccurred.connect(lambda e: None if self._stopping else log.warning("Engine process error: %s", e))
        self.proc.start(executable, ["-u", "src/main.py"])

    def _read(self, data):
        for line in bytes(data).decode("utf-8", "replace").splitlines():
            self._tail = (self._tail + [line])[-12:]
            log.info("[engine] %s", line)

    def _exited(self, code, status):
        if self.state in ("running", "starting"):
            tail = " | ".join(self._tail[-3:])
            if "No module named" in tail or "ModuleNotFoundError" in tail:
                self._set("unavailable", "Missing Python packages. Run setup_and_run.bat (or pip install -r requirements.txt).")
            else:
                self._set("error", f"Server exited (code {code}). {tail}")
        self.proc = None

    def stop(self):
        self._stopping = True                               # Qt reports our own terminate() as ProcessError.Crashed
        self.timer.stop()
        if self.proc and self.proc.state() != QProcess.ProcessState.NotRunning:
            self.proc.terminate()
            if not self.proc.waitForFinished(1500):
                self.proc.kill()
        self.proc = None
        self._set("stopped")

    def restart(self):
        self.stop()
        self.start()

    def check(self):
        self._probe()

    def _probe(self, first=False):
        req = QNetworkRequest(QUrl(f"http://127.0.0.1:{self.port}/api/stats"))
        req.setTransferTimeout(1500)
        rep = self.nam.get(req)
        rep.finished.connect(lambda: self._probed(rep, first))

    def _probed(self, rep, first):
        ok = rep.error() == QNetworkReply.NetworkError.NoError
        try:
            if ok:
                try:
                    self.stats = json.loads(bytes(rep.readAll()).decode())
                except ValueError:
                    self.stats = {}
                self._set("running" if self.proc else "external", "")
            elif first and self.settings.get("autostart_null_search"):
                self._spawn()
            elif self.state == "running":
                self._set("error", "Lost connection to the local search server.")
            elif self.state not in ("starting", "unavailable", "error"):
                self._set("stopped")
        finally:
            rep.deleteLater()

    def info(self):
        return {"state": self.state, "detail": self.detail, "port": self.port,
                "available": bool(self.engine_dir), "stats": self.stats,
                "url": f"http://127.0.0.1:{self.port}/"}
