"""Buduje zestaw zadań z bazy Lichess (licencja CC0).

Użycie::

    python scripts/build_puzzles.py lichess_db_puzzle.csv.zst
    python scripts/build_puzzles.py lichess_db_puzzle.csv --count 3000 --out taktykai/data/puzzles.json

Baza: https://database.lichess.org/lichess_db_puzzle.csv.zst
Kolumny: PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,GameUrl,OpeningTags

Skrypt:
 1. bierze tylko zadania z Popularity > 80 i NbPlays > 500 o rankingu 600–2800,
 2. dzieli je na koszyki co 100 punktów rankingu,
 3. z każdego koszyka losuje (reservoir sampling, stałe ziarno) tyle samo zadań,
    preferując motywy, których jeszcze mało w wyniku (różnorodność),
 4. sprawdza każde zadanie biblioteką python-chess (legalne ruchy) i zapisuje JSON.

Plik .zst czytamy modułem ``compression.zstd`` (Python 3.14+); w starszym Pythonie
rozpakuj bazę poleceniem ``unzstd lichess_db_puzzle.csv.zst``.
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
            sys.exit("Ten Python nie obsługuje .zst — rozpakuj plik: unzstd lichess_db_puzzle.csv.zst")
        return io.TextIOWrapper(zstd.open(path, "rb"), encoding="utf-8", newline="")
    return path.open(encoding="utf-8", newline="")


def read_rows(path: Path) -> Iterator[dict[str, str]]:
    with open_csv(path) as handle:
        yield from csv.DictReader(handle)


def is_valid(fen: str, moves: list[str]) -> bool:
    """Wszystkie ruchy zadania muszą być legalne (python-chess)."""
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
    # Reservoir sampling: każdy kwalifikujący się wiersz ma równe szanse trafić do puli koszyka.
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
            print(f"  przeczytano {total:,} wierszy…", file=sys.stderr)

    # Z puli każdego koszyka wybieramy zadania, preferując rzadkie w wyniku motywy.
    chosen: list[PuzzleJson] = []
    theme_counts: Counter[str] = Counter()
    ignored = {"short", "long", "veryLong", "oneMove", "middlegame", "endgame", "opening", "master", "masterVsMaster", "crushing", "advantage", "equality", "mate"}
    for b in range(buckets):
        pool = pools[b]
        rng.shuffle(pool)
        picked = 0
        while pool and picked < per_bucket[b]:
            # Nagroda za każdy motyw taktyczny, tym większa, im rzadszy jest on w dotychczasowym wyniku.
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
    print(f"Przeczytano {total:,} wierszy, wybrano {len(chosen)} zadań.", file=sys.stderr)
    chosen.sort(key=lambda p: (p["rating"], p["id"]))
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description="Buduje zestaw zadań TaktykAI z bazy Lichess.")
    parser.add_argument("csv", type=Path, help="lichess_db_puzzle.csv albo .csv.zst")
    parser.add_argument("--count", type=int, default=3000, help="liczba zadań (domyślnie 3000)")
    parser.add_argument("--out", type=Path, default=Path("taktykai/data/puzzles.json"))
    parser.add_argument("--seed", type=int, default=2024)
    args = parser.parse_args()
    puzzles = build(args.csv, args.count, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        json.dump(puzzles, handle, ensure_ascii=False, separators=(",", ":"))
    ratings = [p["rating"] for p in puzzles]
    print(f"Zapisano {len(puzzles)} zadań do {args.out} (ranking {min(ratings)}–{max(ratings)}).")


if __name__ == "__main__":
    main()
