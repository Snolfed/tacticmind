"""Główna pętla gry (pygame): okno, skalowanie, ekrany z płynnymi przejściami, język, proces silnika."""

from __future__ import annotations

import os
import random

import pygame

from .. import i18n
from ..engine.process import EngineClient, EngineEvent
from ..puzzles.loader import load_puzzles, puzzle_source
from ..rating.profile import PlayerProfile, load_profile, save_profile
from . import fonts, gfx, sounds
from .anim import ease_out_cubic
from .icon import app_icon
from .scale import compute_scale, set_scale
from .screens.base import Screen
from .screens.home import HomeScreen
from .screens.howto import HowToScreen
from .screens.play import PlayScreen
from .screens.stats import StatsScreen
from .sounds import Sounds
from .topbar import TopBar

DEFAULT_SIZE = (1360, 860)
MIN_SIZE = (420, 600)
TRANSITION = 0.22


class App:
    def __init__(self, size: tuple[int, int] = DEFAULT_SIZE) -> None:
        sounds.pre_init()  # stereo + mały bufor — przed pygame.init(), które otwiera dźwięk
        pygame.init()
        fonts.reset()
        self.profile: PlayerProfile = load_profile()
        i18n.set_language(self.profile.language)
        pygame.display.set_caption(i18n.t("app.caption"))
        pygame.display.set_icon(app_icon(128))  # przed set_mode — na niektórych systemach inaczej nie działa
        self.screen = pygame.display.set_mode(size, pygame.RESIZABLE)
        self.fullscreen = False
        self.windowed_size = size
        pygame.key.set_repeat(300, 60)
        set_scale(compute_scale(*size))
        self.engine = EngineClient()
        self.sounds = Sounds(self.profile.sound, background=True, volume=self.profile.volume)
        self.puzzles = load_puzzles()
        self.puzzle_source = puzzle_source()
        self.rng = random.Random()
        self.topbar = TopBar(self)
        self.screens: dict[str, Screen] = {
            "home": HomeScreen(self),
            "play": PlayScreen(self),
            "stats": StatsScreen(self),
            "howto": HowToScreen(self),
        }
        self.current_name = "home"
        self.running = True
        self._transition: pygame.Surface | None = None
        self._transition_age = 0.0
        self.relayout()
        self.screens["home"].enter()

    @property
    def current(self) -> Screen:
        return self.screens[self.current_name]

    def go(self, name: str) -> None:
        """Przejście do innego ekranu z płynnym przenikaniem."""
        if name == self.current_name:
            return
        self._transition = self.screen.copy()
        self._transition_age = 0.0
        self.current.leave()
        self.current_name = name
        self.relayout()
        self.current.enter()

    def set_language(self, code: str) -> None:
        """Zmiana języka interfejsu (zapamiętywana w profilu)."""
        i18n.set_language(code)
        self.profile.language = i18n.get_language()
        pygame.display.set_caption(i18n.t("app.caption"))
        self.save()
        for screen in self.screens.values():
            screen.on_language_change()
        self.relayout()

    def toggle_fullscreen(self) -> None:
        """F11: pełny ekran w rozdzielczości pulpitu i z powrotem do okna o poprzednim rozmiarze."""
        if not self.fullscreen:
            self.windowed_size = self.screen.get_size()
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.screen = pygame.display.set_mode(self.windowed_size, pygame.RESIZABLE)
        self.fullscreen = not self.fullscreen
        self.relayout()

    def save(self) -> None:
        save_profile(self.profile)

    def relayout(self) -> None:
        w, h = self.screen.get_size()
        set_scale(compute_scale(w, h))
        self.topbar.layout(w)
        top = self.topbar.rect.height
        content = pygame.Rect(0, top, w, h - top)
        for screen in self.screens.values():
            screen.layout(content)

    def _escape_used(self) -> bool:
        """Esc zamyka najpierw podgląd wariantu na ekranie gry, a dopiero potem pełny ekran."""
        play = self.screens.get("play")
        return self.current_name == "play" and getattr(play, "preview", None) is not None

    def dispatch_engine(self, event: EngineEvent) -> None:
        for screen in self.screens.values():
            screen.on_engine(event)

    def frame(self, dt: float) -> None:
        """Jedna klatka: zdarzenia, wiadomości silnika, logika, rysowanie."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type in (pygame.VIDEORESIZE, pygame.WINDOWRESIZED, pygame.WINDOWSIZECHANGED):
                w, h = self.screen.get_size()
                if w < MIN_SIZE[0] or h < MIN_SIZE[1]:
                    self.screen = pygame.display.set_mode((max(w, MIN_SIZE[0]), max(h, MIN_SIZE[1])), pygame.RESIZABLE)
                self.relayout()
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_F11 or event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE and self.fullscreen and not self._escape_used():
                self.toggle_fullscreen()
            elif self.topbar.handle(event):
                continue
            else:
                self.current.handle(event)
        for engine_event in self.engine.poll():
            self.dispatch_engine(engine_event)
        self.topbar.update(dt)
        self.current.update(dt)
        self.screen.blit(gfx.background(self.screen.get_size()), (0, 0))
        self.current.draw(self.screen)
        if self._transition is not None:
            # Przenikanie: stary ekran płynnie znika nad nowym.
            self._transition_age += dt
            fade = 1 - ease_out_cubic(self._transition_age / TRANSITION)
            if fade <= 0.01:
                self._transition = None
            else:
                self._transition.set_alpha(int(255 * fade))
                self.screen.blit(self._transition, (0, 0))
        self.topbar.draw(self.screen)
        pygame.display.flip()

    def run(self) -> None:
        clock = pygame.time.Clock()
        try:
            while self.running:
                dt = clock.tick(60) / 1000
                self.frame(min(dt, 0.1))
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self.save()
        self.engine.close()
        pygame.quit()


def main() -> None:
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    App().run()
