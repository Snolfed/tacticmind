"""Board state for the browser interface.

Python decides what is on the board (position, last move, arrows, badges, hint),
and the browser draws and animates it. Every position change gets a new number (``seq``) and an
animation kind: ``move`` (a move forward), ``undo`` (a take-back — the piece returns, a captured one reappears)
or ``none`` (position set without animation). The player's move arrives from the browser as UCI.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any

import chess

FxSink = Callable[[dict[str, Any]], None]


@lru_cache(maxsize=256)
def legal_moves(fen: str) -> tuple[str, ...]:
    """Legal moves (UCI) in the position — the interface draws the dots and the promotion dialog from them."""
    return tuple(move.uci() for move in chess.Board(fen).legal_moves)


@lru_cache(maxsize=256)
def premove_targets(fen: str) -> tuple[str, ...]:
    """Pre-moves (UCI, from + to) the player may queue while the opponent is to move, like on chess.com: where each of
    their pieces could go on an empty board (the opponent's move may clear the way), including squares their own
    pieces stand on (a recapture once the opponent takes there), a pawn's pushes and diagonals, and castling. Whether
    the move is legal is checked once it is the player's turn."""
    board = chess.Board(fen)
    color = not board.turn
    moves: set[str] = set()
    for square, piece in board.piece_map().items():
        if piece.color != color:
            continue
        alone = chess.BaseBoard.empty()
        alone.set_piece_at(square, piece)
        targets = set(alone.attacks(square))
        if piece.piece_type == chess.PAWN:
            step = 8 if color == chess.WHITE else -8
            if 0 <= square + step < 64:
                targets.add(square + step)
            if chess.square_rank(square) == (1 if color == chess.WHITE else 6):
                targets.add(square + 2 * step)
        elif piece.piece_type == chess.KING and square == (chess.E1 if color == chess.WHITE else chess.E8):
            back = chess.square_rank(square)
            if board.has_kingside_castling_rights(color):
                targets.add(chess.square(6, back))
            if board.has_queenside_castling_rights(color):
                targets.add(chess.square(2, back))
        moves.update(chess.square_name(square) + chess.square_name(target) for target in targets)
    return tuple(sorted(moves))


def color_name(color: chess.Color) -> str:
    return "white" if color == chess.WHITE else "black"


class BoardModel:
    def __init__(self, name: str, fx: FxSink) -> None:
        self.name = name
        self._fx = fx
        self.board = chess.Board()
        self.orientation: chess.Color = chess.WHITE
        self.player_color: chess.Color = chess.WHITE
        self.interactive = False
        #: Pre-moves are allowed while the opponent thinks (a live game against the coach).
        self.premoves = False
        self.on_move: Callable[[chess.Move], None] | None = None
        self.last_move: chess.Move | None = None
        self.hint_square: chess.Square | None = None
        #: Arrows (from, to, CSS colour).
        self.arrows: list[tuple[chess.Square, chess.Square, str]] = []
        #: Badge in the square's corner: ok / bad / brilliant or a move class (cls:best, cls:blunder…).
        self.feedback: dict[str, Any] | None = None
        self.seq = 0
        self.anim = "none"
        self._feedback_seq = 0

    # ------------------------------------------------------------ state
    def set_position(
        self, board: chess.Board, move: chess.Move | None = None, animate: bool = True, undo: chess.Move | None = None
    ) -> None:
        """New position; ``move`` = the move that led to it; ``undo`` = the move being taken back."""
        self.board = board.copy(stack=False)
        self.last_move = move
        self.seq += 1
        if undo is not None and animate:
            self.anim = "undo"
        elif move is not None and animate:
            self.anim = "move"
        else:
            self.anim = "none"

    def show_feedback(self, square: chess.Square, ok: bool, brilliant: bool = False) -> None:
        """✓ (good move), ✗ (mistake) or !! (brilliant move) in the corner of the target square."""
        kind = "brilliant" if ok and brilliant else "ok" if ok else "bad"
        self._set_feedback(square, kind, True)

    def show_badge(self, square: chess.Square, cls: str, effect: bool = True) -> None:
        """Move-class badge (game against the coach): !!, !, ★, ✓, book, ?!, ?, ??."""
        self._set_feedback(square, f"cls:{cls}", effect)

    def _set_feedback(self, square: chess.Square, kind: str, effect: bool) -> None:
        self._feedback_seq += 1
        self.feedback = {"square": chess.square_name(square), "kind": kind, "seq": self._feedback_seq, "effect": effect}

    def clear_feedback(self) -> None:
        self.feedback = None

    def shake(self) -> None:
        """A short board shake after a mistake."""
        self._fx({"type": "shake", "board": self.name})

    def celebrate(self, square: chess.Square) -> None:
        """Confetti from the square on which the puzzle was solved."""
        self._fx({"type": "celebrate", "board": self.name, "square": chess.square_name(square)})

    def can_move(self) -> bool:
        return self.interactive and self.board.turn == self.player_color

    def can_premove(self) -> bool:
        """The opponent is to move in a live game: the player may queue a pre-move."""
        return self.premoves and self.board.turn != self.player_color and not self.board.is_game_over()

    def play(self, uci: str) -> bool:
        """Player's move from the browser (UCI). We check that it is legal and that the player may move now."""
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            return False
        if not self.can_move() or move not in self.board.legal_moves:
            return False
        if self.on_move is not None:
            self.on_move(move)
        return True

    # ------------------------------------------------------------ snapshot
    def snapshot(self) -> dict[str, Any]:
        board = self.board
        fen = board.fen()
        check = board.king(board.turn) if board.is_check() else None
        return {
            "fen": fen,
            "seq": self.seq,
            "anim": self.anim,
            "orientation": color_name(self.orientation),
            "player": color_name(self.player_color),
            "interactive": self.can_move(),
            "legal": list(legal_moves(fen)) if self.can_move() else [],
            "premoves": list(premove_targets(fen)) if self.can_premove() else [],
            "lastMove": self.last_move.uci() if self.last_move is not None else None,
            "check": chess.square_name(check) if check is not None else None,
            "hint": chess.square_name(self.hint_square) if self.hint_square is not None else None,
            "arrows": [[chess.square_name(a), chess.square_name(b), color] for a, b, color in self.arrows],
            "feedback": self.feedback,
        }
