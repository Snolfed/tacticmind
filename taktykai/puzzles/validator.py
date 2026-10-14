"""Ocena ruchu gracza, który różni się od rozwiązania wzorcowego."""

from __future__ import annotations

from enum import Enum

import chess

from ..engine.types import EngineScore

#: Ruch „nadal wyraźnie wygrywa”, gdy ocena po nim przekracza +3 piony…
WINNING_THRESHOLD = 300
#: …i jest najwyżej 50 cp gorsza od najlepszej.
MAX_LOSS = 50


class Alternative(Enum):
    GOOD_BUT_BETTER = "good_but_better"
    MISTAKE = "mistake"


def gives_mate(board: chess.Board, move: chess.Move) -> bool:
    """Czy ruch daje mata? Taki ruch zawsze rozwiązuje zadanie, nawet jeśli różni się od wzorca."""
    board.push(move)
    try:
        return board.is_checkmate()
    finally:
        board.pop()


def score_for(score: EngineScore, color: chess.Color) -> int:
    """Wartość oceny z perspektywy wskazanego koloru (mat = ±(32000 − półruchy))."""
    return score.value if color == chess.WHITE else -score.value


def judge_alternative(best: EngineScore, after: EngineScore, player: chess.Color) -> Alternative:
    """Ocena ruchu innego niż wzorcowy na podstawie analizy silnika.

    :param best: ocena najlepszego ruchu w pozycji przed ruchem gracza,
    :param after: ocena pozycji po ruchu gracza,
    :param player: kolor gracza.

    Jeśli ruch nadal wyraźnie wygrywa (> +3) i jest najwyżej 50 cp gorszy od
    najlepszego, nie liczymy go jako błędu — gracz dostaje drugą szansę.
    """
    best_value = score_for(best, player)
    after_value = score_for(after, player)
    if after_value > WINNING_THRESHOLD and best_value - after_value <= MAX_LOSS:
        return Alternative.GOOD_BUT_BETTER
    return Alternative.MISTAKE
