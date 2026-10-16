"""Measurements for the README: node counts for minimax, alpha-beta and alpha-beta with move ordering.

Usage::

    python scripts/benchmark.py            # depths 1–5, Markdown table
    python scripts/benchmark.py --max-depth 4

Minimax is skipped where the estimated node count (b^d) exceeds the limit —
in pure Python it would take too long. The result (score) of all three
variants must be identical — the script checks this.
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
    ("Italian Game (middlegame)", "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"),
    ("Endgame (CPW position 3)", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"),
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
        print(f"\n**{name}** — `{fen}` (moves in position: {branching})\n")
        print("| Depth | Minimax | Alpha-beta | Alpha-beta + ordering | Alpha-beta savings | Savings with ordering | Score |")
        print("|---:|---:|---:|---:|---:|---:|:---:|")
        for depth in range(1, args.max_depth + 1):
            mm = run_variant(fen, depth, "minimax") if branching**depth <= MINIMAX_LIMIT else None
            ab = run_variant(fen, depth, "alphabeta")
            abo = run_variant(fen, depth, "alphabeta-ordered")
            assert ab.score == abo.score and (mm is None or mm.score == ab.score), "results must be identical"
            base = mm.nodes if mm else None
            saved = f"{100 * (1 - ab.nodes / base):.1f}%" if base else "—"
            saved_o = f"{100 * (1 - abo.nodes / base):.1f}%" if base else f"{100 * (1 - abo.nodes / ab.nodes):.1f}% vs. α-β"
            mm_text = f"{fmt(mm.nodes)} ({mm.time_ms / 1000:.2f} s)" if mm else f"— (≈ {fmt(branching**depth)})"
            print(
                f"| {depth} | {mm_text} | {fmt(ab.nodes)} ({ab.time_ms / 1000:.2f} s) | "
                f"{fmt(abo.nodes)} ({abo.time_ms / 1000:.2f} s) | {saved} | {saved_o} | {format_score(ab.score)} |",
                flush=True,
            )


if __name__ == "__main__":
    main()
