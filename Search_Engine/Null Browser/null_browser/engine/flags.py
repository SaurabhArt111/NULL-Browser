"""Chromium command-line switches: the single place they are decided.

Switches must be in the environment before `QApplication` exists, so settings.json is read directly. Every switch here has a
reason; nothing is added "just in case".
"""
import json
import os
import sys


def build(settings_path, safe=False, enhanced=True, debug=False):
    """Return the list of switches for this start."""
    data = {}
    try:
        with open(settings_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        pass
    flags = []
    gpu = not (safe or data.get("hardware_acceleration") is False)
    if not gpu:
        flags.append("--disable-gpu")
    else:
        flags.append("--enable-gpu-rasterization")          # page tiles are drawn on the GPU: smoother scrolling and less CPU on heavy feeds
    if (data.get("permission_defaults") or {}).get("js_optimization") == "block" and not safe:
        flags.append("--js-flags=--jitless")
    if safe:
        flags.append("--disable-extensions")
    if enhanced and not safe and data.get("smooth_scrolling") is not False:
        flags.append("--enable-smooth-scrolling")           # Chromium's eased wheel / keyboard scrolling (off by default in Qt WebEngine)
    if sys.platform == "win32" and not safe:
        # Chromium on Windows works out which windows are hidden behind others and stops / restarts painting them; with a frameless
        # window that shows up as flashes of the page background while switching tabs, resizing or snapping.
        flags.append("--disable-features=CalculateNativeWinOcclusion")
    if not debug:
        flags.append("--log-level=3")                       # only fatal Chromium messages (hides harmless GPU-fallback "ERROR"s)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        flags.append("--no-sandbox")                        # Chromium refuses to run as root otherwise
    return flags, data


def apply(settings_path, safe=False, enhanced=True, debug=False):
    flags, data = build(settings_path, safe, enhanced, debug)
    existing = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (existing + " " + " ".join(flags)).strip()
    port = int(data.get("remote_debugging_port") or 0)
    if port and "QTWEBENGINE_REMOTE_DEBUGGING" not in os.environ:
        os.environ["QTWEBENGINE_REMOTE_DEBUGGING"] = str(port)
    return flags
