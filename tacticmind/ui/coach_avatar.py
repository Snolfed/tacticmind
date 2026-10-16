"""Coach portrait ("Coach Max") drawn in code — no image files.

It is drawn at 4× resolution and filtered down (anti-aliased edges), and finished portraits
are cached. The coach has several expressions that change during the game:
 - ``neutral`` — calm smile, ``happy`` — good move, ``excited`` — brilliant move or a win,
 - ``thinking`` — the coach is calculating, ``concerned`` — mistake, ``shocked`` — blunder,
and blinks every few seconds.

``python -m tacticmind.ui.coach_avatar`` saves the portrait as ``tacticmind/assets/coach.png``.
"""

from __future__ import annotations

from pathlib import Path

import chess
import pygame

from . import theme
from .pieces import piece_surface

EXPRESSIONS = ("neutral", "happy", "excited", "thinking", "concerned", "shocked")
SS = 4

SKIN = (243, 198, 162)
SKIN_SHADE = (222, 166, 128)
HAIR = (56, 38, 30)
HAIR_LIGHT = (92, 64, 48)
HOODIE = (34, 44, 80)
HOODIE_LIGHT = (54, 68, 116)
SHIRT = (232, 237, 247)
GLASSES = (26, 28, 38)
EYE = (32, 28, 34)
MOUTH = (122, 40, 50)
TONGUE = (218, 104, 110)

Point = tuple[float, float]

_cache: dict[tuple[int, str, bool], pygame.Surface] = {}


