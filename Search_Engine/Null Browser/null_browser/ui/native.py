"""Small OS-level touches: taskbar identity and dark title bars on Windows."""
import logging
import sys

log = logging.getLogger("null.native")


def set_app_user_model_id(app_id):
    """Gives the process its own taskbar icon/group and attributes toast notifications to us."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        except Exception:
            log.debug("AppUserModelID failed", exc_info=True)


def set_dark_titlebar(widget, dark):
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):                      # DWMWA_USE_IMMERSIVE_DARK_MODE (new / old id)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        log.debug("dark titlebar failed", exc_info=True)
