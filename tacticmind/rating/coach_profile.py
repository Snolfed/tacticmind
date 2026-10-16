"""The player's level in games against the coach: calibration, "Your level" and opening progress.

The result of every game is recorded in a separate Glicko-2 rating (opponent = the coach at the chosen Elo,
with uncertainty RD = 80, because the coach's Elo is approximate). We do not show it right away, though:

 - the first 10 games are **calibration** — the rating is only "getting to know" the player,
 - after the 10th game a new difficulty level appears, **"Your level"**: the coach plays at a strength equal
   to the player's rating (rounded to 25, within the coach's Elo range),
 - after that the level changes **every 5 games** (after the 15th, 20th, 25th …), not after every game —
   this keeps the opponent stable and progress shows in "steps", like being promoted a rank.

The coach's help has a cost: every take-back and every hint lowers the game result by 0.1.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from ..coach.strength import ELO_MAX, ELO_MIN
from . import glicko2

CALIBRATION_GAMES = 10
UPDATE_EVERY = 5
#: Uncertainty of the coach's Elo (its strength is approximate).
TRAINER_RD = 80.0
MIN_RD = 50.0
DEFAULT_ELO = 800
#: How many of the newest games keep their moves for the review (older ones keep only the result).
ARCHIVE_LIMIT = 100
STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


@dataclass
class CoachGameRecord:
    trainer_elo: int
    adaptive: bool
    color: str
    result: str
    score: float
    accuracy: float | None
    trainer_accuracy: float | None
    moves: int
    opening: str | None
    helps: int
    rating_before: float
    rating_after: float
    timestamp: float
    #: Moves of the game for the review (``coach/archive.py``); None in old profiles and in games past ``ARCHIVE_LIMIT``.
    plies: list[dict[str, Any]] | None = None
    start_fen: str = STARTING_FEN
    reason: str | None = None


@dataclass
class OpeningProgress:
    completed: int = 0
    flawless: int = 0

    @property
    def stars(self) -> int:
        """0 — not completed, 1 — completed, 2 — once without a mistake, 3 — three times without a mistake."""
        if self.completed == 0:
            return 0
        if self.flawless >= 3:
            return 3
        return 2 if self.flawless >= 1 else 1


@dataclass
class LevelChange:
    """Result of recording a game."""

    rating_before: float
    rating_after: float
    #: The "Your level" level before and after (None before calibration ends).
    level_before: int | None
    level_after: int | None
    calibrated_now: bool


def level_from_rating(rating: float) -> int:
    return int(min(ELO_MAX, max(ELO_MIN, round(rating / 25) * 25)))


@dataclass
class CoachProfile:
    rating: glicko2.Glicko2Rating = field(default_factory=glicko2.Glicko2Rating)
    games: list[CoachGameRecord] = field(default_factory=list)
    #: "Your level" — the coach strength matched to the player (None during calibration).
    level: int | None = None
    openings: dict[str, OpeningProgress] = field(default_factory=dict)
    #: Last settings (remembered between runs).
    elo: int = DEFAULT_ELO
    use_level: bool = False
    color: str = "white"

    # ------------------------------------------------------------ calibration
    @property
    def calibrated(self) -> bool:
        return len(self.games) >= CALIBRATION_GAMES

    def calibration_progress(self) -> int:
        return min(len(self.games), CALIBRATION_GAMES)

    def games_to_update(self) -> int:
        """How many games are left until the next change of "Your level" (or until calibration ends)."""
        n = len(self.games)
        if n < CALIBRATION_GAMES:
            return CALIBRATION_GAMES - n
        return UPDATE_EVERY - (n - CALIBRATION_GAMES) % UPDATE_EVERY

    def record(
        self,
        trainer_elo: int,
        adaptive: bool,
        color: str,
        result: str,
        score: float,
        accuracy: float | None,
        trainer_accuracy: float | None,
        moves: int,
        opening: str | None,
        helps: int,
        plies: list[dict[str, Any]] | None = None,
        start_fen: str = STARTING_FEN,
        reason: str | None = None,
    ) -> LevelChange:
        before = self.rating.rating
        level_before = self.level
        new = glicko2.update(self.rating, [(float(trainer_elo), TRAINER_RD, score)])
        self.rating = glicko2.Glicko2Rating(new.rating, max(MIN_RD, new.rd), new.volatility)
        self.games.append(
            CoachGameRecord(
                trainer_elo=trainer_elo,
                adaptive=adaptive,
                color=color,
                result=result,
                score=score,
                accuracy=None if accuracy is None else round(accuracy, 1),
                trainer_accuracy=None if trainer_accuracy is None else round(trainer_accuracy, 1),
                moves=moves,
                opening=opening,
                helps=helps,
                rating_before=round(before, 1),
                rating_after=round(self.rating.rating, 1),
                timestamp=time.time(),
                plies=plies,
                start_fen=start_fen,
                reason=reason,
            )
        )
        for old in self.games[:-ARCHIVE_LIMIT]:
            old.plies = None
        n = len(self.games)
        calibrated_now = n == CALIBRATION_GAMES
        if n >= CALIBRATION_GAMES and (n - CALIBRATION_GAMES) % UPDATE_EVERY == 0:
            self.level = level_from_rating(self.rating.rating)
        return LevelChange(before, self.rating.rating, level_before, self.level, calibrated_now)

    def record_lesson(self, opening_id: str, mistakes: int) -> OpeningProgress:
        progress = self.openings.setdefault(opening_id, OpeningProgress())
        progress.completed += 1
        if mistakes == 0:
            progress.flawless += 1
        return progress

    def stars(self, opening_id: str) -> int:
        progress = self.openings.get(opening_id)
        return progress.stars if progress else 0

    def reviewable(self, index: int) -> bool:
        """Whether the game with this index has saved moves (can be opened in the review)."""
        return 0 <= index < len(self.games) and bool(self.games[index].plies)

    def results(self) -> tuple[int, int, int]:
        """(wins, draws, losses)."""
        wins = sum(1 for g in self.games if g.result == "win")
        draws = sum(1 for g in self.games if g.result == "draw")
        return wins, draws, len(self.games) - wins - draws

    # ------------------------------------------------------------ persistence
    def to_json(self) -> dict[str, object]:
        return {
            "rating": asdict(self.rating),
            "games": [asdict(g) for g in self.games],
            "level": self.level,
            "openings": {key: asdict(value) for key, value in self.openings.items()},
            "elo": self.elo,
            "use_level": self.use_level,
            "color": self.color,
        }

    @classmethod
    def from_json(cls, data: object) -> CoachProfile:
        if not isinstance(data, dict):
            return cls()
        r = data.get("rating")
        r = r if isinstance(r, dict) else {}
        games = data.get("games")
        openings = data.get("openings")
        level = data.get("level")
        elo = data.get("elo")
        color = data.get("color")
        records = []
        if isinstance(games, list):
            for g in games:
                try:
                    record = CoachGameRecord(**g)
                except TypeError:
                    continue
                if not isinstance(record.plies, list):
                    record.plies = None
                if not isinstance(record.start_fen, str):
                    record.start_fen = STARTING_FEN
                records.append(record)
        progress = {}
        if isinstance(openings, dict):
            for key, value in openings.items():
                if isinstance(value, dict):
                    progress[str(key)] = OpeningProgress(int(value.get("completed", 0)), int(value.get("flawless", 0)))
        return cls(
            rating=glicko2.Glicko2Rating(_num(r.get("rating"), 1200.0), _num(r.get("rd"), 350.0), _num(r.get("volatility"), 0.06)),
            games=records,
            level=int(level) if isinstance(level, (int, float)) and not isinstance(level, bool) else None,
            openings=progress,
            elo=int(min(ELO_MAX, max(ELO_MIN, elo))) if isinstance(elo, int) and not isinstance(elo, bool) else DEFAULT_ELO,
            use_level=bool(data.get("use_level", False)),
            color=color if color in ("white", "black", "random") else "white",
        )


def _num(value: object, default: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return default
