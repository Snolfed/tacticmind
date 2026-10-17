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
brilliant (!!)      ≤ 1          a real piece sacrifice; without it the position was not winning
great (!)           0            the only good move: the second best loses ≥ 15 pts
best                0            the move suggested by the engine
excellent           ≤ 2
good                ≤ 5
book                —            a move from the opening book
inaccuracy (?!)     ≤ 10
mistake (?)         ≤ 20
blunder (??)        > 20
==================  ===========  =================================================

Move accuracy (%) is also as on Lichess: ``103.1668 · e^(−0.04354 · drop) − 3.1669``.
Game accuracy is also Lichess's: the average of the volatility-weighted mean and the **harmonic** mean of
the move accuracies. A plain mean hides blunders among many easy moves (six blunders in a long game still
gave ~87%); the harmonic mean is pulled down hard by every very bad move.
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
#: A brilliant move must be the engine's move or practically equal to it.
BRILLIANT_MAX_DROP = 1.0
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


#: Evaluation loss counted as one point of "drop" (see ``move_loss``), the cap on evaluations, and what a forced mate
#: counts as: more than any evaluation, so throwing a mate away is at least a mistake even when the game stays won.
CP_PER_POINT = 40
CP_CAP = 5000
MATE_CP = CP_CAP + 600


def move_loss(best_value: int, played_value: int) -> float:
    """How bad the move is compared with the best one, in percentage points: the winning-chance drop, but at least the
    evaluation it threw away (``CP_PER_POINT`` centipawns a point). In a decided game the winning chance hardly moves,
    so without this, giving away a queen at +10 (or at −10), or a forced mate, would be "excellent"."""

    def centipawns(value: int) -> int:
        if value > MATE_BOUND:
            return MATE_CP
        if value < -MATE_BOUND:
            return -MATE_CP
        return max(-CP_CAP, min(CP_CAP, value))

    return max(win_drop(best_value, played_value), max(0, centipawns(best_value) - centipawns(played_value)) / CP_PER_POINT)


def move_accuracy(drop: float) -> float:
    """Move accuracy in % (100 = no loss)."""
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * drop) - 3.1669))


#: Lowest move accuracy used in the harmonic mean (one 0% move would otherwise make the whole game 0%).
HARMONIC_FLOOR = 1.0


def game_accuracy(accuracies: list[float], weights: list[float] | None = None) -> float | None:
    """Game accuracy as on Lichess: (weighted mean + harmonic mean) / 2 of the move accuracies."""
    if not accuracies:
        return None
    if weights is None or len(weights) != len(accuracies):
        weights = [1.0] * len(accuracies)
    weighted = sum(a * w for a, w in zip(accuracies, weights)) / sum(weights)
    harmonic = len(accuracies) / sum(1 / max(HARMONIC_FLOOR, a) for a in accuracies)
    return (weighted + harmonic) / 2


def volatility_weights(win_percents: list[float]) -> list[float]:
    """Weight of each move in the game accuracy (Lichess): moves in sharp phases of the game count more.

    :param win_percents: White's winning chance before the first move and after every move (moves + 1 values).
    :return: one weight per move: the standard deviation of the winning chance in a window around it, in 0.5–12.
    """
    moves = len(win_percents) - 1
    if moves <= 0:
        return []
    size = max(2, min(8, moves // 10))
    windows = [win_percents[:size]] * (size - 2) + [win_percents[i : i + size] for i in range(len(win_percents) - size + 1)]
    weights = []
    for window in windows[:moves]:
        mean = sum(window) / len(window)
        deviation = math.sqrt(sum((x - mean) ** 2 for x in window) / len(window))
        weights.append(max(0.5, min(12.0, deviation)))
    return weights


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
    :param recapture: an obvious capture (a recapture, or taking a piece left hanging), so never "great".
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
