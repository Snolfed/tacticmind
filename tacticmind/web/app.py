"""Start interfejsu w przeglądarce: serwer + okno.

Tryby:
 - domyślny — serwer i okno aplikacji: Chrome / Edge / Chromium w trybie ``--app`` (osobne okno bez
   pasków przeglądarki), a gdy żadnej z nich nie ma — zwykła karta w domyślnej przeglądarce,
 - ``--server`` — sam serwer (tak uruchamia go aplikacja Tauri): wypisuje ``TACTICMIND_URL=…``
   i działa, dopóki proces nadrzędny nie zamknie standardowego wejścia,
 - ``--no-window`` — sam serwer z adresem w konsoli (np. do pracy nad interfejsem: ``npm run dev``).
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
#: Po zamknięciu ostatniej karty (zwykła przeglądarka) serwer kończy pracę po tylu sekundach.
IDLE_EXIT = 20.0
#: Jeśli karta w ogóle się nie połączy, kończymy po tylu sekundach.
FIRST_CONNECT = 120.0


def _candidates() -> list[str]:
    """Przeglądarki z trybem aplikacji (``--app``), od najlepszej."""
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
    """Okno aplikacji w Chrome/Edge (``--app``) z osobnym profilem — proces żyje tak długo jak okno."""
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
            args.append("--class=tacticmind")  # klasa okna — pasuje do skrótu .desktop (StartupWMClass)
        try:
            return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            continue
    return None


def _wait_for_parent() -> None:
    """Tryb ``--server``: koniec, gdy proces nadrzędny (Tauri) zamknie nasze standardowe wejście."""
    try:
        while sys.stdin.read(1024):
            pass
    except (OSError, ValueError):
        while True:
            time.sleep(3600)


def _wait_for_tabs(app: WebApp, idle_exit: float = IDLE_EXIT, seen: bool = False) -> None:
    """Działamy, dopóki jakaś karta jest podłączona (i jeszcze ``idle_exit`` s po rozłączeniu ostatniej)."""
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
    parser = argparse.ArgumentParser(prog="tacticmind", description="TacticMind — interfejs w przeglądarce")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="port serwera (0 = dowolny wolny)")
    parser.add_argument("--server", action="store_true", help="sam serwer dla aplikacji Tauri")
    parser.add_argument("--no-window", action="store_true", help="sam serwer, bez otwierania okna")
    parser.add_argument("--browser", action="store_true", help="zwykła karta w domyślnej przeglądarce zamiast okna aplikacji")
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
            print(f"TacticMind: {url}  (Ctrl+C kończy)", flush=True)
            while True:
                time.sleep(3600)
        else:
            window = None if args.browser else open_app_window(url)
            if window is not None:
                print(f"TacticMind: {url}", flush=True)
                window.wait()
                # Gdy okno gry było już otwarte, nowy proces przeglądarki oddaje je staremu i od razu kończy —
                # wtedy serwer działa dalej, dopóki jakaś karta jest podłączona.
                _wait_for_tabs(app, idle_exit=3.0, seen=True)
            else:
                print(f"TacticMind: {url}  (otwieram w przeglądarce)", flush=True)
                webbrowser.open(url)
                _wait_for_tabs(app)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        app.stop()
