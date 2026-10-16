"""The coach's playing strength, depending on the chosen Elo.

The engine always looks for the best moves, but a weaker coach:
 - searches shallower (lower depth and less time),
 - picks a move at random from the few best ones (MultiPV) with probability
   p(move) ~ exp((score − best score) / T) - a softmax distribution with "temperature" T in centipawns:
   with a high T, moves half a pawn worse are almost as likely as the best one,
   with a low T, the coach almost always plays the best move,
 - sometimes plays a completely random move (a "blunder"), like a beginner.

The parameters change smoothly with Elo (400–2000). They are tuned so that the difference between levels
is clear, but the coach's Elo is approximate - it cannot be measured precisely without thousands of games
against players with a known rating.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

ELO_MIN = 400
ELO_MAX = 2000
ELO_STEP = 100


@dataclass(frozen=True)
class Strength:
    elo: int
    #: Maximum search depth (plies).
    depth: int
    #: Time limit per move (ms).
    time_ms: int
    #: How many best moves the engine evaluates exactly (the coach picks among them).
    multi_pv: int
    #: Sampling temperature in centipawns.
    temperature: float
    #: Chance of a completely random move.
    blunder: float


def clamp_elo(elo: float) -> int:
    return int(min(ELO_MAX, max(ELO_MIN, round(elo))))


def strength_for(elo: float) -> Strength:
    """Playing parameters for a given Elo (400 = beginner, 2000 = strong club player)."""
    elo = clamp_elo(elo)
    x = (elo - ELO_MIN) / (ELO_MAX - ELO_MIN)  # 0 … 1
    depth = 1 if elo < 800 else 2 if elo < 1200 else 3 if elo < 1600 else 4 if elo < 1900 else 5
    return Strength(
        elo=elo,
        depth=depth,
        time_ms=int(400 + 2400 * x),
        multi_pv=max(2, round(8 - 6 * x)),
        temperature=5 + 300 * (1 - x) ** 2,
        blunder=0.25 * (1 - x) ** 2,
    )


def choose_move(lines: list[tuple[str, int]], legal: list[str], strength: Strength, rng: random.Random) -> str:
    """Choose the coach's move.

    :param lines: candidate moves (UCI) with a score from the coach's perspective (in centipawns, mate = ±32000),
    :param legal: all legal moves (for "blunders").
    """
    if not lines:
        return rng.choice(legal)
    if legal and rng.random() < strength.blunder:
        return rng.choice(legal)
    best = max(score for _, score in lines)
    weights = [math.exp(max(-50.0, (score - best) / strength.temperature)) for _, score in lines]
    return rng.choices([move for move, _ in lines], weights=weights, k=1)[0]


def describe_level(elo: int) -> str:
    """Translation key describing the level (e.g. "Beginner")."""
    if elo < 800:
        return "coach.level.beginner"
    if elo < 1200:
        return "coach.level.novice"
    if elo < 1600:
        return "coach.level.intermediate"
    if elo < 1900:
        return "coach.level.advanced"
    return "coach.level.expert"
