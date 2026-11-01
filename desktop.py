"""Nexa desktop shell: PyWebView window (floating, frameless, always on top) + local API.

Usage:
    python desktop.py           # production: serves the built frontend (frontend/dist)
    python desktop.py --dev     # window points at the Vite dev server (npm run dev)
"""
from __future__ import annotations

import os
import sys

# The windowed .exe has no console, so sys.stdout / sys.stderr are None. Libraries that write
# to them (tqdm progress bars during the Whisper model download, click, uvicorn) would crash.
# This must run before those libraries are imported.
for _name in ("stdout", "stderr"):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))
if getattr(sys, "frozen", False):
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

import argparse  # noqa: E402
import logging  # noqa: E402
import logging.handlers  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import uvicorn  # noqa: E402
import webview  # noqa: E402

from backend.config import APP_DIR, ENV_FILE, FRONTEND_DIST, FROZEN, Settings  # noqa: E402
from backend.main import create_app  # noqa: E402

DEV_API_PORT = 8765
DEV_UI_URL = "http://localhost:5173/"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def _setup_logging() -> None:
    """Console logging when run from source; a small rotating nexa.log when running as Nexa.exe.

    The .exe has no console (sys.stderr is None), so plain logging/uvicorn would crash or
    go nowhere. The log holds status and error messages only - never questions or answers.
    """
    if not FROZEN:
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
        return
    handler = logging.handlers.RotatingFileHandler(
        APP_DIR / "nexa.log", maxBytes=512_000, backupCount=1, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)


class WindowApi:
    """Methods the React UI can call through window.pywebview.api."""

    def __init__(self) -> None:
        self._window: webview.Window | None = None

    def minimize(self) -> None:
        if self._window:
            self._window.minimize()

    def close(self) -> None:
        if self._window:
            self._window.destroy()

    def set_always_on_top(self, enabled: bool) -> None:
        if self._window:
            self._window.on_top = bool(enabled)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Nexa - AI Interview Copilot")
    parser.add_argument("--dev", action="store_true", help="use the Vite dev server for the UI")
    args = parser.parse_args()

    _setup_logging()
    log = logging.getLogger("nexa.desktop")

    if not args.dev and not FRONTEND_DIST.exists():
        log.error("Frontend files not found at %s", FRONTEND_DIST)
        print("Frontend is not built yet. Run:  cd frontend && npm install && npm run build", file=sys.stderr)
        return 1

    settings = Settings.from_env()
    if not settings.has_llm_key:
        log.warning("No GEMINI_API_KEY / GROQ_API_KEY found. Put a .env file with a key at %s", ENV_FILE)

    port = DEV_API_PORT if args.dev else _free_port()
    # log_config=None: uvicorn's default config writes to sys.stderr, which does not exist in the windowed .exe.
    config = uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning", log_config=None)
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, name="nexa-api", daemon=True).start()

    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            log.error("The local API server did not start")
            print("The local API server did not start.", file=sys.stderr)
            return 1
        time.sleep(0.05)

    api = WindowApi()
    window = webview.create_window(
        "Nexa",
        DEV_UI_URL if args.dev else f"http://127.0.0.1:{port}/",
        js_api=api,
        width=440,
        height=680,
        min_size=(360, 460),
        frameless=True,
        easy_drag=False,  # drag only by the title bar (.pywebview-drag-region) so text stays selectable
        on_top=True,
        text_select=True,
        background_color="#0e1016",
    )
    api._window = window
    window.events.closed += lambda: setattr(server, "should_exit", True)

    webview.start()
    server.should_exit = True
    time.sleep(0.3)  # let the API shut down and stop the audio stream
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
