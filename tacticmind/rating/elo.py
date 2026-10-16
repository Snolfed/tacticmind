"""The player's Elo rating.

A puzzle is treated as an opponent whose rating equals the puzzle's rating.

 - expected score:  E = 1 / (1 + 10^((R_puzzle − R_player) / 400))
 - rating change:   ΔR = K · (S − E)

The K factor decreases with experience: 60 during calibration (first 10 puzzles),
then 32, and 20 after 50 puzzles.
"""

from __future__ import annotations

import math

START_RATING = 1200.0
CALIBRATION_GAMES = 10


def expected_score(player_rating: float, puzzle_rating: float) -> float:
    """Chance of solving the puzzle according to the Elo model."""
    return 1.0 / (1.0 + 10 ** ((puzzle_rating - player_rating) / 400.0))


def k_factor(games_played: int) -> int:
    """K = 60 during calibration (first 10 puzzles), then 32, 20 after 50 puzzles."""
    if games_played < CALIBRATION_GAMES:
        return 60
    if games_played < 50:
        return 32
    return 20


def rating_delta(player_rating: float, puzzle_rating: float, score: float, k: float) -> float:
    """ΔR = K · (S − E)."""
    return k * (score - expected_score(player_rating, puzzle_rating))


def update_elo(player_rating: float, puzzle_rating: float, score: float, games_played: int) -> tuple[float, float]:
    """New rating and change after one puzzle."""
    delta = rating_delta(player_rating, puzzle_rating, score, k_factor(games_played))
    return player_rating + delta, delta


def target_rating_for(player_rating: float, success_chance: float) -> float:
    """Puzzle rating at which the chance of success equals ``success_chance`` (inverse of the E formula)."""
    return player_rating - 400.0 * math.log10(success_chance / (1.0 - success_chance))
