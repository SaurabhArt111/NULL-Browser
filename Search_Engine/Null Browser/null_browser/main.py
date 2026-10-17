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
    ap.add_argument("--enhanced", action="store_true", help="turn the window / animation enhancements back on after they were auto-disabled")
    ap.add_argument("--no-native-frame", action="store_true", help="keep the animations but skip the Windows native window frame (snap / resize)")
    ap.add_argument("--classic", action="store_true", help="run without any of the newer window / animation code (diagnostics)")
    ap.add_argument("--exit-after", type=float, default=0, help=argparse.SUPPRESS)       # diagnostics: quit cleanly after N seconds
    ap.add_argument("--wait-pid", type=int, default=0, help=argparse.SUPPRESS)           # restart: wait for the old process to exit first
    ap.add_argument("--delay", type=float, default=0, help=argparse.SUPPRESS)            # legacy restart argument (seconds to wait)
    ap.add_argument("--new-instance", action="store_true", help="don't hand over to an already running browser")
    return ap.parse_known_args(argv)[0]


def _chromium_flags(settings_path, safe, enhanced=True, debug=False):
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
    if enhanced and not safe and data.get("smooth_scrolling") is not False:
        flags.append("--enable-smooth-scrolling")          # Chromium's eased wheel / keyboard scrolling (off by default in Qt WebEngine)
    if not debug:
        flags.append("--log-level=3")                      # only fatal Chromium messages: hides harmless GPU-fallback "ERROR"s (e.g. GLES3 -> GLES2)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        flags.append("--no-sandbox")                       # Chromium refuses to run as root otherwise
    existing = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (existing + " " + " ".join(flags)).strip()
    port = int(data.get("remote_debugging_port") or 0)
    if port and "QTWEBENGINE_REMOTE_DEBUGGING" not in os.environ:
        os.environ["QTWEBENGINE_REMOTE_DEBUGGING"] = str(port)


def _enhancements(args):
    """Decide whether the optional window / animation enhancements run, and survive a crash they might have caused."""
    from .core import paths
    from .ui import enhance
    off = os.path.join(paths.data_dir(), "enhancements.off")
    counter = os.path.join(paths.data_dir(), "startup-failures.txt")
    if args.classic:
        return False
    if args.enhanced:
        try:
            os.remove(off)
        except OSError:
            pass
        return True
    if args.safe_mode:
        return False
    try:
        with open(counter) as f:
            failed = int(f.read().strip() or 0)
    except (OSError, ValueError):
        failed = 0
    marker_rev, remaining = None, 0
    try:
        with open(off) as f:
            body = f.read()
        marker_rev = int(body.split("rev=", 1)[1].split()[0]) if "rev=" in body else None
        remaining = int(body.split("remaining=", 1)[1].split()[0]) if "remaining=" in body else 3
    except (OSError, ValueError, IndexError):
        pass
    if marker_rev is not None and marker_rev != enhance.REV:      # written by an older revision: that bug is fixed, try again
        try:
            os.remove(off)
        except OSError:
            pass
        marker_rev = None
    if failed >= 1 and marker_rev is None:
        # The last start never finished. Don't know why, but the enhancements are the newest code: turn them off for the next
        # few starts (not forever), forget the failures (so we don't drop into safe mode for something they caused).
        try:
            with open(off, "w") as f:
                f.write(f"rev={enhance.REV}\nremaining=3\nswitched off automatically after a start that did not finish\n")
            os.remove(counter)
        except OSError:
            pass
        enhance.AUTO_DISABLED = True
        return False
    if marker_rev is not None:
        # Count this start down; when it reaches zero the effects get a fresh chance on the start after.
        try:
            if remaining <= 1:
                os.remove(off)
            else:
                with open(off, "w") as f:
                    f.write(f"rev={enhance.REV}\nremaining={remaining - 1}\nswitched off automatically after a start that did not finish\n")
        except OSError:
            pass
        return False
    return True


