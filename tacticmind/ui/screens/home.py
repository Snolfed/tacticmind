"""Ekran startowy: nazwa gry, krótki opis i przyciski „Graj”, „Statystyki”, „Jak działa AI?”."""

from __future__ import annotations

import math
from functools import partial
from typing import TYPE_CHECKING

import chess
import pygame

from ...brain.notation import uci_san
from ...i18n import t
from .. import fonts, gfx, theme
from ..anim import ease_out_cubic
from ..board_view import BoardView
from ..scale import fs, px
from ..widgets import Button, card, draw_text, draw_wrapped
from .base import Screen

if TYPE_CHECKING:
    from ..app import App

#: Pozycja na ozdobnej szachownicy: mat szewski — AI pokazuje strzałką ruch Hxf7#.
DEMO_FEN = "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"


class HomeScreen(Screen):
    def __init__(self, app: App) -> None:
        super().__init__(app)
        self.buttons = [
            Button(partial(t, "home.play"), partial(app.go, "play"), style="primary", size=20),
            Button(partial(t, "home.stats"), partial(app.go, "stats"), size=16),
            Button(partial(t, "home.howto"), partial(app.go, "howto"), size=16),
        ]
        self.demo = BoardView()
        self.demo.set_position(chess.Board(DEMO_FEN), chess.Move.from_uci("f1c4"), animate=False)
        self.text_rect = pygame.Rect(0, 0, 0, 0)
        self.clock = 0.0
        self.wide = True

    def enter(self) -> None:
        self.clock = 0.0

    def layout(self, rect: pygame.Rect) -> None:
        super().layout(rect)
        self.wide = rect.width >= px(860) and rect.width > rect.height
        if self.wide:
            size = min(int(rect.height * 0.66), int(rect.width * 0.4))
            size -= size % 8
            gap = px(64)
            text_w = min(px(470), rect.width - size - gap - px(80))
            total = text_w + gap + size
            left = rect.x + (rect.width - total) // 2
            self.demo.rect = pygame.Rect(left + text_w + gap, rect.y + (rect.height - size) // 2, size, size)
            self.text_rect = pygame.Rect(left, self.demo.rect.y, text_w, size)
        else:
            size = min(rect.width - px(64), int(rect.height * 0.34))
            size -= size % 8
            self.text_rect = pygame.Rect(rect.x + px(24), rect.y + px(28), rect.width - px(48), px(250))
            self.demo.rect = pygame.Rect(rect.centerx - size // 2, self.text_rect.bottom + px(8), size, size)

    def handle(self, event: pygame.event.Event) -> None:
        for button in self.buttons:
            button.handle(event)
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
            self.app.go("play")

    def update(self, dt: float) -> None:
        self.clock += dt
        self.demo.update(dt)
        # AI „myśli”: strzałka najlepszego ruchu pojawia się i pulsuje.
        if self.clock > 0.6:
            alpha = 150 + int(70 * (0.5 + 0.5 * math.sin(self.clock * 2.5)))
            self.demo.arrows = [(chess.H5, chess.F7, (*theme.ACCENT[:3], alpha))]

    def draw(self, surface: pygame.Surface) -> None:
        r = self.text_rect
        appear = ease_out_cubic(self.clock / 0.6)
        slide = round((1 - appear) * px(18))
        y = r.y + slide + (px(24) if self.wide else 0)
        title_size = fs(64) if self.wide else fs(44)
        title = draw_text(surface, "Tactic", (r.x, y), title_size, theme.TEXT, "bold")
        ai = gfx.gradient_text(fonts.render("Mind", title_size, (255, 255, 255), "bold"), theme.ACCENT, theme.VIOLET)
        surface.blit(ai, (title.right, title.y))
        y = title.bottom + px(6)
        y += draw_wrapped(surface, t("home.tagline"), pygame.Rect(r.x, y, r.width, px(64)), fs(20) if self.wide else fs(17), theme.TEXT_SOFT, "bold")
        y += px(8)
        y += draw_wrapped(surface, t("home.desc"), pygame.Rect(r.x, y, r.width, px(70)), fs(15), theme.MUTED)
        y += px(22)
        heights = (px(58), px(50), px(50))
        if not self.wide:
            # W wąskim układzie przyciski są pod szachownicą.
            y = self.demo.rect.bottom + px(26)
        for button, h in zip(self.buttons, heights):
            button.rect = pygame.Rect(r.x, y, min(r.width, px(340)) if self.wide else r.width, h)
            button.draw(surface)
            y += h + px(12)
        profile = self.app.profile
        rating = f"{round(profile.rating)}" + (f" ± {round(profile.rd)}" if profile.rd is not None else "")
        solved = sum(1 for record in profile.history if record.solved)
        info = t("home.rating", rating=rating) + " · " + t("home.solved", n=solved)
        y += px(8)
        draw_text(surface, info, (r.x, y), fs(14), theme.TEXT_SOFT, max_width=r.width)
        source = t("source.full") if self.app.puzzle_source == "full" else t("source.starter")
        draw_text(surface, t("home.source", n=len(self.app.puzzles), source=source), (r.x, y + px(24)), fs(12), theme.DIM, max_width=r.width)
        draw_text(surface, t("home.hint_arrows"), (r.x, y + px(44)), fs(12), theme.DIM, max_width=r.width)

        self.demo.draw(surface)
        if self.clock > 0.6:
            pop = ease_out_cubic((self.clock - 0.6) / 0.4)
            tag = pygame.Rect(0, 0, px(190), px(40))
            tag.midtop = (self.demo.rect.centerx, self.demo.rect.bottom + px(16) - round((1 - pop) * px(8)))
            if self.wide:
                card(surface, tag, tag.height // 2, theme.SURFACE_2)
                gfx.circle(surface, theme.VIOLET, (tag.x + px(20), tag.centery), px(5))
                label = f"AI: {uci_san(DEMO_FEN, 'h5f7')}  (M1)"
                draw_text(surface, label, (tag.x + px(34), tag.centery), fs(15), theme.TEXT, "bold", "midleft", max_width=tag.width - px(40))
