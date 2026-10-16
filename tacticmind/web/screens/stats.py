"""Statistics screen: rating over time, accuracy per theme, puzzle count, best streak, average time."""

from __future__ import annotations

from typing import Any

from ...i18n import fmt_decimal, t
from ...puzzles.themes import theme_name
from ...rating.profile import PlayerProfile
from .base import WebScreen

#: Uncertainty band clipped to ±150 so that the initial RD = 350 does not flatten the chart.
BAND_LIMIT = 150.0


class StatsScreen(WebScreen):
    confirming = False

    def action(self, name: str, data: dict[str, Any]) -> None:
        profile = self.app.profile
        if self.confirming:
            if name == "confirm_yes":
                self.app.profile = PlayerProfile(sound=profile.sound, volume=profile.volume, language=profile.language)
                self.app.rating_delta = None
                self.app.save()
            if name in ("confirm_yes", "confirm_no"):
                self.confirming = False
            return
        if name == "system" and data.get("system") in ("glicko", "elo"):
            profile.system = "elo" if data.get("system") == "elo" else "glicko"
            self.app.save()
        elif name == "reset":
            self.confirming = True

    def snapshot(self) -> dict[str, Any]:
        profile = self.app.profile
        history = profile.history
        solved = sum(1 for h in history if h.solved)
        times = [h.time_s for h in history if h.solved]
        rating = f"{round(profile.rating)}" + (f" ± {round(profile.rd)}" if profile.rd is not None else "")
        cards = [
            {"label": t("stats.rating"), "value": rating, "accent": "accent"},
            {"label": t("stats.puzzles"), "value": str(len(history)), "accent": "violet"},
            {"label": t("stats.accuracy"), "value": f"{round(100 * solved / len(history))}%" if history else "—", "accent": "blue"},
            {"label": t("stats.best_streak"), "value": str(profile.best_streak), "accent": "orange"},
            {"label": t("stats.avg_time"), "value": f"{fmt_decimal(sum(times) / len(times), 0)} s" if times else "—", "accent": "amber"},
            {"label": t("stats.coach_games"), "value": "{}–{}–{}".format(*profile.coach.results()), "accent": "rose"},
        ]
        values = [history[0].rating_before] + [h.rating_after for h in history] if history else []
        band = None
        if profile.system == "glicko" and history and all(h.rd_after is not None for h in history):
            band = [BAND_LIMIT] + [min(BAND_LIMIT, float(h.rd_after or 0)) for h in history]
        stats = sorted(profile.model.stats.items(), key=lambda kv: -kv[1].attempts)
        stats_shown = sorted(stats[:14], key=lambda kv: kv[1].rate)
        themes = [{"name": theme_name(name), "rate": s.rate, "attempts": s.attempts} for name, s in stats_shown]
        return {
            "system": profile.system,
            "cards": cards,
            "ratings": [round(v, 1) for v in values],
            "band": band if band and len(band) == len(values) else None,
            "themes": themes,
            "confirm": self.confirming,
        }
