"""Comparison mode (for the project defence).

The same position searched with:
 1) plain minimax (visits the whole tree),
 2) alpha-beta without move ordering (generator order),
 3) alpha-beta with move ordering (MVV-LVA, killers, history).

All three variants search to the same depth with the same evaluation function,
without quiescence and without a transposition table, so the result must be
identical; they differ only in the number of visited nodes.
"""

from __future__ import annotations

import time

from .board import Board
from .constants import CAPTURE_MASK, FLAG_EP, PAWN
from .evaluation import evaluate
from .movegen import generate_moves, in_check, legal_moves, make_legal_move, move_to_uci
from .types import INFINITY, MATE, CompareResult, CompareVariant, VariantName, to_white_score

INF = INFINITY


class _Counters:
    __slots__ = ("nodes", "cutoffs")

    def __init__(self) -> None:
        self.nodes = 1  # root
        self.cutoffs = 0


def _minimax(board: Board, depth: int, ply: int, c: _Counters) -> int:
    """Minimax in negamax form: our score = -(opponent's score). No cutoffs at all."""
    c.nodes += 1
    if depth == 0:
        return evaluate(board)
    best = -INF
    legal = 0
    for move in generate_moves(board):
        if not make_legal_move(board, move):
            continue
        legal += 1
        score = -_minimax(board, depth - 1, ply + 1, c)
        board.unmake_move()
        if score > best:
            best = score
    if legal == 0:
        return -MATE + ply if in_check(board) else 0
    return best


class _Ordering:
    """Simple move ordering: MVV-LVA captures, promotions, killers, history."""

    def __init__(self) -> None:
        self.killers = [[0, 0] for _ in range(64)]
        self.history = [0] * (16 * 128)

    def order(self, board: Board, moves: list[int], ply: int) -> list[int]:
        sq = board.sq
        killers = self.killers[ply]

        def key(move: int) -> int:
            if move & CAPTURE_MASK:
                victim = PAWN if move & FLAG_EP else sq[(move >> 7) & 0x7F] & 7
                return 1_000_000 + victim * 100 - (sq[move & 0x7F] & 7)
            if (move >> 14) & 7:
                return 950_000 + ((move >> 14) & 7)
            if move == killers[0]:
                return 900_000
            if move == killers[1]:
                return 800_000
            return self.history[sq[move & 0x7F] * 128 + ((move >> 7) & 0x7F)]

        return sorted(moves, key=key, reverse=True)

    def remember(self, board: Board, move: int, depth: int, ply: int) -> None:
        if move & CAPTURE_MASK or (move >> 14) & 7:
            return
        killers = self.killers[ply]
        if killers[0] != move:
            killers[1] = killers[0]
            killers[0] = move
        self.history[board.sq[move & 0x7F] * 128 + ((move >> 7) & 0x7F)] += depth * depth


def _alpha_beta(board: Board, depth: int, alpha: int, beta: int, ply: int, c: _Counters, ordering: _Ordering | None) -> int:
    """Alpha-beta (fail-hard).

    alpha = the score we are already guaranteed; beta = the best score the
    opponent will allow us. When a move scores >= beta, the remaining moves do
    not matter: the opponent will not allow this position (cutoff).
    """
    c.nodes += 1
    if depth == 0:
        return evaluate(board)
    moves = generate_moves(board)
    if ordering is not None:
        moves = ordering.order(board, moves, ply)
    legal = 0
    for move in moves:
        if not make_legal_move(board, move):
            continue
        legal += 1
        score = -_alpha_beta(board, depth - 1, -beta, -alpha, ply + 1, c, ordering)
        board.unmake_move()
        if score >= beta:
            c.cutoffs += 1
            if ordering is not None:
                ordering.remember(board, move, depth, ply)
            return beta
        if score > alpha:
            alpha = score
    if legal == 0:
        return -MATE + ply if in_check(board) else 0
    return alpha


def run_variant(fen: str, depth: int, variant: VariantName) -> CompareVariant:
    """Run one algorithm variant for a FEN position at the given depth."""
    board = Board(fen)
    counters = _Counters()
    ordering = _Ordering() if variant == "alphabeta-ordered" else None
    start = time.perf_counter()

    root_moves = legal_moves(board)
    if ordering is not None:
        root_moves = ordering.order(board, root_moves, 0)
    best_score = -INF
    best_move = 0
    for move in root_moves:
        board.make_move(move)
        if variant == "minimax":
            score = -_minimax(board, depth - 1, 1, counters)
        else:
            score = -_alpha_beta(board, depth - 1, -INF, -best_score, 1, counters, ordering)
        board.unmake_move()
        if score > best_score:
            best_score = score
            best_move = move
    if not root_moves:
        best_score = -MATE if in_check(board) else 0

    return CompareVariant(
        name=variant,
        nodes=counters.nodes,
        time_ms=round((time.perf_counter() - start) * 1000, 1),
        cutoffs=counters.cutoffs,
        score=to_white_score(best_score, board.side),
        best_move=move_to_uci(best_move) if best_move else "",
    )


def compare_algorithms(fen: str, depth: int, include_minimax: bool = True) -> CompareResult:
    """Compare the three variants (minimax is skipped when it would be too slow)."""
    return CompareResult(
        fen=fen,
        depth=depth,
        minimax=run_variant(fen, depth, "minimax") if include_minimax else None,
        alpha_beta=run_variant(fen, depth, "alphabeta"),
        alpha_beta_ordered=run_variant(fen, depth, "alphabeta-ordered"),
    )
