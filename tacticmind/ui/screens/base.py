"""Wspólna baza ekranów."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from ...engine.process import EngineEvent

if TYPE_CHECKING:
    from ..app import App


class Screen:
    def __init__(self, app: App) -> None:
        self.app = app
        self.rect = pygame.Rect(0, 0, 0, 0)

    def enter(self) -> None:
        """Ekran staje się aktywny."""

    def leave(self) -> None:
        """Ekran przestaje być aktywny."""

    def layout(self, rect: pygame.Rect) -> None:
        self.rect = rect

    def handle(self, event: pygame.event.Event) -> None:
        """Obsługa zdarzeń myszy i klawiatury."""

    def update(self, dt: float) -> None:
        """Logika co klatkę."""

    def draw(self, surface: pygame.Surface) -> None:
        """Rysowanie."""

    def on_engine(self, event: EngineEvent) -> None:
        """Wiadomość od procesu silnika."""

    def on_language_change(self) -> None:
        """Zmieniono język interfejsu — ekran może przebudować teksty wygenerowane wcześniej."""
