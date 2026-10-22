"""Launcher: `python main.py` (kept at the project root so it works from any folder)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

BLOCKED_HELP = """Windows refused to load one of the Qt files Null Browser needs:

    {error}

This is a Windows security policy (Smart App Control, Windows Defender Application Control / AppLocker, or a security product),
not a bug in Null Browser. It decided that a Qt library inside your Python environment may not run.

What to try, in this order:
 1. Open Event Viewer > Applications and Services Logs > Microsoft > Windows > CodeIntegrity > Operational (or AppLocker).
    The newest "blocked" entry names the exact file and the policy. That tells you who to ask or what to allow.
 2. If this is a school / work computer, the policy belongs to your administrator: ask them to allow the Python environment folder
    (the venv that contains PyQt6) or to run Null Browser from an allowed location.
 3. On a personal Windows 11 PC with Smart App Control, a freshly installed PyQt6 can be blocked until Microsoft has seen it. Go back to
    the PyQt6 version that worked before: pip install PyQt6==<old version> PyQt6-Qt6==<old version> PyQt6-WebEngine==<old version> PyQt6-WebEngine-Qt6==<old version>
    (`pip list` in the old environment shows the numbers). Turning Smart App Control off is also possible, but on many Windows 11
    versions it cannot be turned back on without resetting Windows.
 4. Windows Security > Protection history shows whether Defender itself blocked the file; restore / allow it there.

Quick try: double-click fix_qt_blocked.bat. It installs Qt into your user profile using widely used PyQt6 releases and, if Windows
still blocks it, prints which file and policy did.

Details: docs/WINDOWS_BLOCKED.md
"""


def _explain_block(err):
    text = BLOCKED_HELP.format(error=str(err).strip())
    try:
        sys.stderr.write("\n" + text + "\n")
    except Exception:
        pass
    try:                                                    # no Qt available to show a dialog, so use the plain Windows one
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "Null Browser could not start", 0x10)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        from null_browser.main import main
        code = main()
    except ImportError as e:
        msg = str(e).lower()
        if "dll load failed" in msg and ("application control" in msg or "blocked" in msg or "policy" in msg):
            _explain_block(e)
            raise SystemExit(3)
        raise
    raise SystemExit(code)
