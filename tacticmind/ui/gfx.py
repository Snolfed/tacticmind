"""Grafika wysokiej jakości: wygładzone (antyaliasowane) kształty, miękkie cienie, gradienty.

pygame rysuje zaokrąglone prostokąty i wielokąty bez wygładzania krawędzi. Tutaj
rysujemy je w potrójnej rozdzielczości i zmniejszamy filtrem (supersampling),
a gotowe kształty trzymamy w pamięci podręcznej — więc kosztują tyle co zwykłe blit.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Sequence

import pygame

from . import theme

SS = 3  # współczynnik supersamplingu
_CACHE_LIMIT = 700
_cache: OrderedDict[tuple[object, ...], pygame.Surface] = OrderedDict()

Color = tuple[int, ...]
Point = tuple[float, float]


def _cached(key: tuple[object, ...]) -> pygame.Surface | None:
    surf = _cache.get(key)
    if surf is not None:
        _cache.move_to_end(key)
    return surf


def _store(key: tuple[object, ...], surf: pygame.Surface) -> pygame.Surface:
    # Format piksela zgodny z ekranem = dużo szybsze rysowanie (blit) półprzezroczystych powierzchni.
    if pygame.display.get_surface() is not None:
        alpha = surf.get_alpha()
        surf = surf.convert_alpha()
        if alpha is not None and alpha < 255:
            surf.set_alpha(alpha)
    _cache[key] = surf
    if len(_cache) > _CACHE_LIMIT:
        _cache.popitem(last=False)
    return surf


def rgba(color: Color, alpha: int | None = None) -> tuple[int, int, int, int]:
    a = color[3] if len(color) == 4 else 255
    if alpha is not None:
        a = alpha
    return (color[0], color[1], color[2], max(0, min(255, a)))


# ---------------------------------------------------------------------------
# Zaokrąglone prostokąty
# ---------------------------------------------------------------------------
def _rrect_surface(size: tuple[int, int], color: Color, radius: int, width: int) -> pygame.Surface:
    key = ("rr", size, rgba(color), radius, width)
    surf = _cached(key)
    if surf is None:
        w, h = size
        big = pygame.Surface((w * SS, h * SS), pygame.SRCALPHA)
        r, g, b, a = rgba(color)
        big.fill((r, g, b, 0))
        radius = max(0, min(radius, min(w, h) // 2))
        pygame.draw.rect(big, (r, g, b, a), big.get_rect(), width * SS, border_radius=radius * SS)
        surf = _store(key, pygame.transform.smoothscale(big, size))
    return surf


def rrect(surface: pygame.Surface, color: Color, rect: pygame.Rect, radius: int, width: int = 0) -> None:
    """Wygładzony zaokrąglony prostokąt (wypełniony albo obrys o grubości ``width``)."""
    if rect.width <= 0 or rect.height <= 0:
        return
    surface.blit(_rrect_surface(rect.size, color, radius, width), rect.topleft)


def rrect_gradient(surface: pygame.Surface, top: Color, bottom: Color, rect: pygame.Rect, radius: int) -> None:
    """Zaokrąglony prostokąt z pionowym gradientem."""
    if rect.width <= 0 or rect.height <= 0:
        return
    key = ("rg", rect.size, rgba(top), rgba(bottom), radius)
    surf = _cached(key)
    if surf is None:
        surf = vertical_gradient(rect.size, top, bottom).copy()
        surf.blit(rounded_mask(rect.size, radius), (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        _store(key, surf)
    surface.blit(surf, rect.topleft)


def rounded_mask(size: tuple[int, int], radius: int) -> pygame.Surface:
    """Biała maska z zaokrąglonymi rogami — mnożona przez kanał alfa zaokrągla dowolny obraz."""
    return _rrect_surface(size, (255, 255, 255, 255), radius, 0)


# ---------------------------------------------------------------------------
# Cienie, gradienty, tło
# ---------------------------------------------------------------------------
def shadow(surface: pygame.Surface, rect: pygame.Rect, radius: int, blur: int, alpha: int = 120, offset: tuple[int, int] = (0, 0)) -> None:
    """Miękki cień pod kartą (rozmycie przez zmniejszenie i powiększenie obrazu)."""
    if rect.width <= 0 or rect.height <= 0:
        return
    blur = max(2, blur)
    key = ("sh", rect.size, radius, blur, alpha)
    surf = _cached(key)
    if surf is None:
        pad = blur * 2
        w, h = rect.width + 2 * pad, rect.height + 2 * pad
        base = pygame.Surface((w, h), pygame.SRCALPHA)
        base.fill((*theme.SHADOW, 0))
        pygame.draw.rect(base, (*theme.SHADOW, alpha), pygame.Rect(pad, pad, rect.width, rect.height), border_radius=radius)
        factor = max(2, blur // 2)
        small = pygame.transform.smoothscale(base, (max(1, w // factor), max(1, h // factor)))
        surf = pygame.transform.smoothscale(small, (w, h))
        _store(key, surf)
    pad = blur * 2
    surface.blit(surf, (rect.x - pad + offset[0], rect.y - pad + offset[1]))


def card_surface(size: tuple[int, int], radius: int, fill: Color, border: Color, border_w: int, blur: int, alpha: int, dy: int) -> tuple[pygame.Surface, int]:
    """Cała karta (cień + wypełnienie + ramka) jako jedna gotowa powierzchnia; zwraca też margines cienia."""
    key = ("card", size, radius, rgba(fill), rgba(border), border_w, blur, alpha, dy)
    pad = blur * 2 + abs(dy)
    surf = _cached(key)
    if surf is None:
        w, h = size
        surf = pygame.Surface((w + 2 * pad, h + 2 * pad), pygame.SRCALPHA)
        if blur > 0:
            shadow(surf, pygame.Rect(pad, pad, w, h), radius, blur, alpha, (0, dy))
        rrect(surf, fill, pygame.Rect(pad, pad, w, h), radius)
        if border_w > 0:
            rrect(surf, border, pygame.Rect(pad, pad, w, h), radius, border_w)
        surf = _store(key, surf)
    return surf, pad


def vertical_gradient(size: tuple[int, int], top: Color, bottom: Color) -> pygame.Surface:
    key = ("vg", size, rgba(top), rgba(bottom))
    surf = _cached(key)
    if surf is None:
        strip = pygame.Surface((1, 2), pygame.SRCALPHA)
        strip.set_at((0, 0), rgba(top))
        strip.set_at((0, 1), rgba(bottom))
        surf = _store(key, pygame.transform.smoothscale(strip, (max(1, size[0]), max(1, size[1]))))
    return surf


def horizontal_gradient(size: tuple[int, int], left: Color, right: Color) -> pygame.Surface:
    key = ("hg", size, rgba(left), rgba(right))
    surf = _cached(key)
    if surf is None:
        strip = pygame.Surface((2, 1), pygame.SRCALPHA)
        strip.set_at((0, 0), rgba(left))
        strip.set_at((1, 0), rgba(right))
        surf = _store(key, pygame.transform.smoothscale(strip, (max(1, size[0]), max(1, size[1]))))
    return surf


def background(size: tuple[int, int]) -> pygame.Surface:
    """Tło aplikacji: granatowy gradient z dwiema miękkimi poświatami (fiolet i turkus)."""
    key = ("bg", size)
    surf = _cached(key)
    if surf is None:
        w, h = size
        surf = vertical_gradient(size, theme.BG_TOP, theme.BG_BOTTOM).copy()
        glow = pygame.Surface((max(1, w // 8), max(1, h // 8)), pygame.SRCALPHA)
        gw, gh = glow.get_size()
        for cx, cy, r, color, alpha in ((0.12, 0.08, 0.45, theme.VIOLET_2, 34), (0.92, 0.95, 0.5, theme.ACCENT_2, 26)):
            radius = int(max(gw, gh) * r)
            for i in range(radius, 0, -max(1, radius // 12)):
                a = int(alpha * (1 - i / radius) ** 1.6)
                pygame.draw.circle(glow, (*color, a), (int(gw * cx), int(gh * cy)), i)
        surf.blit(pygame.transform.smoothscale(glow, size), (0, 0))
        if pygame.display.get_surface() is not None:
            surf = surf.convert()  # tło jest nieprzezroczyste — najszybszy możliwy blit
        _cache[key] = surf
    return surf


# ---------------------------------------------------------------------------
# Koła i kształty
# ---------------------------------------------------------------------------
def circle(surface: pygame.Surface, color: Color, center: Point, radius: float, width: int = 0) -> None:
    """Wygładzone koło (także półprzezroczyste)."""
    r = max(1, int(round(radius)))
    key = ("c", r, rgba(color), width)
    surf = _cached(key)
    if surf is None:
        size = 2 * r + 2
        big = pygame.Surface((size * SS, size * SS), pygame.SRCALPHA)
        cr, cg, cb, ca = rgba(color)
        big.fill((cr, cg, cb, 0))
        pygame.draw.circle(big, (cr, cg, cb, ca), (size * SS // 2, size * SS // 2), r * SS, width * SS)
        surf = _store(key, pygame.transform.smoothscale(big, (size, size)))
    surface.blit(surf, surf.get_rect(center=(round(center[0]), round(center[1]))))


def ring_glow(surface: pygame.Surface, color: Color, center: Point, radius: float, alpha: int) -> None:
    """Miękka radialna poświata (np. szach, podpowiedź)."""
    r = max(2, int(radius))
    key = ("glow", r, color[:3], alpha)
    surf = _cached(key)
    if surf is None:
        size = 2 * r
        small = pygame.Surface((32, 32), pygame.SRCALPHA)
        for i in range(16, 0, -1):
            a = int(alpha * (1 - i / 16) ** 1.4)
            pygame.draw.circle(small, (*color[:3], a), (16, 16), i)
        surf = _store(key, pygame.transform.smoothscale(small, (size, size)))
    surface.blit(surf, surf.get_rect(center=(round(center[0]), round(center[1]))))


def polygon(surface: pygame.Surface, color: Color, points: Sequence[Point]) -> None:
    """Wygładzony wielokąt (supersampling na małej warstwie obejmującej kształt)."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, y0 = math.floor(min(xs)) - 1, math.floor(min(ys)) - 1
    w, h = math.ceil(max(xs)) - x0 + 2, math.ceil(max(ys)) - y0 + 2
    big = pygame.Surface((w * SS, h * SS), pygame.SRCALPHA)
    r, g, b, a = rgba(color)
    big.fill((r, g, b, 0))
    pygame.draw.polygon(big, (r, g, b, a), [((x - x0) * SS, (y - y0) * SS) for x, y in points])
    surface.blit(pygame.transform.smoothscale(big, (w, h)), (x0, y0))


