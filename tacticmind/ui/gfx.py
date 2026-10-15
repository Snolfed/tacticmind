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
#: Wielokąty mają osobną pamięć: ruchome kształty tworzą wiele jednorazowych wpisów i nie mogą
#: wypychać z głównej pamięci drogich powierzchni (tło, karty), których odbudowa to dziesiątki ms.
_POLY_LIMIT = 600
_poly_cache: OrderedDict[tuple[object, ...], pygame.Surface] = OrderedDict()

Color = tuple[int, ...]
Point = tuple[float, float]


def _cached(key: tuple[object, ...]) -> pygame.Surface | None:
    surf = _cache.get(key)
    if surf is not None:
        _cache.move_to_end(key)
    return surf


def _store(
    key: tuple[object, ...], surf: pygame.Surface, cache: OrderedDict[tuple[object, ...], pygame.Surface] = _cache, limit: int = _CACHE_LIMIT
) -> pygame.Surface:
    # Format piksela zgodny z ekranem = dużo szybsze rysowanie (blit) półprzezroczystych powierzchni.
    if pygame.display.get_surface() is not None:
        alpha = surf.get_alpha()
        surf = surf.convert_alpha()
        if alpha is not None and alpha < 255:
            surf.set_alpha(alpha)
    cache[key] = surf
    if len(cache) > limit:
        cache.popitem(last=False)
    return surf


def _blit(surface: pygame.Surface, surf: pygame.Surface, pos: tuple[int, int], alpha: int = 255) -> None:
    """Blit z przezroczystością całej powierzchni.

    Kształty są w pamięci w pełnym kryciu, a alfę koloru nakładamy dopiero tutaj — dzięki temu
    animowana przezroczystość (pulsowanie, podświetlenie) nie tworzy w każdej klatce nowego kształtu.
    """
    if alpha >= 255:
        surface.blit(surf, pos)
    elif alpha > 0:
        surf.set_alpha(alpha)
        surface.blit(surf, pos)
        surf.set_alpha(255)


def rgba(color: Color, alpha: int | None = None) -> tuple[int, int, int, int]:
    a = color[3] if len(color) == 4 else 255
    if alpha is not None:
        a = alpha
    return (color[0], color[1], color[2], max(0, min(255, a)))


