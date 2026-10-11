"""Vector icon set drawn at runtime from SVG (crisp on any DPI, recolourable for light/dark)."""
from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PyQt6.QtSvg import QSvgRenderer

P = {
    "back": '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    "forward": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "reload": '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/>',
    "stop": '<path d="M6 6l12 12M18 6 6 18"/>',
    "home": '<path d="M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10"/>',
    "star": '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
    "star_fill": '<path fill="currentColor" d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
    "lock": '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    "unlock": '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 7.5-2"/>',
    "alert": '<path d="M12 3 2 20h20zM12 10v4M12 17v.5"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
    "more": '<circle cx="12" cy="5" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="19" r="1.3" fill="currentColor"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
    "download": '<path d="M12 4v11m0 0-4-4m4 4 4-4M5 20h14"/>',
    "shield": '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/>',
    "shield_off": '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6zM4 4l16 16"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1"/>',
    "history": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "bookmark": '<path d="M6 3h12v18l-6-4-6 4z"/>',
    "folder": '<path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>',
    "volume": '<path d="M4 9v6h4l5 4V5L8 9zM16 8.5a5 5 0 0 1 0 7M18.5 6a8.5 8.5 0 0 1 0 12"/>',
    "mute": '<path d="M4 9v6h4l5 4V5L8 9zM17 9l5 6M22 9l-5 6"/>',
    "pin": '<path d="M12 17v5M8 3h8l-1 6 3 4H6l3-4z"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "external": '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    "code": '<path d="m8 8-5 4 5 4M16 8l5 4-5 4M14 5l-4 14"/>',
    "eye_off": '<path d="M3 3l18 18M10.6 6.1A9.9 9.9 0 0 1 12 6c5 0 9 6 9 6a15 15 0 0 1-3.2 3.7M6.6 7.4A15 15 0 0 0 3 12s4 6 9 6a9 9 0 0 0 4-1M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
    "zoom": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5M8 11h6M11 8v6"/>',
    "print": '<path d="M7 9V3h10v6M7 17H5a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2M7 14h10v7H7z"/>',
    "file": '<path d="M7 3h7l5 5v13H7zM14 3v5h5"/>',
    "popup": '<rect x="3" y="5" width="14" height="12" rx="2"/><path d="M7 21h14V9M3 5l14 12"/>',
    "bell": '<path d="M6 9a6 6 0 0 1 12 0c0 6 2 7 2 7H4s2-1 2-7M10 20a2 2 0 0 0 4 0"/>',
    "check": '<path d="m5 12 5 5 9-10"/>',
    "up": '<path d="m6 15 6-6 6 6"/>',
    "down": '<path d="m6 9 6 6 6-6"/>',
    "fullscreen": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    "tool": '<path d="M14.7 6.3a4 4 0 0 0-5.4 5L3 17.6V21h3.4l6.3-6.3a4 4 0 0 0 5-5.4l-2.6 2.6-2.4-.6-.6-2.4z"/>',
    "null": '<rect x="3" y="3" width="18" height="18" rx="5" fill="currentColor" stroke="none"/><path d="M8.5 16.5v-9h1.6l4.9 6.3V7.5h1.5v9h-1.6L10 10.2v6.3z" fill="#fff" stroke="none"/>',
}
_cache = {}


def _svg(name, color, stroke=1.9):
    inner = P.get(name, P["globe"]).replace("currentColor", color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{inner}</svg>').encode()


def _render(svg, px):
    img = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(svg)).render(p)
    p.end()
    return img


def pixmap(name, color="#000000", size=20, dpr=2.0):
    key = (name, color, size, dpr)
    pm = _cache.get(key)
    if pm is None:
        pm = QPixmap.fromImage(_render(_svg(name, color), int(size * dpr)))
        pm.setDevicePixelRatio(dpr)
        _cache[key] = pm
    return pm


def _alpha(color, a):
    c = QColor(color)
    c.setAlphaF(a)
    return c.name(QColor.NameFormat.HexArgb)


def icon(name, color="#000000", size=20, disabled_color=None):
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Mode.Normal)
    ic.addPixmap(pixmap(name, disabled_color or _alpha(color, 0.35), size), QIcon.Mode.Disabled)
    return ic


def spinner_frames(color, size=16, steps=12):
    frames = []
    for i in range(steps):
        img = QImage(size * 2, size * 2, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(size, size)
        p.rotate(i * 360 / steps)
        pen = QPen(QColor(color), size * 0.22)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(int(-size * 0.7), int(-size * 0.7), int(size * 1.4), int(size * 1.4), 0, 270 * 16)
        p.end()
        pm = QPixmap.fromImage(img)
        pm.setDevicePixelRatio(2)
        frames.append(QIcon(pm))
    return frames


def app_icon():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="16" fill="#6c5ce7"/>'
           '<path d="M19 47V17h5.5l17 21V17H46v30h-5.5l-17-21v21z" fill="#fff"/></svg>').encode()
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(QPixmap.fromImage(_render(svg, s)))
    return ic
