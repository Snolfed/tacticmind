"""The "Coach" screen: coach strength (Elo or "Your level"), colour and openings to learn."""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import chess

from ...brain.notation import format_line
from ...coach.openings import OPENINGS, Opening, line_ucis, opening_by_id
from ...coach.strength import ELO_MAX, ELO_MIN, ELO_STEP, describe_level
from ...i18n import t, tn
from .base import WebScreen
from .coach_game import CoachGameScreen

if TYPE_CHECKING:
    from ..core import WebApp


class CoachMenuScreen(WebScreen):
    def __init__(self, app: WebApp) -> None:
        super().__init__(app)
        self.pending: Callable[[], None] | None = None
        self.rng = random.Random()

    def _game_screen(self) -> CoachGameScreen:
        screen = self.app.screens["coach_game"]
        assert isinstance(screen, CoachGameScreen)
        return screen

    def game_in_progress(self) -> bool:
        return self._game_screen().in_progress()

    def chosen_elo(self) -> tuple[int, bool]:
        coach = self.app.profile.coach
        if coach.use_level and coach.level is not None:
            return coach.level, True
        return coach.elo, False

    def _player_color(self) -> chess.Color:
        choice = self.app.profile.coach.color
        if choice == "random":
            return self.rng.choice((chess.WHITE, chess.BLACK))
        return chess.WHITE if choice == "white" else chess.BLACK

    def _start(self, action: Callable[[], None]) -> None:
        """New game; a game in progress (from 5 moves on) then counts as a loss — after confirmation."""
        game = self._game_screen().game
        if self.game_in_progress() and game is not None and game.abandon_counts():
            self.pending = action
            return
        self._game_screen().abandon_silently()
        action()

    def play(self) -> None:
        elo, adaptive = self.chosen_elo()
        color = self._player_color()
        self._start(lambda: self.app.start_coach_game(color, elo, adaptive, None))

    def learn(self, opening: Opening) -> None:
        elo, adaptive = self.chosen_elo()
        self._start(lambda: self.app.start_coach_game(opening.side, elo, adaptive, opening))

    # ------------------------------------------------------------ actions
    def action(self, name: str, data: dict[str, Any]) -> None:
        coach = self.app.profile.coach
        if self.pending is not None:
            if name == "confirm_yes":
                action = self.pending
                self.pending = None
                self._game_screen().abandon_and_record()
                action()
            elif name == "confirm_no":
                self.pending = None
            return
        if name == "elo":
            value = data.get("elo")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                steps = round((float(value) - ELO_MIN) / ELO_STEP)
                coach.elo = int(min(ELO_MAX, max(ELO_MIN, ELO_MIN + steps * ELO_STEP)))
                coach.use_level = False
                if data.get("final"):
                    self.app.save()
        elif name == "level":
            if coach.calibrated and coach.level is not None:
                coach.use_level = not coach.use_level
                self.app.save()
        elif name == "color":
            value = data.get("color")
            if value in ("white", "random", "black"):
                coach.color = str(value)
                self.app.save()
        elif name == "play":
            self.play()
        elif name == "resume":
            if self.game_in_progress():
                self.app.go("coach_game")
        elif name == "learn":
            try:
                opening = opening_by_id(str(data.get("id", "")))
            except (KeyError, ValueError):
                return
            self.learn(opening)

    # ------------------------------------------------------------ snapshot
    def _greeting(self) -> str:
        coach = self.app.profile.coach
        if not coach.games:
            return t("coach.hello_new")
        if not coach.calibrated:
            return tn("coach.hello_calibrating", coach.games_to_update())
        return tn("coach.hello_level", coach.games_to_update(), elo=coach.level or coach.elo)

    def snapshot(self) -> dict[str, Any]:
        coach = self.app.profile.coach
        elo, adaptive = self.chosen_elo()
        unlocked = coach.calibrated and coach.level is not None
        level_label = t("coach.your_level", elo=coach.level) if unlocked else t("coach.your_level_locked", n=coach.calibration_progress())
        note = tn("coach.level_note", coach.games_to_update()) if coach.calibrated else t("coach.level_locked_note")
        return {
            "greeting": self._greeting(),
            "elo": elo,
            "sliderElo": coach.elo,
            "adaptive": adaptive,
            "level": describe_level(elo),
            "levelLabel": level_label,
            "levelEnabled": unlocked,
            "levelActive": coach.use_level and unlocked,
            "note": note,
            "color": coach.color,
            "range": [ELO_MIN, ELO_MAX, ELO_STEP],
            "inProgress": self.game_in_progress(),
            "openings": [
                {
                    "id": o.id,
                    "eco": o.eco,
                    "side": "white" if o.side == chess.WHITE else "black",
                    "line": format_line(chess.STARTING_FEN, list(line_ucis(o.id)), 6),
                    "stars": coach.stars(o.id),
                }
                for o in OPENINGS
            ],
            "confirm": {"text": t("coach.abandon_confirm"), "yes": t("coach.abandon_yes")} if self.pending is not None else None,
        }
