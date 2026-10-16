"""Loading the C engine (``engine/native/``) via ctypes.

The library is compiled on first run if the system has a C compiler
(gcc, clang or cc; MinGW-w64 on Windows) and goes to ``engine/native/build/``. On Windows
without a compiler, the prebuilt library from ``engine/native/prebuilt/windows-x64/`` is used.
The build can also be run manually: ``python scripts/build_engine.py``. If the build fails,
the game uses the Python engine (``search.py``): slower, but identical from the interface side.

Environment variables:
 - ``TACTICMIND_ENGINE=python`` - forces the Python engine,
 - ``CC`` - the C compiler,
 - ``TACTICMIND_NET`` - an NNUE network file other than the default ``engine/native/tacticmind.nnue``.
"""

from __future__ import annotations

import contextlib
import ctypes
import hashlib
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

#: Callback invoked by C every ~20 ms: (user, depth, nodes, cutoffs, tt_hits, time_ms) -> 1 = stop.
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
    if sys.platform == "darwin" and not os.environ.get("CC") and not _xcode_tools_installed():
        # Without the Command Line Tools, /usr/bin/gcc is only a stub that opens the installer window.
        return None
    for name in candidates:
        if name and shutil.which(name):
            return name
    return None


def _xcode_tools_installed() -> bool:
    try:
        return subprocess.run(["xcode-select", "-p"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


START_FEN = b"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
STAMP = BUILD_DIR / "cpu.txt"
FAILED = BUILD_DIR / "failed.txt"
#: Library interface version (tm_version in api.c); an older library in build/ is rebuilt.
API_VERSION = 2


def cpu_signature() -> str:
    """CPU fingerprint: a library built with -march=native won't work on a different CPU (SIGILL)."""
    parts = [sys.platform, platform.machine(), platform.processor(), os.environ.get("PROCESSOR_IDENTIFIER", "")]
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as info:
            for line in info:
                if line.startswith(("model name", "flags", "Features", "CPU part")):
                    parts.append(line.split(":", 1)[1].strip())
                if len(parts) >= 7:
                    break
    except OSError:
        pass
    if sys.platform == "darwin":
        keys = ["machdep.cpu.brand_string", "machdep.cpu.features", "machdep.cpu.leaf7_features"]
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            parts.append(subprocess.run(["sysctl", "-n", *keys], capture_output=True, text=True, timeout=10).stdout)
    return hashlib.sha1("|".join(parts).encode()).hexdigest()


def _build_key(compiler: str) -> str:
    """Compiler + CPU + sources, so a failed build is not retried on every game start."""
    sources = [NATIVE_DIR / s for s in CLI_SOURCES + ["api.c", "tm.h"]]
    stamp = [compiler, shutil.which(compiler) or "", cpu_signature()]
    stamp += [f"{src.name}:{src.stat().st_mtime_ns}" for src in sources if src.exists()]
    return hashlib.sha1("|".join(stamp).encode()).hexdigest()


def _needs_build(target: Path) -> bool:
    if not target.exists():
        return True
    try:
        if STAMP.read_text().strip() != cpu_signature():
            return True
    except OSError:
        return True
    mtime = target.stat().st_mtime
    sources = [NATIVE_DIR / s for s in LIB_SOURCES] + [NATIVE_DIR / "tm.h"]
    return any(src.exists() and src.stat().st_mtime > mtime for src in sources)


# Test in a separate process: move generator (perft), network evaluation and a short search, so that
# the vectorised NNUE loops (where the compiler is most likely to use AVX instructions) also run.
_VERIFY_LIB = """
import ctypes, sys
lib = ctypes.CDLL(sys.argv[1])
fen = sys.argv[2].encode()
lib.tm_version.restype = ctypes.c_int
lib.tm_perft.restype = ctypes.c_ulonglong
lib.tm_perft.argtypes = [ctypes.c_char_p, ctypes.c_int]
if lib.tm_version() != int(sys.argv[4]) or lib.tm_perft(fen, 3) != 8902:
    sys.exit(1)
lib.tm_load_net_memory.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
lib.tm_eval.argtypes = [ctypes.c_char_p, ctypes.c_int]
lib.tm_engine_new.restype = ctypes.c_void_p
lib.tm_engine_new.argtypes = [ctypes.c_int]
lib.tm_begin.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
lib.tm_iterate.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_double, ctypes.c_void_p, ctypes.c_void_p]
try:
    data = open(sys.argv[3], "rb").read()
    lib.tm_load_net_memory(data, len(data))
except OSError:
    pass
lib.tm_eval(fen, 1)
engine = lib.tm_engine_new(1)
lib.tm_begin(engine, fen, 1, 0)
for depth in range(1, 5):
    lib.tm_iterate(engine, depth, -1.0, None, None)
"""


def _works(path: Path, cli: bool) -> bool:
    """Check the built file in a separate process, so an unsupported CPU instruction can't crash the game."""
    if cli:
        cmd = [str(path), "bench", "4"]
    else:
        cmd = [sys.executable, "-c", _VERIFY_LIB, str(path), START_FEN.decode(), str(NET_PATH), str(API_VERSION)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def build(*, cli: bool = False, verbose: bool = False, portable: bool = False) -> Path | None:
    """Compile the library (or the ``tmengine`` UCI program for ``cli=True``). Return the path or None."""
    compiler = find_compiler()
    if compiler is None:
        if verbose:
            print("No C compiler found (gcc / clang / cc).", file=sys.stderr)
        return None
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    if cli:
        target = BUILD_DIR / ("tmengine.exe" if sys.platform == "win32" else "tmengine")
        sources, link = CLI_SOURCES, []
    else:
        target = BUILD_DIR / library_name()
        sources = LIB_SOURCES
        link = ["-shared"] + ([] if sys.platform == "win32" else ["-fPIC"])
    # Windows (MinGW): libgcc is linked in statically, otherwise the DLL looks for libgcc_s_seh-1.dll, which Python won't find.
    # Math functions live in the C library there, so -lm only outside Windows.
    link += ["-static-libgcc"] if sys.platform == "win32" else ["-lm"]
    base = [compiler, "-O3", "-std=gnu11"] + ([] if cli else ["-fvisibility=hidden"])
    # -march=native: this CPU's vector instructions (fastest); without it, a portable build.
    variants = [["-march=native"], []] if not portable else [[]]
    # Compile to a temporary file and swap it in; a running process may have the old library open.
    fd, tmp_name = tempfile.mkstemp(dir=BUILD_DIR, suffix=target.suffix or ".bin")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        for extra in variants:
            cmd = [*base, *extra, "-o", str(tmp), *[str(NATIVE_DIR / s) for s in sources], *link]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            except (OSError, subprocess.SubprocessError) as exc:
                result = subprocess.CompletedProcess(cmd, 1, "", str(exc))
            if result.returncode == 0 and _works(tmp, cli):
                os.replace(tmp, target)
                if not cli:
                    STAMP.write_text(cpu_signature())
                    FAILED.unlink(missing_ok=True)
                if verbose:
                    print(" ".join(cmd))
                return target
            if verbose:
                print(result.stderr or f"{target.name}: post-build test failed ({extra})", file=sys.stderr)
        if not cli:
            with contextlib.suppress(OSError):
                FAILED.write_text(_build_key(compiler))
        return None
    finally:
        if tmp.exists():
            tmp.unlink()


class NativeLib:
    """Library functions with argument types (ctypes)."""

    def __init__(self, path: Path) -> None:
        lib = ctypes.CDLL(str(path))
        self.path = path
        self.lib = lib
        lib.tm_version.restype = ctypes.c_int
        if lib.tm_version() != API_VERSION:
            raise OSError(f"{path.name}: interface version mismatch ({lib.tm_version()} instead of {API_VERSION})")
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
        lib.tm_load_net_memory.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
        lib.tm_load_net_memory.restype = ctypes.c_int
        # Python reads the file and C gets the bytes: fopen() on Windows can't handle paths outside the code page.
        net = Path(os.environ.get("TACTICMIND_NET", str(NET_PATH)))
        try:
            data = net.read_bytes()
        except OSError:
            data = b""
        self.nnue = bool(data and lib.tm_load_net_memory(data, len(data)))


_LIB: NativeLib | None = None
_TRIED = False


def load(auto_build: bool = True) -> NativeLib | None:
    """The C engine library, or None (no compiler, error, ``TACTICMIND_ENGINE=python``)."""
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
    if auto_build and _needs_build(target) and not _failed_before():
        with contextlib.suppress(OSError):
            build()
    if target.exists() and _needs_build(target) and not _works(target, cli=False):
        # The build failed, and the old library may have been built for another CPU or interface
        # version; use it only if it passes the test in a separate process.
        candidates.remove(target)
    for path in candidates:
        if path.exists():
            try:
                _LIB = NativeLib(path)
                break
            except OSError:
                continue
    return _LIB


def _failed_before() -> bool:
    compiler = find_compiler()
    if compiler is None:
        return True
    try:
        return FAILED.read_text().strip() == _build_key(compiler)
    except OSError:
        return False


def prebuilt_dll_path() -> Path:
    return NATIVE_DIR / "prebuilt" / "windows-x64" / "tmengine.dll"


def prebuilt_library() -> Path | None:
    """Prebuilt library shipped with the repository (Windows x64, where a C compiler is rare)."""
    if sys.platform == "win32" and platform.machine().lower() in ("amd64", "x86_64"):
        return prebuilt_dll_path()
    return None


def available() -> bool:
    return load() is not None
