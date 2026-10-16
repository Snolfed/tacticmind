"""Common base for the browser interface screens."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import chess

from ...engine.process import EngineEvent

if TYPE_CHECKING:
    from ..core import WebApp


def move_sound(board_before: chess.Board, move: chess.Move) -> str:
    """Move sound (also when stepping back ◀): check, promotion, castling, capture or a plain move."""
    after = board_before.copy(stack=False)
    after.push(move)
    if after.is_check():
        return "check"
    if move.promotion:
        return "promote"
    if board_before.is_castling(move):
        return "castle"
    return "capture" if board_before.is_capture(move) else "move"


class WebScreen:
    def __init__(self, app: WebApp) -> None:
        self.app = app
        self.clock = 0.0
        self.timers: list[tuple[float, Callable[[], None]]] = []

    def enter(self) -> None:
        """The screen becomes active."""

    def leave(self) -> None:
        """The screen stops being active."""

    def schedule(self, delay: float, action: Callable[[], None]) -> None:
        self.timers.append((self.clock + delay, action))

    def update(self, dt: float) -> None:
        """Per-frame logic: the clock and scheduled actions (e.g. the opponent's reply after 400 ms)."""
        self.clock += dt
        due = [timer for timer in self.timers if timer[0] <= self.clock]
        if due:
            self.timers = [timer for timer in self.timers if timer[0] > self.clock]
            for _, action in due:
                action()

    def on_engine(self, event: EngineEvent) -> None:
        """A message from the engine process."""

    def on_language_change(self) -> None:
        """The language changed — the screen may rebuild texts generated earlier."""

    def action(self, name: str, data: dict[str, Any]) -> None:
        """An action from the browser (button click, move on the board…)."""

    def snapshot(self) -> dict[str, Any]:
        """Screen state to draw (JSON)."""
        return {}

    def play_sound(self, board_before: chess.Board, move: chess.Move) -> None:
        self.app.sound(move_sound(board_before, move))
