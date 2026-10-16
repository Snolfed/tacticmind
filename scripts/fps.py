"""Interface smoothness measurement: average frame time (ms) and FPS on each screen, at several resolutions.

Usage::

    python scripts/fps.py                      # real window, 1920×1080 and 2560×1440
    python scripts/fps.py --size 3840x2160     # another resolution (can be given several times)
    python scripts/fps.py --headless           # no window (SDL dummy) — drawing cost only, without flip()

Frames are measured without the 60 FPS cap, so the result shows the performance headroom. The player
profile goes to a temporary directory so the measurement does not change real statistics.
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
    parser.add_argument("--size", action="append", type=parse_size, help="resolution, e.g. 2560x1440")
    parser.add_argument("--frames", type=int, default=240, help="number of measured frames per screen")
    parser.add_argument("--headless", action="store_true", help="no window (SDL dummy)")
    args = parser.parse_args()
    if args.headless:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
    os.environ["TACTICMIND_HOME"] = tempfile.mkdtemp(prefix="tacticmind-fps-")
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

    from tacticmind.ui.app import App

    sizes = args.size or [(1920, 1080), (2560, 1440)]
    print("| Resolution | " + " | ".join(SCREENS) + " |")
    print("|---|" + "---:|" * len(SCREENS))
    for size in sizes:
        app = App(size)
        cells = []
        try:
            for name in SCREENS:
                if name != app.current_name:
                    app.go(name)
                for _ in range(40):  # warm-up: screen transition, shape cache
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
