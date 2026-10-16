"""Animations: easing functions, smooth approach to a target and a spring."""

from __future__ import annotations

import math
import time

_frame_time: float | None = None


def clock() -> float:
    """High-resolution clock (seconds).

    On Windows (Python < 3.13) ``time.monotonic()`` ticks every 15.6 ms — animations driven by it
    skip every other frame. ``perf_counter`` has microsecond resolution on every system.
    """
    return time.perf_counter()


def begin_frame(t: float | None = None) -> float:
    """Sets the current frame time — all animations in this frame see the same instant."""
    global _frame_time
    _frame_time = clock() if t is None else t
    return _frame_time


def now() -> float:
    """Current frame time (or the clock if the game loop has not started yet)."""
    return _frame_time if _frame_time is not None else clock()


def clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def ease_out_cubic(t: float) -> float:
    t = clamp01(t)
    return 1 - (1 - t) ** 3


def ease_in_out_cubic(t: float) -> float:
    t = clamp01(t)
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out_back(t: float, overshoot: float = 1.70158) -> float:
    """Easing with a slight overshoot (a springy pop-in effect)."""
    t = clamp01(t)
    c3 = overshoot + 1
    return 1 + c3 * (t - 1) ** 3 + overshoot * (t - 1) ** 2


def ease_out_quint(t: float) -> float:
    t = clamp01(t)
    return 1 - (1 - t) ** 5


def approach(current: float, target: float, dt: float, rate: float = 12.0) -> float:
    """Exponential approach to a target, independent of the frame rate."""
    return target + (current - target) * math.exp(-rate * dt)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_color(a: tuple[int, ...], b: tuple[int, ...], t: float) -> tuple[int, ...]:
    t = clamp01(t)
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


class Spring:
    """Critically damped spring (e.g. the eval bar): fast, smooth and without oscillation."""

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
    """A 0..1 value smoothly following an on/off state (e.g. button highlight)."""

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
