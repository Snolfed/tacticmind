"""Puzzle loading: the full set (``puzzles.json``) or the bundled starter set."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import chess

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FULL_SET = DATA_DIR / "puzzles.json"
STARTER_SET = DATA_DIR / "starter_puzzles.json"


@dataclass(frozen=True)
class Puzzle:
    """A puzzle in Lichess format.

    Note: ``fen`` is the position BEFORE the opponent's move. The first move in ``moves``
    is played by the opponent, only then does the player start solving. Moves are in UCI.
    """

    id: str
    fen: str
    moves: tuple[str, ...]
    rating: int
    rd: int
    themes: tuple[str, ...]
    popularity: int = 0
    plays: int = 0
    url: str = ""

    @cached_property
    def player_color(self) -> chess.Color:
        """The player plays the side to move after the opponent's first move."""
        return not chess.Board(self.fen).turn

    @cached_property
    def start_fen(self) -> str:
        """The position in which the player starts solving (after the opponent's move)."""
        board = chess.Board(self.fen)
        board.push_uci(self.moves[0])
        return board.fen()

    @property
    def player_moves(self) -> int:
        """Number of moves the player has to find."""
        return len(self.moves) // 2


def as_int(value: object, default: int = 0) -> int:
    """A number from JSON data (with a safe default)."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        try:
            return int(float(value))
        except ValueError:
            return default
    return default


def as_strings(value: object) -> tuple[str, ...]:
    return tuple(str(v) for v in value) if isinstance(value, (list, tuple)) else ()


def puzzle_from_dict(data: dict[str, object]) -> Puzzle:
    return Puzzle(
        id=str(data["id"]),
        fen=str(data["fen"]),
        moves=as_strings(data.get("moves")),
        rating=as_int(data.get("rating"), 1500),
        rd=as_int(data.get("rd"), 80),
        themes=as_strings(data.get("themes")),
        popularity=as_int(data.get("popularity")),
        plays=as_int(data.get("plays")),
        url=str(data.get("url", "")),
    )


def load_puzzles(path: Path | None = None) -> list[Puzzle]:
    """Loads puzzles. Without an argument: the full set, or the starter set when it is missing."""
    if path is None:
        path = FULL_SET if FULL_SET.exists() else STARTER_SET
    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    return [puzzle_from_dict(item) for item in raw]


def puzzle_source(path: Path | None = None) -> str:
    """Puzzle source: ``"full"`` (full set) or ``"starter"`` (starter set)."""
    if path is None:
        path = FULL_SET if FULL_SET.exists() else STARTER_SET
    return "full" if path == FULL_SET else "starter"