class _Pen:
    """Drawing in 0–100 units on an upscaled surface."""

    def __init__(self, surface: pygame.Surface) -> None:
        self.s = surface
        self.k = surface.get_width() / 100

    def p(self, x: float, y: float) -> tuple[int, int]:
        return round(x * self.k), round(y * self.k)

    def rect(self, x: float, y: float, w: float, h: float) -> pygame.Rect:
        return pygame.Rect(round(x * self.k), round(y * self.k), max(1, round(w * self.k)), max(1, round(h * self.k)))

    def ellipse(self, color: tuple[int, ...], x: float, y: float, w: float, h: float) -> None:
        if len(color) == 4:
            layer = pygame.Surface(self.s.get_size(), pygame.SRCALPHA)
            pygame.draw.ellipse(layer, color, self.rect(x, y, w, h))
            self.s.blit(layer, (0, 0))
        else:
            pygame.draw.ellipse(self.s, color, self.rect(x, y, w, h))

    def circle(self, color: tuple[int, ...], x: float, y: float, r: float, width: float = 0) -> None:
        pygame.draw.circle(self.s, color, self.p(x, y), round(r * self.k), round(width * self.k) if width else 0)

    def poly(self, color: tuple[int, ...], points: list[Point]) -> None:
        pygame.draw.polygon(self.s, color, [self.p(x, y) for x, y in points])

    def line(self, color: tuple[int, ...], points: list[Point], width: float) -> None:
        """Thick polyline with rounded caps and joins."""
        w = max(1, round(width * self.k))
        pts = [self.p(x, y) for x, y in points]
        pygame.draw.lines(self.s, color, False, pts, w)
        for pt in pts:
            pygame.draw.circle(self.s, color, pt, w // 2)

    def curve(self, color: tuple[int, ...], a: Point, mid: Point, b: Point, width: float, steps: int = 14) -> None:
        """Quadratic Bézier curve through control point ``mid``."""
        pts = []
        for i in range(steps + 1):
            t = i / steps
            x = (1 - t) ** 2 * a[0] + 2 * (1 - t) * t * mid[0] + t * t * b[0]
            y = (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * mid[1] + t * t * b[1]
            pts.append((x, y))
        self.line(color, pts, width)


def _curve_points(a: Point, mid: Point, b: Point, steps: int = 16) -> list[Point]:
    pts = []
    for i in range(steps + 1):
        t = i / steps
        pts.append(((1 - t) ** 2 * a[0] + 2 * (1 - t) * t * mid[0] + t * t * b[0], (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * mid[1] + t * t * b[1]))
    return pts


def _background(pen: _Pen) -> None:
    size = pen.s.get_width()
    top, bottom = (40, 196, 180), (124, 92, 236)
    for y in range(size):
        t = y / max(1, size - 1)
        color = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
        pygame.draw.line(pen.s, color, (0, y), (size, y))
    # Subtle checkerboard in the background and a bright light spot.
    layer = pygame.Surface(pen.s.get_size(), pygame.SRCALPHA)
    cell = 12.5
    for row in range(8):
        for col in range(8):
            if (row + col) % 2 == 0:
                pygame.draw.rect(layer, (255, 255, 255, 14), pen.rect(col * cell, row * cell, cell, cell))
    pygame.draw.circle(layer, (255, 255, 255, 34), pen.p(30, 22), round(34 * pen.k))
    pen.s.blit(layer, (0, 0))


def _body(pen: _Pen) -> None:
    pen.ellipse(HOODIE, 6, 74, 88, 64)
    pen.ellipse(HOODIE_LIGHT, 22, 70, 56, 22)  # hood around the neck
    pen.ellipse(SHIRT, 37, 72, 26, 12)
    pen.poly(SKIN_SHADE, [(42, 58), (58, 58), (58, 74), (50, 79), (42, 74)])  # neck
    pen.line((210, 220, 240), [(44, 84), (43, 97)], 1.2)  # hood strings
    pen.line((210, 220, 240), [(56, 84), (57, 97)], 1.2)


def _head(pen: _Pen) -> None:
    pen.ellipse(HAIR, 27, 13, 46, 34)  # back of the hair
    pen.ellipse(SKIN_SHADE, 25.5, 39, 8, 12)  # ears
    pen.ellipse(SKIN_SHADE, 66.5, 39, 8, 12)
    pen.ellipse((206, 148, 112), 27.5, 42, 4, 6)
    pen.ellipse((206, 148, 112), 68.5, 42, 4, 6)
    pen.ellipse(SKIN, 30, 19, 40, 47)
    # Fringe combed to the side.
    fringe = [(29, 38), (29, 27), (34, 18), (43, 13.5), (53, 13), (63, 16), (69.5, 23), (71, 36), (68, 29), (63, 24.5)]
    fringe += _curve_points((63, 24.5), (52, 22), (40, 30))
    fringe += [(35, 31), (31, 35)]
    pen.poly(HAIR, fringe)
    pen.curve(HAIR_LIGHT, (38, 18.5), (50, 14.5), (61, 18), 1.3)


def _eyebrows(pen: _Pen, expression: str) -> None:
    w = 1.9
    if expression == "concerned":
        pen.line(HAIR, [(37, 36.5), (46, 33.5)], w)
        pen.line(HAIR, [(54, 33.5), (63, 36.5)], w)
    elif expression in ("excited", "shocked"):
        pen.curve(HAIR, (37, 33), (41.5, 30), (46, 32), w)
        pen.curve(HAIR, (54, 32), (58.5, 30), (63, 33), w)
    elif expression == "thinking":
        pen.line(HAIR, [(37, 35.5), (46, 35.5)], w)
        pen.curve(HAIR, (54, 33), (58.5, 30.5), (63, 33.5), w)
    elif expression == "happy":
        pen.curve(HAIR, (37, 35.5), (41.5, 33), (46, 34.5), w)
        pen.curve(HAIR, (54, 34.5), (58.5, 33), (63, 35.5), w)
    else:
        pen.curve(HAIR, (37, 36), (41.5, 34.5), (46, 35.2), w)
        pen.curve(HAIR, (54, 35.2), (58.5, 34.5), (63, 36), w)


def _eyes(pen: _Pen, expression: str, blink: bool) -> None:
    for cx in (42.0, 58.0):
        if blink or expression == "excited":
            # Closed eyes: a line when blinking, "^" when happy.
            if expression == "excited":
                pen.curve(EYE, (cx - 2.6, 46.2), (cx, 42.6), (cx + 2.6, 46.2), 1.5)
            else:
                pen.curve(EYE, (cx - 2.6, 45.4), (cx, 46.4), (cx + 2.6, 45.4), 1.3)
            continue
        dx, dy = (0.9, -1.1) if expression == "thinking" else (0.0, 0.0)
        w, h = (5.2, 6.6) if expression == "shocked" else (4.3, 5.4)
        if expression == "shocked":
            pen.ellipse((255, 255, 255), cx - 3.6, 45 - 4.2, 7.2, 8.4)
        pen.ellipse(EYE, cx - w / 2 + dx, 45 - h / 2 + dy, w, h)
        pen.circle((255, 255, 255), cx + 0.9 + dx, 43.7 + dy, 0.9)


def _glasses(pen: _Pen) -> None:
    layer = pygame.Surface(pen.s.get_size(), pygame.SRCALPHA)
    lens = _Pen(layer)
    lens.circle((200, 230, 255, 40), 42, 45, 7.3)
    lens.circle((200, 230, 255, 40), 58, 45, 7.3)
    pen.s.blit(layer, (0, 0))
    pen.circle(GLASSES, 42, 45, 7.6, 1.35)
    pen.circle(GLASSES, 58, 45, 7.6, 1.35)
    pen.curve(GLASSES, (49.3, 44.6), (50, 43.6), (50.7, 44.6), 1.3)
    pen.line(GLASSES, [(34.5, 44), (30.5, 42.5)], 1.3)
    pen.line(GLASSES, [(65.5, 44), (69.5, 42.5)], 1.3)
    pen.curve((255, 255, 255), (38, 41.5), (39.2, 40.2), (41, 39.6), 0.8)  # highlight
    pen.curve((255, 255, 255), (54, 41.5), (55.2, 40.2), (57, 39.6), 0.8)


def _mouth(pen: _Pen, expression: str) -> None:
    if expression in ("happy", "excited"):
        depth = 7.5 if expression == "excited" else 5.0
        half = 7.0 if expression == "excited" else 6.0
        top = 58.0
        outline = [(50 - half, top), (50 + half, top)] + list(reversed(_curve_points((50 - half, top), (50, top + 2 * depth), (50 + half, top))))
        pen.poly(MOUTH, outline)
        pen.poly((250, 250, 252), [(50 - half + 0.8, top + 0.3), (50 + half - 0.8, top + 0.3), (50 + half - 2.2, top + 2.0), (50 - half + 2.2, top + 2.0)])
        pen.ellipse(TONGUE, 50 - half * 0.45, top + depth * 0.55, half * 0.9, depth * 0.5)
    elif expression == "shocked":
        pen.ellipse(MOUTH, 47.6, 58.5, 4.8, 6.2)
    elif expression == "thinking":
        pen.curve(MOUTH, (47, 61.5), (51, 61.2), (54.5, 59.8), 1.4)
    elif expression == "concerned":
        pen.curve(MOUTH, (45.5, 62), (50, 59.6), (54.5, 62), 1.4)
    else:
        pen.curve(MOUTH, (44.5, 59.3), (50, 63.2), (55.5, 59.3), 1.5)


def _cheeks(pen: _Pen, expression: str) -> None:
    if expression in ("happy", "excited"):
        pen.ellipse((240, 120, 120, 70), 32.5, 51.5, 7, 4.5)
        pen.ellipse((240, 120, 120, 70), 60.5, 51.5, 7, 4.5)


def coach_portrait(size: int, expression: str = "neutral", blink: bool = False) -> pygame.Surface:
    """Round coach portrait ``size`` pixels in diameter."""
    size = max(8, int(size))
    expression = expression if expression in EXPRESSIONS else "neutral"
    key = (size, expression, blink)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    big = pygame.Surface((size * SS, size * SS), pygame.SRCALPHA)
    pen = _Pen(big)
    _background(pen)
    _body(pen)
    knight = piece_surface(chess.Piece(chess.KNIGHT, chess.WHITE), max(4, round(14 * pen.k)))
    big.blit(knight, knight.get_rect(center=pen.p(65, 87)))
    _head(pen)
    pen.poly(SKIN_SHADE, [(50, 48.5), (47.6, 54.5), (50.8, 55.4)])  # nose
    _cheeks(pen, expression)
    _eyebrows(pen, expression)
    _eyes(pen, expression, blink)
    _glasses(pen)
    _mouth(pen, expression)
    # Circular mask.
    mask = pygame.Surface(big.get_size(), pygame.SRCALPHA)
    pygame.draw.circle(mask, (255, 255, 255, 255), (size * SS // 2, size * SS // 2), size * SS // 2)
    big.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    surf = pygame.transform.smoothscale(big, (size, size))
    if pygame.display.get_surface() is not None:
        surf = surf.convert_alpha()
    if len(_cache) > 64:
        _cache.clear()
    _cache[key] = surf
    return surf


def draw_coach(surface: pygame.Surface, center: tuple[int, int], size: int, expression: str = "neutral", blink: bool = False, ring: tuple[int, ...] = theme.BORDER) -> pygame.Rect:
    """Portrait with a border."""
    portrait = coach_portrait(size, expression, blink)
    rect = portrait.get_rect(center=center)
    pygame.draw.circle(surface, ring, center, size // 2 + max(2, size // 40))
    surface.blit(portrait, rect)
    return rect


def save_png(path: Path | None = None, size: int = 256) -> Path:
    path = path or Path(__file__).resolve().parent.parent / "assets" / "coach.png"
    pygame.image.save(coach_portrait(size, "happy"), str(path))
    return path


if __name__ == "__main__":
    pygame.init()
    print(save_png())
