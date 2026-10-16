"""Równe tempo klatek: precyzyjny limiter FPS i licznik FPS w rogu okna.

``pygame.time.Clock.tick`` liczy w pełnych milisekundach i usypia przez ``SDL_Delay``, które
potrafi zaspać o kilka ms — klatki przychodzą wtedy nierówno (np. 15, 18, 16, 21 ms) i ruch
wygląda, jakby drgał. Tutaj śpimy prawie do celu, a ostatnią chwilę odliczamy aktywnie na zegarze
o rozdzielczości mikrosekund; kolejne cele są w stałych odstępach, więc tempo jest równe.
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

#: Ostatni fragment oczekiwania odliczany aktywnie (sen systemowy bywa mniej dokładny).
SPIN = 0.0015


class FramePacer:
    """Pilnuje, żeby kolejne klatki zaczynały się co ``1 / fps`` sekundy."""

    def __init__(self) -> None:
        self._target: float | None = None

    def wait(self, fps: int) -> None:
        period = 1.0 / max(1, fps)
        current = clock()
        target = current if self._target is None else self._target + period
        if target < current - period:
            # Duże opóźnienie (np. przeciąganie okna, wczytywanie) — bez nadrabiania serią szybkich klatek.
            target = current
        remaining = target - current
        if remaining > SPIN:
            time.sleep(remaining - SPIN)
        while clock() < target:
            pass
        self._target = target


class FpsCounter:
    """Średnia liczba klatek na sekundę i czas przygotowania klatki z ostatniej sekundy."""

    WINDOW = 1.0
    REFRESH = 0.25  # wartości na ekranie odświeżamy 4× na sekundę, żeby dało się je przeczytać

    def __init__(self) -> None:
        self._frames: deque[tuple[float, float]] = deque()
        self.fps = 0.0
        self.frame_ms = 0.0
        self._shown_at = -10.0

    def record(self, start: float, end: float) -> None:
        """Zapisuje klatkę: moment rozpoczęcia i zakończenia (razem z wyświetleniem)."""
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
