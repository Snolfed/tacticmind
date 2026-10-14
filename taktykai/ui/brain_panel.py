"""Panel „Mózg AI”: co AI myśli.

Zawiera liczniki na żywo, 3 najlepsze ruchy kandydujące (z wariantami SAN),
„strumień myśli” i mini drzewo przeszukiwania. Tryby widoczności:
 - Ukryty: tylko statystyki i informacja, że AI liczy — ruchy i ocena ukryte,
 - Podpowiedź: podświetla figurę, którą trzeba ruszyć (zmniejsza nagrodę),
 - Pełny: wszystko widoczne, a po zadaniu AI tłumaczy rozwiązanie.

Wszystkie wymiary są skalowane (``px``/``fs``), a teksty dopasowują się do miejsca.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial

import chess
import pygame

from ..brain.notation import format_line, uci_san
from ..brain.thoughts import Thought
from ..engine.types import EngineScore, SearchInfo, SearchProgress, TreeNode, format_score
from ..i18n import fmt_compact, fmt_decimal, t
from . import fonts, gfx, theme
from .anim import approach, ease_out_cubic, now
from .scale import fs, px
from .widgets import ScrollArea, Segmented, card, draw_text, draw_wrapped

MODES = ("hidden", "hint", "full")
TABS = ("thoughts", "tree")


@dataclass
class BrainState:
    """To, co panel ma pokazać (ustawia ekran gry)."""

    mode: str = "hidden"
    running: bool = False
    fen: str = ""
    info: SearchInfo | None = None
    progress: SearchProgress | None = None
    thoughts: list[Thought] = field(default_factory=list)
    explanation: list[str] = field(default_factory=list)
    status_note: str = ""

    @property
    def reveal(self) -> bool:
        return self.mode == "full"


_THOUGHT_COLORS: dict[str, tuple[int, ...]] = {
    "change": theme.ORANGE,
    "mate": theme.ROSE,
    "prune": theme.BLUE,
    "tt": theme.VIOLET,
    "swing": theme.AMBER,
    "alt": theme.MUTED,
    "done": theme.DIM,
    "depth": theme.ACCENT,
    "info": theme.DIM,
}


class BrainPanel:
    def __init__(self, on_mode: Callable[[str], None], on_preview: Callable[[int], None]) -> None:
        self.rect = pygame.Rect(0, 0, 420, 600)
        modes: list[tuple[str, str | Callable[[], str]]] = [(m, partial(t, f"brain.mode.{m}")) for m in MODES]
        self.segmented = Segmented(modes, "hidden", on_mode, size=12, accent=theme.VIOLET)
        self.on_preview = on_preview
        self.tab = "thoughts"
        self.scroll = ScrollArea()
        self.tree_scroll = ScrollArea(stick_to_bottom=False)
        self.expanded: set[str] = set()
        self.candidate_rects: list[pygame.Rect] = []
        self.tab_rects: list[tuple[str, pygame.Rect]] = []
        self.tree_rows: list[tuple[str, pygame.Rect]] = []
        self.hover_candidate = -1
        self._tab_x = -1.0
        self._seen: list[float] = []  # kiedy pojawiła się każda myśl (do animacji)
        self._last = now()

    # ------------------------------------------------------------ zdarzenia
    def handle(self, event: pygame.event.Event, state: BrainState, mouse_pos: tuple[int, int] | None = None) -> bool:
        if self.segmented.handle(event):
            return True
        if event.type == pygame.MOUSEMOTION:
            self.hover_candidate = next((i for i, r in enumerate(self.candidate_rects) if r.collidepoint(event.pos)), -1)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for tab, rect in self.tab_rects:
                if rect.collidepoint(event.pos):
                    self.tab = tab
                    return True
            if state.reveal:
                for i, rect in enumerate(self.candidate_rects):
                    if rect.collidepoint(event.pos):
                        self.on_preview(i)
                        return True
                if self.tab == "tree":
                    for move, rect in self.tree_rows:
                        if rect.collidepoint(event.pos):
                            self.expanded ^= {move}
                            return True
        area = self.scroll if self.tab == "thoughts" else self.tree_scroll
        return area.handle(event, mouse_pos)

    def wants_wheel(self, pos: tuple[int, int]) -> bool:
        """Czy kółko myszy nad tym miejscem ma przewijać zawartość panelu (a nie całą stronę)?"""
        area = self.scroll if self.tab == "thoughts" else self.tree_scroll
        return area.rect.collidepoint(pos) and area.content_height > area.rect.height

    def reset(self) -> None:
        self.scroll = ScrollArea()
        self.tree_scroll = ScrollArea(stick_to_bottom=False)
        self.expanded.clear()
        self._seen.clear()

    # ------------------------------------------------------------ rysowanie
    def draw(self, surface: pygame.Surface, state: BrainState) -> None:
        clock = now()
        dt = min(0.1, clock - self._last)
        self._last = clock
        self.segmented.value = state.mode
        r = self.rect
        card(surface, r)
        pad = px(16)
        x, y, w = r.x + pad, r.y + px(14), r.width - 2 * pad

        # Nagłówek: ikona „sieci”, tytuł, status i przełącznik trybu
        self._draw_brain_icon(surface, (x + px(11), y + px(15)), px(11), state.running, clock)
        title = draw_text(surface, t("brain.title"), (x + px(28), y + px(15)), fs(19), theme.TEXT, "bold", "midleft")
        seg_w = min(px(270), max(px(150), w - (title.right - x) - px(90)))
        self.segmented.rect = pygame.Rect(r.right - pad - seg_w, y, seg_w, px(30))
        status_x = title.right + px(10)
        status_w = self.segmented.rect.x - status_x - px(8)
        if status_w > px(30):
            if state.running:
                for i in range(3):
                    a = 0.3 + 0.7 * max(0.0, math.sin(clock * 6 - i * 0.7))
                    gfx.circle(surface, (*theme.VIOLET[:3], int(255 * a)), (status_x + px(4) + i * px(10), y + px(16)), px(3))
                draw_text(surface, t("brain.thinking"), (status_x + px(34), y + px(16)), fs(12), theme.MUTED, "regular", "midleft", max_width=status_w - px(34))
            else:
                status = t("brain.ready") if state.info else t("brain.waiting")
                draw_text(surface, status, (status_x, y + px(16)), fs(12), theme.DIM, "regular", "midleft", max_width=status_w)
        self.segmented.draw(surface)
        y += px(44)

        y = self._draw_counters(surface, state, x, y, w)
        y = self._draw_candidates(surface, state, x, y, w)

        # Zakładki z przesuwającym się podkreśleniem
        self.tab_rects = []
        tx = x
        tab_h = px(30)
        for tab in TABS:
            label = t(f"brain.tab.{tab}")
            tw = min(fonts.text_size(label, fs(13), "bold")[0] + px(18), w // 2)
            rect = pygame.Rect(tx, y, tw, tab_h)
            active = tab == self.tab
            draw_text(surface, label, rect.center, fs(13), theme.TEXT if active else theme.MUTED, "bold", "center", max_width=tw - px(6))
            self.tab_rects.append((tab, rect))
            tx += tw + px(6)
        active_rect = next(rect for tab, rect in self.tab_rects if tab == self.tab)
        self._tab_x = active_rect.x if self._tab_x < 0 else approach(self._tab_x, active_rect.x, dt, 16)
        underline = pygame.Rect(round(self._tab_x) + px(6), y + tab_h - px(3), active_rect.width - px(12), px(3))
        gfx.rrect(surface, theme.VIOLET, underline, underline.height // 2)
        pygame.draw.line(surface, theme.BORDER_SOFT, (x, y + tab_h), (x + w, y + tab_h))
        y += tab_h + px(10)
        content = pygame.Rect(x, y, w, r.bottom - y - px(12))
        if content.height < px(30):
            return
        if self.tab == "thoughts":
            self._draw_thoughts(surface, state, content, clock)
        else:
            self._draw_tree(surface, state, content)

    def _draw_brain_icon(self, surface: pygame.Surface, center: tuple[int, int], size: int, running: bool, clock: float) -> None:
        """Mała „sieć neuronowa”: trzy węzły połączone liniami; pulsuje, gdy AI liczy."""
        cx, cy = center
        nodes = [(cx - size * 0.7, cy + size * 0.45), (cx + size * 0.7, cy + size * 0.45), (cx, cy - size * 0.7)]
        for i, a in enumerate(nodes):
            for b in nodes[i + 1 :]:
                gfx.thick_line(surface, (*theme.VIOLET[:3], 140), a, b, max(1.5, px(2)))
        for i, node in enumerate(nodes):
            pulse = 0.5 + 0.5 * math.sin(clock * 6 - i * 2.1) if running else 0.6
            gfx.circle(surface, (*theme.VIOLET[:3], int(150 + 105 * pulse)), node, size * 0.32)

    def _draw_counters(self, surface: pygame.Surface, state: BrainState, x: int, y: int, w: int) -> int:
        info, progress = state.info, state.progress
        live = progress is not None and state.running
        source: SearchInfo | SearchProgress | None = progress if live else info
        depth = (progress.depth if live and progress else (info.depth if info else 0))
        nodes = source.nodes if source else 0
        pruned = f" ({round(info.pruned_percent)}%)" if info and info.pruned_percent else ""
        tiles = [
            (t("brain.depth"), (f"{depth}" + (f" / {info.seldepth}" if info and not state.running else "")) if depth else "—"),
            (t("brain.nodes"), fmt_compact(nodes)),
            (t("brain.nps"), fmt_compact(source.nps if source else 0)),
            (t("brain.cutoffs"), fmt_compact(source.cutoffs if source else 0) + pruned),
            (t("brain.tt"), fmt_compact(source.tt_hits if source else 0)),
            (t("brain.time"), f"{fmt_decimal((source.time_ms if source else 0) / 1000)} s"),
        ]
        cols = 3
        gap = px(6)
        tile_w = (w - (cols - 1) * gap) // cols
        tile_h = px(46)
        for i, (label, value) in enumerate(tiles):
            tx = x + (i % cols) * (tile_w + gap)
            ty = y + (i // cols) * (tile_h + gap)
            rect = pygame.Rect(tx, ty, tile_w, tile_h)
            gfx.rrect(surface, theme.SURFACE_2, rect, px(10))
            draw_text(surface, label, (tx + px(9), ty + px(5)), fs(11), theme.MUTED, "regular", max_width=tile_w - px(14))
            draw_text(surface, value, (tx + px(9), ty + px(20)), fs(15), theme.TEXT, "mono", max_width=tile_w - px(14))
        return y + 2 * (tile_h + gap) + px(6)

    def _draw_candidates(self, surface: pygame.Surface, state: BrainState, x: int, y: int, w: int) -> int:
        draw_text(surface, t("brain.best_moves"), (x, y), fs(12), theme.MUTED, "bold", max_width=w)
        y += px(22)
        self.candidate_rects = []
        lines = state.info.multi_pv if state.info else []
        row_h = px(34)
        for i in range(3):
            rect = pygame.Rect(x, y + i * (row_h + px(5)), w, row_h)
            self.candidate_rects.append(rect)
            hovered = i == self.hover_candidate and state.reveal and i < len(lines)
            gfx.rrect(surface, theme.SURFACE_3 if hovered else theme.SURFACE_2, rect, px(10))
            pill = pygame.Rect(rect.x + px(4), rect.y + px(4), px(64), row_h - px(8))
            text_x = pill.right + px(10)
            text_w = rect.right - text_x - px(10)
            if not state.reveal:
                gfx.rrect(surface, (*theme.VIOLET[:3], 40), pill, px(8))
                for k in range(3):
                    gfx.circle(surface, (*theme.VIOLET[:3], 160), (pill.centerx - px(10) + k * px(10), pill.centery), px(2))
                draw_text(surface, t("brain.hidden_line"), (text_x, rect.centery), fs(12), theme.DIM, "regular", "midleft", max_width=text_w)
                continue
            if i >= len(lines):
                draw_text(surface, "—", (text_x, rect.centery), fs(13), theme.DIM, "regular", "midleft")
                continue
            line = lines[i]
            self._score_pill(surface, pill, line.score)
            text = format_line(state.info.fen if state.info else state.fen, line.pv, 8)
            while text and fonts.text_size(text, fs(14))[0] > text_w and " " in text:
                text = text.rsplit(" ", 1)[0]
            color = theme.TEXT if i == 0 else theme.TEXT_SOFT
            draw_text(surface, text, (text_x, rect.centery), fs(14), color, "regular", "midleft", max_width=text_w)
        return y + 3 * (row_h + px(5)) + px(8)

    def _score_pill(self, surface: pygame.Surface, rect: pygame.Rect, score: EngineScore) -> None:
        white = score.value >= 0
        gfx.rrect(surface, (236, 239, 246) if white else (14, 16, 26), rect, px(8))
        if not white:
            gfx.rrect(surface, theme.BORDER, rect, px(8), max(1, px(1)))
        draw_text(surface, format_score(score), rect.center, fs(13), (24, 27, 38) if white else (236, 239, 246), "bold", "center", max_width=rect.width - px(6))

    def _draw_thoughts(self, surface: pygame.Surface, state: BrainState, area: pygame.Rect, clock: float) -> None:
        self.scroll.rect = area
        visible = state.thoughts if state.reveal else [th for th in state.thoughts if th.kind in ("prune", "tt", "done")]
        if len(self._seen) > len(visible):
            self._seen = self._seen[: len(visible)]
        while len(self._seen) < len(visible):
            self._seen.append(clock)
        blocks: list[tuple[str, str, tuple[int, ...], float]] = []
        if state.reveal and state.explanation:
            blocks.append(("header", t("brain.explains"), theme.ACCENT, 0.0))
            blocks.extend(("explain", line, theme.TEXT, 0.0) for line in state.explanation)
            blocks.append(("header", t("brain.tab.thoughts"), theme.MUTED, 0.0))
        if not state.reveal:
            blocks.append(("note", state.status_note or t("brain.analyzing"), theme.MUTED, 0.0))
        blocks.extend(("thought", th.text, _THOUGHT_COLORS.get(th.kind, theme.MUTED), self._seen[i]) for i, th in enumerate(visible))

        size = fs(13)
        gap = px(3)
        text_w = area.width - px(22)
        heights = []
        for kind, text, _, _ in blocks:
            style = "bold" if kind == "header" else "regular"
            n = len(fonts.wrap(text, size, text_w, style))
            heights.append(n * (fonts.line_height(size, style) + gap) + px(8))
        self.scroll.content_height = sum(heights)
        self.scroll.follow()

        clip = surface.get_clip()
        surface.set_clip(area)
        yy = area.y - int(self.scroll.offset)
        for (kind, text, color, born), h in zip(blocks, heights):
            if yy + h >= area.y and yy <= area.bottom:
                appear = ease_out_cubic((clock - born) / 0.4) if kind == "thought" else 1.0
                slide = round((1 - appear) * px(10))
                if kind == "header":
                    draw_text(surface, text, (area.x, yy + px(4)), size, color, "bold", max_width=area.width - px(8))
                else:
                    style = "regular"
                    text_color: tuple[int, ...] = theme.TEXT_SOFT
                    if kind == "note":
                        text_color = theme.MUTED
                    elif kind == "explain":
                        text_color = theme.TEXT
                    elif color == theme.ORANGE:
                        text_color, style = (255, 214, 170), "bold"
                    if kind in ("thought", "explain"):
                        bar = (*color[:3], int(255 * appear))
                        gfx.rrect(surface, bar, pygame.Rect(area.x, yy + px(3), px(3), h - px(10)), px(2))
                    alpha_color = (*text_color[:3], int(255 * appear)) if appear < 0.99 else text_color
                    draw_wrapped(surface, text, pygame.Rect(area.x + px(12) + slide, yy, text_w, h), size, alpha_color, style, gap)
            yy += h
        surface.set_clip(clip)
        self.scroll.draw_scrollbar(surface)

    def _draw_tree(self, surface: pygame.Surface, state: BrainState, area: pygame.Rect) -> None:
        self.tree_scroll.rect = area
        self.tree_rows = []
        if not state.reveal:
            draw_wrapped(surface, t("brain.tree.hidden"), area, fs(13), theme.MUTED)
            return
        info = state.info
        if info is None or not info.tree:
            draw_wrapped(surface, t("brain.tree.nodata"), area, fs(13), theme.MUTED)
            return
        fen = info.fen
        rows: list[tuple[str, int, TreeNode, str]] = []
        roots = info.tree[:8]
        if roots and not self.expanded.intersection(n.move for n in roots):
            self.expanded.add(roots[0].move)
            # Rozwiń też pierwszy ruch, w którym alfa-beta coś odcięła — żeby było widać cięcie.
            with_cut = next((n for n in roots[1:] if any(c.pruned for c in n.children)), None)
            if with_cut is not None:
                self.expanded.add(with_cut.move)
        for node in roots:
            rows.append(("root", 0, node, fen))
            if node.move in self.expanded:
                board = chess.Board(fen)
                board.push_uci(node.move)
                child_fen = board.fen()
                sign = 1 if board.turn == chess.WHITE else -1
                children = sorted(node.children, key=lambda c: (c.pruned, -(c.score.value if c.score else 0) * sign))
                rows.extend(("child", 1, child, child_fen) for child in children[:12])
                if len(children) > 12:
                    rows.append(("more", 1, TreeNode(str(len(children) - 12), None), child_fen))
        row_h = px(26)
        legend_lines = fonts.wrap(t("brain.tree.legend"), fs(11), area.width - px(10))
        legend_h = len(legend_lines) * (fonts.line_height(fs(11)) + px(2)) + px(8)
        self.tree_scroll.content_height = legend_h + len(rows) * row_h
        self.tree_scroll.follow()
        clip = surface.get_clip()
        surface.set_clip(area)
        yy = area.y - int(self.tree_scroll.offset)
        for line in legend_lines:
            draw_text(surface, line, (area.x, yy), fs(11), theme.MUTED)
            yy += fonts.line_height(fs(11)) + px(2)
        yy += px(8)
        indent_w = px(24)
        for kind, indent, node, parent_fen in rows:
            rect = pygame.Rect(area.x + indent * indent_w, yy, area.width - indent * indent_w - px(10), row_h - px(3))
            if kind == "more":
                draw_text(surface, t("brain.tree.more", n=node.move), (rect.x + px(18), rect.centery), fs(12), theme.DIM, "regular", "midleft")
                yy += row_h
                continue
            san = uci_san(parent_fen, node.move)
            if kind == "root":
                self.tree_rows.append((node.move, rect))
                gfx.rrect(surface, theme.SURFACE_2, rect, px(7))
                cx, cy = rect.x + px(12), rect.centery
                if node.move in self.expanded:
                    gfx.polygon(surface, theme.MUTED, [(cx - px(5), cy - px(3)), (cx + px(5), cy - px(3)), (cx, cy + px(4))])
                else:
                    gfx.polygon(surface, theme.MUTED, [(cx - px(3), cy - px(5)), (cx - px(3), cy + px(5)), (cx + px(4), cy)])
            else:
                pygame.draw.line(surface, theme.BORDER, (rect.x - px(12), yy - px(2)), (rect.x - px(12), yy + row_h // 2), 1)
                pygame.draw.line(surface, theme.BORDER, (rect.x - px(12), yy + row_h // 2), (rect.x - px(2), yy + row_h // 2), 1)
            color = theme.DIM if node.pruned else theme.TEXT
            label_x = rect.x + px(24) if kind == "root" else rect.x + px(2)
            label = draw_text(surface, san, (label_x, rect.centery), fs(13), color, "bold" if kind == "root" else "regular", "midleft")
            value_w = rect.right - label.right - px(14)
            if node.pruned:
                pygame.draw.line(surface, theme.DIM, (label.x - 2, label.centery), (label.right + 2, label.centery), max(1, px(2)))
                draw_text(surface, t("brain.tree.pruned"), (rect.right - px(4), rect.centery), fs(11), theme.DIM, "regular", "midright", max_width=value_w)
            else:
                prefix = {"upper": "≤ ", "lower": "≥ "}.get(node.bound, "")
                value = prefix + format_score(node.score) if node.score else "—"
                if node.tt_cut:
                    value += "  " + t("brain.tree.tt")
                score_color = theme.TEXT_SOFT if node.bound == "exact" else theme.MUTED
                draw_text(surface, value, (rect.right - px(4), rect.centery), fs(12), score_color, "mono", "midright", max_width=value_w)
            yy += row_h
        surface.set_clip(clip)
        self.tree_scroll.draw_scrollbar(surface)
