"""TacticMind palette colours written as CSS (arrows on the board)."""

from __future__ import annotations

#: Palette colours shared with ``web/src/styles.css``: teal = the player, violet = the AI.
ACCENT = (45, 212, 191)
VIOLET = (167, 139, 250)
#: The engine's three candidate moves: best (strong teal), second (faint teal), third (violet).
_ENGINE_ARROWS = ((45, 212, 191, 215), (45, 212, 191, 105), (167, 139, 250, 100))


def rgba(color: tuple[int, ...], alpha: int | None = None) -> str:
    """``(45, 212, 191, 215)`` → ``rgba(45,212,191,0.843)``."""
    r, g, b = color[:3]
    a = alpha if alpha is not None else (color[3] if len(color) > 3 else 255)
    return f"rgba({r},{g},{b},{round(a / 255, 3)})"


ENGINE_ARROWS = tuple(rgba(c) for c in _ENGINE_ARROWS)
#: Colour of the "best" badge (web/src/components/Badge.tsx) — the better-move arrow in a game against the coach.
BEST = (52, 211, 153)
BEST_ARROW = rgba(BEST, 210)
BEST_ARROW_REVIEW = rgba(BEST, 200)
HINT_ARROW = rgba(VIOLET, 210)
LESSON_ARROW = rgba(ACCENT, 200)
