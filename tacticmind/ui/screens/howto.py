"""Strona „Jak działa AI?” — wyjaśnienie algorytmów dla prowadzącego, z interaktywnym porównaniem
minimaksu i alfa-bety (na prawdziwym silniku) oraz demonstracją cięć krok po kroku."""

from __future__ import annotations

from collections.abc import Iterator
from functools import partial
from typing import TYPE_CHECKING

import chess
import pygame

from ...brain.demo import DemoNode, DemoResult, alphabeta_demo, build_demo_tree, minimax_demo
from ...brain.notation import uci_san
from ...engine.process import CompareEvent, EngineEvent, ErrorEvent
from ...engine.types import CompareResult, CompareVariant, format_score
from ...i18n import fmt_decimal, fmt_int, t
from .. import fonts, gfx, theme
from ..anim import approach, now
from ..scale import fs, px
from ..widgets import Button, Segmented, card, draw_text, draw_wrapped, label_text, wrapped_height
from .base import Screen

if TYPE_CHECKING:
    from ..app import App

POSITIONS = [
    ("pos.start", chess.STARTING_FEN),
    ("pos.italian", "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"),
    ("pos.kiwipete", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"),
    ("pos.endgame", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"),
]
#: Powyżej tylu szacowanych węzłów czysty minimaks w Pythonie trwałby zbyt długo.
MINIMAX_LIMIT = 350_000
SECTIONS = ["s1", "s2", "code", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "s10", "s11"]


def _walk(node: DemoNode) -> Iterator[DemoNode]:
    yield node
    for child in node.children:
        yield from _walk(child)


class HowToScreen(Screen):
    def __init__(self, app: App) -> None:
        super().__init__(app)
        self.offset = 0.0
        self.target = 0.0
        self.content_height = 0
        self._last = now()
        self.position_index = 0
        self.depth = 3
        self.request: int | None = None
        self.result: CompareResult | None = None
        self.result_key: tuple[str, int] = ("", 0)
        self.skipped_estimate = 0
        self.error = ""
        self.position_buttons: list[Button] = []
        self.depth_buttons = [Button(str(d), partial(self._set_depth, d), size=14) for d in range(1, 5)]
        self.run_button = Button(partial(t, "compare.run"), self._run, style="primary", size=15)
        self.tree = build_demo_tree()
        self.demo_mode = "alphabeta"
        self.demo: DemoResult = alphabeta_demo(self.tree)
        self.demo_step = 0
        self.demo_switch = Segmented(
            [("minimax", partial(t, "demo.minimax")), ("alphabeta", partial(t, "demo.alphabeta"))], "alphabeta", self._set_demo_mode, size=13
        )
        self.demo_prev = Button("", partial(self._step, -1), icon="left")
        self.demo_next = Button("", partial(self._step, 1), icon="right")
        self.demo_all = Button(partial(t, "demo.all"), partial(self._step, 999), size=13)
        self.demo_reset = Button(partial(t, "demo.reset"), partial(self._step, -999), size=13)
        # Wysokości kart z poprzedniej klatki (tło karty rysujemy przed treścią).
        self._compare_height = 300
        self._demo_height = 420

    # ------------------------------------------------------------ akcje
    def _positions(self) -> list[tuple[str, str]]:
        positions = list(POSITIONS)
        play = self.app.screens.get("play")
        session = getattr(play, "session", None)
        if session is not None and session.status.value != "intro":
            positions.append(("pos.current", session.puzzle.start_fen))
        return positions

    def _set_position(self, index: int) -> None:
        self.position_index = index

    def _set_depth(self, depth: int) -> None:
        self.depth = depth

    def _run(self) -> None:
        positions = self._positions()
        key, fen = positions[min(self.position_index, len(positions) - 1)]
        branching = max(1, chess.Board(fen).legal_moves.count())
        estimate = branching**self.depth
        include_minimax = estimate <= MINIMAX_LIMIT
        self.skipped_estimate = 0 if include_minimax else estimate
        self.request = self.app.engine.compare(fen, self.depth, include_minimax)
        self.result = None
        self.error = ""
        self.result_key = (key, self.depth)

    def _set_demo_mode(self, mode: str) -> None:
        self.demo_mode = mode
        self.demo_switch.value = mode
        self.demo = alphabeta_demo(self.tree) if mode == "alphabeta" else minimax_demo(self.tree)
        self.demo_step = 0

    def _step(self, delta: int) -> None:
        self.demo_step = max(0, min(len(self.demo.steps), self.demo_step + delta))

    def on_engine(self, event: EngineEvent) -> None:
        if self.request is None or event.id != self.request:
            return
        if isinstance(event, CompareEvent):
            self.result = event.result
            self.request = None
        elif isinstance(event, ErrorEvent):
            self.error = event.message
            self.request = None

    # ------------------------------------------------------------ zdarzenia
    def _max_offset(self) -> float:
        return max(0.0, self.content_height - self.rect.height)

    def handle(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEWHEEL:
            self.target = max(0.0, min(self.target - event.y * px(60), self._max_offset()))
            return
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RIGHT:
                self._step(1)
            elif event.key == pygame.K_LEFT:
                self._step(-1)
            elif event.key in (pygame.K_PAGEDOWN, pygame.K_DOWN):
                self.target = min(self.target + px(140), self._max_offset())
            elif event.key in (pygame.K_PAGEUP, pygame.K_UP):
                self.target = max(0.0, self.target - px(140))
        self.run_button.enabled = self.request is None
        buttons = [*self.position_buttons, *self.depth_buttons, self.run_button, self.demo_prev, self.demo_next, self.demo_all, self.demo_reset]
        for button in buttons:
            if button.handle(event):
                return
        self.demo_switch.handle(event)

    # ------------------------------------------------------------ rysowanie
    def draw(self, surface: pygame.Surface) -> None:
        clock = now()
        self.offset = approach(self.offset, self.target, min(0.1, clock - self._last), 16)
        self._last = clock
        clip = surface.get_clip()
        surface.set_clip(self.rect)
        width = min(px(1040), self.rect.width - 2 * px(22))
        x = self.rect.centerx - width // 2
        y = self.rect.y + px(24) - int(self.offset)
        draw_text(surface, t("howto.title"), (x, y), fs(32), theme.TEXT, "bold", max_width=width)
        y += px(52)
        y += draw_wrapped(surface, t("howto.intro"), pygame.Rect(x, y, width, px(400)), fs(15), theme.TEXT_SOFT) + px(18)
        y = self._draw_compare(surface, x, y, width) + px(22)
        y = self._draw_demo(surface, x, y, width) + px(26)
        for key in SECTIONS:
            y = self._draw_section(surface, x, y, width, key)
        self.content_height = int(y + self.offset - self.rect.y + px(30))
        self.target = min(self.target, self._max_offset())
        surface.set_clip(clip)
        if self.content_height > self.rect.height:
            ratio = self.rect.height / self.content_height
            h = max(px(30), self.rect.height * ratio)
            pos = self.rect.y + (self.rect.height - h) * self.offset / max(1, self._max_offset())
            gfx.rrect(surface, (*theme.BORDER[:3], 220), pygame.Rect(self.rect.right - px(8), round(pos), px(5), round(h)), px(2))

    def _draw_section(self, surface: pygame.Surface, x: int, y: int, width: int, key: str) -> int:
        if key == "code":
            draw_text(surface, t("howto.code.title"), (x, y), fs(19), theme.TEXT, "bold", max_width=width)
            y += px(36)
            lines = t("howto.code").split("\n")
            line_h = fonts.line_height(fs(14), "mono") + px(4)
            box = pygame.Rect(x, y, width, len(lines) * line_h + px(28))
            card(surface, box, color=(14, 16, 26), elevated=False)
            for i, line in enumerate(lines):
                draw_text(surface, line, (x + px(20), y + px(14) + i * line_h), fs(14), (190, 242, 228), "mono", max_width=width - px(40))
            return box.bottom + px(26)
        title = draw_text(surface, t(f"howto.{key}.title"), (x + px(14), y), fs(19), theme.ACCENT, "bold", max_width=width - px(14))
        gfx.rrect(surface, theme.ACCENT, pygame.Rect(x, title.y + px(4), px(4), title.height - px(8)), px(2))
        y += px(36)
        body = t(f"howto.{key}.body")
        return y + draw_wrapped(surface, body, pygame.Rect(x, y, width, wrapped_height(body, width, fs(15)) + px(4)), fs(15), theme.TEXT_SOFT) + px(20)

    def _chip(self, button: Button, rect: pygame.Rect, selected: bool) -> None:
        button.rect = rect
        button.style = "primary" if selected else "secondary"

    def _draw_compare(self, surface: pygame.Surface, x: int, y: int, width: int) -> int:
        positions = self._positions()
        self.position_index = min(self.position_index, len(positions) - 1)
        if len(self.position_buttons) != len(positions):
            self.position_buttons = [Button(partial(t, key), partial(self._set_position, i), size=13) for i, (key, _) in enumerate(positions)]
        top = y
        card(surface, pygame.Rect(x, top, width, max(px(10), self._compare_height)), color=theme.SURFACE)
        inner_x = x + px(22)
        inner_w = width - px(44)
        y += px(20)
        draw_text(surface, t("compare.title"), (inner_x, y), fs(19), theme.TEXT, "bold", max_width=inner_w)
        y += px(32)
        y += draw_wrapped(surface, t("compare.subtitle"), pygame.Rect(inner_x, y, inner_w, px(60)), fs(14), theme.MUTED) + px(10)
        label_w = max(fonts.text_size(t("compare.position"), fs(14), "bold")[0], fonts.text_size(t("compare.depth"), fs(14), "bold")[0]) + px(16)
        draw_text(surface, t("compare.position"), (inner_x, y + px(17)), fs(14), theme.TEXT_SOFT, "bold", "midleft")
        bx = inner_x + label_w
        chip_h = px(34)
        for i, button in enumerate(self.position_buttons):
            w = fonts.text_size(label_text(button.label), fs(13), "bold")[0] + px(26)
            if bx + w > inner_x + inner_w and bx > inner_x + label_w:
                bx = inner_x + label_w
                y += chip_h + px(8)
            self._chip(button, pygame.Rect(bx, y, min(w, inner_w - label_w), chip_h), i == self.position_index)
            bx += w + px(8)
        y += chip_h + px(12)
        draw_text(surface, t("compare.depth"), (inner_x, y + px(17)), fs(14), theme.TEXT_SOFT, "bold", "midleft")
        bx = inner_x + label_w
        for d, button in enumerate(self.depth_buttons, start=1):
            self._chip(button, pygame.Rect(bx, y, px(42), chip_h), d == self.depth)
            bx += px(48)
        self.run_button.rect = pygame.Rect(bx + px(14), y - px(2), px(140), chip_h + px(4))
        self.run_button.enabled = self.request is None
        self.run_button.label = partial(t, "compare.running") if self.request is not None else partial(t, "compare.run")
        y += chip_h + px(20)

        result = self.result
        if self.error:
            draw_text(surface, t("compare.error", msg=self.error), (inner_x, y), fs(14), theme.RED, max_width=inner_w)
            y += px(30)
        elif result is None:
            draw_text(surface, t("compare.idle") if self.request is None else t("compare.busy"), (inner_x, y), fs(14), theme.MUTED, max_width=inner_w)
            y += px(30)
        else:
            y = self._draw_result(surface, result, inner_x, y, inner_w)
        for button in [*self.position_buttons, *self.depth_buttons, self.run_button]:
            button.draw(surface)
        self._compare_height = y + px(16) - top
        return y + px(16)

    def _draw_result(self, surface: pygame.Surface, result: CompareResult, x: int, y: int, w: int) -> int:
        key, depth = self.result_key
        draw_text(surface, t("compare.label", position=t(key), depth=depth), (x, y), fs(13), theme.MUTED, "bold", max_width=w)
        y += px(28)
        variants: list[CompareVariant | None] = [result.minimax, result.alpha_beta, result.alpha_beta_ordered]
        max_nodes = max(v.nodes for v in variants if v is not None)
        label_w = min(px(230), w // 3)
        stats_w = min(px(330), w // 3)
        bar_w = w - label_w - stats_w - px(16)
        for variant, name, color in zip(variants, ("minimax", "alphabeta", "alphabeta-ordered"), (theme.RED, theme.AMBER, theme.ACCENT)):
            draw_text(surface, t(f"variant.{name}"), (x, y + px(11)), fs(14), theme.TEXT, "bold", "midleft", max_width=label_w - px(8))
            if variant is None:
                text = t("compare.skipped", n=fmt_int(self.skipped_estimate))
                draw_text(surface, text, (x + label_w, y + px(11)), fs(13), theme.MUTED, "regular", "midleft", max_width=w - label_w)
                y += px(36)
                continue
            track = pygame.Rect(x + label_w, y + px(3), bar_w, px(16))
            gfx.rrect(surface, theme.SURFACE_2, track, track.height // 2)
            fill = track.copy()
            fill.width = max(track.height, int(bar_w * variant.nodes / max_nodes))
            gfx.rrect_gradient(surface, color, tuple(max(0, c - 40) for c in color), fill, fill.height // 2)
            best = uci_san(result.fen, variant.best_move) if variant.best_move else "—"
            stats = t("compare.stats", nodes=fmt_int(variant.nodes), secs=fmt_decimal(variant.time_ms / 1000, 2), score=format_score(variant.score), move=best)
            draw_text(surface, stats, (track.right + px(12), y + px(11)), fs(12), theme.TEXT_SOFT, "regular", "midleft", max_width=stats_w)
            y += px(36)
        same = all(v is None or v.score == result.alpha_beta.score for v in variants)
        summary = t("compare.same") if same else t("compare.diff")
        if result.minimax:
            saved = round(100 * (1 - result.alpha_beta.nodes / result.minimax.nodes))
            saved_ordered = round(100 * (1 - result.alpha_beta_ordered.nodes / result.minimax.nodes))
            summary += " " + t("compare.saved", a=saved, b=saved_ordered)
        else:
            saved = round(100 * (1 - result.alpha_beta_ordered.nodes / max(1, result.alpha_beta.nodes)))
            summary += " " + t("compare.saved_ordering", a=saved)
        h = wrapped_height(summary, w, fs(14))
        return y + px(6) + draw_wrapped(surface, summary, pygame.Rect(x, y + px(6), w, h), fs(14), theme.ACCENT if same else theme.RED)

    def _draw_demo(self, surface: pygame.Surface, x: int, y: int, width: int) -> int:
        top = y
        card(surface, pygame.Rect(x, top, width, self._demo_height), color=theme.SURFACE)
        inner_x = x + px(22)
        inner_w = width - px(44)
        y += px(20)
        seg_w = min(px(240), inner_w // 2)
        draw_text(surface, t("demo.title"), (inner_x, y), fs(19), theme.TEXT, "bold", max_width=inner_w - seg_w - px(12))
        self.demo_switch.rect = pygame.Rect(inner_x + inner_w - seg_w, y - px(2), seg_w, px(34))
        self.demo_switch.draw(surface)
        y += px(40)
        y += draw_wrapped(surface, t("demo.explain"), pygame.Rect(inner_x, y, inner_w, px(80)), fs(13), theme.MUTED) + px(8)

        steps = self.demo.steps[: self.demo_step]
        known: dict[str, float] = {}
        entered: set[str] = set()
        cut: set[str] = set()
        for step in steps:
            entered.add(step.node)
            if step.value is not None and step.key != "demo.cut":
                known[step.node] = step.value
            cut.update(step.cut)

        tree_h = px(240)
        area = pygame.Rect(inner_x + px(50), y, inner_w - px(50), tree_h)
        positions: dict[str, tuple[int, int]] = {}
        level_h = px(66)

        def place(node: DemoNode, depth: int, left: float, right: float) -> None:
            positions[node.id] = (round((left + right) / 2), area.y + px(22) + depth * level_h)
            if node.children:
                span = (right - left) / len(node.children)
                for i, child in enumerate(node.children):
                    place(child, depth + 1, left + i * span, left + (i + 1) * span)

        place(self.tree, 0, area.x, area.right)
        r = px(17)

        def draw_node(node: DemoNode, depth: int) -> None:
            px_, py_ = positions[node.id]
            for child in node.children:
                cx, cy = positions[child.id]
                pruned = child.id in cut
                color = (*theme.DIM[:3], 160) if pruned else (theme.ACCENT if child.id in entered else theme.BORDER)
                gfx.thick_line(surface, color, (px_, py_ + r), (cx, cy - r), max(1.5, px(2)))
                if pruned:
                    mx, my = (px_ + cx) / 2, (py_ + cy) / 2
                    d = px(7)
                    gfx.thick_line(surface, theme.RED, (mx - d, my - d), (mx + d, my + d), max(2.0, px(3)))
                    gfx.thick_line(surface, theme.RED, (mx - d, my + d), (mx + d, my - d), max(2.0, px(3)))
                draw_node(child, depth + 1)
            pruned = node.id in cut
            active = bool(steps) and steps[-1].node == node.id
            fill = (40, 44, 60) if pruned else (theme.ACCENT_DARK if node.id in known else theme.SURFACE_2)
            border = theme.AMBER if active else ((80, 86, 108) if pruned else theme.TEXT_SOFT)
            if active:
                gfx.ring_glow(surface, theme.AMBER, (px_, py_), r * 2.4, 120)
            if depth % 2 == 0:
                gfx.circle(surface, fill, (px_, py_), r)
                gfx.circle(surface, border, (px_, py_), r, max(1, px(2)))
            else:
                rect = pygame.Rect(px_ - r, py_ - r, 2 * r, 2 * r)
                gfx.rrect(surface, fill, rect, px(6))
                gfx.rrect(surface, border, rect, px(6), max(1, px(2)))
            if node.value is not None:
                label, color = str(node.value), theme.DIM if pruned else theme.TEXT
            elif node.id in known:
                label, color = str(int(known[node.id])), theme.TEXT
            else:
                label, color = "?", theme.DIM
            draw_text(surface, label, (px_, py_), fs(14), color, "bold", "center")

        draw_node(self.tree, 0)
        for depth, label in enumerate(("MAX", "MIN", "MAX", t("demo.leaves"))):
            draw_text(surface, label, (inner_x, area.y + px(22) + depth * level_h), fs(11), theme.DIM, "bold", "midleft", max_width=px(48))
        y += tree_h + px(8)

        total = len(self.demo.steps)
        text = t("demo.step", i=self.demo_step, n=total, text=steps[-1].text()) if steps else t("demo.start", n=total)
        if self.demo_step >= total:
            visited = len(self.demo.visited)
            all_nodes = sum(1 for _ in _walk(self.tree))
            if self.demo.pruned:
                text += "  " + t("demo.result_pruned", value=self.demo.value, visited=visited, total=all_nodes, pruned=len(self.demo.pruned))
            else:
                text += "  " + t("demo.result", value=self.demo.value, visited=visited, total=all_nodes)
        buttons_w = px(96) + px(44) * 2 + px(110) + px(24)
        text_w = inner_w - buttons_w - px(12)
        h = max(px(44), wrapped_height(text, text_w, fs(13), "mono"))
        draw_wrapped(surface, text, pygame.Rect(inner_x, y, text_w, h), fs(13), theme.TEXT_SOFT, "mono")
        bx = inner_x + inner_w - buttons_w + px(12)
        self.demo_reset.rect = pygame.Rect(bx, y, px(96), px(38))
        self.demo_prev.rect = pygame.Rect(self.demo_reset.rect.right + px(6), y, px(44), px(38))
        self.demo_next.rect = pygame.Rect(self.demo_prev.rect.right + px(6), y, px(44), px(38))
        self.demo_all.rect = pygame.Rect(self.demo_next.rect.right + px(6), y, px(110), px(38))
        for button in (self.demo_reset, self.demo_prev, self.demo_next, self.demo_all):
            button.draw(surface)
        y += h + px(18)
        self._demo_height = y - top
        return y
