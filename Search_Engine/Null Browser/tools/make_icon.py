"""Renders the Null Browser icon (null_browser/assets/icon.svg) to icon.png and a multi-size icon.ico.

    python tools/make_icon.py

Needs only PyQt6. The .ico holds PNG-compressed images at 16-256 px, which every Windows since Vista reads. It is used for the
window / taskbar (through the SVG), the desktop shortcut and the .exe build (build_exe.bat).
"""
import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(HERE), "null_browser", "assets")
SIZES = (16, 24, 32, 48, 64, 128, 256)

# A rounded square in the browser's violet, with a bold N. The N has a soft shadow so it stays readable on any wallpaper.
SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
<defs>
<linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#9a8bff"/><stop offset="1" stop-color="#5b3fe0"/></linearGradient>
<linearGradient id="h" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".30"/><stop offset=".6" stop-color="#fff" stop-opacity="0"/></linearGradient>
</defs>
<rect width="256" height="256" rx="58" fill="url(#g)"/>
<rect width="256" height="256" rx="58" fill="url(#h)"/>
<path d="M82 194V74l92 120V74" transform="translate(0 7)" fill="none" stroke="#1d0f6b" stroke-opacity=".28" stroke-width="30" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M82 194V74l92 120V74" fill="none" stroke="#fff" stroke-width="30" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""


def render(svg, px):
    img = QImage(px, px, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    QSvgRenderer(QByteArray(svg.encode())).render(p)
    p.end()
    return img


def png_bytes(img):
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def write_ico(path, images):
    """images: [(size, png_bytes)] -> .ico with PNG entries."""
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, data in images:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    with open(path, "wb") as f:
        f.write(head + entries + blobs)


def main():
    QGuiApplication(sys.argv)
    os.makedirs(ASSETS, exist_ok=True)
    with open(os.path.join(ASSETS, "icon.svg"), "w", encoding="utf-8") as f:
        f.write(SVG)
    pngs = [(s, png_bytes(render(SVG, s))) for s in SIZES]
    write_ico(os.path.join(ASSETS, "icon.ico"), pngs)
    with open(os.path.join(ASSETS, "icon.png"), "wb") as f:
        f.write(png_bytes(render(SVG, 512)))
    print("wrote", ", ".join(sorted(os.listdir(ASSETS))), "in", ASSETS)


if __name__ == "__main__":
    main()
