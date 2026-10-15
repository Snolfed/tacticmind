"""Ekran „Trener”: wybór siły trenera (Elo albo „Twój poziom”), koloru i otwarcia do nauki."""

from __future__ import annotations

import random
from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING

import chess
import pygame

from ...brain.notation import format_line
from ...coach.openings import OPENINGS, Opening, line_ucis
from ...coach.strength import ELO_MAX, ELO_MIN, ELO_STEP, describe_level
from ...i18n import t, tn
from .. import gfx, theme
from ..anim import ease_out_cubic
from ..badges import draw_star
from ..coach_avatar import draw_coach
from ..scale import fs, px
from ..widgets import Button, ScrollArea, Segmented, Slider, card, draw_text, draw_wrapped, wrapped_height
from .base import Screen
from .coach_game import CoachGameScreen

if TYPE_CHECKING:
    from ..app import App


def _tx(key: str) -> partial[str]:
    return partial(t, key)


class CoachMenuScreen(Screen):
    def __init__(self, app: App) -> None:
        super().__init__(app)
        coach = app.profile.coach
        self.slider = Slider(self._elo_to_value(coach.elo), self._slider_changed, self._slider_released)
        self.level_button = Button(self._level_label, self._toggle_level, size=13, pill=True)
        self.color = Segmented(
            [("white", _tx("coach.color.white")), ("random", _tx("coach.color.random")), ("black", _tx("coach.color.black"))],
            coach.color,
            self._color_changed,
            size=13,
        )
        self.filter = Segmented(
            [("all", _tx("coach.filter.all")), ("white", _tx("coach.filter.white")), ("black", _tx("coach.filter.black"))],
            "all",
            self._filter_changed,
            size=12,
            accent=theme.VIOLET,
        )
        self.play_button = Button(_tx("coach.play"), self.play, style="primary", size=17)
        self.resume_button = Button(_tx("coach.resume"), partial(app.go, "coach_game"), style="violet", size=15)
        self.confirm_yes = Button(_tx("coach.abandon_yes"), self._confirmed, style="danger", size=14)
        self.confirm_no = Button(_tx("common.cancel"), self._cancel, size=14)
        self.pending: Callable[[], None] | None = None
        self.scroll = ScrollArea(stick_to_bottom=False)
        self.rows: list[tuple[Opening, pygame.Rect]] = []
        self.hover = -1
        self.clock = 0.0
        self.wide = True
        self.coach_rect = pygame.Rect(0, 0, 0, 0)
        self.setup_rect = pygame.Rect(0, 0, 0, 0)
        self.list_rect = pygame.Rect(0, 0, 0, 0)
        # Wąski układ: cała strona przewija się w pionie.
        self.page: pygame.Surface | None = None
        self.page_h = 0
        self.scroll_y = 0.0
        self.rng = random.Random()

    # ------------------------------------------------------------ ustawienia
    @staticmethod
    def _elo_to_value(elo: int) -> float:
        return (elo - ELO_MIN) / (ELO_MAX - ELO_MIN)

    @staticmethod
    def _value_to_elo(value: float) -> int:
        steps = (ELO_MAX - ELO_MIN) // ELO_STEP
        return ELO_MIN + round(value * steps) * ELO_STEP

    def _slider_changed(self, value: float) -> None:
        coach = self.app.profile.coach
        coach.elo = self._value_to_elo(value)
        coach.use_level = False

    def _slider_released(self) -> None:
        self.slider.value = self._elo_to_value(self.app.profile.coach.elo)
        self.app.save()

    def _level_label(self) -> str:
        coach = self.app.profile.coach
        if coach.calibrated and coach.level is not None:
            return t("coach.your_level", elo=coach.level)
        return t("coach.your_level_locked", n=coach.calibration_progress())

    def _toggle_level(self) -> None:
        coach = self.app.profile.coach
        if coach.calibrated and coach.level is not None:
            coach.use_level = not coach.use_level
            self.app.save()

    def _color_changed(self, value: str) -> None:
        self.app.profile.coach.color = value
        self.color.value = value
        self.app.save()

    def _filter_changed(self, value: str) -> None:
        self.filter.value = value
        self.scroll.scroll_to_top()

    def chosen_elo(self) -> tuple[int, bool]:
        coach = self.app.profile.coach
        if coach.use_level and coach.level is not None:
            return coach.level, True
        return coach.elo, False

    def _player_color(self) -> chess.Color:
        choice = self.app.profile.coach.color
        if choice == "random":
            return self.rng.choice((chess.WHITE, chess.BLACK))
        return chess.WHITE if choice == "white" else chess.BLACK

    def _game_screen(self) -> CoachGameScreen:
        screen = self.app.screens["coach_game"]
        assert isinstance(screen, CoachGameScreen)
        return screen

    def game_in_progress(self) -> bool:
        return self._game_screen().in_progress()

    def _start(self, action: Callable[[], None]) -> None:
        """Nowa partia; rozpoczęta partia (od 5 ruchów) liczy się wtedy jako przegrana — po potwierdzeniu."""
        game = self._game_screen().game
        if self.game_in_progress() and game is not None and game.abandon_counts():
            self.pending = action
            return
        self._game_screen().abandon_silently()
        action()

    def _confirmed(self) -> None:
        action = self.pending
        self.pending = None
        if action is not None:
            self._game_screen().abandon_and_record()
            action()

    def _cancel(self) -> None:
        self.pending = None

    def play(self) -> None:
        elo, adaptive = self.chosen_elo()
        color = self._player_color()
        self._start(lambda: self.app.start_coach_game(color, elo, adaptive, None))

    def learn(self, opening: Opening) -> None:
        elo, adaptive = self.chosen_elo()
        self._start(lambda: self.app.start_coach_game(opening.side, elo, adaptive, opening))

    def openings(self) -> list[Opening]:
        side = self.filter.value
        if side == "all":
            return list(OPENINGS)
        color = chess.WHITE if side == "white" else chess.BLACK
        return [o for o in OPENINGS if o.side == color]

    # ------------------------------------------------------------ cykl życia
    def enter(self) -> None:
        self.clock = 0.0
        coach = self.app.profile.coach
        self.slider.value = self._elo_to_value(coach.elo)
        self.color.value = coach.color

    def layout(self, rect: pygame.Rect) -> None:
        super().layout(rect)
        g = px(22)
        self.wide = rect.width >= px(860)
        if self.wide:
            left_w = max(px(380), min(px(500), int(rect.width * 0.38)))
            x = rect.x + g
            self.coach_rect = pygame.Rect(x, rect.y + g, left_w, px(196))
            self.setup_rect = pygame.Rect(x, self.coach_rect.bottom + px(14), left_w, px(330))
            list_x = self.coach_rect.right + px(18)
            self.list_rect = pygame.Rect(list_x, rect.y + g, rect.right - g - list_x, rect.height - 2 * g)
        else:
            w = rect.width - 2 * g
            self.coach_rect = pygame.Rect(g, g, w, px(206))
            self.setup_rect = pygame.Rect(g, self.coach_rect.bottom + px(14), w, px(330))
            rows = len(self.openings())
            self.list_rect = pygame.Rect(g, self.setup_rect.bottom + px(14), w, px(110) + rows * px(68))
            self.page_h = self.list_rect.bottom + g
            self.scroll_y = min(self.scroll_y, max(0, self.page_h - rect.height))

    # ------------------------------------------------------------ zdarzenia
    def _to_page(self, pos: tuple[int, int]) -> tuple[int, int]:
        return (pos[0] - self.rect.x, pos[1] - self.rect.y + int(self.scroll_y))

    def handle(self, event: pygame.event.Event) -> None:
        if self.pending is not None:
            self.confirm_yes.handle(event)
            self.confirm_no.handle(event)
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.pending = None
            return
        mouse = pygame.mouse.get_pos()
        if not self.wide:
            if event.type == pygame.MOUSEWHEEL:
                max_scroll = max(0, self.page_h - self.rect.height)
                self.scroll_y = max(0.0, min(max_scroll, self.scroll_y - event.y * px(60)))
                return
            mouse = self._to_page(mouse)
            if hasattr(event, "pos"):
                event = pygame.event.Event(event.type, {**event.dict, "pos": self._to_page(event.pos)})
        elif self.scroll.handle(event, mouse):
            return
        for widget in (self.slider, self.level_button, self.color, self.filter, self.play_button, self.resume_button):
            if widget.handle(event):
                return
        if event.type == pygame.MOUSEMOTION:
            self.hover = self._row_at(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            index = self._row_at(event.pos)
            if index >= 0:
                self.learn(self.rows[index][0])
        elif event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
            self.play()

    def _row_at(self, pos: tuple[int, int]) -> int:
        clip = self._list_clip()
        if not clip.collidepoint(pos):
            return -1
        for i, (_, rect) in enumerate(self.rows):
            if rect.collidepoint(pos):
                return i
        return -1

    def _list_clip(self) -> pygame.Rect:
        r = self.list_rect
        return pygame.Rect(r.x, r.y + px(96), r.width, r.height - px(104))

    def update(self, dt: float) -> None:
        self.clock += dt
        if not self.wide:
            self.scroll_y = min(self.scroll_y, max(0, self.page_h - self.rect.height))
        coach = self.app.profile.coach
        self.level_button.enabled = coach.calibrated and coach.level is not None
        self.resume_button.visible = self.game_in_progress()
        self.play_button.label = _tx("coach.new_game") if self.resume_button.visible else _tx("coach.play")
        self.level_button.active = coach.use_level and self.level_button.enabled

    # ------------------------------------------------------------ rysowanie
    def draw(self, screen: pygame.Surface) -> None:
        surface = screen
        if not self.wide:
            size = (self.rect.width, self.page_h)
            if self.page is None or self.page.get_size() != size:
                self.page = pygame.Surface(size)
            self.page.blit(gfx.background(screen.get_size()), (0, -self.rect.y))
            surface = self.page
        appear = ease_out_cubic(self.clock / 0.45)
        self._draw_coach(surface, appear)
        self._draw_setup(surface)
        self._draw_openings(surface)
        if not self.wide and self.page is not None:
            screen.blit(self.page, self.rect.topleft, pygame.Rect(0, int(self.scroll_y), self.rect.width, self.rect.height))
            if self.page_h > self.rect.height:
                ratio = self.rect.height / self.page_h
                h = max(px(30), int(self.rect.height * ratio))
                y = self.rect.y + int((self.rect.height - h) * self.scroll_y / max(1, self.page_h - self.rect.height))
                gfx.rrect(screen, (*theme.BORDER[:3], 220), pygame.Rect(self.rect.right - px(6), y, px(4), h), px(2))
        if self.pending is not None:
            self._draw_confirm(screen)

    def _draw_confirm(self, surface: pygame.Surface) -> None:
        shade = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        shade.fill((5, 6, 12, 170))
        surface.blit(shade, (0, 0))
        width = min(px(480), surface.get_width() - px(40))
        text = t("coach.abandon_confirm")
        text_h = wrapped_height(text, width - px(48), fs(16))
        rect = pygame.Rect(0, 0, width, text_h + px(120))
        rect.center = surface.get_rect().center
        card(surface, rect, color=theme.SURFACE_2)
        draw_wrapped(surface, text, pygame.Rect(rect.x + px(24), rect.y + px(24), width - px(48), text_h), fs(16), theme.TEXT)
        button_w = (width - px(48) - px(12)) // 2
        self.confirm_no.rect = pygame.Rect(rect.x + px(24), rect.bottom - px(64), button_w, px(42))
        self.confirm_yes.rect = pygame.Rect(self.confirm_no.rect.right + px(12), rect.bottom - px(64), button_w, px(42))
        self.confirm_yes.draw(surface)
        self.confirm_no.draw(surface)

    def _greeting(self) -> str:
        coach = self.app.profile.coach
        if not coach.games:
            return t("coach.hello_new")
        if not coach.calibrated:
            return tn("coach.hello_calibrating", coach.games_to_update())
        return tn("coach.hello_level", coach.games_to_update(), elo=coach.level or coach.elo)

    def _draw_coach(self, surface: pygame.Surface, appear: float) -> None:
        r = self.coach_rect
        card(surface, r)
        avatar = min(px(132), r.height - px(40))
        blink = (self.clock % 4.3) < 0.12
        expression = "happy" if self.clock < 2.5 else "neutral"
        center = (r.x + px(20) + avatar // 2, r.y + r.height // 2 - round((1 - appear) * px(10)))
        draw_coach(surface, center, avatar, expression, blink, theme.ACCENT)
        x = center[0] + avatar // 2 + px(18)
        w = r.right - x - px(18)
        draw_text(surface, t("coach.name"), (x, r.y + px(18)), fs(22), theme.TEXT, "bold", max_width=w)
        draw_text(surface, t("coach.subtitle"), (x, r.y + px(48)), fs(13), theme.MUTED, max_width=w)
        bubble = pygame.Rect(x - px(6), r.y + px(74), w + px(8), r.bottom - px(14) - (r.y + px(74)))
        gfx.rrect(surface, theme.SURFACE_2, bubble, px(12))
        tail = [(bubble.x, bubble.y + px(18)), (bubble.x - px(9), bubble.y + px(24)), (bubble.x, bubble.y + px(30))]
        gfx.polygon(surface, theme.SURFACE_2, tail)
        draw_wrapped(surface, self._greeting(), bubble.inflate(-px(22), -px(18)), fs(14), theme.TEXT_SOFT, shrink=True)

    def _draw_setup(self, surface: pygame.Surface) -> None:
        r = self.setup_rect
        card(surface, r)
        pad = px(20)
        x, y, w = r.x + pad, r.y + px(16), r.width - 2 * pad
        coach = self.app.profile.coach
        draw_text(surface, t("coach.setup_title"), (x, y), fs(18), theme.TEXT, "bold", max_width=w)
        y += px(36)
        elo, adaptive = self.chosen_elo()
        draw_text(surface, t("coach.strength"), (x, y), fs(12), theme.MUTED, max_width=w // 2)
        value = draw_text(surface, str(elo), (x, y + px(18)), fs(30), theme.ACCENT if adaptive else theme.TEXT, "bold")
        draw_text(surface, t(describe_level(elo)), (value.right + px(10), value.centery + px(3)), fs(14), theme.TEXT_SOFT, "bold", "midleft", max_width=x + w - value.right - px(10))
        y += px(64)
        self.slider.rect = pygame.Rect(x + px(4), y, w - px(8), px(20))
        self.slider.value = self._elo_to_value(coach.elo) if not self.slider.dragging else self.slider.value
        self.slider.draw(surface)
        draw_text(surface, str(ELO_MIN), (x, y + px(20)), fs(11), theme.DIM)
        draw_text(surface, str(ELO_MAX), (x + w, y + px(20)), fs(11), theme.DIM, anchor="topright")
        if adaptive:
            gfx.rrect(surface, (*theme.SURFACE[:3], 150), self.slider.rect.inflate(px(12), px(12)), px(10))
        y += px(46)
        self.level_button.rect = pygame.Rect(x, y, w, px(38))
        self.level_button.draw(surface)
        y += px(44)
        note = tn("coach.level_note", coach.games_to_update()) if coach.calibrated else t("coach.level_locked_note")
        draw_text(surface, note, (x + w // 2, y), fs(11), theme.DIM, anchor="midtop", max_width=w)
        y += px(26)
        self.color.rect = pygame.Rect(x, y, w, px(36))
        self.color.draw(surface)
        y += px(50)
        h = max(px(44), r.bottom - px(16) - y)
        if self.resume_button.visible:
            half = (w - px(10)) // 2
            self.resume_button.rect = pygame.Rect(x, y, half, h)
            self.play_button.rect = pygame.Rect(x + half + px(10), y, half, h)
            self.resume_button.draw(surface)
        else:
            self.play_button.rect = pygame.Rect(x, y, w, h)
        self.play_button.draw(surface)

    def _draw_openings(self, surface: pygame.Surface) -> None:
        r = self.list_rect
        card(surface, r)
        pad = px(20)
        x, w = r.x + pad, r.width - 2 * pad
        draw_text(surface, t("coach.openings_title"), (x, r.y + px(16)), fs(18), theme.TEXT, "bold", max_width=w // 2)
        filter_w = min(px(300), w // 2)
        self.filter.rect = pygame.Rect(r.right - pad - filter_w, r.y + px(14), filter_w, px(32))
        self.filter.draw(surface)
        draw_wrapped(surface, t("coach.openings_desc"), pygame.Rect(x, r.y + px(52), w, px(40)), fs(12), theme.MUTED, max_lines=2)
        clip = self._list_clip()
        openings = self.openings()
        row_h = px(64)
        gap = px(6)
        self.scroll.rect = clip
        self.scroll.content_height = len(openings) * (row_h + gap)
        self.scroll.follow()
        offset = int(self.scroll.offset) if self.wide else 0
        old_clip = surface.get_clip()
        surface.set_clip(clip)
        self.rows = []
        y = clip.y - offset
        for i, opening in enumerate(openings):
            row = pygame.Rect(clip.x + px(10), y, clip.width - px(20), row_h)
            self.rows.append((opening, row))
            if row.bottom >= clip.y and row.y <= clip.bottom:
                self._draw_row(surface, opening, row, i == self.hover)
            y += row_h + gap
        if 0 <= self.hover < len(self.rows):
            self._draw_tooltip(surface, *self.rows[self.hover])
        surface.set_clip(old_clip)
        if self.wide:
            self.scroll.draw_scrollbar(surface)

    def _draw_row(self, surface: pygame.Surface, opening: Opening, row: pygame.Rect, hover: bool) -> None:
        gfx.rrect(surface, theme.SURFACE_3 if hover else theme.SURFACE_2, row, px(12))
        if hover:
            gfx.rrect(surface, (*theme.ACCENT[:3], 120), row, px(12), max(1, px(1)))
        cy = row.centery
        dot = (236, 239, 246) if opening.side == chess.WHITE else (14, 16, 26)
        gfx.circle(surface, dot, (row.x + px(22), cy), px(8))
        gfx.circle(surface, theme.BORDER, (row.x + px(22), cy), px(8), max(1, px(1)))
        stars_w = px(66)
        text_x = row.x + px(42)
        text_w = row.width - (text_x - row.x) - stars_w - px(10)
        draw_text(surface, t(f"opening.{opening.id}.name"), (text_x, row.y + px(11)), fs(15), theme.TEXT, "bold", max_width=text_w)
        line = format_line(chess.STARTING_FEN, list(line_ucis(opening.id)), 6)
        draw_text(surface, f"{opening.eco} · {line}", (text_x, row.y + px(35)), fs(12), theme.MUTED, max_width=text_w)
        stars = self.app.profile.coach.stars(opening.id)
        for i in range(3):
            center = (row.right - px(56) + i * px(20), cy)
            draw_star(surface, center, px(8), theme.AMBER if i < stars else theme.SURFACE)

    def _draw_tooltip(self, surface: pygame.Surface, opening: Opening, row: pygame.Rect) -> None:
        """Krótki opis otwarcia pod wskazanym wierszem (nad nim, gdy brakuje miejsca)."""
        desc = t(f"opening.{opening.id}.desc")
        height = wrapped_height(desc, row.width - px(60), fs(12)) + px(18)
        box = pygame.Rect(row.x + px(30), row.bottom + px(4), row.width - px(30), height)
        if box.bottom > self._list_clip().bottom:
            box.bottom = row.y - px(4)
        card(surface, box, px(10), theme.SURFACE_3)
        draw_wrapped(surface, desc, box.inflate(-px(24), -px(14)), fs(12), theme.TEXT_SOFT)
