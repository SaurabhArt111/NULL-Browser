"""Native-feeling frameless window on Windows (what Chrome / Edge do).

The window stays frameless (our tab strip is the title bar) but is turned back into a *real* resizable top-level
window as far as Windows is concerned:

* WS_THICKFRAME / WS_CAPTION / min / max boxes are put back, so the DWM draws the shadow, the open / close / minimise /
  maximise animations, rounded corners (Windows 11) and Aero Snap, drag-to-restore from maximised, Aero Shake etc. work.
* WM_NCCALCSIZE makes the whole window our client area, and fixes the maximised rectangle so it never hides behind
  (or covers) the taskbar.
* WM_ERASEBKGND fills uncovered areas with the theme colour (only while an edge is being dragged), so dragging an edge never flashes black / white while Chromium
  catches up with the new size; WM_ENTERSIZEMOVE / WM_EXITSIZEMOVE tell the window a live resize is running so it can defer
  expensive work (bookmarks bar rebuild, page fade) until the drag ends.
* DWM is asked for rounded corners on Windows 11 (squared automatically when maximised / snapped).
* WM_NCHITTEST tells Windows which part of our own UI is "caption" (empty tab-strip space), "border" (resize edges) and,
  on Windows 11, "maximise button" (this is what makes the Snap Layouts flyout appear when hovering the button).

Everything here is a no-op on other platforms, and `MainWindow` falls back to its Qt-only edge handling when
`install()` returns False.
"""
import ctypes
import logging
import sys
from ctypes import wintypes

from PyQt6.QtCore import QAbstractNativeEventFilter, QCoreApplication

log = logging.getLogger("null.winframe")

IS_WIN = sys.platform.startswith("win")

# window messages
WM_NCCALCSIZE, WM_NCHITTEST, WM_NCMOUSEMOVE = 0x0083, 0x0084, 0x00A0
WM_NCLBUTTONDOWN, WM_NCLBUTTONUP, WM_NCMOUSELEAVE = 0x00A1, 0x00A2, 0x02A2
WM_ERASEBKGND, WM_ENTERSIZEMOVE, WM_EXITSIZEMOVE = 0x0014, 0x0231, 0x0232
# hit-test results
HTCLIENT, HTCAPTION, HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT = 1, 2, 10, 11, 12, 13, 14
HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT, HTMAXBUTTON = 15, 16, 17, 9
# styles
GWL_STYLE = -16
WS_CAPTION, WS_THICKFRAME, WS_MINIMIZEBOX, WS_MAXIMIZEBOX, WS_SYSMENU = 0x00C00000, 0x00040000, 0x00020000, 0x00010000, 0x00080000
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x0001, 0x0002, 0x0004, 0x0010, 0x0020
MONITOR_DEFAULTTONEAREST = 2
ABM_GETSTATE, ABS_AUTOHIDE = 0x4, 0x1
DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, 2
EDGE, CORNER = 6, 14                                   # resize border thickness / corner reach, in logical px


class _MARGINS(ctypes.Structure):
    _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]


class _NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


class _APPBARDATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uCallbackMessage", wintypes.UINT), ("uEdge", wintypes.UINT),
                ("rc", wintypes.RECT), ("lParam", wintypes.LPARAM)]


def _user32():
    u = ctypes.windll.user32
    u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    u.IsZoomed.argtypes = [wintypes.HWND]
    u.MonitorFromWindow.restype = wintypes.HANDLE
    u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    u.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MONITORINFO)]
    return u


def supports_snap_layouts():
    """Windows 11 (build 22000+) shows the Snap Layouts flyout over a HTMAXBUTTON area."""
    try:
        return IS_WIN and sys.getwindowsversion().build >= 22000
    except Exception:
        return False


