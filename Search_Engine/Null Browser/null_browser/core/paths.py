"""Filesystem locations. Everything the browser writes lives under one data directory."""
import os
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


def package_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def project_engine_dir():
    """Locate the sibling 'Null Search Engine' folder (None if not shipped)."""
    here = os.path.dirname(package_dir())          # .../Null Browser
    cand = os.path.join(os.path.dirname(here), "Null Search Engine")
    return cand if os.path.isfile(os.path.join(cand, "src", "main.py")) else None
