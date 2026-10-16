"""Uruchomienie gry poleceniem: python -m tacticmind (opcje jak w main.py, np. --pygame)."""

import sys

if __name__ == "__main__":
    if "--pygame" in sys.argv:
        from tacticmind.ui.app import main as run_pygame

        run_pygame()
    else:
        from tacticmind.web.app import main

        main(sys.argv[1:])
