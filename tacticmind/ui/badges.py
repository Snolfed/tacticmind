"""Move-classification badges (as in chess.com "Game Review"): !!, !, ★, ✓, book, ?!, ?, ??.

Shapes (star, book, check mark) are drawn as vectors and the exclamation/question marks with a
regular font, so we don't depend on whether the font has symbols like ★.
"""

from __future__ import annotations

import math

import pygame

from . import gfx, theme
from .widgets import draw_text, icon_check

Color = tuple[int, ...]

COLORS: dict[str, Color] = {
    "brilliant": theme.BRILLIANT,
    "great": (96, 145, 250),
    "best": (52, 211, 153),
    "excellent": (110, 200, 120),
    "good": (140, 168, 132),
    "book": (196, 156, 112),
    "inaccuracy": (245, 192, 50),
    "mistake": (251, 146, 60),
    "blunder": (244, 63, 94),
}
_GLYPHS = {"brilliant": "!!", "great": "!", "inaccuracy": "?!", "mistake": "?", "blunder": "??"}


def star_points(center: tuple[float, float], outer: float, inner: float, points: int = 5) -> list[tuple[float, float]]:
    cx, cy = center
    result = []
    for i in range(points * 2):
        r = outer if i % 2 == 0 else inner
        angle = -math.pi / 2 + i * math.pi / points
        result.append((cx + math.cos(angle) * r, cy + math.sin(angle) * r))
    return result


def draw_star(surface: pygame.Surface, center: tuple[float, float], radius: float, color: Color) -> None:
    gfx.polygon(surface, color, star_points(center, radius, radius * 0.45))


def _book(surface: pygame.Surface, center: tuple[float, float], size: float, color: Color) -> None:
    """An open book: two pages with a spine in the middle."""
    cx, cy = center
    w, h = size * 0.36, size * 0.26
    left = [(cx - w, cy - h * 0.8), (cx - w * 0.15, cy - h), (cx, cy - h * 0.7), (cx, cy + h), (cx - w * 0.15, cy + h * 0.75), (cx - w, cy + h)]
    right = [(2 * cx - x, y) for x, y in left]
    gfx.polygon(surface, color, left)
    gfx.polygon(surface, color, right)


def draw_badge(surface: pygame.Surface, center: tuple[float, float], radius: float, cls: str, pop: float = 1.0) -> None:
    """Round move-class badge (``pop`` < 1 — while popping in)."""
    r = radius * pop
    if r < 1.5:
        return
    color = COLORS.get(cls, theme.MUTED)
    gfx.circle(surface, (*theme.SHADOW[:3], 110), (center[0], center[1] + max(1, r * 0.12)), r * 1.06)
    gfx.circle(surface, color, center, r)
    white = (255, 255, 255)
    if cls in _GLYPHS:
        text = _GLYPHS[cls]
        size = max(8, round(r * (1.15 if len(text) > 1 else 1.4)))
        draw_text(surface, text, (center[0], center[1] - r * 0.04), size, white, "bold", "center")
    elif cls == "best":
        draw_star(surface, center, r * 0.62, white)
    elif cls == "book":
        _book(surface, center, r * 1.9, white)
    else:  # excellent, good
        icon_check(surface, center, r * 1.5, white)
