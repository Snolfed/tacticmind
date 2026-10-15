"""Silnik w osobnym procesie, żeby interfejs nigdy się nie przycinał (odpowiednik Web Workera).

Protokół — małe obiekty przesyłane przez ``multiprocessing.Queue``:

Zapytania do silnika:
 - ``AnalyzeRequest`` — wyszukiwanie z iterative deepening (FEN, maks. głębokość, czas, MultiPV),
 - ``CompareRequest`` — tryb porównawczy minimaks vs alfa-beta,
 - ``StopRequest`` — przerwanie bieżącego liczenia,
 - ``QuitRequest`` — zakończenie procesu.

Odpowiedzi silnika:
 - ``InfoEvent`` — po każdej ukończonej głębokości: ``SearchInfo`` z polami
   depth, score (cp lub mat), pv, multi_pv, nodes, nps, cutoffs, tt_hits, time_ms,
 - ``ProgressEvent`` — co ok. 100 ms (liczniki na żywo w trakcie głębokości),
 - ``DoneEvent`` — koniec wyszukiwania (wynik ostatniej pełnej głębokości),
 - ``CompareEvent``, ``ErrorEvent``.

Przerwanie działa natychmiast: interfejs ustawia współdzieloną flagę
``multiprocessing.Event``, a wyszukiwanie sprawdza ją co 1024 węzły.
Proces obsługuje kolejne zapytania bez restartu.
"""

from __future__ import annotations

import multiprocessing as mp
import queue
from dataclasses import dataclass
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Event

from .board import Board
from .compare import compare_algorithms
from .search import Searcher, SearchLimits
from .types import CompareResult, SearchInfo, SearchProgress

# ----------------------------------------------------------------- zapytania


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

# ----------------------------------------------------------------- odpowiedzi


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


# ----------------------------------------------------------------- proces silnika


def _engine_main(requests: Queue[Request], responses: Queue[EngineEvent], stop_event: Event) -> None:
    """Pętla procesu silnika."""
    searcher = Searcher()
    while True:
        message = requests.get()
        # Jeśli w kolejce czeka więcej zapytań, ważne jest tylko najnowsze (chyba że to „quit”).
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
            except Exception as error:  # noqa: BLE001 — błąd raportujemy do interfejsu
                responses.put(ErrorEvent(message.id, str(error)))


def _analyze(
    searcher: Searcher, request: AnalyzeRequest, requests: Queue[Request], responses: Queue[EngineEvent], stop_event: Event
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
    """Strona interfejsu: wysyła zapytania do procesu silnika i odbiera wyniki bez blokowania."""

    def __init__(self) -> None:
        ctx = mp.get_context("spawn")  # ten sam sposób startu na Linuksie, Windowsie i macOS
        self._requests: Queue[Request] = ctx.Queue()
        self._responses: Queue[EngineEvent] = ctx.Queue()
        self._stop = ctx.Event()
        self._process = ctx.Process(
            target=_engine_main, args=(self._requests, self._responses, self._stop), daemon=True, name="TacticMind-silnik"
        )
        self._process.start()
        self._next_id = 0

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def analyze(self, fen: str, *, max_depth: int = 32, time_ms: int = 3000, multi_pv: int = 3) -> int:
        """Rozpoczyna analizę (przerywając poprzednią). Zwraca id zapytania."""
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
        """Wszystkie wiadomości, które przyszły od ostatniego wywołania (nie blokuje)."""
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
