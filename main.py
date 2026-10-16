"""TacticMind — szachowe zadania z AI, które myśli na głos.

Uruchomienie:  python main.py            (interfejs w TypeScript w oknie aplikacji)
               python main.py --pygame   (dawny interfejs w pygame)
               python main.py --help     (pozostałe opcje: --browser, --no-window, --port)
"""

import os
import sys

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
# Stała nazwa klasy okna — pozwala dopasować skrót .desktop (StartupWMClass=tacticmind) i jego ikonę na pasku zadań.
os.environ.setdefault("SDL_VIDEO_X11_WMCLASS", "tacticmind")
os.environ.setdefault("SDL_VIDEO_WAYLAND_WMCLASS", "tacticmind")


def main() -> None:
    # Import wewnątrz funkcji: proces silnika (multiprocessing, tryb "spawn")
    # importuje ten plik ponownie i nie powinien przy tym ładować interfejsu.
    if "--pygame" in sys.argv:
        from tacticmind.ui.app import main as run_pygame

        run_pygame()
        return
    from tacticmind.web.app import main as run

    run([arg for arg in sys.argv[1:] if arg != "--pygame"])


if __name__ == "__main__":
    main()
