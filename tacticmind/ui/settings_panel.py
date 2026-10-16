"""Settings popup under the gear in the top bar: FPS counter and frame-rate limit."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from ..i18n import t
from ..rating.profile import FPS_LIMITS
from . import theme
from .anim import ease_out_cubic, now
from .scale import fs, px
from .widgets import Segmented, card, draw_text

if TYPE_CHECKING:
    from .app import App


class SettingsPanel:
    def __init__(self, app: App) -> None:
        self.app = app
        self.open = False
        self.rect = pygame.Rect(0, 0, 0, 0)
        self._opened_at = -10.0
        self.show_fps = Segmented(
            [("off", lambda: t("settings.off")), ("on", lambda: t("settings.on"))],
            "on" if app.profile.show_fps else "off",
            self._set_show_fps,
            size=12,
        )
        self.fps_limit = Segmented([(str(v), str(v)) for v in FPS_LIMITS], str(app.profile.fps_limit), self._set_fps_limit, size=12, accent=theme.VIOLET)

    def toggle(self) -> None:
        self.open = not self.open
        if self.open:
            self._opened_at = now()

    def _set_show_fps(self, value: str) -> None:
        self.app.profile.show_fps = value == "on"
        self.app.save()

    def _set_fps_limit(self, value: str) -> None:
        self.app.profile.fps_limit = int(value)
        self.app.save()

    def layout(self, anchor: pygame.Rect, screen_w: int) -> None:
        """Popup below the settings button, kept fully inside the window."""
        w, h = px(330), px(196)
        x = min(max(px(12), anchor.centerx - w // 2), screen_w - px(12) - w)
        self.rect = pygame.Rect(x, anchor.bottom + px(8), w, h)

    def handle(self, event: pygame.event.Event) -> bool:
        """Events for the open popup; ``True`` = event handled (not propagated further)."""
        if not self.open:
            return False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.open = False
            return True
        if event.type == pygame.MOUSEMOTION:
            self.show_fps.handle(event)
            self.fps_limit.handle(event)
            return False
        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.rect.collidepoint(event.pos):
                if event.button == 1 and not self.show_fps.handle(event):
                    self.fps_limit.handle(event)
                return True
            # A click outside closes the popup (a click on the gear is handled by the bar, which closes it too).
            if not self.app.topbar.settings.rect.collidepoint(event.pos):
                self.open = False
            return False
        return event.type == pygame.MOUSEWHEEL and self.rect.collidepoint(pygame.mouse.get_pos())

    def draw(self, surface: pygame.Surface) -> None:
        # The profile may have changed elsewhere (e.g. F3).
        self.show_fps.value = "on" if self.app.profile.show_fps else "off"
        self.fps_limit.value = str(self.app.profile.fps_limit)
        if not self.open:
            return
        appear = ease_out_cubic((now() - self._opened_at) / 0.18)
        r = self.rect.move(0, round((1 - appear) * -px(8)))
        card(surface, r, px(14), theme.SURFACE_2)
        pad = px(16)
        x, w = r.x + pad, r.width - 2 * pad
        y = r.y + px(14)
        draw_text(surface, t("settings.title"), (x, y), fs(15), theme.TEXT, "bold", max_width=w)
        y += px(34)
        seg_w = px(118)
        self.show_fps.rect = pygame.Rect(r.right - pad - seg_w, y, seg_w, px(30))
        draw_text(surface, t("settings.show_fps"), (x, y + px(15)), fs(13), theme.TEXT_SOFT, "bold", "midleft", max_width=w - seg_w - px(10))
        self.show_fps.draw(surface)
        y += px(44)
        draw_text(surface, t("settings.fps_limit"), (x, y), fs(13), theme.TEXT_SOFT, "bold", max_width=w)
        y += px(24)
        self.fps_limit.rect = pygame.Rect(x, y, w, px(32))
        self.fps_limit.draw(surface)
        y += px(42)
        draw_text(surface, t("settings.hint"), (x, y), fs(11), theme.MUTED, max_width=w)
