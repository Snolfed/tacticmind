"""The flow of a game with the coach or of an opening lesson (no UI - unit tested).

Opening lesson: the student plays the main-line moves and the coach replies with moves from that line.
A move outside the line is taken back (the coach explains what is played here). After the last move
of the line you can keep playing against the coach - the lesson then turns into a normal game that
counts towards the player's level.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import chess

from .advice import Comment
from .openings import Opening, line_ucis, opening_at
from .review import CLASSES, Classification, game_accuracy, volatility_weights, win_percent

Result = Literal["win", "loss", "draw"]
EndReason = Literal["checkmate", "stalemate", "material", "repetition", "fifty", "resign"]

#: Every takeback or hint lowers the game score by this much (for the player's level).
HELP_PENALTY = 0.1
#: A game abandoned after this many (or more) player moves counts as resigned.
MIN_COUNTED_MOVES = 5


@dataclass
class MoveRecord:
    fen_before: str
    uci: str
    by_player: bool
    classification: Classification | None = None
    accuracy: float | None = None
    comment: Comment = ()
    #: Better move according to the engine (arrow when reviewing the game).
    best_uci: str | None = None
    #: Engine evaluation after the move, from White's perspective (mate = ±(32000 − plies)); None when unknown.
    score: int | None = None

    @property
    def move(self) -> chess.Move:
        return chess.Move.from_uci(self.uci)


class CoachGame:
    def __init__(
        self,
        player_color: chess.Color,
        elo: int,
        *,
        adaptive: bool = False,
        lesson: Opening | None = None,
        start_fen: str = chess.STARTING_FEN,
    ) -> None:
        self.player_color = player_color
        self.elo = elo
        self.adaptive = adaptive
        self.lesson = lesson
        self.lesson_active = lesson is not None
        self.lesson_mistakes = 0
        self.start_fen = start_fen
        self.board = chess.Board(start_fen)
        self.records: list[MoveRecord] = []
        self.takebacks = 0
        self.hints = 0
        self.result: Result | None = None
        self.reason: EndReason | None = None
        #: Whether the player keeps playing after the lesson (then the game counts towards the level).
        self.playing = lesson is None
        self.recorded = False

    # ------------------------------------------------------------ state
    @property
    def player_to_move(self) -> bool:
        return self.board.turn == self.player_color

    @property
    def over(self) -> bool:
        return self.result is not None

    def player_moves(self) -> int:
        return sum(1 for r in self.records if r.by_player)

    def opening_id(self) -> str | None:
        return opening_at(self.board.move_stack, chess.Board(self.start_fen))

    # ------------------------------------------------------------ lesson
    def lesson_line(self) -> tuple[str, ...]:
        return line_ucis(self.lesson.id) if self.lesson is not None else ()

    def lesson_expected(self) -> chess.Move | None:
        """Next move of the line (the player's or the coach's) while the lesson lasts."""
        line = self.lesson_line()
        ply = len(self.board.move_stack)
        if not self.lesson_active or ply >= len(line):
            return None
        return chess.Move.from_uci(line[ply])

    def lesson_progress(self) -> tuple[int, int]:
        line = self.lesson_line()
        return min(len(self.board.move_stack), len(line)), len(line)

    def lesson_complete(self) -> bool:
        return self.lesson is not None and len(self.board.move_stack) >= len(self.lesson_line())

    def continue_after_lesson(self) -> None:
        self.lesson_active = False
        self.playing = True

    # ------------------------------------------------------------ moves
    def push(self, move: chess.Move, by_player: bool, **fields: object) -> MoveRecord:
        record = MoveRecord(self.board.fen(), move.uci(), by_player)
        for name, value in fields.items():
            setattr(record, name, value)
        self.board.push(move)
        self.records.append(record)
        self._update_result()
        return record

    def can_take_back(self) -> bool:
        return not self.over and any(r.by_player for r in self.records)

    def take_back(self) -> list[chess.Move]:
        """Take back the player's last move (and the coach's reply, if already played). Returns the undone moves (last first)."""
        undone: list[chess.Move] = []
        if not self.can_take_back():
            return undone
        while self.records:
            record = self.records.pop()
            undone.append(self.board.pop())
            if record.by_player:
                break
        self.takebacks += 1
        return undone

    def record_hint(self) -> None:
        self.hints += 1

    # ------------------------------------------------------------ end of game
    def _update_result(self) -> None:
        board = self.board
        reason: EndReason | None = None
        winner: chess.Color | None = None
        if board.is_checkmate():
            reason, winner = "checkmate", not board.turn
        elif board.is_stalemate():
            reason = "stalemate"
        elif board.is_insufficient_material():
            reason = "material"
        elif board.can_claim_threefold_repetition():
            reason = "repetition"
        elif board.can_claim_fifty_moves():
            reason = "fifty"
        if reason is None:
            return
        self.reason = reason
        if winner is None:
            self.result = "draw"
        else:
            self.result = "win" if winner == self.player_color else "loss"
        self.lesson_active = False

    def resign(self) -> None:
        if self.result is None:
            self.result = "loss"
            self.reason = "resign"
            self.lesson_active = False

    def counts_for_rating(self) -> bool:
        """Finished games count towards the player's level (lessons alone do not)."""
        return self.result is not None and self.playing and self.player_moves() > 0

    def abandon_counts(self) -> bool:
        """Whether abandoning the game midway should count as resigning."""
        return self.result is None and self.playing and self.player_moves() >= MIN_COUNTED_MOVES

    def score(self) -> float:
        """Score for the rating: 1 / 0.5 / 0, minus 0.1 for every takeback and hint (not less than 0)."""
        base = {"win": 1.0, "draw": 0.5, "loss": 0.0}.get(self.result or "loss", 0.0)
        return round(max(0.0, base - HELP_PENALTY * (self.takebacks + self.hints)), 3)

    # ------------------------------------------------------------ summary
    def accuracy(self, player: bool = True) -> float | None:
        """Game accuracy of the player (or the coach), weighted by how sharp the game was at each move."""
        series = [50.0]
        for record in self.records:
            series.append(win_percent(record.score) if record.score is not None else series[-1])
        weights = volatility_weights(series)
        chosen = [(r.accuracy, w) for r, w in zip(self.records, weights) if r.by_player == player and r.accuracy is not None]
        return game_accuracy([a for a, _ in chosen], [w for _, w in chosen])

    def counts(self, player: bool = True) -> dict[str, int]:
        result: dict[str, int] = {cls: 0 for cls in CLASSES}
        for record in self.records:
            if record.by_player == player and record.classification is not None:
                result[record.classification] += 1
        return result
