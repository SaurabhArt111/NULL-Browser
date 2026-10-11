"""Launcher: `python main.py` (kept at the project root so it works from any folder)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from null_browser.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
