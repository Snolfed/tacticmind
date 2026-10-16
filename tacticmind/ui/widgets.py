"""Kontrolki interfejsu: tekst dopasowany do miejsca, karty, przyciski z animacją, przełącznik
segmentowy, przewijanie i ikony rysowane wektorowo (wygładzone)."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import pygame

from . import fonts, gfx, theme
from .anim import Fader, approach, ease_out_cubic, lerp_color, now
from .scale import fs, px

Color = tuple[int, ...]
Label = str | Callable[[], str]


def label_text(label: Label) -> str:
    return label() if callable(label) else label


# ---------------------------------------------------------------------------
# Tekst
# ---------------------------------------------------------------------------
def draw_text(
    surface: pygame.Surface,
    text: str,
    pos: tuple[float, float],
    size: int,
    color: Color = theme.TEXT,
    style: str = "regular",
    anchor: str = "topleft",
    max_width: int | None = None,
    min_size: int | None = None,
) -> pygame.Rect:
    """Rysuje napis; z ``max_width`` zmniejsza czcionkę i w razie potrzeby skraca tekst „…”."""
    if max_width is not None:
        text, size = fonts.fit(text, max(4, max_width), size, style, min_size)
    surf = fonts.render(text, size, color, style)
    rect = surf.get_rect(**{anchor: (round(pos[0]), round(pos[1]))})
    surface.blit(surf, rect)
    return rect


def draw_wrapped(
    surface: pygame.Surface,
    text: str,
    rect: pygame.Rect,
    size: int,
    color: Color = theme.TEXT_SOFT,
    style: str = "regular",
    gap: int | None = None,
    max_lines: int | None = None,
    shrink: bool = False,
) -> int:
    """Tekst zawijany w prostokącie; nigdy nie wychodzi poza ``rect`` (zmniejsza czcionkę albo skraca).

    Zwraca wysokość zajętą przez tekst.
    """
    gap = px(3) if gap is None else gap
    if shrink:
        lines, size = fonts.fit_wrapped(text, rect.width, rect.height, size, style, gap=gap)
    else:
        limit = max_lines if max_lines is not None else max(1, (rect.height + gap) // (fonts.line_height(size, style) + gap))
        lines = fonts.wrap_limited(text, size, rect.width, limit, style)
    step = fonts.line_height(size, style) + gap
    y = rect.y
    for line in lines:
        draw_text(surface, line, (rect.x, y), size, color, style)
        y += step
    return y - rect.y


def wrapped_height(text: str, width: int, size: int, style: str = "regular", gap: int | None = None) -> int:
    gap = px(3) if gap is None else gap
    return len(fonts.wrap(text, size, width, style)) * (fonts.line_height(size, style) + gap)


# ---------------------------------------------------------------------------
# Karty i ikony
# ---------------------------------------------------------------------------
def card(surface: pygame.Surface, rect: pygame.Rect, radius: int | None = None, color: Color = theme.SURFACE, elevated: bool = True) -> None:
    """Karta: miękki cień, wypełnienie i subtelna ramka."""
    radius = px(theme.RADIUS) if radius is None else radius
    if rect.width <= 0 or rect.height <= 0:
        return
    blur, dy = (px(16), px(6)) if elevated else (0, 0)
    border_w = max(1, px(1))
    surf, pad = gfx.card_surface(rect.size, radius, color, theme.BORDER_SOFT, border_w, blur, 120, dy)
    if len(color) == 4 and color[3] < 255:
        surface.blit(surf, (rect.x - pad, rect.y - pad))
        return
    # Środek nieprzezroczystej karty to jednolity kolor: wypełnienie jest dużo tańsze niż kopiowanie pikseli.
    radius = max(0, min(radius, min(rect.size) // 2))
    inner = pygame.Rect(pad + border_w + 1, pad + radius + 1, rect.width - 2 * (border_w + 1), rect.height - 2 * (radius + 1))
    gfx.blit_frame(surface, surf, (rect.x - pad, rect.y - pad), inner)
    if inner.width > 0 and inner.height > 0:
        surface.fill(color[:3], inner.move(rect.x - pad, rect.y - pad))


def icon_check(surface: pygame.Surface, center: tuple[float, float], size: float, color: Color = theme.TEXT) -> None:
    cx, cy = center
    w = max(2.0, size * 0.16)
    a, b, c = (cx - size * 0.32, cy + size * 0.02), (cx - size * 0.08, cy + size * 0.26), (cx + size * 0.34, cy - size * 0.26)
    gfx.thick_line(surface, color, a, b, w)
    gfx.thick_line(surface, color, b, c, w)


def icon_cross(surface: pygame.Surface, center: tuple[float, float], size: float, color: Color = theme.TEXT) -> None:
    cx, cy = center
    d = size * 0.26
    w = max(2.0, size * 0.16)
    gfx.thick_line(surface, color, (cx - d, cy - d), (cx + d, cy + d), w)
    gfx.thick_line(surface, color, (cx - d, cy + d), (cx + d, cy - d), w)


def icon_chevron(surface: pygame.Surface, center: tuple[float, float], size: float, color: Color, direction: str) -> None:
    cx, cy = center
    d = size * 0.22
    w = max(2.0, size * 0.12)
    if direction == "left":
        gfx.thick_line(surface, color, (cx + d * 0.5, cy - d), (cx - d * 0.5, cy), w)
        gfx.thick_line(surface, color, (cx - d * 0.5, cy), (cx + d * 0.5, cy + d), w)
    elif direction == "right":
        gfx.thick_line(surface, color, (cx - d * 0.5, cy - d), (cx + d * 0.5, cy), w)
        gfx.thick_line(surface, color, (cx + d * 0.5, cy), (cx - d * 0.5, cy + d), w)
    else:  # "down"
        gfx.thick_line(surface, color, (cx - d, cy - d * 0.5), (cx, cy + d * 0.5), w)
        gfx.thick_line(surface, color, (cx, cy + d * 0.5), (cx + d, cy - d * 0.5), w)


def icon_speaker(surface: pygame.Surface, center: tuple[float, float], size: float, color: Color, on: bool) -> None:
    cx, cy = center
    s = size
    body = [
        (cx - s * 0.36, cy - s * 0.12), (cx - s * 0.18, cy - s * 0.12), (cx + s * 0.02, cy - s * 0.3),
        (cx + s * 0.02, cy + s * 0.3), (cx - s * 0.18, cy + s * 0.12), (cx - s * 0.36, cy + s * 0.12),
    ]
    gfx.polygon(surface, color, body)
    w = max(1.5, s * 0.08)
    if on:
        for r in (0.2, 0.34):
            pts = [(cx + s * 0.06 + math.cos(a) * s * r, cy + math.sin(a) * s * r) for a in [i * 0.14 - 0.7 for i in range(11)]]
            for p1, p2 in zip(pts, pts[1:]):
                gfx.thick_line(surface, color, p1, p2, w)
    else:
        d = s * 0.13
        gfx.thick_line(surface, color, (cx + s * 0.18 - d, cy - d), (cx + s * 0.18 + d, cy + d), w)
        gfx.thick_line(surface, color, (cx + s * 0.18 - d, cy + d), (cx + s * 0.18 + d, cy - d), w)


def icon_flame(surface: pygame.Surface, center: tuple[float, float], size: float, t: float = 0.0) -> None:
    """Płomień serii — dwa wielokąty z lekkim „migotaniem”."""
    cx, cy = center
    wobble = math.sin(t * 7) * size * 0.04

    def flame(scale: float, color: Color, lift: float) -> None:
        s = size * scale
        pts = [
            (cx, cy - s * 0.62 + wobble), (cx + s * 0.18, cy - s * 0.25), (cx + s * 0.38, cy - s * 0.32 - wobble),
            (cx + s * 0.42, cy + s * 0.12), (cx + s * 0.28, cy + s * 0.42), (cx, cy + s * 0.5 + lift),
            (cx - s * 0.28, cy + s * 0.42), (cx - s * 0.42, cy + s * 0.1), (cx - s * 0.3, cy - s * 0.18 + wobble),
            (cx - s * 0.12, cy - s * 0.05),
        ]
        gfx.polygon(surface, color, pts)

    flame(1.0, theme.ORANGE, 0)
    flame(0.55, theme.AMBER, -size * 0.05)


# ---------------------------------------------------------------------------
# Przycisk
# ---------------------------------------------------------------------------
_STYLES: dict[str, tuple[Color, Color, Color]] = {
    # (góra gradientu, dół gradientu, kolor tekstu)
    "primary": (theme.ACCENT, theme.ACCENT_2, (8, 28, 34)),
    "violet": (theme.VIOLET, theme.VIOLET_2, (255, 255, 255)),
    "danger": (theme.ROSE, theme.RED, (255, 255, 255)),
    "secondary": (theme.SURFACE_2, theme.SURFACE_2, theme.TEXT_SOFT),
    "ghost": ((0, 0, 0, 0), (0, 0, 0, 0), theme.TEXT_SOFT),
}


@dataclass
class Button:
    label: Label
    on_click: Callable[[], None]
    rect: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, 0, 0, 0))
    style: str = "secondary"
    enabled: bool = True
    visible: bool = True
    size: int = 15  # bazowy rozmiar czcionki (skalowany przez fs)
    icon: str | None = None  # "left" | "right" | "sound_on" | "sound_off" | "fullscreen" | "fullscreen_exit" | "settings"
    pill: bool = False
    active: bool = False  # np. aktywna zakładka nawigacji
    hovered: bool = False
    _fader: Fader = field(default_factory=Fader)
    _pressed_at: float = -10.0

    def handle(self, event: pygame.event.Event) -> bool:
        if not self.visible:
            return False
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.rect.collidepoint(event.pos):
            if self.enabled:
                self._pressed_at = now()
                self.on_click()
            return True
        return False

    def draw(self, surface: pygame.Surface) -> None:
        if not self.visible or self.rect.width <= 0:
            return
        hover = self._fader.step(self.hovered and self.enabled)
        style = "primary" if self.active and self.style in ("secondary", "ghost") else self.style
        top, bottom, text_color = _STYLES.get(style, _STYLES["secondary"])
        if not self.enabled:
            top = bottom = theme.SURFACE
            text_color = theme.DIM
        # Krótkie „wciśnięcie” po kliknięciu.
        press = max(0.0, 1 - (now() - self._pressed_at) / 0.16)
        rect = self.rect.inflate(-round(px(4) * press), -round(px(4) * press))
        radius = rect.height // 2 if self.pill else min(px(12), rect.height // 2)
        if style == "ghost":
            if hover > 0.01:
                gfx.rrect(surface, (*theme.SURFACE_2, int(255 * hover)), rect, radius)
        else:
            if self.enabled and style in ("primary", "violet", "danger"):
                gfx.shadow(surface, rect, radius, px(10), int(60 + 50 * hover), (0, px(3)))
            gfx.rrect_gradient(surface, top, bottom, rect, radius)
            if style == "secondary" or not self.enabled:
                gfx.rrect(surface, lerp_color(theme.BORDER_SOFT, theme.BORDER, hover), rect, radius, max(1, px(1)))
            if hover > 0.01:
                gfx.rrect(surface, (255, 255, 255, int(22 * hover)), rect, radius)
        if self.icon in ("left", "right"):
            icon_chevron(surface, rect.center, min(rect.width, rect.height) * 0.9, text_color, self.icon)
            return
        if self.icon in ("sound_on", "sound_off"):
            icon_speaker(surface, rect.center, rect.height * 0.62, text_color, self.icon == "sound_on")
            return
        if self.icon in ("fullscreen", "fullscreen_exit"):
            icon_fullscreen(surface, rect.center, rect.height * 0.62, text_color, self.icon == "fullscreen_exit")
            return
        if self.icon == "settings":
            icon_gear(surface, rect.center, rect.height * 0.56, text_color)
            return
        draw_text(surface, label_text(self.label), rect.center, fs(self.size), text_color, "bold", "center", max_width=rect.width - px(14))


# ---------------------------------------------------------------------------
# Przełącznik segmentowy
# ---------------------------------------------------------------------------
@dataclass
class Segmented:
    """Przełącznik segmentowy z przesuwającym się wskaźnikiem (np. Ukryty / Podpowiedź / Pełny)."""

    options: list[tuple[str, Label]]  # (wartość, etykieta)
    value: str
    on_change: Callable[[str], None]
    rect: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, 0, 0, 0))
    size: int = 13
    accent: Color = theme.ACCENT
    hovered: int = -1
    _x: float = -1.0
    _last: float = field(default_factory=now)

    def _segment(self, i: int) -> pygame.Rect:
        w = self.rect.width / len(self.options)
        return pygame.Rect(round(self.rect.x + i * w), self.rect.y, round(w), self.rect.height)

    def handle(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEMOTION:
            self.hovered = next((i for i in range(len(self.options)) if self._segment(i).collidepoint(event.pos)), -1)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.rect.collidepoint(event.pos):
            for i, (value, _) in enumerate(self.options):
                if self._segment(i).collidepoint(event.pos):
                    if value != self.value:
                        self.on_change(value)
                    return True
        return False

    def draw(self, surface: pygame.Surface) -> None:
        if self.rect.width <= 0:
            return
        t = now()
        dt = min(0.1, t - self._last)
        self._last = t
        radius = self.rect.height // 2
        gfx.rrect(surface, (12, 14, 22), self.rect, radius)
        gfx.rrect(surface, theme.BORDER_SOFT, self.rect, radius, max(1, px(1)))
        index = next((i for i, (v, _) in enumerate(self.options) if v == self.value), 0)
        target = self._segment(index)
        self._x = target.x if self._x < 0 else approach(self._x, target.x, dt, 16)
        pad = px(3)
        indicator = pygame.Rect(round(self._x) + pad, target.y + pad, target.width - 2 * pad, target.height - 2 * pad)
        gfx.rrect(surface, (*self.accent[:3], 52), indicator, indicator.height // 2)
        gfx.rrect(surface, (*self.accent[:3], 150), indicator, indicator.height // 2, max(1, px(1)))
        for i, (value, label) in enumerate(self.options):
            seg = self._segment(i)
            color = theme.TEXT if value == self.value else (theme.TEXT_SOFT if i == self.hovered else theme.MUTED)
            draw_text(surface, label_text(label), seg.center, fs(self.size), color, "bold", "center", max_width=seg.width - px(10))


# ---------------------------------------------------------------------------
# Przewijanie
# ---------------------------------------------------------------------------
class ScrollArea:
    """Płynne pionowe przewijanie kółkiem myszy."""

    def __init__(self, stick_to_bottom: bool = True) -> None:
        self.offset = 0.0
        self.target = 0.0
        self.content_height = 0
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.stick_to_bottom = stick_to_bottom
        self._last = now()

    def handle(self, event: pygame.event.Event, mouse_pos: tuple[int, int] | None = None) -> bool:
        pos = mouse_pos if mouse_pos is not None else pygame.mouse.get_pos()
        if event.type == pygame.MOUSEWHEEL and self.rect.collidepoint(pos) and self.content_height > self.rect.height:
            self.target = max(0.0, min(self.max_offset(), self.target - event.y * px(48)))
            self.stick_to_bottom = self.target >= self.max_offset() - 2
            return True
        return False

    def max_offset(self) -> float:
        return max(0.0, self.content_height - self.rect.height)

    def scroll_to_top(self) -> None:
        self.target = self.offset = 0.0
        self.stick_to_bottom = False

    def follow(self) -> None:
        """Wywoływane co klatkę po ustaleniu wysokości treści."""
        t = now()
        dt = min(0.1, t - self._last)
        self._last = t
        if self.stick_to_bottom:
            self.target = self.max_offset()
        self.target = min(self.target, self.max_offset())
        self.offset = approach(self.offset, self.target, dt, 18)
        if abs(self.offset - self.target) < 0.5:
            self.offset = self.target

    def draw_scrollbar(self, surface: pygame.Surface) -> None:
        if self.content_height <= self.rect.height:
            return
        ratio = self.rect.height / self.content_height
        h = max(px(24), self.rect.height * ratio)
        y = self.rect.y + (self.rect.height - h) * (self.offset / max(1.0, self.max_offset()))
        w = max(3, px(4))
        gfx.rrect(surface, (*theme.BORDER[:3], 220), pygame.Rect(self.rect.right - w, round(y), w, round(h)), w // 2)


def fade_in(age: float, duration: float = 0.35) -> float:
    """Współczynnik 0..1 do płynnego pojawiania się nowych elementów."""
    return ease_out_cubic(age / duration)


def icon_fullscreen(surface: pygame.Surface, center: tuple[float, float], size: float, color: Color, active: bool) -> None:
    """Ikona pełnego ekranu: narożniki skierowane na zewnątrz (włącz) albo do środka (wyłącz)."""
    cx, cy = center
    d = size * 0.3
    arm = size * 0.16
    w = max(1.5, size * 0.09)
    for sx in (-1, 1):
        for sy in (-1, 1):
            corner = (cx + sx * d, cy + sy * d)
            if active:  # narożniki do środka = wyjście z pełnego ekranu
                tip = (cx + sx * (d - arm), cy + sy * (d - arm))
                gfx.thick_line(surface, color, (tip[0], corner[1]), tip, w)
                gfx.thick_line(surface, color, (corner[0], tip[1]), tip, w)
            else:
                gfx.thick_line(surface, color, corner, (corner[0] - sx * arm, corner[1]), w)
                gfx.thick_line(surface, color, corner, (corner[0], corner[1] - sy * arm), w)


def icon_gear(surface: pygame.Surface, center: tuple[float, float], size: float, color: Color) -> None:
    """Ikona ustawień: koło zębate (pierścień i osiem zębów)."""
    cx, cy = center
    w = max(1.5, size * 0.16)
    for k in range(8):
        a = k * math.pi / 4
        dx, dy = math.cos(a), math.sin(a)
        gfx.thick_line(surface, color, (cx + dx * size * 0.3, cy + dy * size * 0.3), (cx + dx * size * 0.46, cy + dy * size * 0.46), w)
    gfx.circle(surface, color, center, size * 0.31, max(2, round(size * 0.15)))


@dataclass
class Slider:
    """Poziomy suwak 0..1 (np. głośność): przeciąganie, kliknięcie w pasek albo kółko myszy."""

    value: float
    on_change: Callable[[float], None]
    on_release: Callable[[], None] | None = None
    rect: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, 0, 0, 0))
    visible: bool = True
    dragging: bool = False
    hovered: bool = False
    _fader: Fader = field(default_factory=Fader)

    def _hit(self) -> pygame.Rect:
        return self.rect.inflate(px(10), px(16))

    def _set_from_x(self, x: int) -> None:
        value = min(1.0, max(0.0, (x - self.rect.x) / max(1, self.rect.width)))
        if abs(value - self.value) > 1e-3:
            self.value = value
            self.on_change(value)

    def handle(self, event: pygame.event.Event) -> bool:
        if not self.visible:
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self._hit().collidepoint(event.pos):
            self.dragging = True
            self._set_from_x(event.pos[0])
            return True
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self._hit().collidepoint(event.pos)
            if self.dragging:
                self._set_from_x(event.pos[0])
                return True
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.dragging:
            self.dragging = False
            if self.on_release:
                self.on_release()
            return True
        if event.type == pygame.MOUSEWHEEL and self._hit().collidepoint(pygame.mouse.get_pos()):
            value = min(1.0, max(0.0, round((self.value + event.y * 0.05) * 20) / 20))
            if value != self.value:
                self.value = value
                self.on_change(value)
                if self.on_release:
                    self.on_release()
            return True
        return False

    def draw(self, surface: pygame.Surface) -> None:
        if not self.visible or self.rect.width <= 0:
            return
        active = self._fader.step(self.hovered or self.dragging)
        track_h = max(4, px(6))
        track = pygame.Rect(self.rect.x, self.rect.centery - track_h // 2, self.rect.width, track_h)
        gfx.rrect(surface, theme.SURFACE_3, track, track_h // 2)
        filled = track.copy()
        filled.width = max(track_h, round(track.width * self.value))
        if self.value > 0:
            gfx.rrect_gradient(surface, theme.ACCENT, theme.ACCENT_2, filled, track_h // 2)
        knob = (track.x + track.width * self.value, track.centery)
        radius = px(7) + px(2) * active
        gfx.circle(surface, (*theme.SHADOW, 140), (knob[0], knob[1] + px(1)), radius + px(1))
        gfx.circle(surface, (245, 248, 252), knob, radius)
