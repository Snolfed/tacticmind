"""The flow of solving a single puzzle (pure logic, no interface).

States::

    INTRO ──(opponent's move)──▶ PLAYER ──(good move)──▶ OPPONENT ──(reply)──▶ PLAYER …
                                   │                                     ▲
                                   ├──(move off the solution)──▶ CHECKING ──("good, but there is better")
                                   │                                │
                                   │                                └──(mistake)──▶ MISTAKE ──(try again)──▶ PLAYER
                                   └──(last good move or mate)──▶ SOLVED
    MISTAKE/PLAYER ──(show solution)──▶ REVEALED

The rating outcome (``outcome``) is decided only once: at the first mistake,
on solving, or when the solution is shown. Finishing the puzzle later
after a mistake no longer changes the rating (as on chess.com).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

import chess

from .loader import Puzzle
from .validator import Alternative, gives_mate


class Status(Enum):
    INTRO = "intro"
    PLAYER = "player"
    OPPONENT = "opponent"
    CHECKING = "checking"
    MISTAKE = "mistake"
    SOLVED = "solved"
    REVEALED = "revealed"


class Verdict(Enum):
    CORRECT = "correct"
    SOLVED = "solved"
    SOLVED_ALT_MATE = "solved_alt_mate"
    NEEDS_ENGINE = "needs_engine"
    GOOD_BUT_BETTER = "good_but_better"
    MISTAKE = "mistake"
    ILLEGAL = "illegal"
    NOT_YOUR_TURN = "not_your_turn"


@dataclass(frozen=True)
class PuzzleOutcome:
    """Puzzle result needed for the rating update."""

    solved: bool
    mistake: bool
    hint_used: bool
    revealed: bool
    time_s: float


class PuzzleSession:
    def __init__(self, puzzle: Puzzle, clock: Callable[[], float] = time.monotonic) -> None:
        self.puzzle = puzzle
        self.board = chess.Board(puzzle.fen)
        self.solution = [chess.Move.from_uci(m) for m in puzzle.moves]
        self.player_color = puzzle.player_color
        self.ply = 0  # index of the next move of the solution
        self.status = Status.INTRO
        self.mistake = False
        self.hint_used = False
        self.revealed = False
        self.outcome: PuzzleOutcome | None = None
        self._outcome_taken = False
        self.pending: chess.Move | None = None
        self.wrong_move: chess.Move | None = None
        self.refutation: chess.Move | None = None
        self._clock = clock
        self.started_at: float | None = None
        self.finished_at: float | None = None

    # ------------------------------------------------------------ flow
    def play_intro(self) -> chess.Move:
        """The opponent's first move (from the Lichess database). Then the player's task begins."""
        assert self.status == Status.INTRO
        move = self.solution[0]
        self.board.push(move)
        self.ply = 1
        self.status = Status.PLAYER
        self.started_at = self._clock()
        return move

    @property
    def expected_move(self) -> chess.Move | None:
        if self.status not in (Status.PLAYER, Status.CHECKING) or self.ply >= len(self.solution):
            return None
        return self.solution[self.ply]

    @property
    def finished(self) -> bool:
        return self.status in (Status.SOLVED, Status.REVEALED)

    def submit(self, move: chess.Move) -> Verdict:
        """The player's move."""
        if self.status != Status.PLAYER:
            return Verdict.NOT_YOUR_TURN
        if move not in self.board.legal_moves:
            return Verdict.ILLEGAL
        expected = self.solution[self.ply]
        mate = gives_mate(self.board, move)
        if move == expected or mate:
            self.board.push(move)
            self.ply += 1
            if mate or self.ply >= len(self.solution):
                self._finish(solved=True)
                return Verdict.SOLVED if move == expected else Verdict.SOLVED_ALT_MATE
            self.status = Status.OPPONENT
            return Verdict.CORRECT
        # A move outside the solution: the engine decides (it may be "a good move, but there is a better one").
        self.pending = move
        self.status = Status.CHECKING
        return Verdict.NEEDS_ENGINE

    def resolve(self, alternative: Alternative, refutation: chess.Move | None) -> Verdict:
        """The engine's verdict for a move outside the solution.

        :param refutation: the opponent's best reply computed by the engine (for a mistake).
        """
        assert self.status == Status.CHECKING and self.pending is not None
        move = self.pending
        self.pending = None
        if alternative == Alternative.GOOD_BUT_BETTER:
            self.status = Status.PLAYER
            return Verdict.GOOD_BUT_BETTER
        self.board.push(move)
        self.wrong_move = move
        self.refutation = None
        if refutation is not None and refutation in self.board.legal_moves:
            self.board.push(refutation)
            self.refutation = refutation
        self.status = Status.MISTAKE
        self.mistake = True
        if self.outcome is None:
            self._set_outcome(solved=False)
        return Verdict.MISTAKE

    def opponent_reply(self) -> chess.Move:
        """The opponent's reply from the solution (the interface calls it with a ~400 ms delay)."""
        assert self.status == Status.OPPONENT
        move = self.solution[self.ply]
        self.board.push(move)
        self.ply += 1
        self.status = Status.PLAYER
        return move

    def retry(self) -> None:
        """"Try again": take back the wrong move (and the opponent's reply)."""
        assert self.status == Status.MISTAKE
        self._undo_mistake()
        self.status = Status.PLAYER

    def reveal(self) -> list[chess.Move]:
        """"Show solution": returns the remaining solution moves to be played on the board."""
        if self.status == Status.MISTAKE:
            self._undo_mistake()
        if self.status == Status.CHECKING:
            self.pending = None
        remaining = self.solution[self.ply :]
        self.revealed = True
        if self.outcome is None:
            self._set_outcome(solved=False)
        self.status = Status.REVEALED
        self.finished_at = self._clock()
        return remaining

    def forfeit(self) -> None:
        """The player turned on the full analysis view before the puzzle ended: same outcome as showing the solution.

        The puzzle can then be finished for practice, but the rating will no longer change.
        """
        if self.outcome is None:
            self.revealed = True
            self._set_outcome(solved=False)

    def push_revealed(self, move: chess.Move) -> None:
        """Plays the next move of the solution being shown."""
        assert self.status == Status.REVEALED
        self.board.push(move)
        self.ply += 1

    def hint(self) -> chess.Square | None:
        """Hint: the square of the piece that has to move. Reduces the rating reward."""
        expected = self.expected_move
        if expected is None:
            return None
        if self.outcome is None:
            self.hint_used = True
        return expected.from_square

    def take_outcome(self) -> PuzzleOutcome | None:
        """The result to record in the rating — returned only once."""
        if self.outcome is None or self._outcome_taken:
            return None
        self._outcome_taken = True
        return self.outcome

    def elapsed(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at if self.finished_at is not None else self._clock()
        return max(0.0, end - self.started_at)

    # ------------------------------------------------------------ helpers
    def _undo_mistake(self) -> None:
        if self.refutation is not None:
            self.board.pop()
            self.refutation = None
        if self.wrong_move is not None:
            self.board.pop()
            self.wrong_move = None

    def _finish(self, solved: bool) -> None:
        self.status = Status.SOLVED if solved else Status.REVEALED
        self.finished_at = self._clock()
        if self.outcome is None:
            self._set_outcome(solved=solved)

    def _set_outcome(self, solved: bool) -> None:
        self.outcome = PuzzleOutcome(
            solved=solved and not self.mistake,
            mistake=self.mistake,
            hint_used=self.hint_used,
            revealed=self.revealed,
            time_s=self.elapsed() if self.started_at is not None else 0.0,
        )
