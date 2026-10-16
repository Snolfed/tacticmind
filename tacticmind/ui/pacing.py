"""Even frame pacing: a precise FPS limiter and an FPS counter in the window corner.

``pygame.time.Clock.tick`` counts in whole milliseconds and sleeps via ``SDL_Delay``, which
can oversleep by a few ms — frames then arrive unevenly (e.g. 15, 18, 16, 21 ms) and motion
looks jittery. Here we sleep almost up to the target and busy-wait the last moment on a
microsecond-resolution clock; successive targets are evenly spaced, so the pace is steady.
"""

from __future__ import annotations

import time
from collections import deque

import pygame

from ..i18n import t
from . import fonts, gfx, theme
from .anim import clock
from .scale import fs, px
from .widgets import draw_text

#: The final part of the wait is busy-waited (OS sleep can be less accurate).
SPIN = 0.0015


class FramePacer:
    """Makes successive frames start every ``1 / fps`` seconds."""

    def __init__(self) -> None:
        self._target: float | None = None

    def wait(self, fps: int) -> None:
        period = 1.0 / max(1, fps)
        current = clock()
        target = current if self._target is None else self._target + period
        if target < current - period:
            # Large delay (e.g. dragging the window, loading) — don't catch up with a burst of fast frames.
            target = current
        remaining = target - current
        if remaining > SPIN:
            time.sleep(remaining - SPIN)
        while clock() < target:
            pass
        self._target = target


class FpsCounter:
    """Average frames per second and frame preparation time over the last second."""

    WINDOW = 1.0
    REFRESH = 0.25  # on-screen values are refreshed 4× per second so they stay readable

    def __init__(self) -> None:
        self._frames: deque[tuple[float, float]] = deque()
        self.fps = 0.0
        self.frame_ms = 0.0
        self._shown_at = -10.0

    def record(self, start: float, end: float) -> None:
        """Records a frame: its start and end time (including presenting it)."""
        frames = self._frames
        frames.append((start, end - start))
        while frames and frames[0][0] < start - self.WINDOW:
            frames.popleft()
        if start - self._shown_at >= self.REFRESH and len(frames) >= 2:
            self._shown_at = start
            span = frames[-1][0] - frames[0][0]
            self.fps = (len(frames) - 1) / span if span > 0 else 0.0
            self.frame_ms = 1000 * sum(work for _, work in frames) / len(frames)

    def draw(self, surface: pygame.Surface, top: int) -> None:
        text = t("fps.overlay", fps=round(self.fps), ms=f"{self.frame_ms:.1f}".replace(".", t("fmt.decimal")))
        size = fs(12)
        pill = pygame.Rect(0, 0, fonts.text_size(text, size, "bold")[0] + px(18), px(24))
        pill.topright = (surface.get_width() - px(12), top + px(4))
        gfx.rrect(surface, (8, 10, 18, 200), pill, pill.height // 2)
        gfx.rrect(surface, (*theme.BORDER[:3], 160), pill, pill.height // 2, max(1, px(1)))
        draw_text(surface, text, pill.center, size, theme.TEXT, "bold", "center")
