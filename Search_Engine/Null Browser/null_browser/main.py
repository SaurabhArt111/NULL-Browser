"""Entry point: flags -> QApplication -> BrowserApp, with start-up crash-loop protection."""
import argparse
import json
import os
import sys
import traceback


def _parse(argv):
    ap = argparse.ArgumentParser(prog="null-browser", description="Null Browser", add_help=True)
    ap.add_argument("urls", nargs="*", help="URLs or files to open")
    ap.add_argument("--private", "--incognito", "--inprivate", action="store_true", help="open an InPrivate window")
    ap.add_argument("--safe-mode", action="store_true", help="start with ad blocking, API gate and session restore off")
    ap.add_argument("--debug", action="store_true", help="verbose logging")
    ap.add_argument("--data-dir", help="use a different profile folder")
    ap.add_argument("--selftest", metavar="OUTDIR", help="run the headless end-to-end self-test and exit")
    ap.add_argument("--new-instance", action="store_true", help="don't hand over to an already running browser")
    return ap.parse_known_args(argv)[0]


def _chromium_flags(settings_path, safe):
    """Chromium switches must be set before QApplication exists, so read settings.json directly."""
    data = {}
    try:
        with open(settings_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        pass
    flags = []
    if safe or data.get("hardware_acceleration") is False:
        flags.append("--disable-gpu")
    if (data.get("permission_defaults") or {}).get("js_optimization") == "block" and not safe:
        flags.append("--js-flags=--jitless")
    if safe:
        flags.append("--disable-extensions")
    if not safe and data.get("smooth_scrolling") is not False:
        flags.append("--enable-smooth-scrolling")          # Chromium's eased wheel / keyboard scrolling (off by default in Qt WebEngine)
    if not safe and data.get("hardware_acceleration") is not False:
        flags.append("--enable-gpu-rasterization")         # raster on the GPU: smoother scrolling and resizing on heavy pages
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        flags.append("--no-sandbox")                       # Chromium refuses to run as root otherwise
    existing = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (existing + " " + " ".join(flags)).strip()
    port = int(data.get("remote_debugging_port") or 0)
    if port and "QTWEBENGINE_REMOTE_DEBUGGING" not in os.environ:
        os.environ["QTWEBENGINE_REMOTE_DEBUGGING"] = str(port)


def main(argv=None):
    args = _parse(sys.argv[1:] if argv is None else argv)

    from PyQt6.QtCore import QCoreApplication, QTimer, Qt
    from . import constants as C
    from .core import paths

    QCoreApplication.setApplicationName(C.APP_NAME)
    QCoreApplication.setOrganizationName(C.ORG_NAME)
    QCoreApplication.setApplicationVersion(C.VERSION)
    if args.data_dir:
        paths.set_data_dir(args.data_dir)
    _chromium_flags(os.path.join(paths.data_dir(), "settings.json"), args.safe_mode)

    from .web.scheme import register_scheme
    register_scheme()                                       # must precede QApplication

    from PyQt6 import QtWebEngineWidgets  # noqa: F401  (must be imported before QApplication is created)
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from .ui import native
    native.set_app_user_model_id(f"{C.ORG_NAME}.{C.APP_ID}.3")
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp = QApplication(sys.argv[:1])
    for eff in (Qt.UIEffect.UI_AnimateMenu, Qt.UIEffect.UI_FadeMenu, Qt.UIEffect.UI_AnimateCombo,
                Qt.UIEffect.UI_AnimateTooltip, Qt.UIEffect.UI_FadeTooltip):
        qapp.setEffectEnabled(eff, True)                    # menus, combo lists and tooltips ease in instead of popping
    qapp.setApplicationDisplayName(C.APP_NAME)
    qapp.setDesktopFileName("null-browser")

    from .core import crash
    crash.setup_logging(debug=args.debug)
    log = crash.log
    log.info("Starting Null Browser %s (pid %s)", C.VERSION, os.getpid())

    from .app import BrowserApp, forward_to_running_instance

    urls = [u if "://" in u or u.startswith(("about:", "data:")) else _to_url(u) for u in args.urls]
    if not args.new_instance and not args.safe_mode and not args.selftest and forward_to_running_instance(urls, args.private):
        log.info("Handed over to the running instance")
        return 0

    failures = crash.register_startup()
    safe = args.safe_mode
    if failures >= 3 and not safe:
        log.error("%d consecutive failed starts: entering safe mode", failures)
        safe = True

    from .ui import icons
    qapp.setWindowIcon(icons.app_icon())
    try:
        app = BrowserApp(qapp, safe_mode=safe)
        app.start(urls, private=args.private)
    except Exception:
        text = traceback.format_exc()
        log.critical("Fatal start-up error:\n%s", text)
        QMessageBox.critical(None, "Null Browser could not start",
                             f"Something went wrong while starting.\n\nDetails were saved to:\n{paths.logs_dir()}\n\nThe next launch will use safe mode.\n\n{text[-800:]}")
        return 1
    if args.selftest:
        from . import selftest
        QTimer.singleShot(1500, lambda: selftest.run(app, args.selftest))
    code = qapp.exec()
    log.info("Exited with code %s", code)
    return code


def _to_url(path):
    from PyQt6.QtCore import QUrl
    if os.path.exists(path):
        return QUrl.fromLocalFile(os.path.abspath(path)).toString()
    return path


if __name__ == "__main__":
    sys.exit(main())
