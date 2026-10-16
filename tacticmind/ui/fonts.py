"""Fonts (bundled Noto fonts), a text-surface cache and fitting text into its space.

Rendering text in pygame is expensive and the UI is drawn 60 times per second,
so rendered text surfaces are cached. The ``fit`` and ``wrap`` functions make sure
no text spills outside its box: they first shrink the font (down to ``min_size``)
and only then truncate the text with "…".
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import pygame

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_FILES = {
    "regular": FONT_DIR / "NotoSans-Regular.ttf",
    "bold": FONT_DIR / "NotoSans-Bold.ttf",
    "mono": FONT_DIR / "NotoSansMono-Regular.ttf",
    "symbols": FONT_DIR / "NotoSansSymbols2-Regular.ttf",
}
ELLIPSIS = "…"

_fonts: dict[tuple[str, int], pygame.font.Font] = {}
#: Results of fitting and line-wrapping — computed once, not every frame.
_fit_cache: OrderedDict[tuple[str, int, int, str, int], tuple[str, int]] = OrderedDict()
_wrap_cache: OrderedDict[tuple[str, int, int, str], list[str]] = OrderedDict()
_LAYOUT_LIMIT = 4000
_cache: OrderedDict[tuple[str, int, str, tuple[int, ...]], pygame.Surface] = OrderedDict()
_CACHE_LIMIT = 4000


def reset() -> None:
    """Clears the font cache (after pygame is re-initialised, old Font objects are invalid)."""
    _fonts.clear()
    _cache.clear()
    _fit_cache.clear()
    _wrap_cache.clear()


def font(size: int, style: str = "regular") -> pygame.font.Font:
    key = (style, size)
    f = _fonts.get(key)
    if f is None:
        path = _FILES.get(style)
        f = pygame.font.Font(str(path), size) if path and path.exists() else pygame.font.Font(None, size)
        _fonts[key] = f
    return f


def render(text: str, size: int, color: tuple[int, ...], style: str = "regular") -> pygame.Surface:
    """Text rendered as a surface (cached)."""
    key = (style, size, text, color)
    surf = _cache.get(key)
    if surf is None:
        surf = font(size, style).render(text, True, color[:3])
        if len(color) == 4 and color[3] < 255:
            surf.set_alpha(color[3])
        _cache[key] = surf
        if len(_cache) > _CACHE_LIMIT:
            _cache.popitem(last=False)
    else:
        _cache.move_to_end(key)
    return surf


def text_size(text: str, size: int, style: str = "regular") -> tuple[int, int]:
    return font(size, style).size(text)


def line_height(size: int, style: str = "regular") -> int:
    return font(size, style).get_linesize()


def ellipsize(text: str, width: int, size: int, style: str = "regular") -> str:
    """Truncates text with a trailing "…" so it fits in ``width`` pixels."""
    f = font(size, style)
    if f.size(text)[0] <= width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:  # binary search for the longest prefix
        mid = (lo + hi + 1) // 2
        if f.size(text[:mid].rstrip() + ELLIPSIS)[0] <= width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + ELLIPSIS if lo > 0 else ELLIPSIS


def fit(text: str, width: int, size: int, style: str = "regular", min_size: int | None = None) -> tuple[str, int]:
    """Fits text to a width: shrinks the font down to ``min_size``, then truncates."""
    min_size = min_size if min_size is not None else max(9, int(size * 0.78))
    key = (text, width, size, style, min_size)
    cached = _fit_cache.get(key)
    if cached is not None:
        return cached
    current = size
    while current > min_size and text_size(text, current, style)[0] > width:
        current -= 1
    result = (ellipsize(text, width, current, style), current)
    _fit_cache[key] = result
    if len(_fit_cache) > _LAYOUT_LIMIT:
        _fit_cache.popitem(last=False)
    return result


def wrap(text: str, size: int, width: int, style: str = "regular") -> list[str]:
    """Wraps text into lines that fit in ``width`` (words that are too long get truncated)."""
    key = (text, size, width, style)
    cached = _wrap_cache.get(key)
    if cached is not None:
        return list(cached)
    f = font(size, style)
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        line = ""
        for word in words:
            candidate = f"{line} {word}" if line else word
            if f.size(candidate)[0] <= width:
                line = candidate
            elif not line:
                lines.append(ellipsize(word, width, size, style))
            else:
                lines.append(line)
                line = word if f.size(word)[0] <= width else ellipsize(word, width, size, style)
        lines.append(line)
    _wrap_cache[key] = lines
    if len(_wrap_cache) > _LAYOUT_LIMIT:
        _wrap_cache.popitem(last=False)
    return list(lines)


def wrap_limited(text: str, size: int, width: int, max_lines: int, style: str = "regular") -> list[str]:
    """Like ``wrap``, but at most ``max_lines`` lines — the last one ends with "…" if the text does not fit."""
    lines = wrap(text, size, width, style)
    if len(lines) <= max_lines:
        return lines
    kept = lines[:max_lines]
    kept[-1] = ellipsize(kept[-1] + ELLIPSIS, width, size, style)
    return kept


def fit_wrapped(
    text: str, width: int, height: int, size: int, style: str = "regular", min_size: int | None = None, gap: int = 2
) -> tuple[list[str], int]:
    """The largest font size (from ``size`` down) at which the wrapped text fits in a ``width``×``height`` box."""
    min_size = min_size if min_size is not None else max(9, int(size * 0.75))
    current = size
    while True:
        lines = wrap(text, current, width, style)
        if len(lines) * (line_height(current, style) + gap) <= height or current <= min_size:
            max_lines = max(1, height // (line_height(current, style) + gap))
            return wrap_limited(text, current, width, max_lines, style), current
        current -= 1
