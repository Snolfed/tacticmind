"""Wykresy rysowane w pygame: liniowy z gradientem pod linią (ranking w czasie) i słupkowy
(skuteczność w motywach). Wszystkie wymiary są skalowane."""

from __future__ import annotations

import math

import pygame

from ..i18n import t
from . import fonts, gfx, theme
from .scale import fs, px
from .widgets import draw_text


def _nice_step(span: float, ticks: int = 4) -> float:
    raw = span / max(1, ticks)
    magnitude = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * magnitude:
            return m * magnitude
    return 10 * magnitude


def line_chart(
    surface: pygame.Surface,
    rect: pygame.Rect,
    values: list[float],
    color: tuple[int, int, int] = theme.ACCENT,
    band: list[float] | None = None,
) -> None:
    """Wykres liniowy; ``band`` = opcjonalny przedział niepewności (± RD) wokół linii."""
    gfx.rrect(surface, theme.SURFACE, rect, px(12))
    if len(values) < 2:
        draw_text(surface, t("charts.no_data"), rect.center, fs(14), theme.MUTED, "regular", "center", max_width=rect.width - px(20))
        return
    plot = pygame.Rect(rect.x + px(54), rect.y + px(16), rect.width - px(70), rect.height - px(44))
    lows = [v - (band[i] if band else 0) for i, v in enumerate(values)]
    highs = [v + (band[i] if band else 0) for i, v in enumerate(values)]
    lo, hi = min(lows), max(highs)
    if hi - lo < 40:
        mid = (hi + lo) / 2
        lo, hi = mid - 20, mid + 20
    step = _nice_step(hi - lo)
    lo = math.floor(lo / step) * step
    hi = math.ceil(hi / step) * step

    def px_(i: int) -> float:
        return plot.x + plot.width * i / (len(values) - 1)

    def py(v: float) -> float:
        return plot.bottom - plot.height * (v - lo) / (hi - lo)

    value = lo
    while value <= hi + 1e-6:
        y = py(value)
        pygame.draw.line(surface, theme.BORDER_SOFT, (plot.x, y), (plot.right, y), 1)
        draw_text(surface, str(int(value)), (plot.x - px(8), y), fs(11), theme.MUTED, "regular", "midright")
        value += step
    for frac in (0, 0.5, 1):
        i = round((len(values) - 1) * frac)
        draw_text(surface, str(i), (px_(i), plot.bottom + px(6)), fs(11), theme.MUTED, "regular", "midtop")
    layer = pygame.Surface(rect.size, pygame.SRCALPHA)
    if band:
        upper = [(px_(i) - rect.x, py(highs[i]) - rect.y) for i in range(len(values))]
        lower = [(px_(i) - rect.x, py(lows[i]) - rect.y) for i in reversed(range(len(values)))]
        pygame.draw.polygon(layer, (*color, 26), upper + lower)
    # Gradient pod linią
    area_pts = [(px_(i) - rect.x, py(v) - rect.y) for i, v in enumerate(values)]
    area_pts += [(px_(len(values) - 1) - rect.x, plot.bottom - rect.y), (px_(0) - rect.x, plot.bottom - rect.y)]
    fill = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.polygon(fill, (255, 255, 255, 255), area_pts)
    grad = gfx.vertical_gradient(rect.size, (*color, 55), (*color, 0)).copy()
    grad.blit(fill, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    layer.blit(grad, (0, 0))
    surface.blit(layer, rect.topleft)
    points = [(px_(i), py(v)) for i, v in enumerate(values)]
    for a, b in zip(points, points[1:]):
        gfx.thick_line(surface, color, a, b, max(2.0, px(3)))
    if len(points) <= 60:
        for p in points:
            gfx.circle(surface, color, p, max(2, px(3)))
    gfx.circle(surface, theme.TEXT, points[-1], max(3, px(5)))
    gfx.circle(surface, color, points[-1], max(4, px(7)), max(1, px(2)))


def bar_chart(surface: pygame.Surface, rect: pygame.Rect, items: list[tuple[str, float, int]]) -> None:
    """Poziome słupki: (etykieta, skuteczność 0..1, liczba prób)."""
    gfx.rrect(surface, theme.SURFACE, rect, px(12))
    if not items:
        draw_text(surface, t("charts.no_themes"), rect.center, fs(14), theme.MUTED, "regular", "center", max_width=rect.width - px(20))
        return
    label_w = min(rect.width // 3, max(fonts.text_size(label, fs(12))[0] for label, _, _ in items) + px(16))
    row_h = min(px(30), (rect.height - px(16)) // len(items))
    y = rect.y + px(10)
    bar_x = rect.x + px(12) + label_w
    value_w = px(76)
    bar_w = rect.width - label_w - value_w - px(24)
    for label, rate, attempts in items:
        cy = y + row_h // 2
        draw_text(surface, label, (rect.x + px(12), cy), fs(12), theme.TEXT_SOFT, "regular", "midleft", max_width=label_w - px(8))
        track = pygame.Rect(bar_x, cy - px(7), bar_w, px(14))
        gfx.rrect(surface, theme.SURFACE_2, track, track.height // 2)
        color = theme.ACCENT if rate >= 0.65 else theme.AMBER if rate >= 0.45 else theme.RED
        fill = track.copy()
        fill.width = max(track.height, int(bar_w * rate))
        gfx.rrect_gradient(surface, color, tuple(max(0, c - 30) for c in color), fill, fill.height // 2)
        draw_text(surface, f"{round(rate * 100)}% ({attempts})", (track.right + px(8), cy), fs(11), theme.MUTED, "regular", "midleft", max_width=value_w)
        y += row_h
