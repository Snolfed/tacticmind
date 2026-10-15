"""Siła gry trenera zależna od wybranego Elo.

Silnik zawsze szuka najlepszych ruchów, ale słabszy trener:
 - liczy płycej (mniejsza głębokość i krótszy czas),
 - wybiera ruch losowo spośród kilku najlepszych (MultiPV) z prawdopodobieństwem
   p(ruch) ~ exp((ocena − ocena najlepszego) / T) — rozkład softmax z „temperaturą” T w centypionach:
   przy dużym T ruchy gorsze o pół piona są prawie tak samo prawdopodobne jak najlepszy,
   przy małym T trener prawie zawsze gra najlepszy ruch,
 - czasem robi zupełnie przypadkowy ruch („przeoczenie”), jak początkujący gracz.

Parametry zmieniają się płynnie z Elo (400–2000). Dobrane są tak, żeby różnica między poziomami
była wyraźna, ale Elo trenera jest przybliżone — nie da się go dokładnie zmierzyć bez tysięcy partii
z graczami o znanym rankingu.
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
    #: Maksymalna głębokość przeszukiwania (półruchy).
    depth: int
    #: Limit czasu na ruch (ms).
    time_ms: int
    #: Ile najlepszych ruchów silnik ocenia dokładnie (spośród nich trener losuje).
    multi_pv: int
    #: Temperatura losowania w centypionach.
    temperature: float
    #: Szansa na zupełnie przypadkowy ruch.
    blunder: float


def clamp_elo(elo: float) -> int:
    return int(min(ELO_MAX, max(ELO_MIN, round(elo))))


def strength_for(elo: float) -> Strength:
    """Parametry gry dla danego Elo (400 = początkujący, 2000 = silny gracz klubowy)."""
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
    """Wybór ruchu trenera.

    :param lines: ruchy kandydujące (UCI) z oceną z perspektywy trenera (w centypionach, mat = ±32000),
    :param legal: wszystkie legalne ruchy (do „przeoczeń”).
    """
    if not lines:
        return rng.choice(legal)
    if legal and rng.random() < strength.blunder:
        return rng.choice(legal)
    best = max(score for _, score in lines)
    weights = [math.exp(max(-50.0, (score - best) / strength.temperature)) for _, score in lines]
    return rng.choices([move for move, _ in lines], weights=weights, k=1)[0]


def describe_level(elo: int) -> str:
    """Klucz tłumaczenia z opisem poziomu (np. „Początkujący”)."""
    if elo < 800:
        return "coach.level.beginner"
    if elo < 1200:
        return "coach.level.novice"
    if elo < 1600:
        return "coach.level.intermediate"
    if elo < 1900:
        return "coach.level.advanced"
    return "coach.level.expert"
