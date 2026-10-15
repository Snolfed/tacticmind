"""Pomiary do README: liczba węzłów minimaksu, alfa-bety i alfa-bety z porządkowaniem ruchów.

Użycie::

    python scripts/benchmark.py            # głębokości 1–5, tabela w Markdownie
    python scripts/benchmark.py --max-depth 4

Minimaks pomijamy tam, gdzie szacunkowa liczba węzłów (b^d) przekracza limit —
w czystym Pythonie liczyłby się wtedy zbyt długo. Wynik (ocena) wszystkich trzech
wariantów musi być identyczny — skrypt to sprawdza.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tacticmind.engine.board import Board  # noqa: E402
from tacticmind.engine.compare import run_variant  # noqa: E402
from tacticmind.engine.movegen import legal_moves  # noqa: E402
from tacticmind.engine.types import format_score  # noqa: E402

POSITIONS = [
    ("Debiut włoski (gra środkowa)", "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"),
    ("Końcówka (pozycja 3 z CPW)", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"),
]
MINIMAX_LIMIT = 1_000_000


def fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-depth", type=int, default=5)
    args = parser.parse_args()
    for name, fen in POSITIONS:
        branching = len(legal_moves(Board(fen)))
        print(f"\n**{name}** — `{fen}` (ruchów w pozycji: {branching})\n")
        print("| Głębokość | Minimaks | Alfa-beta | Alfa-beta + porządkowanie | Oszczędność alfa-bety | Oszczędność z porządkowaniem | Ocena |")
        print("|---:|---:|---:|---:|---:|---:|:---:|")
        for depth in range(1, args.max_depth + 1):
            mm = run_variant(fen, depth, "minimax") if branching**depth <= MINIMAX_LIMIT else None
            ab = run_variant(fen, depth, "alphabeta")
            abo = run_variant(fen, depth, "alphabeta-ordered")
            assert ab.score == abo.score and (mm is None or mm.score == ab.score), "wyniki muszą być identyczne"
            base = mm.nodes if mm else None
            saved = f"{100 * (1 - ab.nodes / base):.1f}%" if base else "—"
            saved_o = f"{100 * (1 - abo.nodes / base):.1f}%" if base else f"{100 * (1 - abo.nodes / ab.nodes):.1f}% wzgl. α-β"
            mm_text = f"{fmt(mm.nodes)} ({mm.time_ms / 1000:.2f} s)" if mm else f"— (≈ {fmt(branching**depth)})"
            print(
                f"| {depth} | {mm_text} | {fmt(ab.nodes)} ({ab.time_ms / 1000:.2f} s) | "
                f"{fmt(abo.nodes)} ({abo.time_ms / 1000:.2f} s) | {saved} | {saved_o} | {format_score(ab.score)} |",
                flush=True,
            )


if __name__ == "__main__":
    main()
