"""Generator ruchów dla planszy 0x88, wykrywanie szacha/mata/pata i perft.

Generujemy ruchy pseudolegalne (zgodne z ruchem figur, ale mogące zostawić
własnego króla w szachu), a legalność sprawdzamy po wykonaniu ruchu: jeśli
nasz król jest atakowany, ruch cofamy. To prostsze i mniej podatne na błędy
niż wykrywanie związań przed wykonaniem ruchu.
"""

from __future__ import annotations

from collections.abc import Callable

from .board import Board
from .constants import (
    BISHOP,
    BISHOP_RAYS,
    CASTLE_BK,
    CASTLE_BQ,
    CASTLE_WK,
    CASTLE_WQ,
    EMPTY,
    FLAG_CAPTURE,
    FLAG_CASTLE,
    FLAG_DOUBLE,
    FLAG_EP,
    KING,
    KING_TARGETS,
    KNIGHT,
    KNIGHT_TARGETS,
    PAWN,
    PAWN_ATTACKERS,
    QUEEN,
    QUEEN_RAYS,
    ROOK,
    ROOK_RAYS,
    SQUARES,
    WHITE,
    square_name,
)


def is_square_attacked(board: Board, s: int, by: int) -> bool:
    """Czy pole ``s`` jest atakowane przez stronę ``by``?"""
    sq = board.sq
    pawn = (by << 3) | PAWN
    for f in PAWN_ATTACKERS[by][s]:
        if sq[f] == pawn:
            return True
    knight = (by << 3) | KNIGHT
    for f in KNIGHT_TARGETS[s]:
        if sq[f] == knight:
            return True
    king = (by << 3) | KING
    for f in KING_TARGETS[s]:
        if sq[f] == king:
            return True
    # Figury dalekosiężne: idziemy promieniem aż do pierwszej przeszkody.
    bishop = (by << 3) | BISHOP
    queen = (by << 3) | QUEEN
    for ray in BISHOP_RAYS[s]:
        for f in ray:
            p = sq[f]
            if p:
                if p == bishop or p == queen:
                    return True
                break
    rook = (by << 3) | ROOK
    for ray in ROOK_RAYS[s]:
        for f in ray:
            p = sq[f]
            if p:
                if p == rook or p == queen:
                    return True
                break
    return False


def in_check(board: Board) -> bool:
    """Czy strona na ruchu jest w szachu?"""
    return is_square_attacked(board, board.kings[board.side], board.side ^ 1)


def generate_moves(board: Board, captures_only: bool = False) -> list[int]:
    """Ruchy pseudolegalne strony na ruchu.

    :param captures_only: tylko bicia i promocje (dla quiescence search).
    """
    moves: list[int] = []
    add = moves.append
    sq = board.sq
    us = board.side
    forward = 16 if us == WHITE else -16
    start_rank = 1 if us == WHITE else 6
    promo_rank = 7 if us == WHITE else 0
    ep = board.ep

    for frm in SQUARES:
        piece = sq[frm]
        if not piece or (piece >> 3) != us:
            continue
        kind = piece & 7

        if kind == PAWN:
            one = frm + forward
            if not (one & 0x88) and sq[one] == EMPTY:
                if (one >> 4) == promo_rank:
                    # Promocja na wszystkie 4 figury (hetman pierwszy).
                    for promo in (QUEEN, ROOK, BISHOP, KNIGHT):
                        add(frm | (one << 7) | (promo << 14))
                elif not captures_only:
                    add(frm | (one << 7))
                    two = one + forward
                    if (frm >> 4) == start_rank and sq[two] == EMPTY:
                        add(frm | (two << 7) | FLAG_DOUBLE)
            for to in (one - 1, one + 1):
                if to & 0x88:
                    continue
                target = sq[to]
                if target and (target >> 3) != us:
                    if (to >> 4) == promo_rank:
                        for promo in (QUEEN, ROOK, BISHOP, KNIGHT):
                            add(frm | (to << 7) | (promo << 14) | FLAG_CAPTURE)
                    else:
                        add(frm | (to << 7) | FLAG_CAPTURE)
                elif to == ep:
                    add(frm | (to << 7) | FLAG_EP)
            continue

        if kind == KNIGHT or kind == KING:
            for to in KNIGHT_TARGETS[frm] if kind == KNIGHT else KING_TARGETS[frm]:
                target = sq[to]
                if target == EMPTY:
                    if not captures_only:
                        add(frm | (to << 7))
                elif (target >> 3) != us:
                    add(frm | (to << 7) | FLAG_CAPTURE)
            continue

        # Goniec, wieża, hetman: przesuwamy się promieniem do pierwszej przeszkody.
        rays = BISHOP_RAYS[frm] if kind == BISHOP else ROOK_RAYS[frm] if kind == ROOK else QUEEN_RAYS[frm]
        for ray in rays:
            for to in ray:
                target = sq[to]
                if target == EMPTY:
                    if not captures_only:
                        add(frm | (to << 7))
                else:
                    if (target >> 3) != us:
                        add(frm | (to << 7) | FLAG_CAPTURE)
                    break

    if not captures_only and board.castling:
        _generate_castling(board, add)
    return moves


