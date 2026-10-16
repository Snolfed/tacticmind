"""Wspólna baza ekranów interfejsu w przeglądarce."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import chess

from ...engine.process import EngineEvent

if TYPE_CHECKING:
    from ..core import WebApp


def move_sound(board_before: chess.Board, move: chess.Move) -> str:
    """Dźwięk ruchu (także przy cofaniu ◀): szach, promocja, roszada, bicie albo zwykły ruch."""
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
        """Ekran staje się aktywny."""

    def leave(self) -> None:
        """Ekran przestaje być aktywny."""

    def schedule(self, delay: float, action: Callable[[], None]) -> None:
        self.timers.append((self.clock + delay, action))

    def update(self, dt: float) -> None:
        """Logika co klatkę: zegar i zaplanowane akcje (np. odpowiedź przeciwnika po 400 ms)."""
        self.clock += dt
        due = [timer for timer in self.timers if timer[0] <= self.clock]
        if due:
            self.timers = [timer for timer in self.timers if timer[0] > self.clock]
            for _, action in due:
                action()

    def on_engine(self, event: EngineEvent) -> None:
        """Wiadomość od procesu silnika."""

    def on_language_change(self) -> None:
        """Zmieniono język — ekran może przebudować teksty wygenerowane wcześniej."""

    def action(self, name: str, data: dict[str, Any]) -> None:
        """Akcja z przeglądarki (kliknięcie przycisku, ruch na szachownicy…)."""

    def snapshot(self) -> dict[str, Any]:
        """Stan ekranu do narysowania (JSON)."""
        return {}

    def play_sound(self, board_before: chess.Board, move: chess.Move) -> None:
        self.app.sound(move_sound(board_before, move))
