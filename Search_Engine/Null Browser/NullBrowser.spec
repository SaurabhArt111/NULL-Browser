# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for Null Browser (what build_exe.bat runs).  Result: dist/NullBrowser/NullBrowser.exe  (a folder, not one file).

Why a folder ("onedir") and not a single .exe: a one-file build unpacks itself into a temp folder on every start (slow, and exactly
what antivirus and Windows application-control policies dislike). The folder starts in about a second and can be zipped / copied.
UPX is off for the same reason: packed executables look suspicious to security software.
"""
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files

HERE = os.path.abspath(SPECPATH)                                    # .../Search_Engine/Null Browser
ENGINE = os.path.normpath(os.path.join(HERE, "..", "Null Search Engine"))
PKG = os.path.join(HERE, "null_browser")
ICON = os.path.join(PKG, "assets", "icon.ico")


def tree(base, dest_root, skip_dirs=("__pycache__", "tests", ".pytest_cache"), skip_suffix=(".pyc", ".pyo", "-shm", "-wal", ".gitkeep"), py=True):
    """(source file, folder inside the bundle) for every file below `base`."""
    out = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for name in files:
            if name.endswith(skip_suffix) or (not py and name.endswith(".py")):
                continue
            rel = os.path.relpath(root, base)
            out.append((os.path.join(root, name), os.path.normpath(os.path.join(dest_root, rel))))
    return out


datas = []
# The browser's own non-code files (built-in pages, filter lists, icon, the video shim) keep their place inside the package folder.
datas += tree(PKG, "null_browser", py=False)
# The search server travels as plain source: it finds its templates / static files / data next to itself, and `NullBrowser.exe --run-engine` runs it.
datas += tree(ENGINE, os.path.join("Search_Engine", "Null Search Engine"), skip_suffix=(".pyc", ".pyo", "-shm", "-wal", ".gitkeep", ".md", ".bat"))

binaries = []
hiddenimports = []
# The server's packages are only imported by the plain-source copy above, so PyInstaller cannot see them: collect them explicitly.
for name in ("uvicorn", "fastapi", "starlette", "pydantic", "pydantic_core", "anyio", "httpx", "httpcore", "h11", "jinja2", "markupsafe",
             "bs4", "soupsieve", "lxml", "certifi", "idna", "sniffio", "click", "annotated_types", "typing_extensions", "typing_inspection"):
    try:
        d, b, h = collect_all(name)
    except Exception:
        continue                                                    # not installed: the server is optional, the browser is not
    datas += d
    binaries += b
    hiddenimports += h


def engine_imports(src):
    """Every module the server's source files import (standard library included: PyInstaller cannot see into plain-source data files)."""
    import ast
    own = {n[:-3] for n in os.listdir(src) if n.endswith(".py")} | {n for n in os.listdir(src) if os.path.isdir(os.path.join(src, n))}
    found = set()
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests")]
        for name in files:
            if not name.endswith(".py"):
                continue
            try:
                tree_ = ast.parse(open(os.path.join(root, name), encoding="utf-8").read())
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree_):
                if isinstance(node, ast.Import):
                    found.update(a.name for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    found.add(node.module)
                    found.update(f"{node.module}.{a.name}" for a in node.names)
    return sorted(m for m in found if m.split(".")[0] not in own)


hiddenimports += engine_imports(os.path.join(ENGINE, "src"))
try:
    d, b, h = collect_all("tzdata")                                 # zoneinfo has no time-zone database of its own on Windows
    datas += d
    binaries += b
    hiddenimports += h
except Exception:
    pass
datas += collect_data_files("imageio_ffmpeg")                       # the bundled ffmpeg (H.264 -> VP9 for X / Reddit / Instagram / Facebook video)
hiddenimports += ["adblock", "PyQt6.QtSvg", "PyQt6.QtWebChannel", "PyQt6.QtNetwork", "PyQt6.QtTest"]

a = Analysis(
    [os.path.join(HERE, "main.py")],
    pathex=[HERE],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PySide2", "PySide6", "matplotlib", "numpy", "scipy", "pandas", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NullBrowser",
    debug=False,
    strip=False,
    upx=False,
    console=False,                                                  # no black console window; logs go to the data folder
    icon=ICON if sys.platform == "win32" else None,
    version=os.path.join(HERE, "tools", "version_info.txt") if sys.platform == "win32" else None,   # makes Task Manager say "Null Browser"
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="NullBrowser")