def thick_line(surface: pygame.Surface, color: Color, a: Point, b: Point, width: float) -> None:
    """Gruba wygładzona linia z zaokrąglonymi końcami."""
    angle = math.atan2(b[1] - a[1], b[0] - a[0])
    nx, ny = -math.sin(angle) * width / 2, math.cos(angle) * width / 2
    polygon(surface, color, [(a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny), (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny)])
    circle(surface, color, a, width / 2)
    circle(surface, color, b, width / 2)


# ---------------------------------------------------------------------------
# Strzałki (silnika i rysowane przez gracza)
# ---------------------------------------------------------------------------
def _arrow_surface(points: tuple[Point, ...], color: Color, width: float) -> tuple[pygame.Surface, tuple[int, int]]:
    """Jedna wygładzona strzałka wzdłuż łamanej (dla skoczka: kształt litery L), z grotem na końcu."""
    key = ("arrow", points, rgba(color), round(width, 1))
    head_len = width * 2.2
    head_half = width * 1.3
    margin = head_half + 2
    x0 = math.floor(min(p[0] for p in points) - margin)
    y0 = math.floor(min(p[1] for p in points) - margin)
    surf = _cached(key)
    if surf is None:
        w = math.ceil(max(p[0] for p in points) + margin) - x0
        h = math.ceil(max(p[1] for p in points) + margin) - y0
        big = pygame.Surface((w * SS, h * SS), pygame.SRCALPHA)
        r, g, b, a = rgba(color)
        big.fill((r, g, b, 0))
        solid = (r, g, b, 255)

        def local(p: Point) -> tuple[float, float]:
            return ((p[0] - x0) * SS, (p[1] - y0) * SS)

        pts = list(points)
        (px_, py_), (ex, ey) = pts[-2], pts[-1]
        angle = math.atan2(ey - py_, ex - px_)
        bx, by = ex - math.cos(angle) * head_len, ey - math.sin(angle) * head_len
        pts[-1] = (bx, by)
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            seg = math.atan2(y2 - y1, x2 - x1)
            nx, ny = -math.sin(seg) * width / 2, math.cos(seg) * width / 2
            quad = [(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)]
            pygame.draw.polygon(big, solid, [local(q) for q in quad])
        for joint in pts[1:-1]:  # zaokrąglone zgięcie strzałki skoczka
            pygame.draw.circle(big, solid, local(joint), width / 2 * SS)
        hx, hy = -math.sin(angle) * head_half, math.cos(angle) * head_half
        pygame.draw.polygon(big, solid, [local((ex, ey)), local((bx + hx, by + hy)), local((bx - hx, by - hy))])
        surf = pygame.transform.smoothscale(big, (w, h))
        surf.set_alpha(a)  # przezroczystość całej strzałki naraz (bez ciemniejszych zakładek)
        _store(key, surf)
    return surf, (x0, y0)


def draw_arrows(surface: pygame.Surface, arrows: Sequence[tuple[Sequence[Point], Color, float]], alpha: float = 1.0) -> None:
    """Rysuje strzałki; ``alpha`` (0..1) pozwala je płynnie pokazać albo wygasić."""
    for points, color, width in arrows:
        surf, pos = _arrow_surface(tuple((float(x), float(y)) for x, y in points), color, width)
        if alpha < 0.999:
            base = rgba(color)[3]
            surf.set_alpha(int(base * max(0.0, alpha)))
            surface.blit(surf, pos)
            surf.set_alpha(base)
        else:
            surface.blit(surf, pos)


def gradient_text(text_surface: pygame.Surface, left: Color, right: Color) -> pygame.Surface:
    """Nakłada poziomy gradient na wyrenderowany (biały) napis."""
    grad = horizontal_gradient(text_surface.get_size(), left, right).copy()
    grad.blit(text_surface, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return grad


def clear_cache() -> None:
    _cache.clear()
