"""TacticMind palette colours written as CSS (arrows on the board)."""

from __future__ import annotations

from ..ui import theme


def rgba(color: tuple[int, ...], alpha: int | None = None) -> str:
    """``(45, 212, 191, 215)`` → ``rgba(45,212,191,0.843)``."""
    r, g, b = color[:3]
    a = alpha if alpha is not None else (color[3] if len(color) > 3 else 255)
    return f"rgba({r},{g},{b},{round(a / 255, 3)})"


ENGINE_ARROWS = tuple(rgba(c) for c in theme.ENGINE_ARROWS)
#: Colour of the "best" badge (ui/badges.py) — the better-move arrow in a game against the coach.
BEST = (52, 211, 153)
BEST_ARROW = rgba(BEST, 210)
BEST_ARROW_REVIEW = rgba(BEST, 200)
HINT_ARROW = rgba(theme.VIOLET, 210)
LESSON_ARROW = rgba(theme.ACCENT, 200)
