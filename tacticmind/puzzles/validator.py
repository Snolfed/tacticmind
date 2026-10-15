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


def see(board: chess.Board, square: chess.Square) -> int:
    """Wymiana na polu (static exchange evaluation): ile materiału (w pionach) zyskuje strona przy ruchu,
    bijąc figurę stojącą na ``square``, gdy obie strony biją zawsze najtańszą figurą i mogą przerwać wymianę.

    Pierwsze bicie musi być legalne (związanie, szach); dalsze liczone są uproszczenie, ale z promieniami
    rentgenowskimi — po zdjęciu bijącej figury z planszy odsłaniają się figury stojące za nią. 0, gdy nie ma bicia.
    """
    target = board.piece_at(square)
    if target is None:
        return 0
    first = [m for m in board.legal_moves if m.to_square == square]
    if not first:
        return 0
    work = board.copy(stack=False)
    side = board.turn
    gains = [_VALUES[target.piece_type] or 100]
    capture = min(first, key=lambda m: _VALUES[work.piece_type_at(m.from_square) or chess.KING] or 100)
    from_square = capture.from_square
    while True:
        on_square = work.piece_type_at(from_square) or chess.KING
        work.remove_piece_at(from_square)
        work.set_piece_at(square, chess.Piece(on_square, side))
        side = not side
        attackers = work.attackers(side, square)
        if not attackers:
            break
        from_square = min(attackers, key=lambda sq: _VALUES[work.piece_type_at(sq) or chess.KING] or 100)
        if work.piece_type_at(from_square) == chess.KING and work.attackers(not side, square):
            break  # król nie wejdzie pod bicie
        gains.append((_VALUES[on_square] or 100) - gains[-1])
    # Minimaks od końca: każda strona może przerwać wymianę, jeśli dalsze bicie jej się nie opłaca.
    for i in range(len(gains) - 1, 0, -1):
        gains[i - 1] = -max(-gains[i - 1], gains[i])
    return max(0, gains[0])


def _captured_value(board: chess.Board, move: chess.Move) -> int:
    victim = board.piece_at(move.to_square)
    if victim is not None:
        return _VALUES[victim.piece_type]
    return 1 if board.is_en_passant(move) else 0


def _exposed(after: chess.Board, square: chess.Square) -> int:
    """Ile przeciwnik (strona przy ruchu w ``after``) wygrywa, bijąc figurę na ``square`` (bez pionów i króla)."""
    piece = after.piece_at(square)
    if piece is None or piece.piece_type in (chess.PAWN, chess.KING):
        return 0
    return see(after, square)


def _doomed(board: chess.Board, square: chess.Square) -> bool:
    """Czy figury na ``square`` nie da się już uratować — każdy ruch ją oddaje (wtedy to nie poświęcenie)."""
    for move in board.legal_moves:
        target = move.to_square if move.from_square == square else square
        after = board.copy(stack=False)
        after.push(move)
        if _exposed(after, target) - _captured_value(board, move) < SACRIFICE_MIN_LOSS:
            return False
    return True


def sacrifice_loss(board: chess.Board, move: chess.Move) -> int:
    """Ile materiału (w pionach) oddaje ruch: przeciwnik może zbić ruszoną figurę albo figurę zostawioną bez obrony.

    Jak na chess.com, poświęceniem jest też zostawienie figury pod biciem (np. zignorowanie ataku na hetmana)
    albo odejście obrońcą — ale nie oddanie figury, której i tak nie dało się uratować (desperado).
    Zwraca 0, gdy przeciwnik nie może nic wygrać biciem albo ruch daje mata.
    """
    piece = board.piece_at(move.from_square)
    if piece is None:
        return 0
    gained = _captured_value(board, move)
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        return 0
    loss = 0
    for square, other in after.piece_map().items():
        if other.color != piece.color:
            continue
        given = _exposed(after, square) - gained
        if given <= loss:
            continue
        origin = move.from_square if square == move.to_square else square
        if board.piece_at(origin) == other and _exposed_before(board, origin) >= given and _doomed(board, origin):
            continue  # figura i tak była stracona
        loss = given
    return loss


def _exposed_before(board: chess.Board, square: chess.Square) -> int:
    """Ile przeciwnik wygrałby biciem figury na ``square`` przed ruchem (gdyby to on był przy ruchu)."""
    if board.is_check():
        return 0
    null = board.copy(stack=False)
    null.push(chess.Move.null())
    return _exposed(null, square)


def is_sacrifice(board: chess.Board, move: chess.Move) -> bool:
    """Czy ruch jest poświęceniem (oddaje figurę, nie piona, za co najmniej 2 piony materiału)?

    Poprawny ruch, który jest poświęceniem, gra pokazuje jako „genialny” (!!), jak chess.com.
    """
    return sacrifice_loss(board, move) >= SACRIFICE_MIN_LOSS
