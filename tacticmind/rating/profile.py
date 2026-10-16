"""Player profile: rating (Elo and Glicko-2), streaks, history, player model and saving to disk.

Progress is saved in a JSON file (the counterpart of localStorage in the browser):
``~/.tacticmind/profile.json`` or in the directory from the ``TACTICMIND_HOME`` environment variable.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from ..puzzles.loader import Puzzle, as_int
from ..puzzles.session import PuzzleOutcome
from . import elo, glicko2
from .coach_profile import CoachProfile
from .player_model import PlayerModel

RatingSystem = Literal["glicko", "elo"]

#: Minimum RD in Glicko-2 — without it the rating would almost stop changing after hundreds of puzzles.
MIN_RD = 50.0
#: Penalty for a very long time: from 3× the average time, linearly down to −0.2 at 6×.
SLOW_FACTOR = 3.0
MAX_TIME_PENALTY = 0.2


def puzzle_score(outcome: PuzzleOutcome, average_time_s: float | None) -> float:
    """Puzzle score S (not just zero or one).

     - 1.0: solved without a mistake and without a hint,
     - 0.5: solved with a hint,
     - 0.0: a wrong move (even if the player finished afterwards) or the solution was shown,
     - a slight penalty for a very long time (> 3× the player's average time), at most −0.2.
    """
    if not outcome.solved or outcome.mistake or outcome.revealed:
        return 0.0
    score = 0.5 if outcome.hint_used else 1.0
    if average_time_s and outcome.time_s > SLOW_FACTOR * average_time_s:
        over = (outcome.time_s - SLOW_FACTOR * average_time_s) / (SLOW_FACTOR * average_time_s)
        score -= min(MAX_TIME_PENALTY, MAX_TIME_PENALTY * over)
    return round(max(0.0, score), 3)


@dataclass
class PuzzleRecord:
    puzzle_id: str
    puzzle_rating: int
    themes: list[str]
    score: float
    solved: bool
    hint: bool
    time_s: float
    rating_before: float
    rating_after: float
    rd_after: float | None
    mode: str
    timestamp: float


@dataclass
class RatingChange:
    before: float
    after: float
    delta: float
    score: float
    rd: float | None


@dataclass
class PlayerProfile:
    system: RatingSystem = "glicko"
    elo_rating: float = elo.START_RATING
    glicko: glicko2.Glicko2Rating = field(default_factory=glicko2.Glicko2Rating)
    games: int = 0
    streak: int = 0
    best_streak: int = 0
    fail_streak: int = 0
    model: PlayerModel = field(default_factory=PlayerModel)
    history: list[PuzzleRecord] = field(default_factory=list)
    seen: list[str] = field(default_factory=list)
    sound: bool = True
    #: Sound volume 0..1 (slider in the top bar).
    volume: float = 0.7
    language: str = "en"
    #: Games against the coach and opening study (a separate rating and "Your level").
    coach: CoachProfile = field(default_factory=CoachProfile)

    # ------------------------------------------------------------ rating
    @property
    def rating(self) -> float:
        """Rating in the active system."""
        return self.glicko.rating if self.system == "glicko" else self.elo_rating

    @property
    def rd(self) -> float | None:
        """Rating deviation (Glicko-2 only)."""
        return self.glicko.rd if self.system == "glicko" else None

    @property
    def calibrating(self) -> bool:
        return self.games < elo.CALIBRATION_GAMES

    def average_time(self, last: int = 20) -> float | None:
        """Average solving time (from recent solved puzzles), when there are at least 3."""
        times = [r.time_s for r in self.history[-last:] if r.solved]
        return sum(times) / len(times) if len(times) >= 3 else None

    def apply(self, puzzle: Puzzle, outcome: PuzzleOutcome, mode: str = "flow") -> RatingChange:
        """Records a puzzle result: both ratings, streaks, the player model and history."""
        score = puzzle_score(outcome, self.average_time())
        before = self.rating

        self.elo_rating, _ = elo.update_elo(self.elo_rating, puzzle.rating, score, self.games)
        new_glicko = glicko2.update(self.glicko, [(puzzle.rating, puzzle.rd, score)])
        self.glicko = glicko2.Glicko2Rating(new_glicko.rating, max(MIN_RD, new_glicko.rd), new_glicko.volatility)
        self.games += 1

        success = outcome.solved
        if success:
            self.streak += 1
            self.fail_streak = 0
            self.best_streak = max(self.best_streak, self.streak)
        else:
            self.streak = 0
            self.fail_streak += 1
        self.model.record(puzzle.themes, success, score)
        if puzzle.id not in self.seen:
            self.seen.append(puzzle.id)

        after = self.rating
        self.history.append(
            PuzzleRecord(
                puzzle_id=puzzle.id,
                puzzle_rating=puzzle.rating,
                themes=list(puzzle.themes),
                score=score,
                solved=success,
                hint=outcome.hint_used,
                time_s=round(outcome.time_s, 1),
                rating_before=round(before, 1),
                rating_after=round(after, 1),
                rd_after=round(self.glicko.rd, 1) if self.system == "glicko" else None,
                mode=mode,
                timestamp=time.time(),
            )
        )
        return RatingChange(before, after, after - before, score, self.rd)

    # ------------------------------------------------------------ persistence
    def to_json(self) -> dict[str, object]:
        return {
            "version": 1,
            "system": self.system,
            "elo_rating": self.elo_rating,
            "glicko": asdict(self.glicko),
            "games": self.games,
            "streak": self.streak,
            "best_streak": self.best_streak,
            "fail_streak": self.fail_streak,
            "themes": self.model.to_json(),
            "history": [asdict(r) for r in self.history],
            "seen": self.seen,
            "sound": self.sound,
            "volume": self.volume,
            "language": self.language,
            "coach": self.coach.to_json(),
        }

    @classmethod
    def from_json(cls, data: dict[str, object]) -> PlayerProfile:
        """Reading from JSON with type checks (a corrupted file does not crash the game)."""
        g = data.get("glicko")
        g = g if isinstance(g, dict) else {}
        themes = data.get("themes")
        history = data.get("history")
        seen = data.get("seen")
        return cls(
            system="elo" if data.get("system") == "elo" else "glicko",
            elo_rating=as_float(data.get("elo_rating"), elo.START_RATING),
            glicko=glicko2.Glicko2Rating(
                as_float(g.get("rating"), 1200.0), as_float(g.get("rd"), 350.0), as_float(g.get("volatility"), 0.06)
            ),
            games=as_int(data.get("games")),
            streak=as_int(data.get("streak")),
            best_streak=as_int(data.get("best_streak")),
            fail_streak=as_int(data.get("fail_streak")),
            model=PlayerModel.from_json(themes if isinstance(themes, dict) else {}),
            history=[PuzzleRecord(**r) for r in history if isinstance(r, dict)] if isinstance(history, list) else [],
            seen=[str(s) for s in seen] if isinstance(seen, list) else [],
            sound=bool(data.get("sound", True)),
            volume=min(1.0, max(0.0, as_float(data.get("volume"), 0.7))),
            language=str(data.get("language", "pl")),
            coach=CoachProfile.from_json(data.get("coach")),
        )


def as_float(value: object, default: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return default


def data_dir() -> Path:
    if "TACTICMIND_HOME" in os.environ:
        return Path(os.environ["TACTICMIND_HOME"])
    path = Path.home() / ".tacticmind"
    old = Path.home() / ".taktykai"  # directory from before the game was renamed — migrate the progress
    if not path.exists() and old.is_dir():
        try:
            old.rename(path)
        except OSError:
            return old
    return path


def profile_path() -> Path:
    return data_dir() / "profile.json"


def load_profile(path: Path | None = None) -> PlayerProfile:
    path = path or profile_path()
    try:
        with path.open(encoding="utf-8") as handle:
            return PlayerProfile.from_json(json.load(handle))
    except (OSError, ValueError, TypeError, KeyError, AssertionError):
        return PlayerProfile()


def save_profile(profile: PlayerProfile, path: Path | None = None) -> None:
    path = path or profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(profile.to_json(), handle, ensure_ascii=False, indent=1)
    tmp.replace(path)  # atomic write: an interrupted write will not destroy the profile