# ---------------------------------------------------------------------------
# Zaokrąglone prostokąty
# ---------------------------------------------------------------------------
def _rrect_surface(size: tuple[int, int], color: Color, radius: int, width: int) -> pygame.Surface:
    """Kształt w pełnym kryciu (alfa koloru jest pomijana — nakłada ją ``rrect`` przy rysowaniu)."""
    key = ("rr", size, tuple(color[:3]), radius, width)
    surf = _cached(key)
    if surf is None:
        w, h = size
        big = pygame.Surface((w * SS, h * SS), pygame.SRCALPHA)
        r, g, b = color[:3]
        a = 255
        big.fill((r, g, b, 0))
        radius = max(0, min(radius, min(w, h) // 2))
        pygame.draw.rect(big, (r, g, b, a), big.get_rect(), width * SS, border_radius=radius * SS)
        surf = pygame.transform.smoothscale(big, size)
        if width == 0:
            _solid_interior(surf, (r, g, b, a), radius)
        surf = _store(key, surf)
    return surf


def _solid_interior(surf: pygame.Surface, color: tuple[int, int, int, int], radius: int) -> None:
    """Pełne krycie wszędzie, gdzie piksel leży całkowicie wewnątrz zaokrąglonego prostokąta.

    Zmniejszanie (smoothscale) gubi odrobinę krycia (253 zamiast 255). Taka powierzchnia narysowana
    na cieniu wychodzi o kilka odcieni ciemniejsza — a skoro środek karty rysujemy zwykłym fill
    (patrz ``rrect`` i ``card``), w rogach byłyby widać ciemniejsze kwadraty. Brzegi (częściowe
    pokrycie) zostają wygładzone, reszta dostaje dokładny kolor.
    """
    w, h = surf.get_size()
    inset = radius + 1
    surf.fill(color, pygame.Rect(0, inset, w, max(0, h - 2 * inset)))
    surf.fill(color, pygame.Rect(inset, 0, max(0, w - 2 * inset), h))
    if radius <= 0 or w < 2 * inset or h < 2 * inset:
        return
    for y in range(inset):
        # Piksel (x, y) leży cały w kole rogu, gdy jego najdalszy narożnik (x, y) mieści się w promieniu;
        # +1 piksel zapasu na wygładzoną krawędź.
        dy = radius - y
        if dy >= radius:
            continue
        x0 = math.ceil(radius - math.sqrt(radius * radius - dy * dy)) + 1
        if x0 >= inset:
            continue
        span = inset - x0
        for row in (y, h - 1 - y):
            surf.fill(color, pygame.Rect(x0, row, span, 1))
            surf.fill(color, pygame.Rect(w - inset, row, span, 1))


def rrect(surface: pygame.Surface, color: Color, rect: pygame.Rect, radius: int, width: int = 0) -> None:
    """Wygładzony zaokrąglony prostokąt (wypełniony albo obrys o grubości ``width``)."""
    if rect.width <= 0 or rect.height <= 0:
        return
    alpha = rgba(color)[3]
    if alpha <= 0:
        return
    surf = _rrect_surface(rect.size, color, radius, width)
    radius = max(0, min(radius, min(rect.size) // 2))
    if width > 0:
        # Wnętrze obrysu jest przezroczyste — kopiujemy tylko pasy przy krawędziach.
        inner = pygame.Rect(width + 1, radius + 1, rect.width - 2 * (width + 1), rect.height - 2 * (radius + 1))
        blit_frame(surface, surf, rect.topleft, inner, alpha)
    elif alpha == 255 and rect.height > 2 * (radius + 1):
        # Nieprzezroczyste wypełnienie: między zaokrąglonymi rogami same pełne wiersze — wystarczy fill.
        middle = pygame.Rect(0, radius + 1, rect.width, rect.height - 2 * (radius + 1))
        blit_frame(surface, surf, rect.topleft, middle)
        surface.fill(color[:3], middle.move(rect.topleft))
    else:
        _blit(surface, surf, rect.topleft, alpha)


def blit_frame(surface: pygame.Surface, surf: pygame.Surface, pos: tuple[int, int], inner: pygame.Rect, alpha: int = 255) -> None:
    """Rysuje ``surf`` bez prostokąta ``inner`` (we współrzędnych ``surf``), czyli tylko ramkę wokół niego.

    W wysokiej rozdzielczości koszt klatki to głównie liczba kopiowanych pikseli, więc nie kopiujemy
    wnętrza, które jest przezroczyste albo i tak zostanie zaraz zakryte.
    """
    if alpha <= 0:
        return
    w, h = surf.get_size()
    inner = inner.clip(surf.get_rect())
    if inner.width <= 0 or inner.height <= 0:
        _blit(surface, surf, pos, alpha)
        return
    if alpha < 255:
        surf.set_alpha(alpha)
    x, y = pos
    for area in (
        pygame.Rect(0, 0, w, inner.top),
        pygame.Rect(0, inner.bottom, w, h - inner.bottom),
        pygame.Rect(0, inner.top, inner.left, inner.height),
        pygame.Rect(inner.right, inner.top, w - inner.right, inner.height),
    ):
        if area.width > 0 and area.height > 0:
            surface.blit(surf, (x + area.x, y + area.y), area)
    if alpha < 255:
        surf.set_alpha(255)


def round_corners(canvas: pygame.Surface, radius: int) -> None:
    """Zaokrągla rogi nieprzezroczystego płótna (mnoży kanał alfa przez maskę tylko w czterech rogach)."""
    size = canvas.get_size()
    mask = rounded_mask(size, radius)
    for area in corner_areas(size, radius):
        canvas.blit(mask, area, area, special_flags=pygame.BLEND_RGBA_MULT)


def corner_areas(size: tuple[int, int], radius: int) -> list[pygame.Rect]:
    """Kwadraty w czterech rogach prostokąta, w których maska zaokrąglenia nie jest pełna."""
    w, h = size
    c = max(0, min(radius, min(w, h) // 2)) + 1
    return [pygame.Rect(x, y, c, c) for x, y in ((0, 0), (w - c, 0), (0, h - c), (w - c, h - c))]


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
def shadow(
    surface: pygame.Surface, rect: pygame.Rect, radius: int, blur: int, alpha: int = 120, offset: tuple[int, int] = (0, 0), covered: bool = False
) -> None:
    """Miękki cień pod kartą (rozmycie przez zmniejszenie i powiększenie obrazu).

    ``covered=True``: na ``rect`` zaraz zostanie narysowane coś nieprzezroczystego (z rogami o promieniu
    ``radius``), więc pomijamy niewidoczny środek cienia.
    """
    if rect.width <= 0 or rect.height <= 0:
        return
    blur = max(2, blur)
    alpha = max(0, min(255, alpha))
    key = ("sh", rect.size, radius, blur)  # bez alfy — nakładana przy rysowaniu (płynne podświetlenia)
    surf = _cached(key)
    if surf is None:
        pad = blur * 2
        w, h = rect.width + 2 * pad, rect.height + 2 * pad
        base = pygame.Surface((w, h), pygame.SRCALPHA)
        base.fill((*theme.SHADOW, 0))
        pygame.draw.rect(base, (*theme.SHADOW, 255), pygame.Rect(pad, pad, rect.width, rect.height), border_radius=radius)
        factor = max(2, blur // 2)
        small = pygame.transform.smoothscale(base, (max(1, w // factor), max(1, h // factor)))
        surf = pygame.transform.smoothscale(small, (w, h))
        _store(key, surf)
    pad = blur * 2
    pos = (rect.x - pad + offset[0], rect.y - pad + offset[1])
    if covered:
        inner = pygame.Rect(pad - offset[0], pad - offset[1], rect.width, rect.height).inflate(-2 * (radius + 1), -2 * (radius + 1))
        blit_frame(surface, surf, pos, inner, alpha)
    else:
        _blit(surface, surf, pos, alpha)


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
    cr, cg, cb, ca = rgba(color)
    key = ("c", r, (cr, cg, cb), width)
    surf = _cached(key)
    if surf is None:
        size = 2 * r + 2
        big = pygame.Surface((size * SS, size * SS), pygame.SRCALPHA)
        big.fill((cr, cg, cb, 0))
        pygame.draw.circle(big, (cr, cg, cb, 255), (size * SS // 2, size * SS // 2), r * SS, width * SS)
        surf = _store(key, pygame.transform.smoothscale(big, (size, size)))
    _blit(surface, surf, surf.get_rect(center=(round(center[0]), round(center[1]))).topleft, ca)


def ring_glow(surface: pygame.Surface, color: Color, center: Point, radius: float, alpha: int) -> None:
    """Miękka radialna poświata (np. szach, podpowiedź)."""
    r = max(2, int(radius))
    key = ("glow", r, tuple(color[:3]))
    surf = _cached(key)
    if surf is None:
        size = 2 * r
        small = pygame.Surface((32, 32), pygame.SRCALPHA)
        for i in range(16, 0, -1):
            a = int(255 * (1 - i / 16) ** 1.4)
            pygame.draw.circle(small, (*color[:3], a), (16, 16), i)
        surf = _store(key, pygame.transform.smoothscale(small, (size, size)))
    _blit(surface, surf, surf.get_rect(center=(round(center[0]), round(center[1]))).topleft, max(0, min(255, alpha)))


def polygon(surface: pygame.Surface, color: Color, points: Sequence[Point]) -> None:
    """Wygładzony wielokąt (supersampling na małej warstwie obejmującej kształt).

    Gotowy kształt trafia do pamięci podręcznej (klucz: punkty względem rogu warstwy z dokładnością
    do 1/32 piksela), więc ikony i krawędzie rysowane co klatkę w tym samym miejscu kosztują jedno blit.
    """
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, y0 = math.floor(min(xs)) - 1, math.floor(min(ys)) - 1
    local = tuple((round((x - x0) * 32) / 32, round((y - y0) * 32) / 32) for x, y in points)
    r, g, b, a = rgba(color)
    key = ("poly", local, (r, g, b))
    surf = _poly_cache.get(key)
    if surf is None:
        w, h = math.ceil(max(x for x, _ in local)) + 2, math.ceil(max(y for _, y in local)) + 2
        big = pygame.Surface((w * SS, h * SS), pygame.SRCALPHA)
        big.fill((r, g, b, 0))
        pygame.draw.polygon(big, (r, g, b, 255), [(x * SS, y * SS) for x, y in local])
        surf = _store(key, pygame.transform.smoothscale(big, (w, h)), _poly_cache, _POLY_LIMIT)
    else:
        _poly_cache.move_to_end(key)
    _blit(surface, surf, (x0, y0), a)


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
    """Jedna wygładzona strzałka wzdłuż łamanej (dla skoczka: kształt litery L), z grotem na końcu.

    Kształt jest buforowany w pełnym kryciu (klucz bez alfy), a przezroczystość ustawia ``draw_arrows``
    przy rysowaniu — dzięki temu pulsująca strzałka nie jest co klatkę rysowana od nowa.
    """
    key = ("arrow", points, color[:3], round(width, 1))
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
        r, g, b, _ = rgba(color)
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
        surf = _store(key, pygame.transform.smoothscale(big, (w, h)))
    return surf, (x0, y0)


def draw_arrows(surface: pygame.Surface, arrows: Sequence[tuple[Sequence[Point], Color, float]], alpha: float = 1.0) -> None:
    """Rysuje strzałki; ``alpha`` (0..1) pozwala je płynnie pokazać albo wygasić."""
    for points, color, width in arrows:
        surf, pos = _arrow_surface(tuple((float(x), float(y)) for x, y in points), color, width)
        # Przezroczystość całej strzałki naraz (bez ciemniejszych zakładek w miejscu zgięcia).
        surf.set_alpha(int(rgba(color)[3] * max(0.0, min(1.0, alpha))))
        surface.blit(surf, pos)


def gradient_text(text_surface: pygame.Surface, left: Color, right: Color) -> pygame.Surface:
    """Nakłada poziomy gradient na wyrenderowany (biały) napis."""
    grad = horizontal_gradient(text_surface.get_size(), left, right).copy()
    grad.blit(text_surface, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return grad


def clear_cache() -> None:
    _cache.clear()
    _poly_cache.clear()
