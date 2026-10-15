"""Animacje: funkcje wygładzania (easing), płynne dążenie do celu i sprężyna."""

from __future__ import annotations

import math
import time


def now() -> float:
    return time.monotonic()


def clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def ease_out_cubic(t: float) -> float:
    t = clamp01(t)
    return 1 - (1 - t) ** 3


def ease_in_out_cubic(t: float) -> float:
    t = clamp01(t)
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out_back(t: float, overshoot: float = 1.70158) -> float:
    """Wygładzenie z lekkim „przestrzeleniem” (efekt sprężystego pojawienia się)."""
    t = clamp01(t)
    c3 = overshoot + 1
    return 1 + c3 * (t - 1) ** 3 + overshoot * (t - 1) ** 2


def ease_out_quint(t: float) -> float:
    t = clamp01(t)
    return 1 - (1 - t) ** 5


def approach(current: float, target: float, dt: float, rate: float = 12.0) -> float:
    """Wykładnicze dążenie do celu niezależne od liczby klatek na sekundę."""
    return target + (current - target) * math.exp(-rate * dt)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_color(a: tuple[int, ...], b: tuple[int, ...], t: float) -> tuple[int, ...]:
    t = clamp01(t)
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


class Spring:
    """Krytycznie tłumiona sprężyna (np. pasek oceny): szybko, płynnie i bez drgań."""

    def __init__(self, value: float = 0.0, stiffness: float = 120.0, damping: float | None = None) -> None:
        self.value = value
        self.velocity = 0.0
        self.stiffness = stiffness
        self.damping = damping if damping is not None else 2 * math.sqrt(stiffness)

    def update(self, target: float, dt: float) -> float:
        steps = max(1, int(dt / 0.008))
        h = dt / steps
        for _ in range(steps):
            force = self.stiffness * (target - self.value) - self.damping * self.velocity
            self.velocity += force * h
            self.value += self.velocity * h
        return self.value


class Fader:
    """Wartość 0..1 płynnie podążająca za stanem włączony/wyłączony (np. podświetlenie przycisku)."""

    def __init__(self, rate: float = 14.0) -> None:
        self.value = 0.0
        self.rate = rate
        self._last = now()

    def step(self, on: bool) -> float:
        t = now()
        dt = min(0.1, t - self._last)
        self._last = t
        self.value = approach(self.value, 1.0 if on else 0.0, dt, self.rate)
        return self.value
