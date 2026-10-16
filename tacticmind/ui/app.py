"""Main game loop (pygame): window, scaling, screens with smooth transitions, language, engine process."""

from __future__ import annotations

import gc
import os
import random

import chess
import pygame

from .. import i18n
from ..coach.openings import Opening
from ..engine.process import EngineClient, EngineEvent
from ..puzzles.loader import load_puzzles, puzzle_source
from ..rating.profile import PlayerProfile, load_profile, save_profile
from . import fonts, gfx, sounds
from .anim import begin_frame, clock, ease_out_cubic
from .icon import app_icon
from .pacing import FpsCounter, FramePacer
from .scale import compute_scale, set_scale
from .screens.base import Screen
from .screens.coach_game import CoachGameScreen
from .screens.coach_menu import CoachMenuScreen
from .screens.home import HomeScreen
from .screens.howto import HowToScreen
from .screens.play import PlayScreen
from .screens.stats import StatsScreen
from .settings_panel import SettingsPanel
from .sounds import Sounds
from .topbar import TopBar

DEFAULT_SIZE = (1360, 860)
MIN_SIZE = (420, 600)
TRANSITION = 0.22


class App:
    def __init__(self, size: tuple[int, int] = DEFAULT_SIZE) -> None:
        sounds.pre_init()  # stereo + small buffer — before pygame.init(), which opens audio
        pygame.init()
        fonts.reset()
        self.profile: PlayerProfile = load_profile()
        i18n.set_language(self.profile.language)
        pygame.display.set_caption(i18n.t("app.caption"))
        pygame.display.set_icon(app_icon(128))  # before set_mode — otherwise it doesn't work on some systems
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
        self.settings = SettingsPanel(self)
        self.fps = FpsCounter()
        self.topbar = TopBar(self)
        self.screens: dict[str, Screen] = {
            "home": HomeScreen(self),
            "play": PlayScreen(self),
            "coach": CoachMenuScreen(self),
            "coach_game": CoachGameScreen(self),
            "stats": StatsScreen(self),
            "howto": HowToScreen(self),
        }
        self.current_name = "home"
        self.running = True
        self._transition: pygame.Surface | None = None
        self._transition_age = 0.0
        self.relayout()
        self.screens["home"].enter()
        # Objects created while loading (puzzles, fonts, screens) live until the game ends — we move them out of
        # the garbage collector's reach so full collections don't stall a frame for a dozen-plus ms now and then.
        gc.freeze()

    @property
    def current(self) -> Screen:
        return self.screens[self.current_name]

    def go(self, name: str) -> None:
        """Switches to another screen with a smooth cross-fade."""
        if name == self.current_name:
            return
        self._transition = self.screen.copy()
        self._transition_age = 0.0
        self.current.leave()
        self.current_name = name
        self.relayout()
        self.current.enter()

    def start_coach_game(self, color: chess.Color, elo: int, adaptive: bool, lesson: Opening | None) -> None:
        """A new coach game or opening lesson (from the "Coach" screen)."""
        screen = self.screens["coach_game"]
        assert isinstance(screen, CoachGameScreen)
        screen.start(color, elo, adaptive, lesson)
        self.go("coach_game")

    def set_language(self, code: str) -> None:
        """Changes the UI language (remembered in the profile)."""
        i18n.set_language(code)
        self.profile.language = i18n.get_language()
        pygame.display.set_caption(i18n.t("app.caption"))
        self.save()
        for screen in self.screens.values():
            screen.on_language_change()
        self.relayout()

    def toggle_fullscreen(self) -> None:
        """F11: fullscreen at desktop resolution and back to a window of the previous size."""
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
        """Esc first closes the variation preview on the game screen, and only then exits fullscreen."""
        play = self.screens.get("play")
        return self.current_name == "play" and getattr(play, "preview", None) is not None

    def dispatch_engine(self, event: EngineEvent) -> None:
        for screen in self.screens.values():
            screen.on_engine(event)

    def toggle_fps(self) -> None:
        """F3: FPS counter in the window corner."""
        self.profile.show_fps = not self.profile.show_fps
        self.save()

    def frame(self, dt: float, start: float | None = None) -> None:
        """One frame: events, engine messages, logic, drawing."""
        start = begin_frame(start)  # one shared time for all animations in this frame
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type in (pygame.VIDEORESIZE, pygame.WINDOWRESIZED, pygame.WINDOWSIZECHANGED):
                w, h = self.screen.get_size()
                if w < MIN_SIZE[0] or h < MIN_SIZE[1]:
                    self.screen = pygame.display.set_mode((max(w, MIN_SIZE[0]), max(h, MIN_SIZE[1])), pygame.RESIZABLE)
                self.relayout()
            elif self.settings.handle(event):
                continue
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_F11 or event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE and self.fullscreen and not self._escape_used():
                self.toggle_fullscreen()
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_F3:
                self.toggle_fps()
            elif self.topbar.handle(event):
                continue
            else:
                self.current.handle(event)
        for engine_event in self.engine.poll():
            self.dispatch_engine(engine_event)
        self.topbar.update(dt)
        self.current.update(dt)
        # The top bar has its own opaque background — the app background is not copied under it.
        top = self.topbar.rect.height
        self.screen.blit(gfx.background(self.screen.get_size()), (0, top), pygame.Rect(0, top, self.screen.get_width(), self.screen.get_height() - top))
        self.current.draw(self.screen)
        if self._transition is not None:
            # Cross-fade: the old screen fades out over the new one.
            self._transition_age += dt
            fade = 1 - ease_out_cubic(self._transition_age / TRANSITION)
            if fade <= 0.01:
                self._transition = None
            else:
                self._transition.set_alpha(int(255 * fade))
                self.screen.blit(self._transition, (0, 0))
        self.topbar.draw(self.screen)
        self.settings.draw(self.screen)
        if self.profile.show_fps:
            self.fps.draw(self.screen, self.topbar.rect.height)
        pygame.display.flip()
        self.fps.record(start, clock())

    def run(self) -> None:
        pacer = FramePacer()
        last = clock()
        try:
            while self.running:
                pacer.wait(self.profile.fps_limit)
                start = clock()
                dt, last = start - last, start
                self.frame(min(dt, 0.1), start)
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self.save()
        self.engine.close()
        pygame.quit()


def main() -> None:
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    App().run()
