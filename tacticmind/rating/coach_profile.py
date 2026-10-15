"""Poziom gracza w partiach z trenerem: kalibracja, „Twój poziom” i postępy w otwarciach.

Wynik każdej partii księgujemy w osobnym rankingu Glicko-2 (przeciwnik = trener o wybranym Elo,
z niepewnością RD = 80, bo Elo trenera jest przybliżone). Nie pokazujemy go jednak od razu:

 - przez pierwsze 10 partii trwa **kalibracja** — ranking dopiero „poznaje” gracza,
 - po 10. partii pojawia się nowy poziom trudności **„Twój poziom”**: trener gra z siłą równą
   rankingowi gracza (zaokrągloną do 25, w zakresie 400–2000),
 - potem ten poziom zmienia się **co 5 partii** (po 15., 20., 25. …), a nie po każdej partii —
   dzięki temu przeciwnik jest stabilny i postęp widać „skokami”, jak awans na kolejny stopień.

Pomoc trenera kosztuje: każde cofnięcie ruchu i każda podpowiedź obniżają wynik partii o 0,1.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

from ..coach.strength import ELO_MAX, ELO_MIN
from . import glicko2

CALIBRATION_GAMES = 10
UPDATE_EVERY = 5
#: Niepewność Elo trenera (jego siła jest przybliżona).
TRAINER_RD = 80.0
MIN_RD = 50.0
DEFAULT_ELO = 800


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


@dataclass
class OpeningProgress:
    completed: int = 0
    flawless: int = 0

    @property
    def stars(self) -> int:
        """0 — nieukończone, 1 — ukończone, 2 — raz bez błędu, 3 — trzy razy bez błędu."""
        if self.completed == 0:
            return 0
        if self.flawless >= 3:
            return 3
        return 2 if self.flawless >= 1 else 1


@dataclass
class LevelChange:
    """Wynik zaksięgowania partii."""

    rating_before: float
    rating_after: float
    #: Poziom „Twój poziom” przed i po (None przed końcem kalibracji).
    level_before: int | None
    level_after: int | None
    calibrated_now: bool


def level_from_rating(rating: float) -> int:
    return int(min(ELO_MAX, max(ELO_MIN, round(rating / 25) * 25)))


@dataclass
class CoachProfile:
    rating: glicko2.Glicko2Rating = field(default_factory=glicko2.Glicko2Rating)
    games: list[CoachGameRecord] = field(default_factory=list)
    #: „Twój poziom” — siła trenera dopasowana do gracza (None w trakcie kalibracji).
    level: int | None = None
    openings: dict[str, OpeningProgress] = field(default_factory=dict)
    #: Ostatnie ustawienia (pamiętane między uruchomieniami).
    elo: int = DEFAULT_ELO
    use_level: bool = False
    color: str = "white"

    # ------------------------------------------------------------ kalibracja
    @property
    def calibrated(self) -> bool:
        return len(self.games) >= CALIBRATION_GAMES

    def calibration_progress(self) -> int:
        return min(len(self.games), CALIBRATION_GAMES)

    def games_to_update(self) -> int:
        """Ile partii zostało do następnej zmiany „Twojego poziomu” (albo do końca kalibracji)."""
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
            )
        )
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

    def results(self) -> tuple[int, int, int]:
        """(wygrane, remisy, porażki)."""
        wins = sum(1 for g in self.games if g.result == "win")
        draws = sum(1 for g in self.games if g.result == "draw")
        return wins, draws, len(self.games) - wins - draws

    # ------------------------------------------------------------ zapis
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
                    records.append(CoachGameRecord(**g))
                except TypeError:
                    continue
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
