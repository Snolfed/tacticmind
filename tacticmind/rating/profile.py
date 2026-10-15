"""Profil gracza: ranking (Elo i Glicko-2), serie, historia, model gracza i zapis na dysk.

Postępy zapisujemy w pliku JSON (odpowiednik localStorage w przeglądarce):
``~/.tacticmind/profile.json`` albo w katalogu z zmiennej środowiskowej ``TACTICMIND_HOME``.
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
from .player_model import PlayerModel

RatingSystem = Literal["glicko", "elo"]

#: Minimalne RD w Glicko-2 — bez tego ranking po setkach zadań prawie przestałby się zmieniać.
MIN_RD = 50.0
#: Kara za bardzo długi czas: od 3× przeciętnego czasu, liniowo do −0.2 przy 6×.
SLOW_FACTOR = 3.0
MAX_TIME_PENALTY = 0.2


def puzzle_score(outcome: PuzzleOutcome, average_time_s: float | None) -> float:
    """Wynik S zadania (nie zero-jedynkowy).

     - 1.0: rozwiązane bez błędu i bez podpowiedzi,
     - 0.5: rozwiązane z podpowiedzią,
     - 0.0: błędny ruch (nawet jeśli gracz potem dokończył) albo pokazane rozwiązanie,
     - lekka kara za bardzo długi czas (> 3× przeciętnego czasu gracza), maksymalnie −0.2.
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
    #: Głośność dźwięków 0..1 (suwak w górnym pasku).
    volume: float = 0.7
    language: str = "pl"

    # ------------------------------------------------------------ ranking
    @property
    def rating(self) -> float:
        """Ranking w aktywnym systemie."""
        return self.glicko.rating if self.system == "glicko" else self.elo_rating

    @property
    def rd(self) -> float | None:
        """Odchylenie rankingu (tylko Glicko-2)."""
        return self.glicko.rd if self.system == "glicko" else None

    @property
    def calibrating(self) -> bool:
        return self.games < elo.CALIBRATION_GAMES

    def average_time(self, last: int = 20) -> float | None:
        """Przeciętny czas rozwiązania (z ostatnich udanych zadań), gdy są co najmniej 3."""
        times = [r.time_s for r in self.history[-last:] if r.solved]
        return sum(times) / len(times) if len(times) >= 3 else None

    def apply(self, puzzle: Puzzle, outcome: PuzzleOutcome, mode: str = "flow") -> RatingChange:
        """Księguje wynik zadania: oba rankingi, serie, model gracza i historię."""
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

    # ------------------------------------------------------------ zapis
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
        }

    @classmethod
    def from_json(cls, data: dict[str, object]) -> PlayerProfile:
        """Odczyt z JSON-a z kontrolą typów (uszkodzony plik nie wywraca gry)."""
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
        )


def as_float(value: object, default: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return default


def data_dir() -> Path:
    if "TACTICMIND_HOME" in os.environ:
        return Path(os.environ["TACTICMIND_HOME"])
    path = Path.home() / ".tacticmind"
    old = Path.home() / ".taktykai"  # katalog sprzed zmiany nazwy gry — przenosimy postępy
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
    tmp.replace(path)  # zapis atomowy: przerwany zapis nie zniszczy profilu
