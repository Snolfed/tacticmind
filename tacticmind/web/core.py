"""Core of the browser interface: app state, screens, engine and snapshot broadcasting.

Everything happens under a single lock (``lock``):
 - the clock thread, every ~40 ms, receives engine messages, counts down scheduled screen actions
   (e.g. the opponent's reply after 400 ms) and broadcasts a new snapshot if the state changed,
 - the HTTP server threads run actions from the browser (``dispatch``) and broadcast a snapshot right away.

Two kinds of messages flow to the browser: ``state`` (the full state of the current screen)
and ``fx`` (one-off events: sound, confetti, board shake).
"""

from __future__ import annotations

import json
import queue
import random
import threading
import time
from pathlib import Path
from typing import Any

import chess

from .. import i18n
from ..coach.openings import Opening
from ..engine.process import EngineClient, EngineEvent
from ..puzzles.loader import load_puzzles, puzzle_source
from ..rating.profile import PlayerProfile, RatingChange, data_dir, load_profile, save_profile
from .screens.base import WebScreen
from .screens.coach_game import CoachGameScreen
from .screens.coach_menu import CoachMenuScreen
from .screens.home import HomeScreen
from .screens.howto import HowToScreen
from .screens.play import PlayScreen
from .screens.stats import StatsScreen

TICK = 0.04
SCREENS = ("home", "play", "coach", "coach_game", "stats", "howto")
#: Settings of the interface itself (FPS counter, frame limit) — a separate file next to the profile.
FPS_LIMITS = (60, 120, 144, 170, 240, 0)
DEFAULT_SETTINGS: dict[str, Any] = {"showFps": False, "fpsLimit": 0}


def settings_path() -> Path:
    return data_dir() / "ui_settings.json"


