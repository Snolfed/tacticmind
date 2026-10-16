"""The game window: a native window (pywebview) showing the interface served by the local server.

pywebview uses the web engine the system already has: WebKitGTK on Linux, WebView2 (Edge) on Windows 10 and 11,
WKWebView on macOS. No browser is opened and nothing has to be built.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import site
import sys
from pathlib import Path
from typing import Any

TITLE = "TacticMind"
SIZE = (1360, 860)
MIN_SIZE = (720, 520)
#: The page background, shown before the interface loads (no white flash).
BACKGROUND = "#0f111a"
ICON = Path(__file__).resolve().parent / "static" / "icon.png"
#: Window class on X11 and app id on Wayland (taskbar grouping, ``StartupWMClass`` of a .desktop shortcut).
APP_ID = "tacticmind"
#: Present when the proprietary NVIDIA driver is loaded.
NVIDIA_DRIVER = Path("/proc/driver/nvidia/version")

MISSING_PYWEBVIEW = """TacticMind: the pywebview library for the game window is not installed.
Install the game's libraries in the activated .venv:  pip install -r requirements.txt"""

MISSING_GTK = """TacticMind: the game window needs WebKitGTK and the GTK bindings for Python (PyGObject):
  Arch / Manjaro:         sudo pacman -S --needed python-gobject webkit2gtk-4.1
  Debian / Ubuntu / Mint: sudo apt install python3-gi gir1.2-webkit2-4.1
  Fedora:                 sudo dnf install python3-gobject webkit2gtk4.1
The .venv uses the system PyGObject by itself, as long as it was created with the system Python."""


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
    """With the proprietary NVIDIA driver under Wayland, WebKitGTK's DMA-BUF renderer kills the window at once
    ("Error 71 (Protocol error) dispatching to Wayland display"); its older renderer works. A value the player set wins."""
    if os.environ.get("WAYLAND_DISPLAY") and os.environ.get("GDK_BACKEND", "wayland").startswith("wayland") and NVIDIA_DRIVER.exists():
        os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")


def check() -> str | None:
    """Prepares the window (Linux) and says why it cannot open on this computer (with what to install), or ``None``."""
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