class _Filter(QAbstractNativeEventFilter):
    """One application-wide native event filter that routes the few messages we care about to the right window.

    (Overriding `nativeEvent` on the window itself crashed PyQt6 6.11 on Windows while the native window was being
    created, so no Python runs for a window until `install()` has registered it, after the window exists.)
    """
    HANDLED = frozenset((WM_NCCALCSIZE, WM_NCHITTEST, WM_NCMOUSEMOVE, WM_NCMOUSELEAVE, WM_NCLBUTTONDOWN, WM_NCLBUTTONUP,
                         WM_ERASEBKGND, WM_ENTERSIZEMOVE, WM_EXITSIZEMOVE))

    def __init__(self):
        super().__init__()
        self.windows = {}                                  # hwnd -> MainWindow

    def nativeEventFilter(self, event_type, message):
        try:
            if not self.windows or bytes(event_type) != b"windows_generic_MSG":
                return False, 0
            m = _msg(message)
            if m.message not in self.HANDLED:
                return False, 0
            win = self.windows.get(int(m.hWnd or 0))
            if win is None:
                return False, 0
            return native_event(win, m)
        except Exception:
            log.debug("native event filter", exc_info=True)
            return False, 0


_filter = None


def registered_hwnd(window):
    if _filter is None:
        return None
    for h, w in _filter.windows.items():
        if w is window:
            return h
    return None


def _register(window, hwnd):
    global _filter
    if _filter is None:
        _filter = _Filter()
        QCoreApplication.instance().installNativeEventFilter(_filter)
    for h in [h for h, w in _filter.windows.items() if w is window]:
        _filter.windows.pop(h, None)
    _filter.windows[hwnd] = window
    window.destroyed.connect(lambda *_a, h=hwnd: _filter.windows.pop(h, None))


def install(window):
    """Give `window` (already created, frameless) the real-window styles. Returns True on success."""
    from . import enhance
    if not IS_WIN or not enhance.ENABLED or not enhance.NATIVE_FRAME:
        return False
    try:
        u = _user32()
        hwnd = int(window.winId())
        _register(window, hwnd)
        style = u.GetWindowLongPtrW(hwnd, GWL_STYLE)
        style |= WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU
        u.SetWindowLongPtrW(hwnd, GWL_STYLE, style)
        # 1px of "glass" is what makes the DWM draw the drop shadow around a window without a visible frame
        margins = _MARGINS(1, 1, 1, 1)
        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(margins))
        try:                                               # Windows 11: rounded corners (ignored by Windows 10)
            pref = ctypes.c_int(DWMWCP_ROUND)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(pref), ctypes.sizeof(pref))
        except Exception:
            log.debug("corner preference", exc_info=True)
        u.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        return True
    except Exception:
        log.warning("native frame set-up failed; using the Qt fallback", exc_info=True)
        return False


def set_background(window, color):
    """Colour (QColor) painted into any part of the window Qt has not drawn yet (live resize, first show)."""
    if not IS_WIN or registered_hwnd(window) is None:
        return
    try:
        gdi = ctypes.windll.gdi32
        gdi.CreateSolidBrush.restype = ctypes.c_void_p
        gdi.CreateSolidBrush.argtypes = [wintypes.DWORD]
        gdi.DeleteObject.argtypes = [ctypes.c_void_p]
        brush = gdi.CreateSolidBrush(color.red() | (color.green() << 8) | (color.blue() << 16))
        old = getattr(window, "_bg_brush", None)
        window._bg_brush = brush
        if old:
            gdi.DeleteObject(old)
    except Exception:
        log.debug("set_background", exc_info=True)


def _erase_background(win, m):
    brush = getattr(win, "_bg_brush", None)
    if not brush or not getattr(win, "_live_resize", False):
        return False, 0                  # only while an edge is being dragged; at any other time Qt's own painting is left alone (no flicker)
    u = _user32()
    u.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), ctypes.c_void_p]
    u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    rc = wintypes.RECT()
    u.GetClientRect(int(m.hWnd), ctypes.byref(rc))
    u.FillRect(m.wParam, ctypes.byref(rc), brush)
    return True, 1


def _msg(message):
    return wintypes.MSG.from_address(int(message))


def _taskbar_autohides():
    try:
        data = _APPBARDATA()
        data.cbSize = ctypes.sizeof(_APPBARDATA)
        return bool(ctypes.windll.shell32.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(data)) & ABS_AUTOHIDE)
    except Exception:
        return False