def _generate_castling(board: Board, add: Callable[[int], None]) -> None:
    """Roszady: pola między królem a wieżą puste, król nie przechodzi przez atakowane pole."""
    sq = board.sq
    us = board.side
    them = us ^ 1
    base = 0 if us == WHITE else 112
    king_sq = base + 4
    if sq[king_sq] != (us << 3) | KING:
        return
    rook = (us << 3) | ROOK
    king_side = CASTLE_WK if us == WHITE else CASTLE_BK
    queen_side = CASTLE_WQ if us == WHITE else CASTLE_BQ
    if (
        board.castling & king_side
        and sq[base + 5] == EMPTY
        and sq[base + 6] == EMPTY
        and sq[base + 7] == rook
        and not is_square_attacked(board, king_sq, them)
        and not is_square_attacked(board, base + 5, them)
        and not is_square_attacked(board, base + 6, them)
    ):
        add(king_sq | ((base + 6) << 7) | FLAG_CASTLE)
    if (
        board.castling & queen_side
        and sq[base + 3] == EMPTY
        and sq[base + 2] == EMPTY
        and sq[base + 1] == EMPTY
        and sq[base] == rook
        and not is_square_attacked(board, king_sq, them)
        and not is_square_attacked(board, base + 3, them)
        and not is_square_attacked(board, base + 2, them)
    ):
        add(king_sq | ((base + 2) << 7) | FLAG_CASTLE)


def make_legal_move(board: Board, move: int) -> bool:
    """Wykonuje ruch; jeśli zostawia własnego króla w szachu — cofa go i zwraca False."""
    us = board.side
    board.make_move(move)
    if is_square_attacked(board, board.kings[us], us ^ 1):
        board.unmake_move()
        return False
    return True


def legal_moves(board: Board) -> list[int]:
    result = []
    for move in generate_moves(board):
        if make_legal_move(board, move):
            board.unmake_move()
            result.append(move)
    return result


def is_checkmate(board: Board) -> bool:
    return in_check(board) and not legal_moves(board)


def is_stalemate(board: Board) -> bool:
    return not in_check(board) and not legal_moves(board)


_PROMO_CHARS = ("", "", "n", "b", "r", "q")


def move_to_uci(move: int) -> str:
    """Ruch w notacji UCI, np. ``e2e4``, ``e7e8q``."""
    return square_name(move & 0x7F) + square_name((move >> 7) & 0x7F) + _PROMO_CHARS[(move >> 14) & 7]


def parse_uci_move(board: Board, uci: str) -> int:
    """Zamienia napis UCI na legalny ruch silnika (albo 0, jeśli ruch nielegalny)."""
    for move in legal_moves(board):
        if move_to_uci(move) == uci:
            return move
    return 0


def perft(board: Board, depth: int) -> int:
    """Liczba liści drzewa legalnych ruchów na danej głębokości.

    Porównanie ze znanymi wartościami to standardowy test poprawności generatora.
    """
    if depth == 0:
        return 1
    nodes = 0
    for move in generate_moves(board):
        if not make_legal_move(board, move):
            continue
        nodes += 1 if depth == 1 else perft(board, depth - 1)
        board.unmake_move()
    return nodes


def divide(board: Board, depth: int) -> dict[str, int]:
    """Perft z podziałem na ruchy z korzenia (narzędzie do szukania błędów generatora)."""
    result = {}
    for move in legal_moves(board):
        board.make_move(move)
        result[move_to_uci(move)] = perft(board, depth - 1)
        board.unmake_move()
    return result


__all__ = [
    "generate_moves",
    "in_check",
    "is_checkmate",
    "is_square_attacked",
    "is_stalemate",
    "legal_moves",
    "make_legal_move",
    "move_to_uci",
    "parse_uci_move",
    "perft",
    "divide",
]