def load_settings(path: Path | None = None) -> dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    try:
        raw = json.loads((path or settings_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return settings
    if isinstance(raw, dict):
        if isinstance(raw.get("showFps"), bool):
            settings["showFps"] = raw["showFps"]
        if raw.get("fpsLimit") in FPS_LIMITS and not isinstance(raw.get("fpsLimit"), bool):
            settings["fpsLimit"] = raw["fpsLimit"]
    return settings


class WebApp:
    def __init__(self, engine: EngineClient | None = None, profile: PlayerProfile | None = None, persist: bool = True) -> None:
        self.lock = threading.RLock()
        self.persist = persist
        self.profile = profile if profile is not None else load_profile()
        i18n.set_language(self.profile.language)
        self.settings = load_settings() if persist else dict(DEFAULT_SETTINGS)
        self.engine = engine if engine is not None else EngineClient()
        self.puzzles = load_puzzles()
        self.puzzle_source = puzzle_source()
        self.rng = random.Random()
        self.rating_delta: int | None = None
        self.delta_seq = 0
        self._fx: list[dict[str, Any]] = []
        self._subscribers: list[queue.Queue[str | None]] = []
        self._last_state = ""
        self._last_time = time.monotonic()
        self._running = False
        self._thread: threading.Thread | None = None
        self.screens: dict[str, WebScreen] = {
            "home": HomeScreen(self),
            "play": PlayScreen(self),
            "coach": CoachMenuScreen(self),
            "coach_game": CoachGameScreen(self),
            "stats": StatsScreen(self),
            "howto": HowToScreen(self),
        }
        self.current_name = "home"
        self.screens["home"].enter()

    # ================================================================ helpers for screens
    @property
    def current(self) -> WebScreen:
        return self.screens[self.current_name]

    def fx(self, event: dict[str, Any]) -> None:
        self._fx.append(event)

    def sound(self, name: str) -> None:
        self.fx({"type": "sound", "name": name})

    def go(self, name: str) -> None:
        if name == self.current_name or name not in self.screens:
            return
        coach_game = self.screens["coach_game"]
        if name == "coach_game" and isinstance(coach_game, CoachGameScreen) and coach_game.game is None:
            return  # there is no game yet
        self.current.leave()
        self.current_name = name
        self.current.enter()

    def start_coach_game(self, color: chess.Color, elo: int, adaptive: bool, lesson: Opening | None) -> None:
        screen = self.screens["coach_game"]
        assert isinstance(screen, CoachGameScreen)
        screen.start(color, elo, adaptive, lesson)
        self.go("coach_game")

    def open_coach_review(self, index: int) -> None:
        """Opens a saved game with the coach in the review."""
        screen = self.screens["coach_game"]
        assert isinstance(screen, CoachGameScreen)
        if screen.open_archived(index):
            self.go("coach_game")

    def on_rating_change(self, change: RatingChange) -> None:
        self.rating_delta = round(change.delta)
        self.delta_seq += 1

    def save(self) -> None:
        if self.persist:
            save_profile(self.profile)

    def save_settings(self) -> None:
        if not self.persist:
            return
        path = settings_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self.settings), encoding="utf-8")
        except OSError:
            pass

    def set_language(self, code: str) -> None:
        if code not in i18n.LANGUAGES:
            return
        i18n.set_language(code)
        self.profile.language = i18n.get_language()
        self.save()
        for screen in self.screens.values():
            screen.on_language_change()

    # ================================================================ actions from the browser
    def dispatch(self, action: dict[str, Any]) -> None:
        """Action from the browser: ``{"type": ..., ...}``. Screen actions: ``{"type": "screen", "screen": ..., "name": ...}``."""
        with self.lock:
            kind = action.get("type")
            if kind == "go":
                self.go(str(action.get("screen", "")))
            elif kind == "language":
                self.set_language(str(action.get("code", "")))
            elif kind == "sound":
                self._sound_settings(action)
            elif kind == "settings":
                self._ui_settings(action)
            elif kind == "screen":
                name = str(action.get("screen", ""))
                data = action.get("data")
                if name == self.current_name:
                    self.current.action(str(action.get("name", "")), data if isinstance(data, dict) else {})
            self.publish()

    def _sound_settings(self, action: dict[str, Any]) -> None:
        profile = self.profile
        if action.get("toggle"):
            profile.sound = not profile.sound
            if profile.sound and profile.volume < 0.02:
                profile.volume = 0.5  # turning sound on while the slider is at zero
        volume = action.get("volume")
        if isinstance(volume, (int, float)) and not isinstance(volume, bool):
            profile.volume = min(1.0, max(0.0, float(volume)))
            if profile.volume > 0.02 and not profile.sound:
                profile.sound = True
        if action.get("final", True):
            self.save()

    def _ui_settings(self, action: dict[str, Any]) -> None:
        show = action.get("showFps")
        if isinstance(show, bool):
            self.settings["showFps"] = show
        limit = action.get("fpsLimit")
        if limit in FPS_LIMITS and not isinstance(limit, bool):
            self.settings["fpsLimit"] = limit
        self.save_settings()

    # ================================================================ clock
    def tick(self) -> None:
        """One logic frame: engine messages, scheduled actions, state broadcast."""
        with self.lock:
            now = time.monotonic()
            dt = min(0.25, now - self._last_time)
            self._last_time = now
            for event in self.engine.poll():
                self.dispatch_engine(event)
            self.current.update(dt)
            self.publish()

    def dispatch_engine(self, event: EngineEvent) -> None:
        for screen in self.screens.values():
            screen.on_engine(event)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="TacticMind-clock")
        self._thread.start()

    def _loop(self) -> None:
        while self._running:
            started = time.monotonic()
            try:
                self.tick()
            except Exception:  # noqa: BLE001 — an error in one frame must not stop the whole app
                import traceback

                traceback.print_exc()
            time.sleep(max(0.0, TICK - (time.monotonic() - started)))

    def stop(self) -> None:
        self._running = False
        with self.lock:
            for subscriber in self._subscribers:
                subscriber.put(None)
            self.save()
        self.engine.close()

    # ================================================================ snapshots
    def topbar(self) -> dict[str, Any]:
        profile = self.profile
        coach = self.current_name.startswith("coach")
        if coach:
            rating: float = profile.coach.rating.rating
            rd: float | None = profile.coach.rating.rd
            caption = i18n.t("rating.coach_caption")
            if not profile.coach.calibrated:
                caption += " · " + i18n.t("rating.calibration", n=profile.coach.calibration_progress())
        else:
            rating, rd = profile.rating, profile.rd
            system = "Glicko-2" if profile.system == "glicko" else "Elo"
            caption = i18n.t("rating.caption", system=system)
            if profile.calibrating:
                caption += " · " + i18n.t("rating.calibration", n=profile.games)
        return {
            "source": "coach" if coach else "puzzles",
            "rating": round(rating),
            "rd": round(rd) if rd is not None else None,
            "caption": caption,
            "streak": 0 if coach else profile.streak,
            "delta": self.rating_delta,
            "deltaSeq": self.delta_seq,
            "sound": profile.sound,
            "volume": profile.volume,
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "screen": self.current_name,
            "lang": i18n.get_language(),
            "topbar": self.topbar(),
            "settings": self.settings,
            "view": self.current.snapshot(),
        }

    def state_message(self) -> str:
        with self.lock:
            return self._last_state or self._encode_state()

    def _encode_state(self) -> str:
        self._last_state = json.dumps(self.snapshot(), ensure_ascii=False, separators=(",", ":"))
        return self._last_state

    def publish(self) -> None:
        """Broadcasts the state (only when it changed) and the collected ``fx`` events."""
        previous = self._last_state
        state = self._encode_state()
        messages: list[str] = []
        if state != previous:
            messages.append("event: state\ndata: " + state + "\n\n")
        if self._fx:
            messages.append("event: fx\ndata: " + json.dumps(self._fx, separators=(",", ":")) + "\n\n")
            self._fx = []
        if not messages:
            return
        for subscriber in list(self._subscribers):
            for message in messages:
                subscriber.put(message)

    def subscribe(self) -> queue.Queue[str | None]:
        subscriber: queue.Queue[str | None] = queue.Queue()
        with self.lock:
            self._subscribers.append(subscriber)
            subscriber.put("event: state\ndata: " + (self._last_state or self._encode_state()) + "\n\n")
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[str | None]) -> None:
        with self.lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    @property
    def clients(self) -> int:
        return len(self._subscribers)
