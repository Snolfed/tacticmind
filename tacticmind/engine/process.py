"""The engine in a separate process, so the UI never stutters (the equivalent of a Web Worker).

Protocol: small objects sent through ``multiprocessing.Queue``:

Requests to the engine:
 - ``AnalyzeRequest`` - iterative deepening search (FEN, max depth, time, MultiPV),
 - ``CompareRequest`` - minimax vs alpha-beta comparison mode,
 - ``StopRequest`` - stop the current search,
 - ``QuitRequest`` - terminate the process.

Engine responses:
 - ``InfoEvent`` - after each completed depth: ``SearchInfo`` with the fields
   depth, score (cp or mate), pv, multi_pv, nodes, nps, cutoffs, tt_hits, time_ms,
 - ``ProgressEvent`` - every ~100 ms (live counters during a depth),
 - ``DoneEvent`` - end of search (result of the last full depth),
 - ``CompareEvent``, ``ErrorEvent``.

Stopping is immediate: the UI sets a shared ``multiprocessing.Event`` flag,
and the search checks it every 1024 nodes.
The process handles successive requests without restarting.
"""

from __future__ import annotations

import multiprocessing as mp
import queue
from dataclasses import dataclass
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Event

from .board import Board
from .compare import compare_algorithms
from .csearch import AnySearcher, make_searcher
from .search import SearchLimits
from .types import CompareResult, SearchInfo, SearchProgress

# ----------------------------------------------------------------- requests


@dataclass(frozen=True)
class AnalyzeRequest:
    id: int
    fen: str
    max_depth: int
    time_ms: int
    multi_pv: int


@dataclass(frozen=True)
class CompareRequest:
    id: int
    fen: str
    depth: int
    include_minimax: bool


@dataclass(frozen=True)
class StopRequest:
    pass


@dataclass(frozen=True)
class QuitRequest:
    pass


Request = AnalyzeRequest | CompareRequest | StopRequest | QuitRequest

# ----------------------------------------------------------------- responses


@dataclass(frozen=True)
class InfoEvent:
    id: int
    info: SearchInfo


@dataclass(frozen=True)
class ProgressEvent:
    id: int
    progress: SearchProgress


@dataclass(frozen=True)
class DoneEvent:
    id: int
    info: SearchInfo
    stopped: bool


@dataclass(frozen=True)
class CompareEvent:
    id: int
    result: CompareResult


@dataclass(frozen=True)
class ErrorEvent:
    id: int
    message: str


EngineEvent = InfoEvent | ProgressEvent | DoneEvent | CompareEvent | ErrorEvent


# ----------------------------------------------------------------- engine process


def _engine_main(requests: Queue[Request], responses: Queue[EngineEvent], stop_event: Event) -> None:
    """Engine process loop."""
    searcher = make_searcher()  # C engine (NNUE), or the Python one when there is no compiler
    while True:
        message = requests.get()
        # If more requests are queued, only the newest matters (unless it's "quit").
        while not isinstance(message, QuitRequest):
            try:
                message = requests.get_nowait()
            except queue.Empty:
                break
        if isinstance(message, QuitRequest):
            return
        if isinstance(message, StopRequest):
            continue
        stop_event.clear()
        if isinstance(message, AnalyzeRequest):
            _analyze(searcher, message, requests, responses, stop_event)
        else:
            try:
                result = compare_algorithms(message.fen, message.depth, message.include_minimax)
                responses.put(CompareEvent(message.id, result))
            except Exception as error:  # noqa: BLE001 - report the error to the UI
                responses.put(ErrorEvent(message.id, str(error)))


def _analyze(
    searcher: AnySearcher, request: AnalyzeRequest, requests: Queue[Request], responses: Queue[EngineEvent], stop_event: Event
) -> None:
    try:
        board = Board(request.fen)
    except ValueError as error:
        responses.put(ErrorEvent(request.id, str(error)))
        return

    def interrupted() -> bool:
        return stop_event.is_set() or not requests.empty()

    def progress(p: SearchProgress) -> None:
        p.id = request.id
        responses.put(ProgressEvent(request.id, p))

    searcher.should_stop = interrupted
    searcher.on_progress = progress
    limits = SearchLimits(max_depth=request.max_depth, time_ms=request.time_ms, multi_pv=request.multi_pv, record_tree=True)
    searcher.start(board, limits)
    while not searcher.is_finished():
        info = searcher.iterate()
        if info is not None:
            info.id = request.id
            responses.put(InfoEvent(request.id, info))
        if interrupted():
            break
    result = searcher.result()
    result.id = request.id
    responses.put(DoneEvent(request.id, result, interrupted()))


class EngineClient:
    """UI side: sends requests to the engine process and receives results without blocking."""

    def __init__(self) -> None:
        ctx = mp.get_context("spawn")  # the same start method on Linux, Windows and macOS
        self._requests: Queue[Request] = ctx.Queue()
        self._responses: Queue[EngineEvent] = ctx.Queue()
        self._stop = ctx.Event()
        self._process = ctx.Process(
            target=_engine_main, args=(self._requests, self._responses, self._stop), daemon=True, name="TacticMind-engine"
        )
        self._process.start()
        self._next_id = 0

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def analyze(self, fen: str, *, max_depth: int = 32, time_ms: int = 3000, multi_pv: int = 3) -> int:
        """Start an analysis (interrupting the previous one). Return the request id."""
        req_id = self._new_id()
        self._stop.set()
        self._requests.put(AnalyzeRequest(req_id, fen, max_depth, time_ms, multi_pv))
        return req_id

    def compare(self, fen: str, depth: int, include_minimax: bool = True) -> int:
        req_id = self._new_id()
        self._stop.set()
        self._requests.put(CompareRequest(req_id, fen, depth, include_minimax))
        return req_id

    def stop(self) -> None:
        self._stop.set()
        self._requests.put(StopRequest())

    def poll(self) -> list[EngineEvent]:
        """All messages that arrived since the last call (non-blocking)."""
        events: list[EngineEvent] = []
        while True:
            try:
                events.append(self._responses.get_nowait())
            except queue.Empty:
                return events

    def alive(self) -> bool:
        return self._process.is_alive()

    def close(self) -> None:
        try:
            self._stop.set()
            self._requests.put(QuitRequest())
            self._process.join(timeout=1.0)
        finally:
            if self._process.is_alive():
                self._process.terminate()
