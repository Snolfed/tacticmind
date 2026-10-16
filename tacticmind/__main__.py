"""Run the game with: python -m tacticmind (same options as main.py, e.g. --no-window)."""

import sys

if __name__ == "__main__":
    from tacticmind.web.app import main

    main(sys.argv[1:])
