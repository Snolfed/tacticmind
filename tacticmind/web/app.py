"""Browser interface launcher: server + window.

Modes:
 - default — server and app window: Chrome / Edge / Chromium in ``--app`` mode (a separate window without
   browser bars), and when none of them is available — a regular tab in the default browser,
 - ``--server`` — server only (this is how the Tauri app runs it): prints ``TACTICMIND_URL=…``
   and runs until the parent process closes standard input,
 - ``--no-window`` — server only, with the address in the console (e.g. for interface work: ``npm run dev``).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from ..rating.profile import data_dir
from .core import WebApp
from .server import DEFAULT_PORT, TacticMindServer

WINDOW_SIZE = (1360, 860)
#: After the last tab is closed (regular browser) the server shuts down after this many seconds.
IDLE_EXIT = 20.0
#: If no tab connects at all, we exit after this many seconds.
FIRST_CONNECT = 120.0


def _candidates() -> list[str]:
    """Browsers with an app mode (``--app``), best first."""
    names = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "microsoft-edge-stable", "brave-browser", "vivaldi"]
    found = [path for name in names if (path := shutil.which(name))]
    if sys.platform == "win32":
        roots = [os.environ.get(var, "") for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        for root in roots:
            if not root:
                continue
            for relative in (r"Google\Chrome\Application\chrome.exe", r"Microsoft\Edge\Application\msedge.exe", r"BraveSoftware\Brave-Browser\Application\brave.exe"):
                path = Path(root) / relative
                if path.is_file():
                    found.append(str(path))
    elif sys.platform == "darwin":
        for app in ("Google Chrome", "Microsoft Edge", "Chromium", "Brave Browser"):
            path = Path("/Applications") / f"{app}.app" / "Contents" / "MacOS" / app
            if path.is_file():
                found.append(str(path))
    return found


def open_app_window(url: str) -> subprocess.Popen[bytes] | None:
    """App window in Chrome/Edge (``--app``) with a separate profile — the process lives as long as the window."""
    custom = os.environ.get("TACTICMIND_BROWSER")
    browsers = [custom] if custom else _candidates()
    profile = data_dir() / "window"
    for exe in browsers:
        args = [
            exe,
            f"--app={url}",
            f"--user-data-dir={profile}",
            f"--window-size={WINDOW_SIZE[0]},{WINDOW_SIZE[1]}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate",
        ]
        if sys.platform.startswith("linux"):
            args.append("--class=tacticmind")  # window class — matches the .desktop shortcut (StartupWMClass)
        try:
            return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            continue
    return None


def _wait_for_parent() -> None:
    """``--server`` mode: exit when the parent process (Tauri) closes our standard input."""
    try:
        while sys.stdin.read(1024):
            pass
    except (OSError, ValueError):
        while True:
            time.sleep(3600)


def _wait_for_tabs(app: WebApp, idle_exit: float = IDLE_EXIT, seen: bool = False) -> None:
    """Keep running while any tab is connected (and for ``idle_exit`` s after the last one disconnects)."""
    started = time.monotonic()
    while True:
        time.sleep(0.5)
        if app.clients:
            seen = True
            continue
        idle = time.monotonic() - app.last_client
        if (seen and idle > idle_exit) or (not seen and time.monotonic() - started > FIRST_CONNECT):
            return


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tacticmind", description="TacticMind — browser interface")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="server port (0 = any free port)")
    parser.add_argument("--server", action="store_true", help="server only, for the Tauri app")
    parser.add_argument("--no-window", action="store_true", help="server only, without opening a window")
    parser.add_argument("--browser", action="store_true", help="a regular tab in the default browser instead of an app window")
    args, _ = parser.parse_known_args(argv)

    app = WebApp()
    server = TacticMindServer(app, args.port)
    app.start()
    threading.Thread(target=server.serve_forever, daemon=True, name="TacticMind-http").start()
    url = server.url
    try:
        if args.server:
            print(f"TACTICMIND_URL={url}", flush=True)
            _wait_for_parent()
        elif args.no_window:
            print(f"TacticMind: {url}  (Ctrl+C to quit)", flush=True)
            while True:
                time.sleep(3600)
        else:
            window = None if args.browser else open_app_window(url)
            if window is not None:
                print(f"TacticMind: {url}", flush=True)
                window.wait()
                # If the game window was already open, the new browser process hands over to the old one and exits
                # immediately — then the server keeps running while any tab is connected.
                _wait_for_tabs(app, idle_exit=3.0, seen=True)
            else:
                print(f"TacticMind: {url}  (opening in the browser)", flush=True)
                webbrowser.open(url)
                _wait_for_tabs(app)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        app.stop()
