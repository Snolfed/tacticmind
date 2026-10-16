"""Transposition table (TT).

The same position often appears in the tree many times (a different order of
the same moves = a transposition). The TT remembers, per position (keyed by
Zobrist hash): depth, score, score type and best move. When we meet the
position again we can return the result immediately, or at least start from
the best move (which improves alpha-beta cutoffs).

The score type follows from alpha-beta:
 - EXACT: exact value (alpha < score < beta),
 - LOWER: score >= the stored one (there was a beta cutoff),
 - UPPER: score <= the stored one (no move improved alpha).
"""

from __future__ import annotations

TT_EXACT = 1
TT_LOWER = 2
TT_UPPER = 3


class TranspositionTable:
    """Size-bounded dict hash -> (depth, type, score, move, age)."""

    def __init__(self, max_entries: int = 400_000) -> None:
        self.max_entries = max_entries
        self.table: dict[int, tuple[int, int, int, int, int]] = {}
        self.age = 0

    def new_search(self) -> None:
        """New search: entries from previous searches are overwritten first."""
        self.age = (self.age + 1) & 0xFF

    def clear(self) -> None:
        self.table.clear()

    def probe(self, key: int) -> tuple[int, int, int, int, int] | None:
        return self.table.get(key)

    def store(self, key: int, depth: int, flag: int, score: int, move: int) -> None:
        table = self.table
        old = table.get(key)
        if old is not None:
            # A deeper entry from the current search is more valuable; don't overwrite it with a shallower bound.
            if old[4] == self.age and old[0] > depth and flag != TT_EXACT:
                return
            if move == 0:
                move = old[3]  # don't lose the best move
        elif len(table) >= self.max_entries:
            # Simple overflow strategy: drop all stale entries (or everything).
            current = self.age
            stale = [k for k, v in table.items() if v[4] != current]
            if len(stale) > len(table) // 4:
                for k in stale:
                    del table[k]
            else:
                table.clear()
        table[key] = (depth, flag, score, move, self.age)

    def __len__(self) -> int:
        return len(self.table)
