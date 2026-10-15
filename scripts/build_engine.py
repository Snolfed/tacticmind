"""Kompilacja silnika w C: biblioteka dla gry (ctypes) i program UCI ``tmengine``.

Użycie::

    python scripts/build_engine.py             # biblioteka + tmengine (zoptymalizowane pod ten procesor)
    python scripts/build_engine.py --portable  # bez -march=native (do kopiowania na inne komputery)

Gra buduje bibliotekę sama przy pierwszym uruchomieniu, jeśli znajdzie kompilator C,
więc ten skrypt jest potrzebny tylko do ręcznej przebudowy i do programu UCI
(mecze, generowanie danych do sieci NNUE — patrz scripts/nnue/README.md).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tacticmind.engine.native import build, find_compiler  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--portable", action="store_true", help="bez -march=native")
    args = parser.parse_args()
    if find_compiler() is None:
        sys.exit("Nie znaleziono kompilatora C. Linux: gcc (apt install build-essential), macOS: xcode-select --install, "
                 "Windows: MinGW-w64 (np. przez MSYS2). Bez kompilatora gra użyje silnika w Pythonie.")
    lib = build(verbose=True, portable=args.portable)
    cli = build(cli=True, verbose=True, portable=args.portable)
    if lib is None or cli is None:
        sys.exit("Kompilacja nie powiodła się.")
    print(f"Biblioteka: {lib}\nProgram UCI: {cli}")


if __name__ == "__main__":
    main()
