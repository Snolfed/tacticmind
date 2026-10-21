"""The game window: a native window showing the interface served by the local server.

On Linux the window is an app window of an installed Chromium-based browser (``--app``: no tabs, no address bar, its
own profile), because the engines pywebview has there draw at most 60 frames per second on some systems (see
``find_browser``). Without such a browser, and on Windows and macOS, it is a pywebview window with the system's engine:
WebKitGTK on Linux, WebView2 (Edge) on Windows 10 and 11, WKWebView on macOS. Nothing has to be built.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import shutil
import signal
import site
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from types import FrameType
from typing import Any

from ..rating.profile import data_dir

TITLE = "TacticMind"
SIZE = (1360, 860)
MIN_SIZE = (720, 520)
#: The page background, shown before the interface loads (no white flash).
BACKGROUND = "#0f111a"
#: Windows' window (WinForms) takes only a real .ico (``scripts/make_icon.py``); with a PNG it does not open at all.
ICON = Path(__file__).resolve().parent / "static" / ("icon.ico" if sys.platform == "win32" else "icon.png")
#: Window class on X11 and app id on Wayland (taskbar grouping, ``StartupWMClass`` of a .desktop shortcut).
APP_ID = "tacticmind"
#: Present when the proprietary NVIDIA driver is loaded.
NVIDIA_DRIVER = Path("/proc/driver/nvidia/version")
#: Chromium-based browsers whose app mode can hold the game on Linux, in order of preference.
BROWSERS = (
    "chromium",
    "chromium-browser",
    "google-chrome-stable",
    "google-chrome",
    "brave",
    "brave-browser",
    "microsoft-edge-stable",
    "vivaldi-stable",
    "vivaldi",
)
#: ``TACTICMIND_WINDOW=webview`` keeps the pywebview window on Linux; ``TACTICMIND_BROWSER`` names a browser to use.
WINDOW_VARIABLE = "TACTICMIND_WINDOW"
BROWSER_VARIABLE = "TACTICMIND_BROWSER"

MISSING_PYWEBVIEW = """TacticMind: the pywebview library for the game window is not installed.
Install the game's libraries in the activated .venv:  pip install -r requirements.txt"""

MISSING_GTK = """TacticMind: the game window needs WebKitGTK and the GTK bindings for Python (PyGObject):
  Arch / Manjaro:         sudo pacman -S --needed python-gobject webkit2gtk-4.1
  Debian / Ubuntu / Mint: sudo apt install python3-gi gir1.2-webkit2-4.1
  Fedora:                 sudo dnf install python3-gobject webkit2gtk4.1
The .venv uses the system PyGObject by itself, as long as it was created with the system Python.
With a Chromium-based browser installed (Chromium, Chrome, Brave, Edge, Vivaldi) the game opens in its app window instead."""


class WindowApi:
    """Methods the interface calls as ``window.pywebview.api.…``: full screen of the window itself (F11, the ⛶ button).

    The page's own Fullscreen API is not enough: WebView2 only stretches the page to the size of the window,
    and WKWebView does not offer it at all.
    """

    def __init__(self) -> None:
        self._window: Any = None
        self._fullscreen = False

    def toggle_fullscreen(self) -> bool:
        if self._window is not None:
            self._window.toggle_fullscreen()
            self._fullscreen = not self._fullscreen
        return self._fullscreen

    def is_fullscreen(self) -> bool:
        return self._fullscreen


def _borrow_system_gi() -> None:
    """Linux: PyGObject does not install into a venv without build tools and headers, so use the system one
    (python-gobject / python3-gi) — what ``python -m venv --system-site-packages`` would do, but only when needed."""
    if importlib.util.find_spec("gi") is not None:
        return
    for path in site.getsitepackages([sys.base_prefix]):
        if path in sys.path or not (Path(path) / "gi").is_dir():
            continue
        sys.path.append(path)
        try:
            importlib.import_module("gi")
            return
        except ImportError:  # built for a different Python version
            sys.path.remove(path)


def _avoid_nvidia_wayland_crash() -> None:
    """With the proprietary NVIDIA driver under Wayland, the driver's explicit sync kills WebKitGTK's window at once
    ("Error 71 (Protocol error) dispatching to Wayland display"). Turning explicit sync off keeps the fast DMA-BUF
    renderer (60 FPS); WebKitGTK's fallback renderer (``WEBKIT_DISABLE_DMABUF_RENDERER=1``) also works, but measured
    11–24 FPS at 2560×1440. A value the player set wins."""
    if os.environ.get("WAYLAND_DISPLAY") and os.environ.get("GDK_BACKEND", "wayland").startswith("wayland") and NVIDIA_DRIVER.exists():
        os.environ.setdefault("__NV_DISABLE_EXPLICIT_SYNC", "1")


