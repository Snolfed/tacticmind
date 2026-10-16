"""Evaluation bar: spring-animated, showing a value such as +1.5 or M3."""

from __future__ import annotations

import math

import pygame

from ..engine.types import EngineScore, format_score
from . import gfx, theme
from .anim import Spring
from .scale import fs, px
from .widgets import draw_text


def white_share(score: EngineScore) -> float:
    """Fraction of the bar belonging to White (0..1). The pawn evaluation is passed through a logistic function."""
    if score.mate is not None:
        if score.mate == 0:
            return 1.0 if score.value > 0 else 0.0
        return 1.0 if score.mate > 0 else 0.0
    cp = score.cp or 0
    return 0.5 + 0.5 * (2 / (1 + math.exp(-0.0042 * cp)) - 1)


class EvalBar:
    def __init__(self) -> None:
        self.spring = Spring(0.5, stiffness=60)
        self.target = 0.5
        self.label = "0.0"
        self.white_winning = True
        self.hidden = True
        self.white_bottom = True
        self.horizontal = False
        self._dt = 1 / 60

    @property
    def share(self) -> float:
        return self.spring.value

    def reset(self) -> None:
        self.spring = Spring(0.5, stiffness=60)
        self.target = 0.5

    def set_score(self, score: EngineScore | None) -> None:
        if score is None:
            return
        share = white_share(score)
        self.target = share if score.mate is not None else min(0.97, max(0.03, share))
        self.label = format_score(score).lstrip("+-")
        self.white_winning = score.value >= 0

    def update(self, dt: float) -> None:
        self.spring.update(self.target, dt)

    def draw(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        radius = min(rect.width, rect.height) // 2
        gfx.shadow(surface, rect, radius, px(10), 110, (0, px(4)))
        gfx.rrect(surface, (24, 27, 40), rect, radius)
        if self.hidden:
            gfx.rrect(surface, theme.BORDER_SOFT, rect, radius, max(1, px(1)))
            draw_text(surface, "?", rect.center, fs(15), theme.MUTED, "bold", "center")
            return
        share = min(1.0, max(0.0, self.spring.value))
        canvas = pygame.Surface(rect.size, pygame.SRCALPHA)
        canvas.fill((24, 27, 40, 255))
        light = (236, 239, 246)
        if self.horizontal:
            w = round(rect.width * share)
            white = pygame.Rect(0, 0, w, rect.height) if self.white_bottom else pygame.Rect(rect.width - w, 0, w, rect.height)
        else:
            h = round(rect.height * share)
            white = pygame.Rect(0, rect.height - h, rect.width, h) if self.white_bottom else pygame.Rect(0, 0, rect.width, h)
        pygame.draw.rect(canvas, light, white)
        # Subtle centre line (evaluation 0.0)
        if self.horizontal:
            pygame.draw.line(canvas, (*theme.ACCENT[:3], 160), (rect.width // 2, 0), (rect.width // 2, rect.height))
        else:
            pygame.draw.line(canvas, (*theme.ACCENT[:3], 160), (0, rect.height // 2), (rect.width, rect.height // 2))
        canvas.blit(gfx.rounded_mask(rect.size, radius), (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        surface.blit(canvas, rect.topleft)
        gfx.rrect(surface, (255, 255, 255, 25), rect, radius, max(1, px(1)))
        # Value shown on the winning side.
        color = (30, 33, 44) if self.white_winning else (236, 239, 246)
        size = fs(11) if not self.horizontal else fs(12)
        if self.horizontal:
            at_left = self.white_winning == self.white_bottom
            pos = (rect.x + px(8), rect.centery) if at_left else (rect.right - px(8), rect.centery)
            draw_text(surface, self.label, pos, size, color, "bold", "midleft" if at_left else "midright")
        else:
            at_bottom = self.white_winning == self.white_bottom
            pos = (rect.centerx, rect.bottom - px(6)) if at_bottom else (rect.centerx, rect.y + px(6))
            draw_text(surface, self.label, pos, size, color, "bold", "midbottom" if at_bottom else "midtop", max_width=rect.width - 2)
