"""Filesystem locations. Everything the browser writes lives under one data directory."""
import os
import sys
from PyQt6.QtCore import QStandardPaths

_override = None


def set_data_dir(path):
    global _override
    _override = os.path.abspath(path)


def data_dir():
    if _override:
        base = _override
    else:
        base = os.environ.get("NULL_BROWSER_DATA") or QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation)
        if not base:
            base = os.path.join(os.path.expanduser("~"), ".null_browser")
    os.makedirs(base, exist_ok=True)
    return base


def sub(*parts):
    """A directory below the data folder (created on demand), e.g. sub('profile', 'cache')."""
    d = os.path.join(data_dir(), *parts)
    os.makedirs(d, exist_ok=True)
    return d


def logs_dir():
    d = os.path.join(data_dir(), "logs")
    os.makedirs(d, exist_ok=True)
    return d


def downloads_dir():
    d = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
    return d or os.path.join(os.path.expanduser("~"), "Downloads")


def is_frozen():
    """True in a PyInstaller build (NullBrowser.exe)."""
    return bool(getattr(sys, "frozen", False))


def bundle_dir():
    """Folder that holds the bundled data files in a PyInstaller build (None when running from source)."""
    return getattr(sys, "_MEIPASS", None) if is_frozen() else None


def package_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def project_engine_dir():
    """Locate the 'Null Search Engine' folder: next to the browser in the project, or inside the .exe bundle (None if not shipped)."""
    b = bundle_dir()
    if b:
        cand = os.path.join(b, "Search_Engine", "Null Search Engine")
    else:
        here = os.path.dirname(package_dir())          # .../Null Browser
        cand = os.path.join(os.path.dirname(here), "Null Search Engine")
    return cand if os.path.isfile(os.path.join(cand, "src", "main.py")) else None
