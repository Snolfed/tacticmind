"""Game launcher: the local server and the game window.

Modes:
 - default — the server and the game window (``window.py``: a native window with the system's web engine);
   closing the window ends the game,
 - ``--no-window`` — server only, with the address in the console (for interface work: ``npm run dev``).
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

from . import window
from .core import WebApp
from .server import DEFAULT_PORT, TacticMindServer


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tacticmind", description="TacticMind — chess puzzles with an AI that thinks out loud")
    parser.add_argument("--no-window", action="store_true", help=f"server only, without the window (port {DEFAULT_PORT}, for npm run dev)")
    parser.add_argument("--port", type=int, default=None, help="server port (0 = any free port)")
    args, _ = parser.parse_known_args(argv)

    if not args.no_window:
        # Before the server and the engine start: without the window there is nothing to show.
        problem = window.check()
        if problem:
            print(problem, file=sys.stderr, flush=True)
            raise SystemExit(1)
    port = args.port if args.port is not None else (DEFAULT_PORT if args.no_window else 0)

    app = WebApp()
    server = TacticMindServer(app, port)
    app.start()
    threading.Thread(target=server.serve_forever, daemon=True, name="TacticMind-http").start()
    url = server.url
    try:
        if args.no_window:
            print(f"TacticMind: {url}  (Ctrl+C to quit)", flush=True)
            while True:
                time.sleep(3600)
        else:
            print(f"TacticMind: {url}", flush=True)
            window.show(url)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        app.stop()
