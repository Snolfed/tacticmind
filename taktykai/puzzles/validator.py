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


# ---------------------------------------------------------------------------
# Genialny ruch (!!) — poświęcenie materiału
# ---------------------------------------------------------------------------
_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
#: Ile pionów (co najmniej) trzeba oddać, żeby ruch uznać za poświęcenie.
SACRIFICE_MIN_LOSS = 2


def sacrifice_loss(board: chess.Board, move: chess.Move) -> int:
    """Ile materiału (w pionach) traci strona wykonująca ruch, jeśli przeciwnik zbije ruszoną figurę.

    Uproszczona wymiana na polu docelowym: zyskujemy zbitą figurę, tracimy ruszoną figurę
    (zbija ją najtańszy napastnik przeciwnika), a jeśli pole jest bronione — odbijamy tego napastnika.
    Zwraca 0, gdy przeciwnik nie może legalnie zbić ruszonej figury.
    """
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type == chess.KING:
        return 0
    moved = _VALUES[move.promotion] if move.promotion else _VALUES[piece.piece_type]
    victim = board.piece_at(move.to_square)
    gained = _VALUES[victim.piece_type] if victim else (1 if board.is_en_passant(move) else 0)
    after = board.copy(stack=False)
    after.push(move)
    captures = [m for m in after.legal_moves if m.to_square == move.to_square]
    if not captures:
        return 0
    cheapest = min(captures, key=lambda m: _VALUES[after.piece_type_at(m.from_square) or chess.KING])
    attacker = after.piece_type_at(cheapest.from_square) or chess.KING
    recapture = _VALUES[attacker] if attacker != chess.KING and after.is_attacked_by(piece.color, move.to_square) else 0
    return max(0, moved - gained - recapture)


def is_sacrifice(board: chess.Board, move: chess.Move) -> bool:
    """Czy ruch jest poświęceniem (figura, nie pion, oddana za co najmniej 2 piony materiału)?

    Poprawny ruch, który jest poświęceniem, gra pokazuje jako „genialny” (!!), jak chess.com.
    """
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type in (chess.PAWN, chess.KING):
        return False
    return sacrifice_loss(board, move) >= SACRIFICE_MIN_LOSS
