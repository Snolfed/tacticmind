"""Typy wymieniane między silnikiem, procesem silnika i interfejsem.

Wszystkie oceny wysyłane do interfejsu są z perspektywy BIAŁYCH.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .constants import WHITE

#: Wartość mata. Wynik MATE - n oznacza mata za n półruchów od korzenia.
MATE = 32000
#: Wyniki o module większym niż MATE_BOUND są wynikami matowymi.
MATE_BOUND = MATE - 1000
INFINITY = 100_000


@dataclass(slots=True, frozen=True)
class EngineScore:
    """Ocena pozycji z perspektywy białych."""

    #: Centypiony albo None, gdy jest mat.
    cp: int | None
    #: Mat w N ruchów (dodatni: białe matują, ujemny: czarne matują, 0: pozycja już matowa).
    mate: int | None
    #: Wartość liczbowa do sortowania i paska oceny (mat = ±(MATE - półruchy)).
    value: int


def to_white_score(score: int, side_to_move: int) -> EngineScore:
    """Zamiana wyniku wewnętrznego (perspektywa strony na ruchu) na ocenę z perspektywy białych."""
    value = score if side_to_move == WHITE else -score
    if abs(value) > MATE_BOUND:
        plies = MATE - abs(value)
        moves = (plies + 1) // 2
        return EngineScore(None, moves if value > 0 else -moves, value)
    return EngineScore(value, None, value)


def format_score(score: EngineScore) -> str:
    """Ocena jak na chess.com: ``+1.5``, ``-0.3``, ``M3``, ``-M2``."""
    if score.mate is not None:
        if score.mate == 0:
            return "1-0" if score.value > 0 else "0-1"
        return f"M{score.mate}" if score.mate > 0 else f"-M{-score.mate}"
    pawns = (score.cp or 0) / 100
    if abs(pawns) < 0.05:
        return "0.0"
    return f"{pawns:+.1f}"


@dataclass(slots=True)
class PvLine:
    """Jedna linia MultiPV: ruch kandydujący z oceną i wariantem (UCI)."""

    move: str
    score: EngineScore
    pv: list[str]


Bound = Literal["exact", "upper", "lower"]
Terminal = Literal["checkmate", "stalemate"]
VariantName = Literal["minimax", "alphabeta", "alphabeta-ordered"]


@dataclass(slots=True)
class TreeNode:
    """Węzeł mini-drzewa przeszukiwania (dwa pierwsze poziomy) do wizualizacji."""

    move: str
    #: Ocena z perspektywy białych; None dla gałęzi odciętych (w ogóle nieliczonych).
    score: EngineScore | None
    #: 'exact' — dokładna, 'upper' — co najwyżej (≤), 'lower' — co najmniej (≥).
    bound: Bound = "exact"
    #: Gałąź odcięta przez alfa-betę.
    pruned: bool = False
    #: Węzeł rozstrzygnięty od razu przez tablicę transpozycji.
    tt_cut: bool = False
    children: list[TreeNode] = field(default_factory=list)


@dataclass(slots=True)
class SearchInfo:
    """Wiadomość wysyłana po każdej ukończonej głębokości."""

    id: int
    fen: str
    depth: int
    seldepth: int
    #: Ocena najlepszej linii w centypionach (perspektywa białych) albo None przy macie.
    score_cp: int | None
    #: Mat w N (perspektywa białych) albo None.
    mate_in: int | None
    score: EngineScore
    best_move: str
    pv: list[str]
    multi_pv: list[PvLine]
    nodes: int
    qnodes: int
    nps: int
    #: Liczba cięć alfa-beta (beta cutoffs).
    cutoffs: int
    tt_hits: int
    #: Jaki odsetek wygenerowanych ruchów alfa-beta pominęła.
    pruned_percent: float
    time_ms: int
    tree: list[TreeNode]
    #: Pozycja końcowa: mat albo pat (wtedy nie ma czego liczyć).
    terminal: Terminal | None = None


@dataclass(slots=True)
class SearchProgress:
    """Liczniki na żywo w trakcie liczenia jednej głębokości."""

    id: int
    depth: int
    nodes: int
    nps: int
    cutoffs: int
    tt_hits: int
    time_ms: int


@dataclass(slots=True)
class CompareVariant:
    """Wynik jednego algorytmu w trybie porównawczym."""

    name: VariantName
    nodes: int
    time_ms: float
    cutoffs: int
    score: EngineScore
    best_move: str


@dataclass(slots=True)
class CompareResult:
    fen: str
    depth: int
    minimax: CompareVariant | None
    alpha_beta: CompareVariant
    alpha_beta_ordered: CompareVariant
