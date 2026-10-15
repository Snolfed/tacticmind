"""Model gracza: skuteczność w każdym motywie taktycznym.

To drugi element „AI” w grze: zamiast tylko jednej liczby (rankingu) system
pamięta, w których motywach (widełki, związania, maty…) gracz radzi sobie
gorzej, i podsuwa mu takie zadania częściej.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..puzzles.themes import skill_themes

#: Wygładzanie Bayesa: zakładamy, że „na start” gracz ma ok. 65% skuteczności,
#: warte tyle co 2 zadania. Dzięki temu jedno nieudane zadanie nie robi z motywu „słabej strony”.
PRIOR_RATE = 0.65
PRIOR_WEIGHT = 2.0


@dataclass
class ThemeStat:
    attempts: int = 0
    successes: int = 0
    score_sum: float = 0.0

    @property
    def rate(self) -> float:
        """Surowa skuteczność (do wyświetlania)."""
        return self.successes / self.attempts if self.attempts else 0.0

    @property
    def smoothed_rate(self) -> float:
        """Skuteczność wygładzona (do porównywania motywów)."""
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
        """Najsłabsze motywy (z co najmniej ``min_attempts`` próbami), od najgorszego.

        Zwraca pary (motyw, surowa skuteczność). Bierzemy tylko motywy poniżej
        przeciętnej skuteczności gracza — „słaba strona” musi być naprawdę słabsza.
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
