"""TaktykAI — szachowe zadania z AI, które myśli na głos.

Uruchomienie:  python main.py
"""

import os

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
# Stała nazwa klasy okna — pozwala dopasować skrót .desktop (StartupWMClass=taktykai) i jego ikonę na pasku zadań.
os.environ.setdefault("SDL_VIDEO_X11_WMCLASS", "taktykai")
os.environ.setdefault("SDL_VIDEO_WAYLAND_WMCLASS", "taktykai")


def main() -> None:
    # Import wewnątrz funkcji: proces silnika (multiprocessing, tryb "spawn")
    # importuje ten plik ponownie i nie powinien przy tym ładować pygame.
    from taktykai.ui.app import main as run

    run()


if __name__ == "__main__":
    main()
