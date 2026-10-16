"""Stan szachownicy dla interfejsu w przeglądarce (odpowiednik ``ui/board_view.py`` bez rysowania).

Python decyduje, co jest na szachownicy (pozycja, ostatni ruch, strzałki, znaczki, podpowiedź),
a przeglądarka to rysuje i animuje. Każda zmiana pozycji dostaje nowy numer (``seq``) i rodzaj
animacji: ``move`` (ruch do przodu), ``undo`` (cofnięcie — figura wraca, zbita pojawia się z powrotem)
albo ``none`` (pozycja ustawiona bez animacji). Ruch gracza przychodzi z przeglądarki jako UCI.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any

import chess

FxSink = Callable[[dict[str, Any]], None]


@lru_cache(maxsize=256)
def legal_moves(fen: str) -> tuple[str, ...]:
    """Legalne ruchy (UCI) w pozycji — interfejs rysuje z nich kropki i okno promocji."""
    return tuple(move.uci() for move in chess.Board(fen).legal_moves)


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
        self.on_move: Callable[[chess.Move], None] | None = None
        self.last_move: chess.Move | None = None
        self.hint_square: chess.Square | None = None
        #: Strzałki (od, do, kolor CSS).
        self.arrows: list[tuple[chess.Square, chess.Square, str]] = []
        #: Znaczek w rogu pola: ok / bad / brilliant albo klasa ruchu (cls:best, cls:blunder…).
        self.feedback: dict[str, Any] | None = None
        self.seq = 0
        self.anim = "none"
        self._feedback_seq = 0

    # ------------------------------------------------------------ stan
    def set_position(
        self, board: chess.Board, move: chess.Move | None = None, animate: bool = True, undo: chess.Move | None = None
    ) -> None:
        """Nowa pozycja; ``move`` = ruch, który do niej prowadził; ``undo`` = właśnie cofany ruch."""
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
        """✓ (dobry ruch), ✗ (błąd) albo !! (genialny ruch) w rogu pola docelowego."""
        kind = "brilliant" if ok and brilliant else "ok" if ok else "bad"
        self._set_feedback(square, kind, True)

    def show_badge(self, square: chess.Square, cls: str, effect: bool = True) -> None:
        """Znaczek klasy ruchu (gra z trenerem): !!, !, ★, ✓, książka, ?!, ?, ??."""
        self._set_feedback(square, f"cls:{cls}", effect)

    def _set_feedback(self, square: chess.Square, kind: str, effect: bool) -> None:
        self._feedback_seq += 1
        self.feedback = {"square": chess.square_name(square), "kind": kind, "seq": self._feedback_seq, "effect": effect}

    def clear_feedback(self) -> None:
        self.feedback = None

    def shake(self) -> None:
        """Krótkie potrząśnięcie szachownicą po błędzie."""
        self._fx({"type": "shake", "board": self.name})

    def celebrate(self, square: chess.Square) -> None:
        """Konfetti z pola, na którym rozwiązano zadanie."""
        self._fx({"type": "celebrate", "board": self.name, "square": chess.square_name(square)})

    def can_move(self) -> bool:
        return self.interactive and self.board.turn == self.player_color

    def play(self, uci: str) -> bool:
        """Ruch gracza z przeglądarki (UCI). Sprawdzamy, czy jest legalny i czy gracz może teraz ruszać."""
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            return False
        if not self.can_move() or move not in self.board.legal_moves:
            return False
        if self.on_move is not None:
            self.on_move(move)
        return True

    # ------------------------------------------------------------ migawka
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
            "lastMove": self.last_move.uci() if self.last_move is not None else None,
            "check": chess.square_name(check) if check is not None else None,
            "hint": chess.square_name(self.hint_square) if self.hint_square is not None else None,
            "arrows": [[chess.square_name(a), chess.square_name(b), color] for a, b, color in self.arrows],
            "feedback": self.feedback,
        }
