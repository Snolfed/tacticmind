"""Pomiar płynności interfejsu: średni czas klatki (ms) i FPS na każdym ekranie, w kilku rozdzielczościach.

Użycie::

    python scripts/fps.py                      # prawdziwe okno, 1920×1080 i 2560×1440
    python scripts/fps.py --size 3840x2160     # inna rozdzielczość (można podać kilka razy)
    python scripts/fps.py --headless           # bez okna (SDL dummy) — sam koszt rysowania, bez flip()

Klatki liczone są bez limitu 60 FPS, więc wynik pokazuje zapas mocy. Profil gracza
trafia do katalogu tymczasowego, żeby pomiar nie zmieniał prawdziwych statystyk.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SCREENS = ["home", "play", "coach", "stats", "howto"]


def parse_size(text: str) -> tuple[int, int]:
    w, h = text.lower().split("x")
    return int(w), int(h)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--size", action="append", type=parse_size, help="rozdzielczość, np. 2560x1440")
    parser.add_argument("--frames", type=int, default=240, help="liczba mierzonych klatek na ekran")
    parser.add_argument("--headless", action="store_true", help="bez okna (SDL dummy)")
    args = parser.parse_args()
    if args.headless:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
    os.environ["TACTICMIND_HOME"] = tempfile.mkdtemp(prefix="tacticmind-fps-")
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

    from tacticmind.ui.app import App

    sizes = args.size or [(1920, 1080), (2560, 1440)]
    print("| Rozdzielczość | " + " | ".join(SCREENS) + " |")
    print("|---|" + "---:|" * len(SCREENS))
    for size in sizes:
        app = App(size)
        cells = []
        try:
            for name in SCREENS:
                if name != app.current_name:
                    app.go(name)
                for _ in range(40):  # rozgrzewka: przejście między ekranami, pamięć podręczna kształtów
                    app.frame(1 / 60)
                start = time.perf_counter()
                for _ in range(args.frames):
                    app.frame(1 / 60)
                ms = (time.perf_counter() - start) / args.frames * 1000
                cells.append(f"{ms:.1f} ms ({1000 / ms:.0f} FPS)")
        finally:
            app.shutdown()
        print(f"| {size[0]}×{size[1]} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
