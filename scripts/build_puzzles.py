"""Builds a puzzle set from the Lichess database (CC0 license).

Usage::

    python scripts/build_puzzles.py lichess_db_puzzle.csv.zst
    python scripts/build_puzzles.py lichess_db_puzzle.csv --count 3000 --out tacticmind/data/puzzles.json

Database: https://database.lichess.org/lichess_db_puzzle.csv.zst
Columns: PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,GameUrl,OpeningTags

The script:
 1. takes only puzzles with Popularity > 80 and NbPlays > 500 rated 600–2800,
 2. splits them into buckets of 100 rating points,
 3. samples the same number of puzzles from each bucket (reservoir sampling, fixed seed),
    preferring themes that are still rare in the result (variety),
 4. checks every puzzle with python-chess (legal moves) and writes JSON.

The .zst file is read with the ``compression.zstd`` module (Python 3.14+); on older Python
decompress the database with ``unzstd lichess_db_puzzle.csv.zst``.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import io
import json
import random
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO, TypedDict

import chess

MIN_RATING = 600
MAX_RATING = 2800
BUCKET = 100


def open_csv(path: Path) -> TextIO:
    if path.suffix == ".zst":
        try:
            zstd = importlib.import_module("compression.zstd")  # Python 3.14+
        except ImportError:
            sys.exit("This Python does not support .zst — decompress the file: unzstd lichess_db_puzzle.csv.zst")
        return io.TextIOWrapper(zstd.open(path, "rb"), encoding="utf-8", newline="")
    return path.open(encoding="utf-8", newline="")


def read_rows(path: Path) -> Iterator[dict[str, str]]:
    with open_csv(path) as handle:
        yield from csv.DictReader(handle)


def is_valid(fen: str, moves: list[str]) -> bool:
    """All of the puzzle's moves must be legal (python-chess)."""
    try:
        board = chess.Board(fen)
        for uci in moves:
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves:
                return False
            board.push(move)
        return True
    except ValueError:
        return False


class PuzzleJson(TypedDict):
    id: str
    fen: str
    moves: list[str]
    rating: int
    rd: int
    popularity: int
    plays: int
    themes: list[str]
    url: str


def to_puzzle(row: dict[str, str]) -> PuzzleJson:
    return {
        "id": row["PuzzleId"],
        "fen": row["FEN"],
        "moves": row["Moves"].split(),
        "rating": int(row["Rating"]),
        "rd": int(row["RatingDeviation"]),
        "popularity": int(row["Popularity"]),
        "plays": int(row["NbPlays"]),
        "themes": row["Themes"].split(),
        "url": row["GameUrl"],
    }


def build(path: Path, count: int, seed: int, pool_factor: int = 12) -> list[PuzzleJson]:
    rng = random.Random(seed)
    buckets = (MAX_RATING - MIN_RATING) // BUCKET
    per_bucket = [count // buckets + (1 if i < count % buckets else 0) for i in range(buckets)]
    # Reservoir sampling: every qualifying row has an equal chance of landing in the bucket's pool.
    pools: list[list[dict[str, str]]] = [[] for _ in range(buckets)]
    seen = [0] * buckets
    total = 0
    for row in read_rows(path):
        total += 1
        try:
            rating = int(row["Rating"])
            if int(row["Popularity"]) <= 80 or int(row["NbPlays"]) <= 500:
                continue
        except (KeyError, ValueError):
            continue
        if not MIN_RATING <= rating < MAX_RATING:
            continue
        b = (rating - MIN_RATING) // BUCKET
        seen[b] += 1
        capacity = per_bucket[b] * pool_factor
        if len(pools[b]) < capacity:
            pools[b].append(row)
        else:
            j = rng.randrange(seen[b])
            if j < capacity:
                pools[b][j] = row
        if total % 500_000 == 0:
            print(f"  read {total:,} rows…", file=sys.stderr)

    # Pick puzzles from each bucket's pool, preferring themes that are rare in the result.
    chosen: list[PuzzleJson] = []
    theme_counts: Counter[str] = Counter()
    ignored = {"short", "long", "veryLong", "oneMove", "middlegame", "endgame", "opening", "master", "masterVsMaster", "crushing", "advantage", "equality", "mate"}
    for b in range(buckets):
        pool = pools[b]
        rng.shuffle(pool)
        picked = 0
        while pool and picked < per_bucket[b]:
            # A reward for each tactical theme, larger the rarer it is in the result so far.
            best_index = max(
                range(len(pool)),
                key=lambda i: sum(1.0 / (1 + theme_counts[t]) for t in pool[i]["Themes"].split() if t not in ignored),
            )
            row = pool.pop(best_index)
            moves = row["Moves"].split()
            if len(moves) < 2 or not is_valid(row["FEN"], moves):
                continue
            chosen.append(to_puzzle(row))
            theme_counts.update(t for t in row["Themes"].split() if t not in ignored)
            picked += 1
    print(f"Read {total:,} rows, selected {len(chosen)} puzzles.", file=sys.stderr)
    chosen.sort(key=lambda p: (p["rating"], p["id"]))
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description="Builds the TacticMind puzzle set from the Lichess database.")
    parser.add_argument("csv", type=Path, help="lichess_db_puzzle.csv or .csv.zst")
    parser.add_argument("--count", type=int, default=3000, help="number of puzzles (default 3000)")
    parser.add_argument("--out", type=Path, default=Path("tacticmind/data/puzzles.json"))
    parser.add_argument("--seed", type=int, default=2024)
    args = parser.parse_args()
    puzzles = build(args.csv, args.count, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        json.dump(puzzles, handle, ensure_ascii=False, separators=(",", ":"))
    ratings = [p["rating"] for p in puzzles]
    print(f"Saved {len(puzzles)} puzzles to {args.out} (rating {min(ratings)}–{max(ratings)}).")


if __name__ == "__main__":
    main()
