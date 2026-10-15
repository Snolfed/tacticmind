"""Dobór kolejnego zadania pod gracza (adaptacyjny poziom trudności).

Zasady:
 - „strefa flow”: celujemy w ok. 65% szans na sukces, czyli zadanie o rankingu
   ≈ R_gracza − 100 (bo E(−100) ≈ 0.64), z losowym rozrzutem ±75,
 - ok. 30% zadań pochodzi z najsłabszych motywów gracza (model gracza),
 - ochrona przed frustracją: po 3 porażkach z rzędu zadanie wyraźnie łatwiejsze,
 - po 5 sukcesach z rzędu „zadanie bonusowe”, trudniejsze o ok. 200,
 - zadania się nie powtarzają, a motywy są zróżnicowane (kara za motywy
   z ostatnich zadań).
Każda decyzja ma uzasadnienie (okienko „Dlaczego to zadanie?”). Uzasadnienia są
zapisane jako klucze tłumaczeń, więc wyświetlają się w bieżącym języku interfejsu.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from ..i18n import t, tn
from ..puzzles.loader import Puzzle
from ..puzzles.themes import skill_themes, theme_name
from .elo import expected_score
from .profile import PlayerProfile

FLOW_OFFSET = -100
FLOW_SPREAD = 75
EASIER_OFFSET = -300
BONUS_OFFSET = 200
WEAKNESS_SHARE = 0.30
#: Ile punktów rankingu „kosztuje” powtórzenie motywu z ostatnich zadań.
REPEAT_THEME_PENALTY = 40
RECENT = 3

Mode = Literal["flow", "easier", "bonus", "weakness"]


@dataclass(frozen=True)
class Reason:
    """Jedno zdanie uzasadnienia: klucz tłumaczenia + parametry (tekst powstaje przy wyświetlaniu)."""

    key: str
    params: tuple[tuple[str, object], ...] = ()
    count: int | None = None  # dla zdań z liczbą mnogą („3 porażki z rzędu”)

    def text(self) -> str:
        params = {k: theme_name(str(v)) if k == "theme" else v for k, v in self.params}
        if self.count is not None:
            return tn(self.key, self.count, **params)
        return t(self.key, **params)


@dataclass
class Selection:
    puzzle: Puzzle
    target: int
    expected: float
    mode: Mode
    weak_theme: tuple[str, float] | None = None
    reasons: list[Reason] = field(default_factory=list)

    def reason_texts(self) -> list[str]:
        return [reason.text() for reason in self.reasons]


def select_next(puzzles: Sequence[Puzzle], profile: PlayerProfile, rng: random.Random | None = None) -> Selection:
    """Wybiera następne zadanie dla gracza i zwraca je razem z uzasadnieniem."""
    if not puzzles:
        raise ValueError("Brak zadań do wyboru")
    rng = rng or random.Random()
    rating = profile.rating
    reasons: list[Reason] = []

    # 1) Docelowy ranking zadania.
    mode: Mode
    if profile.fail_streak >= 3:
        mode = "easier"
        target = rating + EASIER_OFFSET + rng.uniform(-25, 25)
        reasons.append(Reason("reason.easier", count=profile.fail_streak))
    elif profile.streak >= 5 and profile.streak % 5 == 0:
        mode = "bonus"
        target = rating + BONUS_OFFSET + rng.uniform(-25, 25)
        reasons.append(Reason("reason.bonus", count=profile.streak))
    else:
        mode = "flow"
        target = rating + FLOW_OFFSET + rng.uniform(-FLOW_SPREAD, FLOW_SPREAD)

    # 2) Pula: bez powtórek (gdy wszystko już było — zaczynamy od nowa).
    seen = set(profile.seen)
    pool = [p for p in puzzles if p.id not in seen] or list(puzzles)

    # 3) Ok. 30% zadań z najsłabszych motywów gracza.
    weak_theme: tuple[str, float] | None = None
    if mode == "flow":
        weakest = profile.model.weakest()
        if weakest and rng.random() < WEAKNESS_SHARE:
            theme, rate = weakest[0] if len(weakest) == 1 or rng.random() < 0.6 else rng.choice(weakest)
            themed = [p for p in pool if theme in p.themes and abs(p.rating - target) <= 250]
            if themed:
                pool = themed
                weak_theme = (theme, rate)
                mode = "weakness"

    # 4) Najbliżej celu, z karą za motywy z ostatnich zadań (różnorodność).
    recent = {t for r in profile.history[-RECENT:] for t in skill_themes(r.themes)}

    def cost(p: Puzzle) -> float:
        overlap = len(recent.intersection(skill_themes(p.themes)))
        return abs(p.rating - target) + REPEAT_THEME_PENALTY * overlap

    window = 50
    candidates: list[Puzzle] = []
    while not candidates:
        candidates = [p for p in pool if abs(p.rating - target) <= window]
        window *= 2
        if window > 4000:
            candidates = list(pool)
    candidates.sort(key=cost)
    puzzle = rng.choice(candidates[:5])
    expected = expected_score(rating, puzzle.rating)

    # 5) Uzasadnienie.
    if mode in ("flow", "weakness"):
        reasons.insert(0, Reason("reason.flow", (("target", round(target)), ("pct", round(expected * 100)))))
    else:
        reasons.append(Reason("reason.chance", (("pct", round(expected * 100)),)))
    if weak_theme is not None:
        reasons.append(Reason("reason.weak", (("theme", weak_theme[0]), ("pct", round(weak_theme[1] * 100)))))
    fresh = [theme for theme in skill_themes(puzzle.themes) if theme not in recent]
    if recent and fresh:
        reasons.append(Reason("reason.fresh", (("theme", fresh[0]),)))
    if profile.calibrating:
        reasons.append(Reason("reason.calibration", (("n", profile.games + 1),)))
    return Selection(puzzle, round(target), expected, mode, weak_theme, reasons)
