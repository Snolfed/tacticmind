"""Player model: accuracy in each tactical theme.

This is the second "AI" element in the game: instead of a single number (the rating) the system
remembers in which themes (forks, pins, mates…) the player does worse,
and offers such puzzles more often.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..puzzles.themes import skill_themes

#: Bayesian smoothing: we assume the player starts at ~65% accuracy,
#: worth as much as 2 puzzles. This way one failed puzzle does not turn a theme into a "weakness".
PRIOR_RATE = 0.65
PRIOR_WEIGHT = 2.0


@dataclass
class ThemeStat:
    attempts: int = 0
    successes: int = 0
    score_sum: float = 0.0

    @property
    def rate(self) -> float:
        """Raw accuracy (for display)."""
        return self.successes / self.attempts if self.attempts else 0.0

    @property
    def smoothed_rate(self) -> float:
        """Smoothed accuracy (for comparing themes)."""
        return (self.successes + PRIOR_RATE * PRIOR_WEIGHT) / (self.attempts + PRIOR_WEIGHT)


class PlayerModel:
    def __init__(self, stats: dict[str, ThemeStat] | None = None) -> None:
        self.stats: dict[str, ThemeStat] = stats if stats is not None else {}

    def record(self, themes: tuple[str, ...] | list[str], success: bool, score: float) -> None:
        for theme in skill_themes(themes):
            stat = self.stats.setdefault(theme, ThemeStat())
            stat.attempts += 1
            stat.successes += int(success)
            stat.score_sum += score

    def rate(self, theme: str) -> float | None:
        stat = self.stats.get(theme)
        return stat.rate if stat and stat.attempts else None

    def overall_rate(self) -> float:
        attempts = sum(s.attempts for s in self.stats.values())
        successes = sum(s.successes for s in self.stats.values())
        return successes / attempts if attempts else PRIOR_RATE

    def weakest(self, min_attempts: int = 2, limit: int = 3) -> list[tuple[str, float]]:
        """The weakest themes (with at least ``min_attempts`` attempts), worst first.

        Returns pairs (theme, raw accuracy). We take only themes below the player's
        average accuracy — a "weakness" has to be genuinely weaker.
        """
        overall = self.overall_rate()
        candidates = [
            (theme, stat)
            for theme, stat in self.stats.items()
            if stat.attempts >= min_attempts and stat.smoothed_rate < max(overall, PRIOR_RATE)
        ]
        candidates.sort(key=lambda item: (item[1].smoothed_rate, -item[1].attempts))
        return [(theme, stat.rate) for theme, stat in candidates[:limit]]

    def to_json(self) -> dict[str, dict[str, float]]:
        return {t: {"attempts": s.attempts, "successes": s.successes, "score_sum": s.score_sum} for t, s in self.stats.items()}

    @classmethod
    def from_json(cls, data: dict[str, dict[str, float]]) -> PlayerModel:
        return cls(
            {
                t: ThemeStat(int(v.get("attempts", 0)), int(v.get("successes", 0)), float(v.get("score_sum", 0.0)))
                for t, v in data.items()
            }
        )
