"""Types exchanged between the engine, the engine process and the UI.

All scores sent to the UI are from WHITE's perspective.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .constants import WHITE

#: Mate value. A score of MATE - n means mate in n plies from the root.
MATE = 32000
#: Scores with absolute value greater than MATE_BOUND are mate scores.
MATE_BOUND = MATE - 1000
INFINITY = 100_000


@dataclass(slots=True, frozen=True)
class EngineScore:
    """Position score from White's perspective."""

    #: Centipawns, or None when there is a mate.
    cp: int | None
    #: Mate in N moves (positive: White mates, negative: Black mates, 0: already checkmate).
    mate: int | None
    #: Numeric value for sorting and the eval bar (mate = ±(MATE - plies)).
    value: int


def to_white_score(score: int, side_to_move: int) -> EngineScore:
    """Convert an internal score (side to move's perspective) to a score from White's perspective."""
    value = score if side_to_move == WHITE else -score
    if abs(value) > MATE_BOUND:
        plies = MATE - abs(value)
        moves = (plies + 1) // 2
        return EngineScore(None, moves if value > 0 else -moves, value)
    return EngineScore(value, None, value)


def format_score(score: EngineScore) -> str:
    """Score formatted like chess.com: ``+1.5``, ``-0.3``, ``M3``, ``-M2``."""
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
    """One MultiPV line: a candidate move with its score and line (UCI)."""

    move: str
    score: EngineScore
    pv: list[str]


Bound = Literal["exact", "upper", "lower"]
Terminal = Literal["checkmate", "stalemate"]
VariantName = Literal["minimax", "alphabeta", "alphabeta-ordered"]


@dataclass(slots=True)
class TreeNode:
    """A node of the search mini tree (first two levels) for visualisation."""

    move: str
    #: Score from White's perspective; None for pruned branches (never searched).
    score: EngineScore | None
    #: 'exact' - exact, 'upper' - at most (≤), 'lower' - at least (≥).
    bound: Bound = "exact"
    #: Branch pruned by alpha-beta.
    pruned: bool = False
    #: Node resolved immediately by the transposition table.
    tt_cut: bool = False
    children: list[TreeNode] = field(default_factory=list)


@dataclass(slots=True)
class SearchInfo:
    """Message sent after each completed depth."""

    id: int
    fen: str
    depth: int
    seldepth: int
    #: Best line score in centipawns (White's perspective), or None for a mate.
    score_cp: int | None
    #: Mate in N (White's perspective), or None.
    mate_in: int | None
    score: EngineScore
    best_move: str
    pv: list[str]
    multi_pv: list[PvLine]
    nodes: int
    qnodes: int
    nps: int
    #: Number of alpha-beta cutoffs (beta cutoffs).
    cutoffs: int
    tt_hits: int
    #: Percentage of generated moves that alpha-beta skipped.
    pruned_percent: float
    time_ms: int
    tree: list[TreeNode]
    #: Terminal position: checkmate or stalemate (nothing to search then).
    terminal: Terminal | None = None


@dataclass(slots=True)
class SearchProgress:
    """Live counters while searching one depth."""

    id: int
    depth: int
    nodes: int
    nps: int
    cutoffs: int
    tt_hits: int
    time_ms: int


@dataclass(slots=True)
class CompareVariant:
    """Result of one algorithm in comparison mode."""

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
