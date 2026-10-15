"""Ocena ruchów jak w „Game Review” na chess.com: najlepszy, świetny, dobry, niedokładność, błąd…

Podstawą jest **szansa na wygraną** (w %) z perspektywy gracza, liczona z oceny silnika wzorem
z Lichess: ``W(cp) = 50 + 50 · (2 / (1 + e^(−0.00368208 · cp)) − 1)``. Przy ocenie 0 to 50%,
przy +3 pionach ok. 87%, przy macie 100%. Ruch oceniamy po tym, o ile **spadła** szansa na wygraną
w porównaniu z najlepszym ruchem — utrata pół piona w wyrównanej pozycji boli bardziej niż przy
przewadze +8, i ta skala to uwzględnia.

Progi spadku szansy na wygraną (punkty procentowe):

==================  ===========  =================================================
Klasa               Spadek       Uwagi
==================  ===========  =================================================
genialny (!!)       ≤ 2          najlepszy lub prawie najlepszy ruch i poświęcenie figury
świetny (!)         0            jedyny dobry ruch: drugi najlepszy traci ≥ 15 pkt
najlepszy           0            ruch wskazany przez silnik
znakomity           ≤ 2
dobry               ≤ 5
z teorii            —            ruch z książki otwarć
niedokładność (?!)  ≤ 10
błąd (?)            ≤ 20
przeoczenie (??)    > 20
==================  ===========  =================================================

Celność ruchu (%) też jak na Lichess: ``103.1668 · e^(−0.04354 · spadek) − 3.1669``,
celność partii to średnia celności ruchów.
"""

from __future__ import annotations

import math
from typing import Literal

import chess

from ..engine.types import MATE_BOUND, EngineScore

Classification = Literal["brilliant", "great", "best", "excellent", "good", "book", "inaccuracy", "mistake", "blunder"]

#: Kolejność do podsumowania partii (od najlepszych).
CLASSES: tuple[Classification, ...] = ("brilliant", "great", "best", "excellent", "good", "book", "inaccuracy", "mistake", "blunder")
#: Klasy, po których trener zatrzymuje partię i proponuje cofnięcie ruchu.
SERIOUS: frozenset[str] = frozenset({"mistake", "blunder"})
#: Klasy uznawane za błąd (trener podaje lepszy ruch).
WEAK: frozenset[str] = frozenset({"inaccuracy", "mistake", "blunder"})

GREAT_GAP = 15.0
BRILLIANT_MAX_DROP = 2.0
#: Poświęcenie w pozycji „wygranej na 97%” nie jest genialne — wygrywa wszystko.
BRILLIANT_MAX_WIN = 97.0


def score_for(score: EngineScore, color: chess.Color) -> int:
    """Ocena (wartość liczbowa, mat = ±(32000 − półruchy)) z perspektywy ``color``."""
    return score.value if color == chess.WHITE else -score.value


def win_percent(value: int) -> float:
    """Szansa na wygraną (0–100) dla oceny z perspektywy gracza."""
    if value > MATE_BOUND:
        return 100.0
    if value < -MATE_BOUND:
        return 0.0
    cp = max(-1500, min(1500, value))
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def win_drop(best_value: int, played_value: int) -> float:
    """O ile punktów procentowych ruch zmniejszył szansę na wygraną względem najlepszego (≥ 0)."""
    return max(0.0, win_percent(best_value) - win_percent(played_value))


def move_accuracy(drop: float) -> float:
    """Celność ruchu w % (100 = bez strat)."""
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
    """Klasa ruchu.

    :param drop: spadek szansy na wygraną względem najlepszego ruchu,
    :param is_best: czy to ruch wskazany przez silnik,
    :param book: ruch z teorii otwarć,
    :param sacrifice: ruch oddaje materiał (patrz ``puzzles.validator.is_sacrifice``),
    :param second_drop: o ile gorszy jest drugi najlepszy ruch (do „świetnego” ruchu),
    :param win_before: szansa na wygraną przy najlepszej grze (genialne poświęcenie nie w pozycji już wygranej),
    :param recapture: odbicie figury — oczywiste, więc nigdy nie jest „świetne”.
    """
    if book:
        return "book"
    if sacrifice and drop <= BRILLIANT_MAX_DROP and win_before < BRILLIANT_MAX_WIN and win_before - drop > 40:
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
