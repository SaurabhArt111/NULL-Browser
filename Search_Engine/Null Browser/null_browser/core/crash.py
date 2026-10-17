"""Self error handling: logging, crash capture, safe slots, restart helper.

Nothing in the browser should be able to take the whole app down silently:
 * unhandled Python exceptions (main thread, worker threads, unraisables) are
   logged, remembered for null://logs and surfaced as a toast;
 * native crashes dump a traceback via faulthandler;
 * Qt/Chromium warnings are routed into the same log;
 * a start-up crash-loop detector boots into safe mode after repeated failures.
"""
import collections
import faulthandler
import functools
import logging
import logging.handlers
import os
import sys
import threading
import time
import traceback

from PyQt6.QtCore import QObject, pyqtSignal, QtMsgType, qInstallMessageHandler, QProcess

from . import paths

log = logging.getLogger("null")
RING = collections.deque(maxlen=1500)       # recent log lines for null://logs
ERRORS = collections.deque(maxlen=200)      # recent exceptions for null://logs


class _RingHandler(logging.Handler):
    def emit(self, record):
        try:
            RING.append({"t": record.created, "level": record.levelname,
                         "name": record.name, "msg": self.format(record)})
        except Exception:
            pass


class ErrorBus(QObject):
    """Qt signal hub so any thread can report a problem to the UI."""
    error = pyqtSignal(str)          # short human readable message
    too_many = pyqtSignal()          # error storm detected


bus = None
_fault_file = None
_recent = collections.deque(maxlen=8)


def setup_logging(debug=False):
    global bus, _fault_file
    bus = ErrorBus()
    root = logging.getLogger("null")
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        fh = logging.handlers.RotatingFileHandler(
            os.path.join(paths.logs_dir(), "null-browser.log"), maxBytes=1_000_000,
            backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass
    rh = _RingHandler()
    rh.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(rh)
    if debug or sys.stderr:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        root.addHandler(sh)

    try:                                   # native crash dump
        _fault_file = open(os.path.join(paths.logs_dir(), "native-crash.log"), "a", buffering=1)
        faulthandler.enable(_fault_file, all_threads=True)
    except Exception:
        pass

    sys.excepthook = _excepthook
    threading.excepthook = lambda a: _excepthook(a.exc_type, a.exc_value, a.exc_traceback)
    sys.unraisablehook = lambda u: log.warning("Unraisable: %s %s", u.err_msg, u.exc_value)
    qInstallMessageHandler(_qt_message)


def _excepthook(etype, value, tb):
    if issubclass(etype, KeyboardInterrupt):
        sys.__excepthook__(etype, value, tb)
        return
    text = "".join(traceback.format_exception(etype, value, tb))
    log.error("Unhandled exception:\n%s", text)
    ERRORS.append({"t": time.time(), "title": f"{etype.__name__}: {value}", "trace": text})
    now = time.time()
    _recent.append(now)
    try:
        if bus:
            bus.error.emit(f"{etype.__name__}: {value}")
            if len(_recent) >= 6 and now - _recent[0] < 10:
                _recent.clear()
                bus.too_many.emit()
    except Exception:
        pass


_NOISE = ("QRhiGles2", "Failed to create RHI", "dbus", "GpuInfo", "SharedImageManager",
          "Fontconfig", "libpng warning", "propagateSizeHints", "QFont::", "GPU process")


def _qt_message(mode, ctx, msg):
    if any(n in msg for n in _NOISE):
        return
    lvl = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO,
           QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
           QtMsgType.QtFatalMsg: logging.CRITICAL}.get(mode, logging.INFO)
    logging.getLogger("null.qt").log(lvl, msg)


def guarded(func=None, *, default=None, quiet=False):
    """Decorator: log + report exceptions instead of letting them escape a Qt slot."""
    def deco(f):
        @functools.wraps(f)
        def wrapper(*a, **kw):
            try:
                return f(*a, **kw)
            except Exception:                                   # noqa: BLE001
                etype, value, tb = sys.exc_info()
                if quiet:
                    log.debug("quiet error in %s", f.__name__, exc_info=True)
                else:
                    _excepthook(etype, value, tb)
                return default
        return wrapper
    return deco(func) if func else deco


# ---- start-up crash loop detection ------------------------------------------------
def _counter_file():
    return os.path.join(paths.data_dir(), "startup-failures.txt")


def register_startup():
    """Returns the number of consecutive failed starts (including this one)."""
    n = 0
    try:
        with open(_counter_file()) as f:
            n = int(f.read().strip() or 0)
    except (OSError, ValueError):
        pass
    n += 1
    try:
        with open(_counter_file(), "w") as f:
            f.write(str(n))
    except OSError:
        pass
    return n


def mark_startup_ok():
    try:
        os.remove(_counter_file())
    except OSError:
        pass


def restart_app(extra_args=None):
    """Start a fresh copy of the browser (detached). Works for `python -m null_browser`, run.py and frozen builds.

    The new process gets `--wait-pid=<this pid>` and waits (up to a few seconds) until this one has really exited, so the
    single-instance check, the data folder lock and the local search port are free when it starts."""
    skip = ("--safe-mode", "--selftest", "--delay", "--wait-pid")
    rest = [a for a in sys.argv[1:] if not a.startswith(skip)] + [f"--wait-pid={os.getpid()}"] + list(extra_args or [])
    if getattr(sys, "frozen", False):
        program, args, cwd = sys.executable, rest, ""
    else:
        program, args = sys.executable, ["-m", "null_browser"] + rest
        cwd = os.path.dirname(paths.package_dir())
    log.info("Restarting: %s %s (cwd=%s)", program, args, cwd)
    QProcess.startDetached(program, args, cwd)


def wait_for_pid(pid, timeout=10.0):
    """Block until process `pid` has exited (or `timeout` seconds pass). Used by a restarted copy."""
    deadline = time.time() + timeout
    if sys.platform.startswith("win"):
        import ctypes
        SYNCHRONIZE = 0x00100000
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = ctypes.c_void_p
        h = k32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if not h:
            return True                                   # already gone
        try:
            k32.WaitForSingleObject(ctypes.c_void_p(h), int(max(0.0, deadline - time.time()) * 1000))
        finally:
            k32.CloseHandle(ctypes.c_void_p(h))
        return True
    while time.time() < deadline:
        try:
            os.kill(int(pid), 0)
        except OSError:
            return True
        time.sleep(0.05)
    return False
