"""Evaluation of a player's move that differs from the reference solution."""

from __future__ import annotations

from enum import Enum

import chess

from ..engine.types import EngineScore

#: A move "still clearly wins" when the evaluation after it exceeds +3 pawns…
WINNING_THRESHOLD = 300
#: …and is at most 50 cp worse than the best one.
MAX_LOSS = 50


class Alternative(Enum):
    GOOD_BUT_BETTER = "good_but_better"
    MISTAKE = "mistake"


def gives_mate(board: chess.Board, move: chess.Move) -> bool:
    """Does the move deliver mate? Such a move always solves the puzzle, even if it differs from the reference."""
    board.push(move)
    try:
        return board.is_checkmate()
    finally:
        board.pop()


def score_for(score: EngineScore, color: chess.Color) -> int:
    """Evaluation value from the perspective of the given colour (mate = ±(32000 − plies))."""
    return score.value if color == chess.WHITE else -score.value


def judge_alternative(best: EngineScore, after: EngineScore, player: chess.Color) -> Alternative:
    """Judges a move other than the reference one based on engine analysis.

    :param best: evaluation of the best move in the position before the player's move,
    :param after: evaluation of the position after the player's move,
    :param player: the player's colour.

    If the move still clearly wins (> +3) and is at most 50 cp worse than
    the best one, we do not count it as a mistake — the player gets a second chance.
    """
    best_value = score_for(best, player)
    after_value = score_for(after, player)
    if after_value > WINNING_THRESHOLD and best_value - after_value <= MAX_LOSS:
        return Alternative.GOOD_BUT_BETTER
    return Alternative.MISTAKE


# ---------------------------------------------------------------------------
# Brilliant move (!!) — a material sacrifice
# ---------------------------------------------------------------------------
_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
#: How many pawns (at least) must be given up for a move to count as a sacrifice.
SACRIFICE_MIN_LOSS = 2


def see(board: chess.Board, square: chess.Square) -> int:
    """Static exchange evaluation: how much material (in pawns) the side to move gains by capturing
    the piece on ``square``, when both sides always capture with the cheapest piece and may stop the exchange.

    The first capture must be legal (pins, check); later ones are computed in a simplified way, but with
    X-rays — removing the capturing piece from the board uncovers the pieces behind it. 0 when there is no capture.
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
            break  # the king will not step into a capture
        gains.append((_VALUES[on_square] or 100) - gains[-1])
    # Minimax from the end: each side may stop the exchange if capturing further does not pay off.
    for i in range(len(gains) - 1, 0, -1):
        gains[i - 1] = -max(-gains[i - 1], gains[i])
    return max(0, gains[0])


def _captured_value(board: chess.Board, move: chess.Move) -> int:
    victim = board.piece_at(move.to_square)
    if victim is not None:
        return _VALUES[victim.piece_type]
    return 1 if board.is_en_passant(move) else 0


def _exposed(after: chess.Board, square: chess.Square) -> int:
    """How much the opponent (the side to move in ``after``) wins by capturing the piece on ``square`` (excluding pawns and the king)."""
    piece = after.piece_at(square)
    if piece is None or piece.piece_type in (chess.PAWN, chess.KING):
        return 0
    return see(after, square)


def material_at_risk(board: chess.Board, move: chess.Move) -> int:
    """How much material (in pawns) the opponent can win right after ``move`` by capturing one of our pieces:
    the moved piece or a piece left undefended, net of what the move itself captured. 0 after a mate."""
    piece = board.piece_at(move.from_square)
    if piece is None:
        return 0
    gained = _captured_value(board, move)
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        return 0
    worst = 0
    for square, other in after.piece_map().items():
        if other.color == piece.color:
            worst = max(worst, _exposed(after, square) - gained)
    return worst


def sacrifice_loss(board: chess.Board, move: chess.Move) -> int:
    """How much material (in pawns) the move gives up **compared with the safest move** in the position.

    As on chess.com, leaving a piece en prise (e.g. ignoring an attack on the queen) or moving a defender away
    also counts as a sacrifice. But material that every move loses is not sacrificed: a trapped piece that
    takes a pawn (desperado), or saving one of two attacked pieces, gives up nothing the player had a choice about.
    Returns 0 when the opponent cannot win anything by capturing or the move delivers mate.
    """
    risk = material_at_risk(board, move)
    if risk < SACRIFICE_MIN_LOSS:
        return max(0, risk)
    safest = min(material_at_risk(board, other) for other in board.legal_moves)
    return max(0, risk - safest)


def is_sacrifice(board: chess.Board, move: chess.Move) -> bool:
    """Is the move a sacrifice (gives up a piece, not a pawn, for at least 2 pawns of material)?

    A correct move that is a sacrifice is shown by the game as "brilliant" (!!), like chess.com.
    """
    return sacrifice_loss(board, move) >= SACRIFICE_MIN_LOSS
