"""TacticMind — chess puzzles with an AI that thinks out loud.

Usage:  python main.py            (the game in its own window)
        python main.py --help     (other options: --no-window, --port)
"""

import sys


def main() -> None:
    # Import inside the function: the engine process (multiprocessing, "spawn" mode)
    # imports this file again and should not load the interface when it does.
    from tacticmind.web.app import main as run

    run(sys.argv[1:])


if __name__ == "__main__":
    main()
