"""Przebieg partii z trenerem albo lekcji otwarcia (bez interfejsu — testowane jednostkowo).

Lekcja otwarcia: uczeń gra ruchy głównej linii, a trener odpowiada ruchami z tej linii. Ruch spoza
linii jest cofany (trener tłumaczy, co się tu gra). Po ostatnim ruchu linii można grać dalej
z trenerem — wtedy lekcja zamienia się w zwykłą partię, liczoną do poziomu gracza.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import chess

from .advice import Comment
from .openings import Opening, line_ucis, opening_at
from .review import CLASSES, Classification, game_accuracy

Result = Literal["win", "loss", "draw"]
EndReason = Literal["checkmate", "stalemate", "material", "repetition", "fifty", "resign"]

#: Każde cofnięcie ruchu albo podpowiedź obniża wynik partii o tyle (do poziomu gracza).
HELP_PENALTY = 0.1
#: Partia przerwana po tylu (i więcej) ruchach gracza liczy się jako poddana.
MIN_COUNTED_MOVES = 5


@dataclass
class MoveRecord:
    fen_before: str
    uci: str
    by_player: bool
    classification: Classification | None = None
    accuracy: float | None = None
    comment: Comment = ()
    #: Lepszy ruch według silnika (strzałka przy przeglądaniu partii).
    best_uci: str | None = None

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
        #: Czy po lekcji gracz gra dalej (wtedy partia liczy się do poziomu).
        self.playing = lesson is None
        self.recorded = False

    # ------------------------------------------------------------ stan
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

    # ------------------------------------------------------------ lekcja
    def lesson_line(self) -> tuple[str, ...]:
        return line_ucis(self.lesson.id) if self.lesson is not None else ()

    def lesson_expected(self) -> chess.Move | None:
        """Następny ruch linii (gracza albo trenera), dopóki lekcja trwa."""
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

    # ------------------------------------------------------------ ruchy
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
        """Cofa ostatni ruch gracza (i odpowiedź trenera, jeśli już padła). Zwraca cofnięte ruchy (od końca)."""
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

    # ------------------------------------------------------------ koniec partii
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
        """Do poziomu gracza liczą się zakończone partie (nie same lekcje)."""
        return self.result is not None and self.playing and self.player_moves() > 0

    def abandon_counts(self) -> bool:
        """Czy porzucenie partii w trakcie ma się liczyć jako poddanie."""
        return self.result is None and self.playing and self.player_moves() >= MIN_COUNTED_MOVES

    def score(self) -> float:
        """Wynik do rankingu: 1 / 0,5 / 0, minus 0,1 za każde cofnięcie ruchu i podpowiedź (nie mniej niż 0)."""
        base = {"win": 1.0, "draw": 0.5, "loss": 0.0}.get(self.result or "loss", 0.0)
        return round(max(0.0, base - HELP_PENALTY * (self.takebacks + self.hints)), 3)

    # ------------------------------------------------------------ podsumowanie
    def accuracy(self, player: bool = True) -> float | None:
        values = [r.accuracy for r in self.records if r.by_player == player and r.accuracy is not None]
        return game_accuracy(values)

    def counts(self, player: bool = True) -> dict[str, int]:
        result: dict[str, int] = {cls: 0 for cls in CLASSES}
        for record in self.records:
            if record.by_player == player and record.classification is not None:
                result[record.classification] += 1
        return result
