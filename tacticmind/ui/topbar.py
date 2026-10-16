"""Top bar: logo, navigation, language, sound, a large rating with an animated change and a streak with a flame."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

import pygame

from ..i18n import LANGUAGES, get_language, t
from ..rating.profile import RatingChange
from . import fonts, gfx, theme
from .anim import approach, ease_out_back, ease_out_cubic, now
from .scale import fs, px
from .widgets import Button, Segmented, Slider, draw_text, icon_flame

if TYPE_CHECKING:
    from .app import App

BASE_HEIGHT = 68
_NAV = (("play", "nav.play"), ("coach", "nav.coach"), ("stats", "nav.stats"), ("howto", "nav.howto"))
#: Screens on which a given tab is highlighted.
_ACTIVE = {"coach": ("coach", "coach_game")}


def height() -> int:
    return px(BASE_HEIGHT)


class TopBar:
    def __init__(self, app: App) -> None:
        self.app = app
        self.rect = pygame.Rect(0, 0, 0, height())
        self.nav = [Button(t(key), partial(app.go, name), size=14, pill=True, style="ghost") for name, key in _NAV]
        self.sound = Button("", self._toggle_sound, style="ghost", pill=True)
        self.volume = Slider(app.profile.volume, self._volume_changed, self._volume_released)
        self.fullscreen = Button("", app.toggle_fullscreen, style="ghost", pill=True, icon="fullscreen")
        self.settings = Button("", app.settings.toggle, style="ghost", pill=True, icon="settings")
        options: list[tuple[str, str]] = [(code, code.upper()) for code in LANGUAGES]
        self.language = Segmented(list(options), get_language(), app.set_language, size=12, accent=theme.VIOLET)
        self.logo_rect = pygame.Rect(0, 0, 0, 0)
        self.shown_rating = app.profile.rating
        self.source = "puzzles"
        self.delta: float | None = None
        self.delta_at = -10.0
        self.two_rows = False
        self.row_h = height()

    def _toggle_sound(self) -> None:
        profile = self.app.profile
        profile.sound = not profile.sound
        if profile.sound and profile.volume < 0.02:
            profile.volume = self.volume.value = 0.5  # enabling sound while the slider is at zero
            self.app.sounds.set_volume(profile.volume)
        self.app.sounds.enabled = profile.sound
        self.app.save()

    def _volume_changed(self, value: float) -> None:
        profile = self.app.profile
        profile.volume = value
        self.app.sounds.set_volume(value)
        if value > 0.02 and not profile.sound:
            profile.sound = True
            self.app.sounds.enabled = True

    def _volume_released(self) -> None:
        self.app.save()
        self.app.sounds.play("move")  # sample: the new volume is heard right away

    def on_rating_change(self, change: RatingChange) -> None:
        self.delta = change.delta
        self.delta_at = now()

    def layout(self, width: int) -> None:
        """Lays out the items in one row, or in two when the window is narrow
        (logo and rating on top, navigation, language and sound below)."""
        logo_w = fonts.text_size("TacticMind", fs(26), "bold")[0]
        narrow = width < px(560)
        slider_w = px(56) if narrow else px(90)
        self.fullscreen.visible = not narrow  # in a very narrow window fullscreen stays available via F11
        controls_w = px(84) + px(8) + px(40) + px(6) + slider_w + (px(12) + px(40) if self.fullscreen.visible else 0) + px(6) + px(40)
        labels = [t(key) for _, key in _NAV]
        widths = [fonts.text_size(label, fs(14), "bold")[0] + px(30) for label in labels]
        nav_w = sum(widths) + 2 * px(6)
        single_row = px(22) + logo_w + px(22) + nav_w + px(8) + controls_w + px(20) + px(200) <= width
        self.two_rows = not single_row
        if single_row:
            self.rect = pygame.Rect(0, 0, width, height())
            self.row_h = self.rect.height
            x, row_y, row_h = px(22) + logo_w + px(22), 0, self.rect.height
        else:
            self.row_h = px(60)
            self.rect = pygame.Rect(0, 0, width, self.row_h + px(52))
            x, row_y, row_h = px(14), self.row_h, px(52)
            available = width - x - controls_w - px(30)
            if nav_w > available:
                labels[-1] = t("nav.howto_short")
                widths = [fonts.text_size(label, fs(13), "bold")[0] + px(22) for label in labels]
            factor = min(1.0, available / max(1, sum(widths) + 2 * px(6)))
            widths = [int(w * factor) for w in widths]
        button_h = px(38)
        for button, label, w in zip(self.nav, labels, widths):
            button.label = label
            button.rect = pygame.Rect(x, row_y + (row_h - button_h) // 2, w, button_h)
            x += w + px(6)
        if self.two_rows:
            x = width - px(14) - controls_w
        self.language.rect = pygame.Rect(x + px(8), row_y + (row_h - px(32)) // 2, px(84), px(32))
        self.sound.rect = pygame.Rect(self.language.rect.right + px(8), row_y + (row_h - px(38)) // 2, px(40), px(38))
        self.volume.rect = pygame.Rect(self.sound.rect.right + px(6), row_y + (row_h - px(20)) // 2, slider_w, px(20))
        self.fullscreen.rect = pygame.Rect(self.volume.rect.right + px(12), row_y + (row_h - px(38)) // 2, px(40), px(38))
        settings_x = (self.fullscreen.rect.right if self.fullscreen.visible else self.volume.rect.right + px(6)) + px(6)
        self.settings.rect = pygame.Rect(settings_x, row_y + (row_h - px(38)) // 2, px(40), px(38))
        self.app.settings.layout(self.settings.rect, width)

    def handle(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.logo_rect.collidepoint(event.pos):
            self.app.go("home")
            return True
        if self.volume.handle(event) or self.language.handle(event):
            return True
        return any(button.handle(event) for button in [*self.nav, self.sound, self.fullscreen, self.settings])

    def _source(self) -> str:
        """On the coach screens the bar shows the coach-game rating instead of the puzzle rating."""
        return "coach" if self.app.current_name.startswith("coach") else "puzzles"

    def _rating(self) -> tuple[float, float | None]:
        profile = self.app.profile
        if self._source() == "coach":
            return profile.coach.rating.rating, profile.coach.rating.rd
        return profile.rating, profile.rd

    def update(self, dt: float) -> None:
        target, _ = self._rating()
        source = self._source()
        if source != self.source:
            self.source = source
            self.shown_rating = target  # a different rating — don't animate the number rolling
        self.shown_rating = approach(self.shown_rating, target, dt, 5)
        if abs(target - self.shown_rating) < 0.5:
            self.shown_rating = target

    def draw(self, surface: pygame.Surface) -> None:
        h = self.row_h
        surface.blit(gfx.vertical_gradient(self.rect.size, (22, 25, 38), (17, 19, 30)), (0, 0))
        pygame.draw.line(surface, theme.BORDER_SOFT, (0, self.rect.height - 1), (self.rect.width, self.rect.height - 1))
        if self.two_rows:
            pygame.draw.line(surface, (*theme.BORDER_SOFT[:3],), (px(14), h), (self.rect.width - px(14), h))
        # Logo: "Tactic" + "Mind" in a teal → violet gradient
        logo = draw_text(surface, "Tactic", (px(22), h // 2), fs(26), theme.TEXT, "bold", "midleft")
        ai_surface = gfx.gradient_text(fonts.render("Mind", fs(26), (255, 255, 255), "bold"), theme.ACCENT, theme.VIOLET)
        ai_rect = ai_surface.get_rect(midleft=(logo.right, h // 2))
        surface.blit(ai_surface, ai_rect)
        self.logo_rect = logo.union(ai_rect)
        for button, (name, _) in zip(self.nav, _NAV):
            button.active = self.app.current_name in _ACTIVE.get(name, (name,))
            button.draw(surface)
        self.language.value = get_language()
        self.language.draw(surface)
        audible = self.app.profile.sound and self.app.profile.volume > 0.02
        self.sound.icon = "sound_on" if audible else "sound_off"
        self.sound.draw(surface)
        self.volume.value = self.app.profile.volume if self.app.profile.sound else 0.0
        self.volume.draw(surface)
        self.fullscreen.icon = "fullscreen_exit" if self.app.fullscreen else "fullscreen"
        self.fullscreen.draw(surface)
        self.settings.active = self.app.settings.open
        self.settings.draw(surface)
        self._draw_rating(surface)

    def _draw_rating(self, surface: pygame.Surface) -> None:
        profile = self.app.profile
        h = self.row_h
        right = self.rect.right - px(22)
        clock = now()
        streak_w = 0
        coach = self._source() == "coach"
        _, rd = self._rating()
        if profile.streak > 0 and not coach:
            label = draw_text(surface, str(profile.streak), (right, h // 2), fs(22), theme.ORANGE, "bold", "midright")
            icon_flame(surface, (label.x - px(14), h // 2), px(26), clock)
            streak_w = label.width + px(36)
        rx = right - streak_w
        if rd is not None:
            rd_rect = draw_text(surface, f"± {round(rd)}", (rx, h // 2 + px(6)), fs(14), theme.MUTED, "bold", "midright")
            rx = rd_rect.x - px(6)
        # The number bounces slightly right after the rating changes.
        age = clock - self.delta_at
        value_surf = fonts.render(str(round(self.shown_rating)), fs(30), theme.TEXT, "bold")
        if age < 0.6:
            value_surf = pygame.transform.smoothscale_by(value_surf, 1.0 + 0.12 * (1 - ease_out_cubic(age / 0.6)))
        value = value_surf.get_rect(midright=(rx, h // 2 + px(4)))
        surface.blit(value_surf, value)
        if coach:
            caption = t("rating.coach_caption")
            if not profile.coach.calibrated:
                caption += " · " + t("rating.calibration", n=profile.coach.calibration_progress())
        else:
            system = "Glicko-2" if profile.system == "glicko" else "Elo"
            caption = t("rating.caption", system=system)
            if profile.calibrating:
                caption += " · " + t("rating.calibration", n=profile.games)
        draw_text(surface, caption, (right - streak_w, px(5)), fs(11), theme.MUTED, "regular", "topright", max_width=px(240))
        # Animated change: +12 in teal, −9 in red — pops up, floats and fades.
        if self.delta is not None and age < 2.6:
            pop = ease_out_back(age / 0.35, 2.0)
            fade = 1.0 if age < 1.8 else max(0.0, 1 - (age - 1.8) / 0.8)
            delta = round(self.delta)
            text = f"+{delta}" if delta >= 0 else f"−{abs(delta)}"
            color = theme.ACCENT if delta >= 0 else theme.RED
            surf = fonts.render(text, fs(18), color, "bold")
            surf = pygame.transform.smoothscale_by(surf, max(0.05, pop)) if pop < 0.999 or pop > 1.001 else surf.copy()
            surf.set_alpha(int(255 * fade))
            pill = surf.get_rect(midright=(value.x - px(12), h // 2 + px(8)))
            bg = pill.inflate(px(14), px(6))
            gfx.rrect(surface, (*color[:3], int(40 * fade)), bg, bg.height // 2)
            surface.blit(surf, pill)