def _fit_maximised(hwnd, lparam):
    """WM_NCCALCSIZE for a maximised window: use exactly the monitor's work area."""
    u = _user32()
    params = _NCCALCSIZE_PARAMS.from_address(lparam)
    mon = u.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
    if not u.GetMonitorInfoW(mon, ctypes.byref(info)):
        return
    r = params.rgrc[0]
    r.left, r.top, r.right, r.bottom = info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom
    if _taskbar_autohides():
        r.bottom -= 1                                  # leave a 1px strip so the hidden taskbar can still be summoned


def native_event(win, m):
    """Handle one message for `win`. Returns (handled, result) for the native event filter."""
    try:
        code = m.message
        if code == WM_NCCALCSIZE:
            # ask Windows, not Qt: this message arrives before Qt has noticed the window became maximised
            if m.wParam and not win.isFullScreen() and _user32().IsZoomed(int(m.hWnd)):
                _fit_maximised(int(m.hWnd), m.lParam)
            return True, 0                             # client area == whole window
        if code == WM_NCHITTEST:
            return True, _hit_test(win, m)
        if code == WM_ERASEBKGND:
            return _erase_background(win, m)
        if code == WM_ENTERSIZEMOVE:
            win.begin_live_resize()
            return False, 0                            # Qt still sees it
        if code == WM_EXITSIZEMOVE:
            win.end_live_resize()
            return False, 0
        if code == WM_NCMOUSEMOVE and m.wParam == HTMAXBUTTON:
            win.wc.set_max_state(hot=True)
        elif code == WM_NCMOUSELEAVE:
            win.wc.set_max_state(hot=False, pressed=False)
        elif code == WM_NCLBUTTONDOWN and m.wParam == HTMAXBUTTON:
            win.wc.set_max_state(hot=True, pressed=True)
            return True, 0
        elif code == WM_NCLBUTTONUP and m.wParam == HTMAXBUTTON:
            win.wc.set_max_state(hot=False, pressed=False)
            win.toggle_maximized()
            return True, 0
    except Exception:
        log.debug("native_event", exc_info=True)
    return False, 0


def edge_hit(px, py, w, h, dpr):
    """Resize-border hit test for a point `px, py` (physical pixels, relative to the window) in a `w` x `h` window.

    The border is EDGE logical px thick; the corner zones reach CORNER px along each side, so diagonals are easy to grab.
    Returns an HT* code, or None for the interior."""
    b, c = int(round(EDGE * dpr)), int(round(CORNER * dpr))
    left, right, top, bottom = px < b, px >= w - b, py < b, py >= h - b
    left = left or (px < c and (py < b or py >= h - b))
    right = right or (px >= w - c and (py < b or py >= h - b))
    top = top or (py < c and (px < b or px >= w - b))
    bottom = bottom or (py >= h - c and (px < b or px >= w - b))
    if top and left:
        return HTTOPLEFT
    if top and right:
        return HTTOPRIGHT
    if bottom and left:
        return HTBOTTOMLEFT
    if bottom and right:
        return HTBOTTOMRIGHT
    if left:
        return HTLEFT
    if right:
        return HTRIGHT
    if top:
        return HTTOP
    if bottom:
        return HTBOTTOM
    return None


def _hit_test(win, m):
    from PyQt6.QtCore import QPoint
    u = _user32()
    lp = m.lParam
    x = ctypes.c_short(lp & 0xFFFF).value
    y = ctypes.c_short((lp >> 16) & 0xFFFF).value
    rect = wintypes.RECT()
    u.GetWindowRect(int(m.hWnd), ctypes.byref(rect))
    px, py = x - rect.left, y - rect.top                       # physical pixels inside the window
    w, h = rect.right - rect.left, rect.bottom - rect.top
    dpr = max(1.0, win.devicePixelRatioF())

    if not (win.isMaximized() or win.isFullScreen()):
        hit = edge_hit(px, py, w, h, dpr)
        if hit is not None:
            return hit

    widget = win.childAt(QPoint(int(px / dpr), int(py / dpr)))
    if widget is None:
        return HTCLIENT
    if win.snap_layouts and widget is win.wc.max_btn:
        return HTMAXBUTTON
    if widget is win.strip:
        return HTCAPTION                                        # empty tab-strip space drags / double-click maximises natively
    return HTCLIENT
