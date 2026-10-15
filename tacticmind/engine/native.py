"""Ładowanie silnika w C (``engine/native/``) przez ctypes.

Biblioteka jest kompilowana przy pierwszym uruchomieniu, jeśli w systemie jest kompilator C
(gcc, clang albo cc; na Windowsie MinGW-w64), i trafia do ``engine/native/build/``. Na Windowsie
bez kompilatora używana jest gotowa biblioteka z ``engine/native/prebuilt/windows-x64/``. Kompilację
można też uruchomić ręcznie: ``python scripts/build_engine.py``. Gdy kompilacja się nie uda,
gra używa silnika w Pythonie (``search.py``) — działa wolniej, ale identycznie od strony interfejsu.

Zmienne środowiskowe:
 - ``TACTICMIND_ENGINE=python`` — wymusza silnik w Pythonie,
 - ``CC`` — kompilator C,
 - ``TACTICMIND_NET`` — inny plik sieci NNUE niż domyślny ``engine/native/tacticmind.nnue``.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

NATIVE_DIR = Path(__file__).resolve().parent / "native"
BUILD_DIR = NATIVE_DIR / "build"
NET_PATH = NATIVE_DIR / "tacticmind.nnue"
LIB_SOURCES = ["bitboard.c", "position.c", "movegen.c", "eval.c", "nnue.c", "search.c", "api.c"]
CLI_SOURCES = [*LIB_SOURCES[:-1], "uci.c"]

#: Funkcja zwrotna wywoływana przez C co ok. 20 ms: (user, depth, nodes, cutoffs, tt_hits, time_ms) → 1 = przerwij.
POLL_FN = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_int
)


def library_name() -> str:
    if sys.platform == "win32":
        return "tmengine.dll"
    if sys.platform == "darwin":
        return "libtmengine.dylib"
    return "libtmengine.so"


def find_compiler() -> str | None:
    candidates = [os.environ.get("CC", ""), "gcc", "clang", "cc"]
    for name in candidates:
        if name and shutil.which(name):
            return name
    return None


def _needs_build(target: Path) -> bool:
    if not target.exists():
        return True
    mtime = target.stat().st_mtime
    sources = [NATIVE_DIR / s for s in LIB_SOURCES] + [NATIVE_DIR / "tm.h"]
    return any(src.exists() and src.stat().st_mtime > mtime for src in sources)


def build(*, cli: bool = False, verbose: bool = False, portable: bool = False) -> Path | None:
    """Kompiluje bibliotekę (albo program UCI ``tmengine`` dla ``cli=True``). Zwraca ścieżkę albo None."""
    compiler = find_compiler()
    if compiler is None:
        if verbose:
            print("Nie znaleziono kompilatora C (gcc / clang / cc).", file=sys.stderr)
        return None
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    if cli:
        target = BUILD_DIR / ("tmengine.exe" if sys.platform == "win32" else "tmengine")
        sources, link = CLI_SOURCES, []
    else:
        target = BUILD_DIR / library_name()
        sources = LIB_SOURCES
        link = ["-shared"] + ([] if sys.platform == "win32" else ["-fPIC"])
    base = [compiler, "-O3", "-std=gnu11"] + ([] if cli else ["-fvisibility=hidden"])
    # -march=native: wektorowe instrukcje tego procesora (najszybciej); bez niego — wersja przenośna.
    variants = [["-march=native"], []] if not portable else [[]]
    # Kompilujemy do pliku tymczasowego i podmieniamy — działający proces może mieć starą bibliotekę otwartą.
    fd, tmp_name = tempfile.mkstemp(dir=BUILD_DIR, suffix=target.suffix or ".bin")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        for extra in variants:
            cmd = [*base, *extra, *link, "-o", str(tmp), *[str(NATIVE_DIR / s) for s in sources], "-lm"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                os.replace(tmp, target)
                if verbose:
                    print(" ".join(cmd))
                return target
            if verbose:
                print(result.stderr, file=sys.stderr)
        return None
    finally:
        if tmp.exists():
            tmp.unlink()


class NativeLib:
    """Funkcje biblioteki z typami argumentów (ctypes)."""

    def __init__(self, path: Path) -> None:
        lib = ctypes.CDLL(str(path))
        self.path = path
        self.lib = lib
        lib.tm_version.restype = ctypes.c_int
        lib.tm_load_net.argtypes = [ctypes.c_char_p]
        lib.tm_load_net.restype = ctypes.c_int
        lib.tm_net_loaded.restype = ctypes.c_int
        lib.tm_engine_new.argtypes = [ctypes.c_int]
        lib.tm_engine_new.restype = ctypes.c_void_p
        lib.tm_engine_free.argtypes = [ctypes.c_void_p]
        lib.tm_engine_clear.argtypes = [ctypes.c_void_p]
        lib.tm_set_use_nnue.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.tm_begin.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
        lib.tm_begin.restype = ctypes.c_int
        lib.tm_terminal.argtypes = [ctypes.c_void_p]
        lib.tm_terminal.restype = ctypes.c_int
        lib.tm_iterate.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_double, POLL_FN, ctypes.c_void_p]
        lib.tm_iterate.restype = ctypes.c_int
        lib.tm_report.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
        lib.tm_report.restype = ctypes.c_int
        lib.tm_eval.argtypes = [ctypes.c_char_p, ctypes.c_int]
        lib.tm_eval.restype = ctypes.c_int
        lib.tm_perft.argtypes = [ctypes.c_char_p, ctypes.c_int]
        lib.tm_perft.restype = ctypes.c_ulonglong
        net = Path(os.environ.get("TACTICMIND_NET", str(NET_PATH)))
        self.nnue = bool(net.exists() and lib.tm_load_net(str(net).encode()))


_LIB: NativeLib | None = None
_TRIED = False


def load(auto_build: bool = True) -> NativeLib | None:
    """Biblioteka silnika w C albo None (brak kompilatora, błąd, ``TACTICMIND_ENGINE=python``)."""
    global _LIB, _TRIED
    if _TRIED:
        return _LIB
    _TRIED = True
    if os.environ.get("TACTICMIND_ENGINE", "").lower() == "python":
        return None
    target = BUILD_DIR / library_name()
    candidates = [target]
    prebuilt = prebuilt_library()
    if prebuilt is not None:
        candidates.append(prebuilt)
    if auto_build and _needs_build(target):
        with contextlib.suppress(OSError):
            build()
    for path in candidates:
        if path.exists():
            try:
                _LIB = NativeLib(path)
                break
            except OSError:
                continue
    return _LIB


def prebuilt_library() -> Path | None:
    """Gotowa biblioteka dołączona do repozytorium (Windows x64 — tam rzadko jest kompilator C)."""
    if sys.platform == "win32" and platform.machine().lower() in ("amd64", "x86_64"):
        return NATIVE_DIR / "prebuilt" / "windows-x64" / "tmengine.dll"
    return None


def available() -> bool:
    return load() is not None
