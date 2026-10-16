"""Common base class for screens."""

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
        """The screen becomes active."""

    def leave(self) -> None:
        """The screen stops being active."""

    def layout(self, rect: pygame.Rect) -> None:
        self.rect = rect

    def handle(self, event: pygame.event.Event) -> None:
        """Handles mouse and keyboard events."""

    def update(self, dt: float) -> None:
        """Per-frame logic."""

    def draw(self, surface: pygame.Surface) -> None:
        """Drawing."""

    def on_engine(self, event: EngineEvent) -> None:
        """A message from the engine process."""

    def on_language_change(self) -> None:
        """The UI language changed — the screen may rebuild previously generated texts."""
