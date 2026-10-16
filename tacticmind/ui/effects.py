"""Visual effects: a confetti burst after solving a puzzle and expanding rings."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import pygame

from . import gfx
from .scale import px


@dataclass
class _Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    color: tuple[int, int, int]
    size: float
    angle: float
    spin: float


@dataclass
class _Ring:
    x: float
    y: float
    age: float
    duration: float
    radius: float
    color: tuple[int, int, int]


class Effects:
    def __init__(self) -> None:
        self.particles: list[_Particle] = []
        self.rings: list[_Ring] = []
        self._rng = random.Random()

    def burst(self, center: tuple[float, float], colors: list[tuple[int, int, int]], count: int = 46) -> None:
        """Confetti from a point (e.g. the square where mate was delivered)."""
        for _ in range(count):
            angle = self._rng.uniform(-math.pi, 0) if self._rng.random() < 0.8 else self._rng.uniform(0, math.tau)
            speed = self._rng.uniform(px(160), px(520))
            life = self._rng.uniform(0.8, 1.5)
            self.particles.append(
                _Particle(
                    center[0],
                    center[1],
                    math.cos(angle) * speed,
                    math.sin(angle) * speed,
                    life,
                    life,
                    self._rng.choice(colors),
                    self._rng.uniform(px(3), px(7)),
                    self._rng.uniform(0, math.tau),
                    self._rng.uniform(-9, 9),
                )
            )

    def ring(self, center: tuple[float, float], radius: float, color: tuple[int, int, int], duration: float = 0.6) -> None:
        self.rings.append(_Ring(center[0], center[1], 0.0, duration, radius, color))

    def update(self, dt: float) -> None:
        gravity = px(900)
        for p in self.particles:
            p.life -= dt
            p.vy += gravity * dt
            p.vx *= math.exp(-1.6 * dt)
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.angle += p.spin * dt
        self.particles = [p for p in self.particles if p.life > 0]
        for r in self.rings:
            r.age += dt
        self.rings = [r for r in self.rings if r.age < r.duration]

    @property
    def active(self) -> bool:
        return bool(self.particles or self.rings)

    def draw(self, surface: pygame.Surface) -> None:
        for r in self.rings:
            t = r.age / r.duration
            radius = r.radius * (0.6 + 0.9 * (1 - (1 - t) ** 3))
            alpha = int(200 * (1 - t))
            gfx.circle(surface, (*r.color, alpha), (r.x, r.y), radius, max(2, px(3)))
        for p in self.particles:
            alpha = int(255 * min(1.0, p.life / (p.max_life * 0.5)))
            w, h = p.size, p.size * 0.55
            c, s = math.cos(p.angle), math.sin(p.angle)
            pts = [(p.x + dx * c - dy * s, p.y + dx * s + dy * c) for dx, dy in ((-w, -h), (w, -h), (w, h), (-w, h))]
            if alpha >= 250:
                pygame.draw.polygon(surface, p.color, pts)
            else:
                _alpha_poly(surface, (*p.color, alpha), pts)


def _alpha_poly(surface: pygame.Surface, color: tuple[int, int, int, int], pts: list[tuple[float, float]]) -> None:
    xs = [x for x, _ in pts]
    ys = [y for _, y in pts]
    x0, y0 = int(min(xs)) - 1, int(min(ys)) - 1
    layer = pygame.Surface((int(max(xs)) - x0 + 2, int(max(ys)) - y0 + 2), pygame.SRCALPHA)
    pygame.draw.polygon(layer, color, [(x - x0, y - y0) for x, y in pts])
    surface.blit(layer, (x0, y0))
