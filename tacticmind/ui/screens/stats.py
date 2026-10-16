"""Statistics screen: rating over time, success rate per motif, puzzle count, best streak, average time."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

import pygame

from ...i18n import fmt_decimal, t
from ...puzzles.themes import theme_name
from ...rating.profile import PlayerProfile
from .. import theme
from ..charts import bar_chart, line_chart
from ..scale import fs, px
from ..widgets import Button, Segmented, card, draw_text, draw_wrapped, wrapped_height
from .base import Screen

if TYPE_CHECKING:
    from ..app import App


class StatsScreen(Screen):
    def __init__(self, app: App) -> None:
        super().__init__(app)
        self.system = Segmented([("glicko", "Glicko-2"), ("elo", "Elo")], app.profile.system, self._set_system, size=13)
        self.reset_button = Button(partial(t, "stats.reset"), self._ask_reset, style="danger", size=13)
        self.confirm_yes = Button(partial(t, "stats.reset_yes"), self._reset, style="danger", size=14)
        self.confirm_no = Button(partial(t, "common.cancel"), self._cancel, size=14)
        self.confirming = False
        self.play_button = Button(partial(t, "stats.play"), partial(app.go, "play"), style="primary", size=14)

    def _set_system(self, value: str) -> None:
        self.app.profile.system = "elo" if value == "elo" else "glicko"
        self.system.value = value
        self.app.save()

    def _ask_reset(self) -> None:
        self.confirming = True

    def _cancel(self) -> None:
        self.confirming = False

    def _reset(self) -> None:
        self.app.profile = PlayerProfile(sound=self.app.profile.sound, volume=self.app.profile.volume, language=self.app.profile.language)
        self.app.topbar.shown_rating = self.app.profile.rating
        self.app.save()
        self.confirming = False

    def handle(self, event: pygame.event.Event) -> None:
        if self.confirming:
            self.confirm_yes.handle(event)
            self.confirm_no.handle(event)
            return
        self.system.handle(event)
        self.reset_button.handle(event)
        self.play_button.handle(event)

    def draw(self, surface: pygame.Surface) -> None:
        profile = self.app.profile
        self.system.value = profile.system
        g = px(22)
        r = self.rect.inflate(-2 * g, -2 * g)
        narrow = r.width < px(760)
        title = draw_text(surface, t("stats.title"), (r.x, r.y), fs(30), theme.TEXT, "bold")
        seg_w = px(220)
        self.system.rect = pygame.Rect(r.right - seg_w, r.y + px(2), seg_w, px(34))
        self.system.draw(surface)
        label_w = self.system.rect.x - title.right - px(24)
        if label_w > px(60):
            draw_text(surface, t("stats.system"), (self.system.rect.x - px(10), self.system.rect.centery), fs(13), theme.MUTED, "regular", "midright", max_width=label_w)

        history = profile.history
        solved = sum(1 for h in history if h.solved)
        times = [h.time_s for h in history if h.solved]
        rating = f"{round(profile.rating)}" + (f" ± {round(profile.rd)}" if profile.rd is not None else "")
        cards = [
            (t("stats.rating"), rating, theme.ACCENT),
            (t("stats.puzzles"), str(len(history)), theme.VIOLET),
            (t("stats.accuracy"), f"{round(100 * solved / len(history))}%" if history else "—", theme.BLUE),
            (t("stats.best_streak"), str(profile.best_streak), theme.ORANGE),
            (t("stats.avg_time"), f"{fmt_decimal(sum(times) / len(times), 0)} s" if times else "—", theme.AMBER),
            (t("stats.coach_games"), "{}–{}–{}".format(*profile.coach.results()), theme.ROSE),
        ]
        y = r.y + px(54)
        cols = 3 if narrow else len(cards)
        gap = px(12)
        card_w = (r.width - (cols - 1) * gap) // cols
        card_h = px(80)
        for i, (label, value, accent) in enumerate(cards):
            cx = r.x + (i % cols) * (card_w + gap)
            cy = y + (i // cols) * (card_h + gap)
            rect = pygame.Rect(cx, cy, card_w, card_h)
            card(surface, rect)
            pygame.draw.rect(surface, accent, (rect.x + px(14), rect.y + px(14), px(4), card_h - px(28)), border_radius=px(2))
            draw_text(surface, label, (rect.x + px(28), rect.y + px(12)), fs(12), theme.MUTED, max_width=card_w - px(36))
            draw_text(surface, value, (rect.x + px(28), rect.y + px(32)), fs(26), theme.TEXT, "bold", max_width=card_w - px(36))
        y += ((len(cards) - 1) // cols + 1) * (card_h + gap) + px(10)

        bottom = r.bottom - px(56)
        if not narrow:
            left = pygame.Rect(r.x, y + px(30), r.width * 55 // 100, bottom - y - px(30))
            right = pygame.Rect(left.right + px(16), y + px(30), r.right - left.right - px(16), bottom - y - px(30))
        else:
            h = (bottom - y - px(70)) // 2
            left = pygame.Rect(r.x, y + px(30), r.width, h)
            right = pygame.Rect(r.x, left.bottom + px(40), r.width, bottom - left.bottom - px(40))
        heading = draw_text(surface, t("stats.rating_chart"), (left.x, left.y - px(26)), fs(16), theme.TEXT, "bold", max_width=left.width // 2)
        if profile.system == "glicko":
            draw_text(surface, t("stats.band_note"), (heading.right + px(10), heading.centery), fs(11), theme.MUTED, "regular", "midleft", max_width=left.right - heading.right - px(10))
        values = [history[0].rating_before] + [h.rating_after for h in history] if history else []
        band = None
        if profile.system == "glicko" and history and all(h.rd_after is not None for h in history):
            # Uncertainty band clipped to ±150 so the initial RD = 350 doesn't flatten the chart.
            band = [150.0] + [min(150.0, float(h.rd_after or 0)) for h in history]
        line_chart(surface, left, values, theme.ACCENT, band if band and len(band) == len(values) else None)

        draw_text(surface, t("stats.themes_chart"), (right.x, right.y - px(26)), fs(16), theme.TEXT, "bold", max_width=right.width)
        stats = sorted(profile.model.stats.items(), key=lambda kv: -kv[1].attempts)
        max_rows = max(1, (right.height - px(16)) // px(26))
        items = [(theme_name(name), s.rate, s.attempts) for name, s in stats[:max_rows]]
        items.sort(key=lambda item: item[1])
        bar_chart(surface, right, items)

        self.play_button.rect = pygame.Rect(r.x, r.bottom - px(44), px(170), px(44))
        self.reset_button.rect = pygame.Rect(r.right - px(190), r.bottom - px(44), px(190), px(44))
        self.play_button.draw(surface)
        self.reset_button.draw(surface)
        if self.confirming:
            self._draw_confirm(surface)

    def _draw_confirm(self, surface: pygame.Surface) -> None:
        shade = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        shade.fill((5, 6, 12, 170))
        surface.blit(shade, (0, 0))
        width = min(px(460), surface.get_width() - px(40))
        body_h = wrapped_height(t("stats.reset_body"), width - px(48), fs(14))
        rect = pygame.Rect(0, 0, width, px(130) + body_h)
        rect.center = surface.get_rect().center
        card(surface, rect, color=theme.SURFACE_2)
        draw_text(surface, t("stats.reset_title"), (rect.x + px(24), rect.y + px(20)), fs(18), theme.TEXT, "bold", max_width=width - px(48))
        draw_wrapped(surface, t("stats.reset_body"), pygame.Rect(rect.x + px(24), rect.y + px(54), width - px(48), body_h), fs(14), theme.TEXT_SOFT)
        button_w = (width - px(60)) // 2
        self.confirm_no.rect = pygame.Rect(rect.x + px(24), rect.bottom - px(62), button_w, px(42))
        self.confirm_yes.rect = pygame.Rect(self.confirm_no.rect.right + px(12), rect.bottom - px(62), button_w, px(42))
        self.confirm_yes.draw(surface)
        self.confirm_no.draw(surface)
