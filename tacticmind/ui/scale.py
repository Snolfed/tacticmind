"""Scaling the UI to the window resolution.

The whole UI is designed for a 1360×860 window (wide layout) or 560×1000
(narrow, phone-like layout). At any other size all distances and fonts are
multiplied by the ``scale()`` factor — so text is not tiny on a 4K screen and
nothing spills outside its frame in a small window.
"""

from __future__ import annotations

BASE_WIDE = (1360, 860)
BASE_NARROW = (560, 1000)
MIN_SCALE = 0.68
MAX_SCALE = 2.6

_scale = 1.0


def is_wide(width: int, height: int) -> bool:
    """Wide layout (panel beside the board) or narrow (panel below it)."""
    return width >= 860 and width / max(1, height) > 1.1


def compute_scale(width: int, height: int) -> float:
    base_w, base_h = BASE_WIDE if is_wide(width, height) else BASE_NARROW
    return max(MIN_SCALE, min(MAX_SCALE, min(width / base_w, height / base_h)))


def set_scale(value: float) -> None:
    global _scale
    _scale = value


def scale() -> float:
    return _scale


def px(value: float) -> int:
    """Scaled distance in pixels (at least 1 for positive values)."""
    scaled = round(value * _scale)
    return max(1, scaled) if value > 0 else scaled


def fs(size: float) -> int:
    """Scaled font size (no less than 9 px, so text stays readable)."""
    return max(9, round(size * _scale))
