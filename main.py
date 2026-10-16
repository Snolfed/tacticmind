"""TacticMind — chess puzzles with an AI that thinks out loud.

Usage:  python main.py            (TypeScript interface in an app window)
        python main.py --pygame   (legacy pygame interface)
        python main.py --help     (other options: --browser, --no-window, --port)
"""

import os
import sys

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
# Fixed window class name — lets the .desktop shortcut (StartupWMClass=tacticmind) and its taskbar icon match the window.
os.environ.setdefault("SDL_VIDEO_X11_WMCLASS", "tacticmind")
os.environ.setdefault("SDL_VIDEO_WAYLAND_WMCLASS", "tacticmind")


def main() -> None:
    # Import inside the function: the engine process (multiprocessing, "spawn" mode)
    # imports this file again and should not load the interface when it does.
    if "--pygame" in sys.argv:
        from tacticmind.ui.app import main as run_pygame

        run_pygame()
        return
    from tacticmind.web.app import main as run

    run([arg for arg in sys.argv[1:] if arg != "--pygame"])


if __name__ == "__main__":
    main()
