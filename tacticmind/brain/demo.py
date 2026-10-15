"""Mała demonstracja minimaksu i alfa-bety na abstrakcyjnym drzewie (strona „Jak działa AI?”).

Drzewo ma 3 poziomy: korzeń MAX, węzły MIN, węzły MAX i liście z ocenami.
Funkcje zwracają kolejne kroki algorytmu, żeby w interfejsie można było
przechodzić je strzałką „Krok ▶” i zobaczyć, kiedy i dlaczego następuje cięcie.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..i18n import t, tn


@dataclass
class DemoNode:
    id: str
    value: int | None = None  # tylko liście mają wartość z góry
    children: list[DemoNode] = field(default_factory=list)


@dataclass(frozen=True)
class DemoStep:
    node: str
    #: Klucz tłumaczenia opisu kroku i jego parametry (tekst w bieżącym języku: ``text()``).
    key: str
    params: tuple[tuple[str, object], ...]
    alpha: float
    beta: float
    value: float | None
    #: Węzły odcięte w tym kroku (tylko dla kroku z cięciem).
    cut: tuple[str, ...] = ()

    def text(self) -> str:
        params = dict(self.params)
        if self.key == "demo.cut":
            # Zdanie z cięciem: powód (MIN/MAX) + liczba pominiętych gałęzi w odpowiedniej formie.
            reason = t(str(params["reason"]), a=params["a"], b=params["b"])
            return tn("demo.cut", len(self.cut_roots), reason=reason)
        return t(self.key, **params)

    @property
    def cut_roots(self) -> tuple[str, ...]:
        """Korzenie odciętych poddrzew (identyfikatory o najkrótszej długości wśród odciętych)."""
        if not self.cut:
            return ()
        shortest = min(len(node) for node in self.cut)
        return tuple(node for node in self.cut if len(node) == shortest)


@dataclass
class DemoResult:
    value: int
    visited: list[str]
    pruned: set[str]
    values: dict[str, int]
    steps: list[DemoStep]


def build_demo_tree() -> DemoNode:
    """Drzewo przykładowe, w którym alfa-beta odcina dwie gałęzie."""
    leaves = [[[3, 5], [6, 9]], [[1, 2], [0, -1]], [[7, 4], [8, 6]]]
    root = DemoNode("R")
    for i, min_children in enumerate(leaves):
        min_node = DemoNode(f"R{i}")
        for j, leaf_values in enumerate(min_children):
            max_node = DemoNode(f"R{i}{j}")
            for k, v in enumerate(leaf_values):
                max_node.children.append(DemoNode(f"R{i}{j}{k}", v))
            min_node.children.append(max_node)
        root.children.append(min_node)
    return root


def _all_ids(node: DemoNode) -> list[str]:
    ids = [node.id]
    for child in node.children:
        ids.extend(_all_ids(child))
    return ids


def _fmt(x: float) -> str:
    return "−∞" if x == float("-inf") else "+∞" if x == float("inf") else str(int(x))


def minimax_demo(root: DemoNode) -> DemoResult:
    visited: list[str] = []
    values: dict[str, int] = {}
    steps: list[DemoStep] = []
    inf = float("inf")

    def visit(node: DemoNode, maximizing: bool) -> int:
        visited.append(node.id)
        if node.value is not None:
            values[node.id] = node.value
            steps.append(DemoStep(node.id, "demo.leaf", (("v", node.value),), -inf, inf, node.value))
            return node.value
        results = [visit(c, not maximizing) for c in node.children]
        value = max(results) if maximizing else min(results)
        values[node.id] = value
        key = "demo.max_picks" if maximizing else "demo.min_picks"
        steps.append(DemoStep(node.id, key, (("v", value),), -inf, inf, value))
        return value

    value = visit(root, True)
    return DemoResult(value, visited, set(), values, steps)


def alphabeta_demo(root: DemoNode) -> DemoResult:
    visited: list[str] = []
    values: dict[str, int] = {}
    pruned: set[str] = set()
    steps: list[DemoStep] = []

    def visit(node: DemoNode, alpha: float, beta: float, maximizing: bool) -> int:
        visited.append(node.id)
        if node.value is not None:
            values[node.id] = node.value
            steps.append(DemoStep(node.id, "demo.leaf", (("v", node.value),), alpha, beta, node.value))
            return node.value
        kind = "MAX" if maximizing else "MIN"
        enter = (("kind", kind), ("a", _fmt(alpha)), ("b", _fmt(beta)))
        steps.append(DemoStep(node.id, "demo.enter", enter, alpha, beta, None))
        best = float("-inf") if maximizing else float("inf")
        for i, child in enumerate(node.children):
            result = visit(child, alpha, beta, not maximizing)
            if maximizing:
                best = max(best, result)
                alpha = max(alpha, best)
            else:
                best = min(best, result)
                beta = min(beta, best)
            if alpha >= beta:
                rest = node.children[i + 1 :]
                cut_ids = [nid for skipped in rest for nid in _all_ids(skipped)]
                pruned.update(cut_ids)
                if rest:
                    params = (
                        ("reason", "demo.cut_min" if not maximizing else "demo.cut_max"),
                        ("a", _fmt(alpha)),
                        ("b", _fmt(beta)),
                    )
                    steps.append(DemoStep(node.id, "demo.cut", params, alpha, beta, best, tuple(cut_ids)))
                break
        values[node.id] = int(best)
        steps.append(DemoStep(node.id, "demo.returns", (("kind", kind), ("v", int(best))), alpha, beta, best))
        return int(best)

    value = visit(root, float("-inf"), float("inf"), True)
    return DemoResult(value, visited, pruned, values, steps)
