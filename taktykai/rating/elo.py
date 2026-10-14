"""Ranking Elo gracza.

Zadanie traktujemy jak przeciwnika o rankingu równym rankingowi zadania.

 - oczekiwany wynik:  E = 1 / (1 + 10^((R_zadania − R_gracza) / 400))
 - zmiana rankingu:   ΔR = K · (S − E)

Współczynnik K maleje z doświadczeniem: 60 w kalibracji (pierwsze 10 zadań),
potem 32, a po 50 zadaniach 20.
"""

from __future__ import annotations

import math

START_RATING = 1200.0
CALIBRATION_GAMES = 10


def expected_score(player_rating: float, puzzle_rating: float) -> float:
    """Szansa na rozwiązanie zadania wg modelu Elo."""
    return 1.0 / (1.0 + 10 ** ((puzzle_rating - player_rating) / 400.0))


def k_factor(games_played: int) -> int:
    """K = 60 w kalibracji (pierwsze 10 zadań), potem 32, po 50 zadaniach 20."""
    if games_played < CALIBRATION_GAMES:
        return 60
    if games_played < 50:
        return 32
    return 20


def rating_delta(player_rating: float, puzzle_rating: float, score: float, k: float) -> float:
    """ΔR = K · (S − E)."""
    return k * (score - expected_score(player_rating, puzzle_rating))


def update_elo(player_rating: float, puzzle_rating: float, score: float, games_played: int) -> tuple[float, float]:
    """Nowy ranking i zmiana po jednym zadaniu."""
    delta = rating_delta(player_rating, puzzle_rating, score, k_factor(games_played))
    return player_rating + delta, delta


def target_rating_for(player_rating: float, success_chance: float) -> float:
    """Ranking zadania, przy którym szansa na sukces wynosi ``success_chance`` (odwrotność wzoru na E)."""
    return player_rating - 400.0 * math.log10(success_chance / (1.0 - success_chance))
