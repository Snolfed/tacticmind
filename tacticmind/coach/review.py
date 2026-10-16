"""Move review as in chess.com's "Game Review": best, great, good, inaccuracy, mistake...

The basis is the player's **winning chance** (in %), computed from the engine score with the
Lichess formula: ``W(cp) = 50 + 50 · (2 / (1 + e^(−0.00368208 · cp)) − 1)``. A score of 0 gives 50%,
+3 pawns about 87%, mate 100%. A move is judged by how much it **lowered** the winning chance
compared with the best move - losing half a pawn in a level position hurts more than with
a +8 advantage, and this scale accounts for that.

Winning-chance drop thresholds (percentage points):

==================  ===========  =================================================
Class               Drop         Notes
==================  ===========  =================================================
brilliant (!!)      ≤ 2          a piece sacrifice without which the position was not winning
great (!)           0            the only good move: the second best loses ≥ 15 pts
best                0            the move suggested by the engine
excellent           ≤ 2
good                ≤ 5
book                —            a move from the opening book
inaccuracy (?!)     ≤ 10
mistake (?)         ≤ 20
blunder (??)        > 20
==================  ===========  =================================================

Move accuracy (%) is also as on Lichess: ``103.1668 · e^(−0.04354 · drop) − 3.1669``;
game accuracy is the mean of the move accuracies.
"""

from __future__ import annotations

import math
from typing import Literal

import chess

from ..engine.types import MATE_BOUND, EngineScore

Classification = Literal["brilliant", "great", "best", "excellent", "good", "book", "inaccuracy", "mistake", "blunder"]

#: Order for the game summary (best first).
CLASSES: tuple[Classification, ...] = ("brilliant", "great", "best", "excellent", "good", "book", "inaccuracy", "mistake", "blunder")
#: Classes after which the coach pauses the game and offers to take the move back.
SERIOUS: frozenset[str] = frozenset({"mistake", "blunder"})
#: Classes counted as errors (the coach shows a better move).
WEAK: frozenset[str] = frozenset({"inaccuracy", "mistake", "blunder"})

GREAT_GAP = 15.0
BRILLIANT_MAX_DROP = 2.0
#: A sacrifice is not brilliant when the position is 97% winning even without it - then everything wins.
#: What counts is the second best move: a sacrifice that itself leads to mate can be brilliant.
BRILLIANT_MAX_WIN = 97.0


def score_for(score: EngineScore, color: chess.Color) -> int:
    """Score (numeric value, mate = ±(32000 − plies)) from the perspective of ``color``."""
    return score.value if color == chess.WHITE else -score.value


def win_percent(value: int) -> float:
    """Winning chance (0–100) for a score from the player's perspective."""
    if value > MATE_BOUND:
        return 100.0
    if value < -MATE_BOUND:
        return 0.0
    cp = max(-1500, min(1500, value))
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def win_drop(best_value: int, played_value: int) -> float:
    """By how many percentage points the move lowered the winning chance compared with the best move (≥ 0)."""
    return max(0.0, win_percent(best_value) - win_percent(played_value))


def move_accuracy(drop: float) -> float:
    """Move accuracy in % (100 = no loss)."""
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * drop) - 3.1669))


def game_accuracy(accuracies: list[float]) -> float | None:
    return sum(accuracies) / len(accuracies) if accuracies else None


def classify(
    drop: float,
    *,
    is_best: bool,
    book: bool = False,
    sacrifice: bool = False,
    second_drop: float | None = None,
    win_before: float = 50.0,
    recapture: bool = False,
) -> Classification:
    """Class of the move.

    :param drop: winning-chance drop compared with the best move,
    :param is_best: whether this is the move suggested by the engine,
    :param book: a move from opening theory,
    :param sacrifice: the move gives up material (see ``puzzles.validator.is_sacrifice``),
    :param second_drop: how much worse the second best move is (for a "great" move),
    :param win_before: winning chance with best play; without the sacrifice (with the second best move,
        ``win_before − second_drop``) the position must not already be winning, and after the move it must not be lost,
    :param recapture: a recapture - obvious, so never "great".
    """
    if book:
        return "book"
    win_without = win_before - second_drop if second_drop is not None else win_before
    if sacrifice and drop <= BRILLIANT_MAX_DROP and win_without < BRILLIANT_MAX_WIN and win_before - drop > 40:
        return "brilliant"
    if is_best:
        if second_drop is not None and second_drop >= GREAT_GAP and not recapture:
            return "great"
        return "best"
    if drop <= 2:
        return "excellent"
    if drop <= 5:
        return "good"
    if drop <= 10:
        return "inaccuracy"
    if drop <= 20:
        return "mistake"
    return "blunder"
