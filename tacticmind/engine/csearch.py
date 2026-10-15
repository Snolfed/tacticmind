"""Silnik w C (bitboardy + NNUE) z tym samym interfejsem co ``search.Searcher``.

Python steruje iterative deepening: każda głębokość to jedno wywołanie ``tm_iterate``
w C, a po niej powstaje ``SearchInfo`` — dokładnie taki sam jak z silnika w Pythonie
(MultiPV, statystyki, mini-drzewo). Dzięki temu panel „Mózg AI”, trener i ocena
zadań działają bez zmian, tylko liczą ok. 50–100× szybciej.

``make_searcher()`` wybiera silnik w C, a gdy biblioteka jest niedostępna — silnik w Pythonie.
"""

from __future__ import annotations

import ctypes
import time
from collections.abc import Callable

from .board import Board
from .native import POLL_FN, NativeLib, load
from .search import Searcher, SearchLimits
from .types import (
    MATE,
    MATE_BOUND,
    Bound,
    EngineScore,
    PvLine,
    SearchInfo,
    SearchProgress,
    Terminal,
    TreeNode,
    to_white_score,
)

REPORT_SIZE = 4 << 20
_BOUNDS: tuple[Bound, Bound, Bound] = ("exact", "upper", "lower")


class CSearcher:
    """Wyszukiwanie w silniku C; API jak ``Searcher`` (start / iterate / result / search)."""

    #: Nazwa silnika do wyświetlenia.
    name = "C + NNUE"

    def __init__(self, lib: NativeLib, tt_mb: int = 64) -> None:
        self._lib = lib
        self._handle = lib.lib.tm_engine_new(tt_mb)
        if not self._handle:
            raise MemoryError("nie udało się utworzyć silnika C")
        self.name = "C + NNUE" if lib.nnue else "C"
        self.should_stop: Callable[[], bool] | None = None
        self.on_progress: Callable[[SearchProgress], None] | None = None
        self.limits = SearchLimits()
        self.root_side = 0
        self.root_fen = ""
        self.depth_done = 0
        self.finished = True
        self.stopped = False
        self.start_time = 0.0
        self.last_progress = 0.0
        self.last_info: SearchInfo | None = None
        self.terminal: Terminal | None = None
        self._buffer = ctypes.create_string_buffer(REPORT_SIZE)
        self._poll = POLL_FN(self._on_poll)

    def __del__(self) -> None:
        handle = getattr(self, "_handle", None)
        if handle:
            self._lib.lib.tm_engine_free(handle)
            self._handle = None

    # ------------------------------------------------------------------ API
    def start(self, board: Board | str, limits: SearchLimits) -> None:
        fen = board if isinstance(board, str) else board.fen()
        self.limits = limits
        self.root_fen = fen
        self.root_side = 0 if fen.split()[1] == "w" else 1
        self.depth_done = 0
        self.finished = False
        self.stopped = False
        self.last_info = None
        self.terminal = None
        self.start_time = time.perf_counter()
        self.last_progress = self.start_time
        count = self._lib.lib.tm_begin(self._handle, fen.encode(), max(1, limits.multi_pv), int(limits.record_tree))
        if count < 0:
            raise ValueError(f"Niepoprawny FEN: {fen}")
        if count == 0:
            self.terminal = "checkmate" if self._lib.lib.tm_terminal(self._handle) == 1 else "stalemate"
            self.finished = True

    def is_finished(self) -> bool:
        return self.finished

    def result(self) -> SearchInfo:
        return self.last_info if self.last_info is not None else self._terminal_info()

    def iterate(self) -> SearchInfo | None:
        if self.finished:
            return None
        depth = self.depth_done + 1
        elapsed = time.perf_counter() - self.start_time
        # Nie zaczynaj nowej głębokości, gdy zużyto ponad połowę czasu — i tak by się nie skończyła.
        if depth > min(self.limits.max_depth, 100) or (depth > 1 and elapsed > self.limits.time_ms / 1000 * 0.5):
            self.finished = True
            return None
        stop_after = float(self.limits.time_ms) if depth > 1 else -1.0
        done = self._lib.lib.tm_iterate(self._handle, depth, stop_after, self._poll, None)
        if not done:
            self.finished = True
            return None
        self.depth_done = depth
        info = self._read_report(depth)
        self.last_info = info
        # Mat potwierdzony z zapasem głębokości (redukcje mogą chwilowo ukryć krótszego mata) — kończymy wcześniej.
        best = info.multi_pv[0].score.value if info.multi_pv else 0
        if abs(best) > MATE_BOUND and depth >= 2 * (MATE - abs(best)) + 4:
            self.finished = True
        return info

    def search(
        self, board: Board | str, limits: SearchLimits, on_info: Callable[[SearchInfo], None] | None = None
    ) -> SearchInfo:
        self.start(board, limits)
        while not self.finished:
            info = self.iterate()
            if info is not None and on_info is not None:
                on_info(info)
        return self.result()

    def clear(self) -> None:
        """Czyści tablicę transpozycji i historię (nowa partia)."""
        self._lib.lib.tm_engine_clear(self._handle)

    # ------------------------------------------------------------------ wewnętrzne
    def _on_poll(self, _user: object, depth: int, nodes: int, cutoffs: int, tt_hits: int, time_ms: int) -> int:
        try:
            if self.should_stop is not None and self.should_stop():
                self.stopped = True
                return 1
            now = time.perf_counter()
            if self.on_progress is not None and now - self.last_progress >= 0.1:
                self.last_progress = now
                self.on_progress(
                    SearchProgress(
                        id=0,
                        depth=depth,
                        nodes=nodes,
                        nps=int(nodes * 1000 / max(time_ms, 1)),
                        cutoffs=cutoffs,
                        tt_hits=tt_hits,
                        time_ms=time_ms,
                    )
                )
            return 0
        except Exception:  # noqa: BLE001 — wyjątek nie może przejść przez kod C
            self.stopped = True
            return 1

    def _read_report(self, depth: int) -> SearchInfo:
        size = self._lib.lib.tm_report(self._handle, self._buffer, REPORT_SIZE, depth)
        text = self._buffer.raw[:size].decode()
        side = self.root_side
        lines: list[PvLine] = []
        tree: list[TreeNode] = []
        stats = [0] * 9
        for row in text.splitlines():
            parts = row.split()
            if not parts:
                continue
            kind = parts[0]
            if kind == "stats":
                stats = [int(x) for x in parts[1:10]]
            elif kind == "line":
                pv = parts[2:]
                lines.append(PvLine(pv[0], to_white_score(int(parts[1]), side), pv))
            elif kind == "node":
                score = to_white_score(int(parts[2]), side)
                tree.append(TreeNode(parts[1], score, "exact" if parts[3] == "1" else "upper", tt_cut=parts[4] == "1"))
            elif kind == "child" and tree:
                pruned = parts[4] == "1"
                child_score = None if pruned else to_white_score(int(parts[2]), side ^ 1)
                tree[-1].children.append(TreeNode(parts[1], child_score, _BOUNDS[int(parts[3])], pruned=pruned))
        _, seldepth, nodes, qnodes, cutoffs, tt_hits, searched, pruned_moves, _ = stats
        if self.limits.record_tree:
            sign = 1 if side == 0 else -1
            tree.sort(key=lambda n: sign * n.score.value if n.score else -MATE, reverse=True)
        elapsed = max(time.perf_counter() - self.start_time, 1e-3)
        main = lines[0]
        total = searched + pruned_moves
        return SearchInfo(
            id=0,
            fen=self.root_fen,
            depth=depth,
            seldepth=max(seldepth, depth),
            score_cp=main.score.cp,
            mate_in=main.score.mate,
            score=main.score,
            best_move=main.move,
            pv=main.pv,
            multi_pv=lines,
            nodes=nodes,
            qnodes=qnodes,
            nps=int(nodes / elapsed),
            cutoffs=cutoffs,
            tt_hits=tt_hits,
            pruned_percent=round(100 * pruned_moves / total, 1) if total else 0.0,
            time_ms=int(elapsed * 1000),
            tree=tree if self.limits.record_tree else [],
        )

    def _terminal_info(self) -> SearchInfo:
        mated = self.terminal == "checkmate"
        if mated:
            value = -MATE if self.root_side == 0 else MATE
            score = EngineScore(None, 0, value)
        else:
            score = EngineScore(0, None, 0)
        return SearchInfo(
            id=0,
            fen=self.root_fen,
            depth=0,
            seldepth=0,
            score_cp=score.cp,
            mate_in=score.mate,
            score=score,
            best_move="",
            pv=[],
            multi_pv=[],
            nodes=0,
            qnodes=0,
            nps=0,
            cutoffs=0,
            tt_hits=0,
            pruned_percent=0.0,
            time_ms=int((time.perf_counter() - self.start_time) * 1000),
            tree=[],
            terminal=self.terminal,
        )


AnySearcher = Searcher | CSearcher


def make_searcher() -> AnySearcher:
    """Silnik w C, jeśli biblioteka jest dostępna; w przeciwnym razie silnik w Pythonie."""
    lib = load()
    if lib is not None:
        try:
            return CSearcher(lib)
        except MemoryError:
            pass
    return Searcher()


def find_best_move_c(fen: str, **limits: int | bool) -> SearchInfo:
    """Odpowiednik ``search.find_best_move`` dla silnika w C (testy, skrypty)."""
    lib = load()
    if lib is None:
        raise RuntimeError("silnik w C jest niedostępny")
    params = SearchLimits(max_depth=64, time_ms=5000, multi_pv=1)
    for key, value in limits.items():
        setattr(params, key, value)
    return CSearcher(lib).search(fen, params)