def main(argv=None):
    args = _parse(sys.argv[1:] if argv is None else argv)

    from PyQt6.QtCore import QCoreApplication, QTimer, Qt
    from . import constants as C
    from .core import paths

    if args.wait_pid:
        from .core import crash as _crash
        _crash.wait_for_pid(args.wait_pid, 10.0)            # restarted by the previous copy: let it finish cleaning up first
    elif args.delay > 0:
        import time
        time.sleep(min(args.delay, 5.0))

    QCoreApplication.setApplicationName(C.APP_NAME)
    QCoreApplication.setOrganizationName(C.ORG_NAME)
    QCoreApplication.setApplicationVersion(C.VERSION)
    if args.data_dir:
        paths.set_data_dir(args.data_dir)
    from .ui import enhance
    enhance.ENABLED = _enhancements(args)
    enhance.NATIVE_FRAME = not args.no_native_frame
    _chromium_flags(os.path.join(paths.data_dir(), "settings.json"), args.safe_mode, enhance.ENABLED, args.debug)

    from .web.scheme import register_scheme
    register_scheme()                                       # must precede QApplication

    from PyQt6 import QtWebEngineWidgets  # noqa: F401  (must be imported before QApplication is created)
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from .ui import native
    native.set_app_user_model_id(f"{C.ORG_NAME}.{C.APP_ID}.3")
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp = QApplication(sys.argv[:1])
    if enhance.ENABLED:
        for eff in (Qt.UIEffect.UI_AnimateMenu, Qt.UIEffect.UI_FadeMenu, Qt.UIEffect.UI_AnimateCombo,
                    Qt.UIEffect.UI_AnimateTooltip, Qt.UIEffect.UI_FadeTooltip):
            qapp.setEffectEnabled(eff, True)                # menus, combo lists and tooltips ease in instead of popping
    qapp.setApplicationDisplayName(C.APP_NAME)
    qapp.setDesktopFileName("null-browser")

    from .core import crash
    crash.setup_logging(debug=args.debug)
    log = crash.log
    log.info("Starting Null Browser %s (pid %s)", C.VERSION, os.getpid())
    log.info("Data folder: %s", paths.data_dir())
    log.info("Window enhancements: %s", "on" if enhance.ENABLED else ("OFF (previous start failed; use --enhanced to retry)" if enhance.AUTO_DISABLED else "off"))

    from .app import BrowserApp, forward_to_running_instance

    urls = [u if "://" in u or u.startswith(("about:", "data:")) else _to_url(u) for u in args.urls]
    if not args.new_instance and not args.safe_mode and not args.selftest and forward_to_running_instance(urls, args.private):
        log.info("Handed over to the running instance")
        return 0

    log.info("Start-up check passed (no running instance to hand over to)")
    failures = crash.register_startup()
    safe = args.safe_mode
    if failures >= 3 and not safe:
        log.error("%d consecutive failed starts: entering safe mode", failures)
        safe = True

    from .ui import icons
    qapp.setWindowIcon(icons.app_icon())
    try:
        log.info("Creating the browser (safe mode: %s)", safe)
        app = BrowserApp(qapp, safe_mode=safe)
        log.info("Browser object ready; opening windows")
        app.start(urls, private=args.private)
        log.info("Windows opened: %d", len(app.windows))
        if enhance.AUTO_DISABLED and app.windows:
            app.windows[0].add_infobar("The last start didn't finish, so the new window effects (native snap / resize, animations) were switched off. "
                                       "Start with --enhanced to try them again.", [("Dismiss", lambda: None)])
    except Exception:
        text = traceback.format_exc()
        log.critical("Fatal start-up error:\n%s", text)
        QMessageBox.critical(None, "Null Browser could not start",
                             f"Something went wrong while starting.\n\nDetails were saved to:\n{paths.logs_dir()}\n\nThe next launch will use safe mode.\n\n{text[-800:]}")
        return 1
    if args.selftest:
        from . import selftest
        QTimer.singleShot(1500, lambda: selftest.run(app, args.selftest))
    if args.exit_after > 0:
        QTimer.singleShot(int(args.exit_after * 1000), qapp.quit)
    log.info("Entering the event loop")
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
