"""Null Search Engine entry point:  python src/main.py   ->  http://127.0.0.1:8000  (NULL_SEARCH_PORT to change)."""
import os
import socket
import sys

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from Engine.config import LOOPBACK_HOST, Settings  # noqa: E402


def main() -> int:
    settings = Settings.from_env()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:      # fail fast with a readable message
        if s.connect_ex((LOOPBACK_HOST, settings.port)) == 0:
            print(f"Port {settings.port} is already in use. Set NULL_SEARCH_PORT to another port.", file=sys.stderr)
            return 1
    import uvicorn
    from Engine.app import create_app
    uvicorn.run(create_app(settings), host=LOOPBACK_HOST, port=settings.port, log_level="warning", access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
