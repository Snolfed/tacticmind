"""Panel „Mózg AI” — dane do narysowania w przeglądarce (odpowiednik ``ui/brain_panel.py``).

Tryby widoczności są te same co w pygame:
 - Ukryty: tylko liczniki i informacja, że AI liczy — ruchy i ocena ukryte,
 - Podpowiedź: podświetla figurę, którą trzeba ruszyć (zmniejsza nagrodę),
 - Pełny: wszystko widoczne, a po zadaniu AI tłumaczy rozwiązanie.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import chess

from ..brain.notation import format_line, uci_san
from ..brain.thoughts import Thought
from ..engine.types import EngineScore, SearchInfo, SearchProgress, TreeNode, format_score
from ..i18n import fmt_compact, fmt_decimal, get_language, t

#: Myśli widoczne w trybie ukrytym (nie zdradzają ruchów ani oceny).
HIDDEN_KINDS = ("prune", "tt", "done")


@dataclass
class BrainState:
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


def score_json(score: EngineScore | None) -> dict[str, Any] | None:
    if score is None:
        return None
    return {"cp": score.cp, "mate": score.mate, "value": score.value, "label": format_score(score)}


def counters(state: BrainState) -> list[dict[str, str]]:
    """Liczniki na żywo: głębokość, węzły, węzły/s, cięcia, trafienia w TT, czas."""
    info, progress = state.info, state.progress
    live = progress is not None and state.running
    source: SearchInfo | SearchProgress | None = progress if live else info
    depth = progress.depth if live and progress else (info.depth if info else 0)
    nodes = source.nodes if source else 0
    pruned = f" ({round(info.pruned_percent)}%)" if info and info.pruned_percent else ""
    depth_text = (f"{depth}" + (f" / {info.seldepth}" if info and not state.running else "")) if depth else "—"
    return [
        {"label": t("brain.depth"), "value": depth_text},
        {"label": t("brain.nodes"), "value": fmt_compact(nodes)},
        {"label": t("brain.nps"), "value": fmt_compact(source.nps if source else 0)},
        {"label": t("brain.cutoffs"), "value": fmt_compact(source.cutoffs if source else 0) + pruned},
        {"label": t("brain.tt"), "value": fmt_compact(source.tt_hits if source else 0)},
        {"label": t("brain.time"), "value": f"{fmt_decimal((source.time_ms if source else 0) / 1000)} s"},
    ]


def candidates(state: BrainState) -> list[dict[str, Any]] | None:
    """3 najlepsze ruchy kandydujące z oceną i wariantem SAN (None = ukryte)."""
    if not state.reveal:
        return None
    info = state.info
    if info is None:
        return []
    return [
        {"score": format_score(line.score), "white": line.score.value >= 0, "line": format_line(info.fen, line.pv, 8)}
        for line in info.multi_pv[:3]
    ]


_tree_cache: dict[tuple[int, str], list[dict[str, Any]]] = {}


def tree(info: SearchInfo | None) -> list[dict[str, Any]] | None:
    """Mini-drzewo przeszukiwania: pierwsze 8 ruchów i ich odpowiedzi (z SAN i oceną)."""
    if info is None or not info.tree:
        return None
    key = (id(info), get_language())
    cached = _tree_cache.get(key)
    if cached is not None:
        return cached
    roots = []
    for node in info.tree[:8]:
        board = chess.Board(info.fen)
        board.push_uci(node.move)
        child_fen = board.fen()
        sign = 1 if board.turn == chess.WHITE else -1
        children = sorted(node.children, key=lambda c: (c.pruned, -(c.score.value if c.score else 0) * sign))
        roots.append({**_node(node, info.fen), "children": [_node(child, child_fen) for child in children[:12]], "more": max(0, len(children) - 12)})
    if len(_tree_cache) > 64:
        _tree_cache.clear()
    _tree_cache[key] = roots
    return roots


def _node(node: TreeNode, parent_fen: str) -> dict[str, Any]:
    prefix = {"upper": "≤ ", "lower": "≥ "}.get(node.bound, "")
    value = prefix + format_score(node.score) if node.score else "—"
    return {
        "move": node.move,
        "san": uci_san(parent_fen, node.move),
        "value": value,
        "exact": node.bound == "exact",
        "pruned": node.pruned,
        "tt": node.tt_cut,
    }


def snapshot(state: BrainState) -> dict[str, Any]:
    reveal = state.reveal
    visible = state.thoughts if reveal else [th for th in state.thoughts if th.kind in HIDDEN_KINDS]
    return {
        "mode": state.mode,
        "running": state.running,
        "hasInfo": state.info is not None,
        "statusNote": state.status_note,
        "counters": counters(state),
        "candidates": candidates(state),
        "thoughts": [{"text": th.text, "kind": th.kind} for th in visible],
        "explanation": list(state.explanation) if reveal else [],
        "tree": tree(state.info) if reveal else None,
    }
