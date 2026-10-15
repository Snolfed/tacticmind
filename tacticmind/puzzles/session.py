"""Przebieg rozwiązywania jednego zadania (czysta logika, bez interfejsu).

Stany::

    INTRO ──(ruch przeciwnika)──▶ PLAYER ──(dobry ruch)──▶ OPPONENT ──(odpowiedź)──▶ PLAYER …
                                     │                                         ▲
                                     ├──(ruch spoza wzorca)──▶ CHECKING ──(„dobry, ale jest lepszy”)
                                     │                             │
                                     │                             └──(błąd)──▶ MISTAKE ──(spróbuj ponownie)──▶ PLAYER
                                     └──(ostatni dobry ruch albo mat)──▶ SOLVED
    MISTAKE/PLAYER ──(pokaż rozwiązanie)──▶ REVEALED

Wynik rankingowy (``outcome``) ustalamy tylko raz: przy pierwszym błędzie,
przy rozwiązaniu albo przy pokazaniu rozwiązania. Późniejsze dokończenie
zadania po błędzie nie zmienia już rankingu (jak na chess.com).
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
    """Wynik zadania potrzebny do aktualizacji rankingu."""

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
        self.ply = 0  # indeks następnego ruchu z rozwiązania
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

    # ------------------------------------------------------------ przebieg
    def play_intro(self) -> chess.Move:
        """Pierwszy ruch przeciwnika (z bazy Lichess). Potem zaczyna się zadanie gracza."""
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
        """Ruch gracza."""
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
        # Ruch spoza rozwiązania: decyzję podejmie silnik (może to „dobry ruch, ale jest lepszy”).
        self.pending = move
        self.status = Status.CHECKING
        return Verdict.NEEDS_ENGINE

    def resolve(self, alternative: Alternative, refutation: chess.Move | None) -> Verdict:
        """Werdykt silnika dla ruchu spoza rozwiązania.

        :param refutation: najlepsza odpowiedź przeciwnika wyliczona przez silnik (dla błędu).
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
        """Odpowiedź przeciwnika z rozwiązania (interfejs wywołuje ją z opóźnieniem ok. 400 ms)."""
        assert self.status == Status.OPPONENT
        move = self.solution[self.ply]
        self.board.push(move)
        self.ply += 1
        self.status = Status.PLAYER
        return move

    def retry(self) -> None:
        """„Spróbuj ponownie”: cofnij błędny ruch (i odpowiedź przeciwnika)."""
        assert self.status == Status.MISTAKE
        self._undo_mistake()
        self.status = Status.PLAYER

    def reveal(self) -> list[chess.Move]:
        """„Pokaż rozwiązanie”: zwraca pozostałe ruchy rozwiązania do odegrania na planszy."""
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
        """Gracz włączył pełny podgląd analizy przed końcem zadania: wynik jak przy pokazaniu rozwiązania.

        Zadanie można potem dokończyć dla treningu, ale ranking już się nie zmieni.
        """
        if self.outcome is None:
            self.revealed = True
            self._set_outcome(solved=False)

    def push_revealed(self, move: chess.Move) -> None:
        """Odgrywa kolejny ruch pokazywanego rozwiązania."""
        assert self.status == Status.REVEALED
        self.board.push(move)
        self.ply += 1

    def hint(self) -> chess.Square | None:
        """Podpowiedź: pole figury, którą trzeba ruszyć. Zmniejsza nagrodę rankingową."""
        expected = self.expected_move
        if expected is None:
            return None
        if self.outcome is None:
            self.hint_used = True
        return expected.from_square

    def take_outcome(self) -> PuzzleOutcome | None:
        """Wynik do zaksięgowania w rankingu — zwracany tylko raz."""
        if self.outcome is None or self._outcome_taken:
            return None
        self._outcome_taken = True
        return self.outcome

    def elapsed(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at if self.finished_at is not None else self._clock()
        return max(0.0, end - self.started_at)

    # ------------------------------------------------------------ pomocnicze
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
