"""Build the C engine: the library for the game (ctypes) and the ``tmengine`` UCI program.

Usage::

    python scripts/build_engine.py             # library + tmengine (optimized for this CPU)
    python scripts/build_engine.py --portable  # without -march=native (for copying to other computers)
    python scripts/build_engine.py --windows-dll  # prebuilt library for Windows x64 (MinGW-w64 compiler on Linux)

The game builds the library itself on first launch if it finds a C compiler,
so this script is only needed for manual rebuilds and for the UCI program
(matches, generating NNUE training data — see scripts/nnue/README.md).
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
    """Library for Windows without a compiler: x86-64-v2 (CPUs from about 2009 on), libgcc linked in statically."""
    compiler = shutil.which("x86_64-w64-mingw32-gcc")
    if compiler is None:
        sys.exit("x86_64-w64-mingw32-gcc not found (Debian/Ubuntu: apt install gcc-mingw-w64-x86-64).")
    target = prebuilt_dll_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = [compiler, "-O3", "-std=gnu11", "-march=x86-64-v2", "-shared", "-static-libgcc", "-s", "-o", str(target)]
    subprocess.run([*cmd, *[str(NATIVE_DIR / s) for s in LIB_SOURCES]], check=True)
    print(f"Windows library: {target}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--portable", action="store_true", help="without -march=native")
    parser.add_argument("--windows-dll", action="store_true", help="build a prebuilt library for Windows x64 (MinGW-w64)")
    args = parser.parse_args()
    if args.windows_dll:
        build_windows_dll()
        return
    if find_compiler() is None:
        sys.exit("No C compiler found. Linux: gcc (apt install build-essential), macOS: xcode-select --install, "
                 "Windows: MinGW-w64 (e.g. via MSYS2). Without a compiler the game uses the Python engine.")
    lib = build(verbose=True, portable=args.portable)
    cli = build(cli=True, verbose=True, portable=args.portable)
    if lib is None or cli is None:
        sys.exit("Build failed.")
    print(f"Library: {lib}\nUCI program: {cli}")


if __name__ == "__main__":
    main()
