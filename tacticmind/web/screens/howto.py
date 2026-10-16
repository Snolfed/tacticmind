"""Strona „Jak działa AI?” — porównanie minimaksu z alfa-betą na prawdziwym silniku
i demonstracja cięć krok po kroku na małym drzewie."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import chess

from ...brain.demo import DemoNode, DemoResult, alphabeta_demo, build_demo_tree, minimax_demo
from ...brain.notation import uci_san
from ...engine.process import CompareEvent, EngineEvent, ErrorEvent
from ...engine.types import CompareResult, CompareVariant, format_score
from ...i18n import fmt_decimal, fmt_int, t
from .base import WebScreen

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


def _tree_json(node: DemoNode) -> dict[str, Any]:
    return {"id": node.id, "value": node.value, "children": [_tree_json(child) for child in node.children]}


class HowToScreen(WebScreen):
    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self.position_index = 0
        self.depth = 3
        self.request: int | None = None
        self.result: CompareResult | None = None
        self.result_key: tuple[str, int] = ("", 0)
        self.skipped_estimate = 0
        self.error = ""
        self.tree = build_demo_tree()
        self.demos: dict[str, DemoResult] = {"minimax": minimax_demo(self.tree), "alphabeta": alphabeta_demo(self.tree)}

    def _positions(self) -> list[tuple[str, str]]:
        positions = list(POSITIONS)
        play = self.app.screens.get("play")
        session = getattr(play, "session", None)
        if session is not None and session.status.value != "intro":
            positions.append(("pos.current", session.puzzle.start_fen))
        return positions

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

    def action(self, name: str, data: dict[str, Any]) -> None:
        if name == "position":
            index = data.get("index")
            if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(self._positions()):
                self.position_index = index
        elif name == "depth":
            depth = data.get("depth")
            if isinstance(depth, int) and not isinstance(depth, bool) and 1 <= depth <= 4:
                self.depth = depth
        elif name == "run" and self.request is None:
            self._run()

    def on_engine(self, event: EngineEvent) -> None:
        if self.request is None or event.id != self.request:
            return
        if isinstance(event, CompareEvent):
            self.result = event.result
            self.request = None
        elif isinstance(event, ErrorEvent):
            self.error = event.message
            self.request = None

    # ------------------------------------------------------------ migawka
    def _result(self, result: CompareResult) -> dict[str, Any]:
        key, depth = self.result_key
        variants: list[CompareVariant | None] = [result.minimax, result.alpha_beta, result.alpha_beta_ordered]
        max_nodes = max(v.nodes for v in variants if v is not None)
        rows: list[dict[str, Any]] = []
        for variant, name in zip(variants, ("minimax", "alphabeta", "alphabeta-ordered")):
            if variant is None:
                rows.append({"name": t(f"variant.{name}"), "skipped": t("compare.skipped", n=fmt_int(self.skipped_estimate))})
                continue
            best = uci_san(result.fen, variant.best_move) if variant.best_move else "—"
            stats = t("compare.stats", nodes=fmt_int(variant.nodes), secs=fmt_decimal(variant.time_ms / 1000, 2), score=format_score(variant.score), move=best)
            rows.append({"name": t(f"variant.{name}"), "share": variant.nodes / max_nodes, "stats": stats})
        same = all(v is None or v.score == result.alpha_beta.score for v in variants)
        summary = t("compare.same") if same else t("compare.diff")
        if result.minimax:
            saved = round(100 * (1 - result.alpha_beta.nodes / result.minimax.nodes))
            saved_ordered = round(100 * (1 - result.alpha_beta_ordered.nodes / result.minimax.nodes))
            summary += " " + t("compare.saved", a=saved, b=saved_ordered)
        else:
            saved = round(100 * (1 - result.alpha_beta_ordered.nodes / max(1, result.alpha_beta.nodes)))
            summary += " " + t("compare.saved_ordering", a=saved)
        return {"label": t("compare.label", position=t(key), depth=depth), "rows": rows, "summary": summary, "same": same}

    def _demo(self, demo: DemoResult) -> dict[str, Any]:
        total_nodes = sum(1 for _ in _walk(self.tree))
        visited = len(demo.visited)
        if demo.pruned:
            result = t("demo.result_pruned", value=demo.value, visited=visited, total=total_nodes, pruned=len(demo.pruned))
        else:
            result = t("demo.result", value=demo.value, visited=visited, total=total_nodes)
        steps = [
            {"node": s.node, "text": s.text(), "value": s.value if s.key != "demo.cut" else None, "cut": list(s.cut)}
            for s in demo.steps
        ]
        return {"steps": steps, "result": result}

    def snapshot(self) -> dict[str, Any]:
        positions = self._positions()
        self.position_index = min(self.position_index, len(positions) - 1)
        if self.error:
            status = t("compare.error", msg=self.error)
        elif self.result is None:
            status = t("compare.idle") if self.request is None else t("compare.busy")
        else:
            status = ""
        return {
            "positions": [t(key) for key, _ in positions],
            "position": self.position_index,
            "depth": self.depth,
            "running": self.request is not None,
            "status": status,
            "error": bool(self.error),
            "result": self._result(self.result) if self.result is not None else None,
            "tree": _tree_json(self.tree),
            "demos": {name: self._demo(demo) for name, demo in self.demos.items()},
            "sections": SECTIONS,
        }
