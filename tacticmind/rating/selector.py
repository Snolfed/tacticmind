"""Choosing the next puzzle for the player (adaptive difficulty).

Rules:
 - "flow zone": we aim for a ~65% chance of success, i.e. a puzzle rated
   ≈ R_player − 100 (because E(−100) ≈ 0.64), with a random spread of ±75,
 - ~30% of puzzles come from the player's weakest themes (player model),
 - frustration guard: after 3 losses in a row the puzzle is clearly easier,
 - after 5 successes in a row a "bonus puzzle", about 200 harder,
 - puzzles do not repeat and themes are varied (a penalty for themes
   from recent puzzles).
Every decision has a justification (the "Why this puzzle?" box). Justifications are
stored as translation keys, so they are shown in the current interface language.
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
#: How many rating points repeating a theme from recent puzzles "costs".
REPEAT_THEME_PENALTY = 40
RECENT = 3

Mode = Literal["flow", "easier", "bonus", "weakness"]


@dataclass(frozen=True)
class Reason:
    """One justification sentence: translation key + parameters (the text is produced at display time)."""

    key: str
    params: tuple[tuple[str, object], ...] = ()
    count: int | None = None  # for sentences with plurals ("3 losses in a row")

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
    """Picks the next puzzle for the player and returns it together with the justification."""
    if not puzzles:
        raise ValueError("No puzzles to choose from")
    rng = rng or random.Random()
    rating = profile.rating
    reasons: list[Reason] = []

    # 1) Target puzzle rating.
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

    # 2) Pool: no repeats (when everything has been played — start over).
    seen = set(profile.seen)
    pool = [p for p in puzzles if p.id not in seen] or list(puzzles)

    # 3) ~30% of puzzles from the player's weakest themes.
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

    # 4) Closest to the target, with a penalty for themes from recent puzzles (variety).
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

    # 5) Justification.
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