def find_browser() -> str | None:
    """Linux: the Chromium-based browser that will hold the game window, or ``None`` (then pywebview).

    Chromium paces frames by the monitor (170 Hz stays 170 Hz). Both engines pywebview has on Linux may not: WebKitGTK
    falls back to a 60 Hz timer when it cannot use the display's vblank (the proprietary NVIDIA driver does not support
    the call it needs), and Qt WebEngine always draws at 60 Hz."""
    if not sys.platform.startswith("linux") or os.environ.get(WINDOW_VARIABLE, "").strip().lower() == "webview":
        return None
    chosen = os.environ.get(BROWSER_VARIABLE, "").strip()
    for name in (chosen, *BROWSERS) if chosen else BROWSERS:
        path = shutil.which(name)
        if path:
            return path
    return None


def _profile_in_use(profile: Path) -> bool:
    """Chromium's lock is a symlink to "host-pid" while a browser has the profile open."""
    try:
        pid = int(os.readlink(profile / "SingletonLock").rsplit("-", 1)[1])
        os.kill(pid, 0)
    except (OSError, ValueError, IndexError):
        return False
    return True


def _exit_on_signal(signum: int, frame: FrameType | None) -> None:
    raise SystemExit(128 + signum)


def show_in_browser(browser: str, url: str) -> None:
    """Shows the game in an app window of the browser and returns once the player closes it."""
    profile = data_dir() / "window"
    spare = None
    if _profile_in_use(profile):  # a second game: the browser would hand the window over to the first one and exit at once
        spare = tempfile.mkdtemp(prefix="tacticmind-window-")
        profile = Path(spare)
    command = [
        browser,
        f"--app={url}",
        f"--user-data-dir={profile}",  # the game's own profile: no extensions, history or sign-in of the player's browser
        f"--window-size={SIZE[0]},{SIZE[1]}",
        f"--class={APP_ID}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate",
    ]
    # Closing the terminal (SIGHUP) or `kill` (SIGTERM) would end Python without the `finally` below and leave the
    # window open on a dead server: as SystemExit they close the browser together with the game.
    previous: dict[int, Any] = {}
    if threading.current_thread() is threading.main_thread():
        for name in ("SIGTERM", "SIGHUP"):
            number = getattr(signal, name, None)
            if number is not None:
                previous[number] = signal.signal(number, _exit_on_signal)
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        process.wait()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(5)
        if spare:
            shutil.rmtree(spare, ignore_errors=True)
        for number, handler in previous.items():
            if handler is not None:
                signal.signal(number, handler)


def check() -> str | None:
    """Prepares the window (Linux) and says why it cannot open on this computer (with what to install), or ``None``."""
    if find_browser():
        return None
    if importlib.util.find_spec("webview") is None:
        return MISSING_PYWEBVIEW
    if sys.platform.startswith("linux"):
        _borrow_system_gi()
        _avoid_nvidia_wayland_crash()
        try:
            glib = importlib.import_module("gi.repository.GLib")
            # Before GTK starts: otherwise the window is named after the script ("main.py").
            glib.set_prgname(APP_ID)
            glib.set_application_name(TITLE)
            # The same imports pywebview makes itself: GTK 3 and WebKit2GTK (4.1 or 4.0).
            importlib.import_module("webview.platforms.gtk")
        except (ImportError, ValueError) as error:
            return f"{MISSING_GTK}\n({error})"
    return None


def show(url: str) -> None:
    """Shows the game in its window and returns once the player closes it. Must run on the main thread."""
    browser = find_browser()
    if browser:
        show_in_browser(browser, url)
        return
    import webview

    api = WindowApi()
    api._window = webview.create_window(
        TITLE,
        url,
        js_api=api,
        width=SIZE[0],
        height=SIZE[1],
        min_size=MIN_SIZE,
        background_color=BACKGROUND,
        text_select=True,  # the interface decides itself what can be selected
    )
    # On Linux only GTK: pywebview would otherwise try Qt first under KDE and print its error.
    webview.start(gui="gtk" if sys.platform.startswith("linux") else None, icon=str(ICON))
