"""Kompilacja silnika w C: biblioteka dla gry (ctypes) i program UCI ``tmengine``.

Użycie::

    python scripts/build_engine.py             # biblioteka + tmengine (zoptymalizowane pod ten procesor)
    python scripts/build_engine.py --portable  # bez -march=native (do kopiowania na inne komputery)
    python scripts/build_engine.py --windows-dll  # gotowa biblioteka dla Windows x64 (kompilator MinGW-w64 na Linuksie)

Gra buduje bibliotekę sama przy pierwszym uruchomieniu, jeśli znajdzie kompilator C,
więc ten skrypt jest potrzebny tylko do ręcznej przebudowy i do programu UCI
(mecze, generowanie danych do sieci NNUE — patrz scripts/nnue/README.md).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tacticmind.engine.native import LIB_SOURCES, NATIVE_DIR, build, find_compiler, prebuilt_dll_path  # noqa: E402


def build_windows_dll() -> None:
    """Biblioteka dla Windows bez kompilatora: x86-64-v2 (procesory od ok. 2009), libgcc wkompilowana."""
    compiler = shutil.which("x86_64-w64-mingw32-gcc")
    if compiler is None:
        sys.exit("Brak x86_64-w64-mingw32-gcc (Debian/Ubuntu: apt install gcc-mingw-w64-x86-64).")
    target = prebuilt_dll_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = [compiler, "-O3", "-std=gnu11", "-march=x86-64-v2", "-shared", "-static-libgcc", "-s", "-o", str(target)]
    subprocess.run([*cmd, *[str(NATIVE_DIR / s) for s in LIB_SOURCES]], check=True)
    print(f"Biblioteka dla Windows: {target}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--portable", action="store_true", help="bez -march=native")
    parser.add_argument("--windows-dll", action="store_true", help="zbuduj gotową bibliotekę dla Windows x64 (MinGW-w64)")
    args = parser.parse_args()
    if args.windows_dll:
        build_windows_dll()
        return
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
