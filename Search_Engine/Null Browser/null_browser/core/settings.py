"""JSON-backed user settings with change notifications and self-healing load."""
import json
import logging
import os
import time

from PyQt6.QtCore import QObject, pyqtSignal

from . import paths

log = logging.getLogger("null.settings")

DEFAULTS = {
    # appearance
    "theme": "system",                 # system | light | dark
    "accent": "#6c5ce7",
    "show_bookmarks_bar": True,
    "show_home_button": False,
    "homepage": "null://newtab",
    "font_size": 16,
    "min_font_size": 0,
    "default_zoom": 100,
    "web_dark_mode": False,
    "tab_hover_cards": True,
    # search
    "search_engine": "google",
    "custom_engines": [],
    "search_suggestions": True,
    "autostart_null_search": True,
    "null_search_port": 8000,
    # startup
    "startup_mode": "newtab",          # newtab | continue | urls
    "startup_urls": [],
    # privacy
    "adblock": True,
    "block_trackers": True,
    "send_dnt": True,
    "https_first": True,
    "clear_on_exit": [],               # subset of: history, cookies, cache, downloads
    # downloads
    "download_dir": "",
    "ask_download_location": False,
    "warn_dangerous_downloads": True,
    "open_downloads_panel": True,
    # performance
    "memory_saver": True,
    "memory_saver_minutes": 15,
    "hardware_acceleration": True,
    "smooth_scrolling": True,
    # languages
    "accept_languages": "en-US,en",
    # system / developer
    "devtools_dock": "right",          # right | bottom | window
    "remote_debugging_port": 0,
    "spellcheck": False,
    "desktop_notifications": True,
    "background_running": False,
    # permissions: global defaults (feature -> value), see permissions.py
    "permission_defaults": {},
    "profile_name": "You",
    "last_version": "",
}

RESTART_KEYS = {"hardware_acceleration", "remote_debugging_port"}


class Settings(QObject):
    changed = pyqtSignal(str)

    def __init__(self, path=None):
        super().__init__()
        self.path = path or os.path.join(paths.data_dir(), "settings.json")
        self.data = {}
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise ValueError("settings root must be an object")
            self.data = loaded
        except FileNotFoundError:
            self.data = {}
        except (OSError, ValueError) as exc:
            bad = f"{self.path}.corrupt-{int(time.time())}"
            log.error("settings.json unreadable (%s); backing up to %s and using defaults", exc, bad)
            try:
                os.replace(self.path, bad)
            except OSError:
                pass
            self.data = {}

    def get(self, key, default=None):
        if key in self.data:
            return self.data[key]
        if key in DEFAULTS:
            return DEFAULTS[key]
        return default

    def set(self, key, value, silent=False):
        if key not in DEFAULTS:
            log.warning("Ignoring unknown setting %r", key)
            return False
        if self.data.get(key, DEFAULTS[key]) == value:
            return True
        self.data[key] = value
        self.save()
        if not silent:
            self.changed.emit(key)
        return True

    def reset(self, keys=None):
        for k in (keys or list(self.data.keys())):
            self.data.pop(k, None)
            self.changed.emit(k)
        self.save()

    def all(self):
        out = dict(DEFAULTS)
        out.update(self.data)
        return out

    def save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            log.exception("Could not save settings")


def peek(path=None):
    """Read settings.json with plain file IO (usable before QApplication exists)."""
    path = path or os.path.join(paths.data_dir(), "settings.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}
