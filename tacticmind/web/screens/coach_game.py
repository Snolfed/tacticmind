"""Game against the coach and opening lesson.

The turn flow:
 1. **Player's move** — the engine analyses the position in the background (MultiPV 3); a theory move is "book" right away.
 2. **Evaluation** — move class and the coach's comment; after a mistake or a blunder the game pauses.
 3. **Coach's move** — from the opening book or from a search whose strength depends on Elo.

Engine requests go one at a time (a job queue) — the engine process computes one thing at a time.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

import chess

from ...brain.notation import uci_san
from ...coach.advice import Comment, Phrase, San, book_comment, phrase, player_comment, render_comment, trainer_comment
from ...coach.archive import decode_plies, encode_plies, eval_curve, game_pgn, pgn_filename
from ...coach.game import CoachGame, MoveRecord
from ...coach.openings import Opening, book_moves, comment_key, is_book_move, move_comment, opening_name
from ...coach.review import CLASSES, SERIOUS, WEAK, classify, move_accuracy, score_for, win_drop, win_percent
from ...coach.strength import FULL_DEPTH, choose_move, describe_level, strength_for
from ...engine.constants import WHITE
from ...engine.process import DoneEvent, EngineEvent, ErrorEvent
from ...engine.types import MATE, SearchInfo, to_white_score
from ...i18n import fmt_decimal, get_language, t, tn
from ...puzzles.validator import SACRIFICE_MIN_LOSS, is_sacrifice, see
from ...rating.coach_profile import CALIBRATION_GAMES, CoachGameRecord, LevelChange
from ...rating.profile import RatingChange, data_dir
from .. import brain
from ..board import BoardModel
from ..colors import BEST_ARROW, BEST_ARROW_REVIEW, HINT_ARROW, LESSON_ARROW
from .base import WebScreen

if TYPE_CHECKING:
    from ..core import WebApp

#: Analysis of the player's position (to judge their move, for hints and the evaluation bar): as deep as the time
#: allows, like the strongest coach, so the bar and the move classes follow what the engine really thinks.
COACH_DEPTH = FULL_DEPTH
PRE_TIME = 1600
POST_TIME = 1000
#: The coach "thinks" at least this long (s), even when it computes faster — the game looks more natural.
MIN_THINK = 0.7
#: Pause between the comment on the player's move and the coach's move.
TRAINER_PAUSE = 0.35
LESSON_REPLY = 0.75
#: The coach plays from the opening book for at most this many plies.
BOOK_PLIES = 24
#: The game summary appears shortly after the game ends.
SUMMARY_DELAY = 0.9
#: How long a notice ("PGN copied", "Saved to …") stays visible (s).
NOTICE_TIME = 4.0

Text = Callable[[], str]
Arrow = tuple[chess.Move, frozenset[str], str]

_REACTIONS = {
    "brilliant": "excited",
    "great": "excited",
    "best": "happy",
    "excellent": "happy",
    "book": "happy",
    "good": "neutral",
    "inaccuracy": "concerned",
    "mistake": "concerned",
    "blunder": "shocked",
}
_PIECE_ORDER = (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN)
_START_COUNT = {chess.PAWN: 8, chess.KNIGHT: 2, chess.BISHOP: 2, chess.ROOK: 2, chess.QUEEN: 1}
_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}


def tx(key: str, **params: object) -> Text:
    return partial(t, key, **params)


@dataclass
class _Job:
    kind: str  # "pre" | "post" | "ref" | "play"
    fen: str
    depth: int
    time_ms: int
    multi_pv: int
    callback: Callable[[SearchInfo | None], None]


@dataclass
class _Judge:
    record: MoveRecord
    board: chess.Board
    move: chess.Move


@dataclass
class _TrainerRef:
    """The coach's best evaluation in the position after the player's move — to judge the coach's move."""

    fen: str
    value: int
    best_uci: str | None


@dataclass
class _Summary:
    opened_at: float
    change: LevelChange | None = None
    counted: bool = False
    notes: list[str] = field(default_factory=list)
    #: A game opened from the list of saved games (not just played).
    archived: CoachGameRecord | None = None


class CoachGameScreen(WebScreen):
    def __init__(self, app: WebApp) -> None:
        super().__init__(app)
        self.board_view = BoardModel("coach", app.fx)
        self.board_view.on_move = self.on_player_move
        self.game: CoachGame | None = None
        self.settings: tuple[chess.Color, int, bool, Opening | None] = (chess.WHITE, 800, False, None)
        self.strength = strength_for(800)
        self.rng = random.Random()
        self.phase = "idle"
        self.turn_started = 0.0
        # Engine job queue.
        self.jobs: list[_Job] = []
        self.job: _Job | None = None
        self.job_id: int | None = None
        self.analyses: dict[str, SearchInfo] = {}
        self.judge: _Judge | None = None
        self.trainer_ref: _TrainerRef | None = None
        self.pending_grade: tuple[MoveRecord, _TrainerRef] | None = None
        self.hint_pending = False
        # Coach comments: main (about the player's move) and side (about the coach's move).
        self.main: Comment = ()
        self.main_cls: str | None = None
        self.main_seq = 0
        self.side: Comment = ()
        self.reaction = "neutral"
        self.reaction_until = 0.0
        self.arrow: Arrow | None = None
        self.view_index: int | None = None
        self.summary: _Summary | None = None
        self.confirm: tuple[Text, Callable[[], None], str] | None = None
        self.game_seq = 0
        #: The saved game shown in the review (None for a game played now).
        self.archived: CoachGameRecord | None = None
        self.played_at: float | None = None
        self.notice: tuple[Text, float] | None = None
        self._pgn_cache: tuple[tuple[int, str], str] | None = None

    # ================================================================ start and lifecycle
    def start(self, color: chess.Color, elo: int, adaptive: bool, lesson: Opening | None) -> None:
        self._reset_engine()
        self.timers.clear()
        self.settings = (color, elo, adaptive, lesson)
        self.game = CoachGame(color, elo, adaptive=adaptive, lesson=lesson)
        self.game_seq += 1
        self.strength = strength_for(elo)
        self.analyses.clear()
        self.judge = None
        self.trainer_ref = None
        self.pending_grade = None
        self.hint_pending = False
        self.view_index = None
        self.arrow = None
        self.summary = None
        self.confirm = None
        self.archived = None
        self.played_at = None
        self.notice = None
        self.side = ()
        bv = self.board_view
        bv.orientation = color
        bv.player_color = color
        bv.interactive = False
        bv.feedback = None
        bv.arrows = []
        bv.hint_square = None
        bv.set_position(self.game.board, None, animate=False)
        if lesson is not None:
            self.say((phrase("coach.lesson_intro", name=Phrase(f"opening.{lesson.id}.name")), Phrase(f"opening.{lesson.id}.desc")))
        else:
            side = "coach.intro_white" if color == chess.WHITE else "coach.intro_black"
            self.say((phrase("coach.game_intro", elo=elo), Phrase(side)))
        self.react("happy", 3.0)
        self.phase = "intro"
        self.schedule(0.9, self.next_turn)

    def rematch(self) -> None:
        color, elo, adaptive, lesson = self.settings
        if lesson is None and adaptive and self.app.profile.coach.level is not None:
            elo = self.app.profile.coach.level  # "Your level" may have just changed
        self.start(color, elo, adaptive, lesson)

    def enter(self) -> None:
        if self.job is not None:
            # We are back on the screen: restart the interrupted engine job.
            self.jobs.insert(0, self.job)
            self.job = None
            self.job_id = None
        self._pump()

    def leave(self) -> None:
        self.app.engine.stop()

    def in_progress(self) -> bool:
        return self.game is not None and not self.game.over and self.phase != "idle"

    # ================================================================ comments and the coach's expression
    def say(self, comment: Comment, cls: str | None = None) -> None:
        self.main = comment
        self.main_cls = cls
        self.main_seq += 1

    def say_side(self, comment: Comment) -> None:
        self.side = comment

    def react(self, expression: str, seconds: float = 2.8) -> None:
        self.reaction = expression
        self.reaction_until = self.clock + seconds

    def expression(self) -> str:
        if self.clock < self.reaction_until:
            return self.reaction
        if self.phase in ("judging", "trainer"):
            return "thinking"
        return "neutral"

    # ================================================================ engine (job queue)
    def _reset_engine(self) -> None:
        self.jobs.clear()
        self.job = None
        self.job_id = None
        self.app.engine.stop()

    def queue(self, job: _Job) -> None:
        self.jobs.append(job)
        self._pump()

    def _pump(self) -> None:
        if self.job is not None or not self.jobs or self.app.current_name != "coach_game":
            return
        self.job = self.jobs.pop(0)
        self.job_id = self.app.engine.analyze(self.job.fen, max_depth=self.job.depth, time_ms=self.job.time_ms, multi_pv=self.job.multi_pv)

    def on_engine(self, event: EngineEvent) -> None:
        if self.job is None or event.id != self.job_id:
            return
        if isinstance(event, (DoneEvent, ErrorEvent)):
            job = self.job
            self.job = None
            self.job_id = None
            info = event.info if isinstance(event, DoneEvent) else None
            job.callback(info)
            self._pump()

    def ensure_analysis(self, fen: str) -> None:
        if fen in self.analyses:
            return
        if (self.job is not None and self.job.kind == "pre" and self.job.fen == fen) or any(j.kind == "pre" and j.fen == fen for j in self.jobs):
            return
        self.queue(_Job("pre", fen, COACH_DEPTH, PRE_TIME, 3, partial(self._on_pre, fen)))

    def _on_pre(self, fen: str, info: SearchInfo | None) -> None:
        if info is not None and info.depth:
            self.analyses[fen] = info
        self._grade_trainer_move(fen, info)
        if self.judge is not None and self.judge.board.fen() == fen:
            self._continue_judgement()
        if self.hint_pending and self.game is not None and self.game.board.fen() == fen:
            self.hint_pending = False
            self._show_hint()

    # ================================================================ turns
    def next_turn(self) -> None:
        game = self.game
        if game is None:
            return
        if game.over:
            self.finish()
            return
        if game.lesson_active and game.lesson_complete():
            self.lesson_finished()
            return
        self.go_live()
        if game.player_to_move:
            self.begin_player_turn()
        else:
            self.begin_trainer_turn()

    def begin_player_turn(self) -> None:
        assert self.game is not None
        self.phase = "player"
        self.turn_started = self.clock
        self.board_view.interactive = self.view_index is None
        if not self.game.lesson_active:
            self.ensure_analysis(self.game.board.fen())

    def _show_move(self, board_before: chess.Board, move: chess.Move, animate: bool = True) -> None:
        after = board_before.copy()
        after.push(move)
        self.board_view.set_position(after, move, animate)
        self.play_sound(board_before, move)

    # ---------------------------------------------------------------- player's move
    def on_player_move(self, move: chess.Move) -> None:
        game = self.game
        if game is None or self.phase != "player" or game.over or not game.player_to_move or self.view_index is not None:
            return
        board_before = game.board.copy()
        self.arrow = None
        self.board_view.hint_square = None
        if game.lesson_active:
            self._lesson_move(board_before, move)
            return
        book = is_book_move(board_before, move)
        record = game.push(move, True)
        self._show_move(board_before, move)
        self.board_view.interactive = False
        self.trainer_ref = None
        if game.board.is_checkmate():
            record.classification, record.accuracy = "best", 100.0
            record.score = MATE if board_before.turn == chess.WHITE else -MATE
            record.comment = player_comment(board_before, move, "best", None, [], MATE, MATE, [])
            self._after_judgement(record, board_before, move)
            return
        if book:
            found = move_comment(board_before, move)
            record.classification, record.accuracy = "book", 100.0
            record.comment = book_comment(board_before, move, game.opening_id(), comment_key(*found) if found else None, trainer=False)
            self._after_judgement(record, board_before, move)
            return
        self.phase = "judging"
        self.judge = _Judge(record, board_before, move)
        if board_before.fen() in self.analyses:
            self._continue_judgement()
        else:
            self.ensure_analysis(board_before.fen())

    def _continue_judgement(self) -> None:
        judge = self.judge
        if judge is None:
            return
        info = self.analyses.get(judge.board.fen())
        if info is None or not info.multi_pv:
            self.judge = None
            self._after_judgement(judge.record, judge.board, judge.move)
            return
        line = next((line for line in info.multi_pv if line.move == judge.move.uci()), None)
        if line is not None:
            self._finish_judgement(info, score_for(line.score, judge.board.turn), line.pv[1:])
            return
        after = judge.board.copy()
        after.push(judge.move)
        self.queue(_Job("post", after.fen(), COACH_DEPTH - 1, POST_TIME, 1, self._on_post))

    def _on_post(self, info: SearchInfo | None) -> None:
        judge = self.judge
        if judge is None:
            return
        best = self.analyses.get(judge.board.fen())
        if info is None or best is None:
            self.judge = None
            self._after_judgement(judge.record, judge.board, judge.move)
            return
        played = score_for(info.score, judge.board.turn)
        self._finish_judgement(best, played, list(info.pv))

    def _finish_judgement(self, info: SearchInfo, played: int, reply: list[str]) -> None:
        judge = self.judge
        assert judge is not None
        self.judge = None
        board, move, record = judge.board, judge.move, judge.record
        me = board.turn
        best = info.multi_pv[0]
        best_value = score_for(best.score, me)
        is_best = best.move == move.uci()
        if is_best:
            played = best_value
        drop = 0.0 if is_best else win_drop(best_value, played)
        second = win_drop(best_value, score_for(info.multi_pv[1].score, me)) if len(info.multi_pv) > 1 else None
        last = board.peek() if board.move_stack else None
        # Recapturing, or taking a piece the opponent left hanging, is obvious: never a "great" move.
        recapture = board.is_capture(move) and (
            (last is not None and move.to_square == last.to_square) or see(board, move.to_square) >= SACRIFICE_MIN_LOSS
        )
        cls = classify(
            drop, is_best=is_best, sacrifice=is_sacrifice(board, move), second_drop=second, win_before=win_percent(best_value), recapture=recapture
        )
        record.classification = cls
        record.accuracy = move_accuracy(drop)
        record.best_uci = None if is_best else best.move
        record.score = played if me == chess.WHITE else -played
        record.comment = player_comment(board, move, cls, best.move, list(best.pv), best_value, played, reply)
        after = board.copy(stack=False)
        after.push(move)
        self.trainer_ref = _TrainerRef(after.fen(), -played, reply[0] if reply else None)
        self._after_judgement(record, board, move)

    def _after_judgement(self, record: MoveRecord, board: chess.Board, move: chess.Move) -> None:
        game = self.game
        assert game is not None
        cls = record.classification
        self.say(record.comment, cls)
        if cls is not None:
            self.board_view.show_badge(move.to_square, cls)
            self.react(_REACTIONS.get(cls, "neutral"))
            if cls == "brilliant":
                self.app.sound("brilliant")
            elif cls in SERIOUS:
                self.app.sound("error")
        if game.over:
            self.phase = "waiting"
            self.schedule(0.6, self.next_turn)
            return
        if cls in SERIOUS:
            self.phase = "paused"
            if record.best_uci:
                after = board.copy(stack=False)
                after.push(move)
                self.arrow = (chess.Move.from_uci(record.best_uci), frozenset({board.fen(), after.fen()}), BEST_ARROW)
            return
        self.phase = "waiting"
        self.schedule(TRAINER_PAUSE, self.next_turn)

    def continue_after_pause(self) -> None:
        if self.phase != "paused":
            return
        self.arrow = None
        self.phase = "waiting"
        self.next_turn()

    # ---------------------------------------------------------------- opening lesson
    def _lesson_move(self, board_before: chess.Board, move: chess.Move) -> None:
        game = self.game
        assert game is not None and game.lesson is not None
        expected = game.lesson_expected()
        if expected is None:
            return
        ply = len(board_before.move_stack) + 1
        key = comment_key(game.lesson.id, ply)
        if move == expected:
            record = game.push(move, True, classification="book", accuracy=100.0)
            record.comment = (Phrase("coach.lesson_ok"), Phrase(key))
            self._show_move(board_before, move)
            self.board_view.show_badge(move.to_square, "book")
            self.say(record.comment, "book")
            self.react("happy", 1.8)
            self.board_view.interactive = False
            self.phase = "waiting"
            self.schedule(LESSON_REPLY, self.next_turn)
            return
        game.lesson_mistakes += 1
        fen = board_before.fen()
        expected_san = San(fen, expected.uci())
        if is_book_move(board_before, move):
            first = phrase("coach.lesson_other", move=San(fen, move.uci()), expected=expected_san)
        else:
            first = phrase("coach.lesson_wrong", expected=expected_san)
        self._show_move(board_before, move)
        self.board_view.show_feedback(move.to_square, False)
        self.app.sound("error")
        self.say((first, Phrase(key)), None)
        self.react("concerned")
        self.arrow = (expected, frozenset({fen}), LESSON_ARROW)
        self.board_view.interactive = False
        self.phase = "lesson_wrong"
        self.schedule(0.95, partial(self._undo_lesson_move, board_before, move))

    def _undo_lesson_move(self, board_before: chess.Board, move: chess.Move) -> None:
        if self.game is None or self.phase != "lesson_wrong":
            return
        self.board_view.set_position(board_before, board_before.peek() if board_before.move_stack else None, undo=move)
        self.play_sound(board_before, move)
        self.board_view.feedback = None
        self.phase = "player"
        self.board_view.interactive = self.view_index is None

    def lesson_finished(self) -> None:
        game = self.game
        assert game is not None and game.lesson is not None
        self.app.profile.coach.record_lesson(game.lesson.id, game.lesson_mistakes)
        self.app.save()
        self.phase = "lesson_done"
        self.board_view.interactive = False
        mistakes = game.lesson_mistakes
        result = Phrase("coach.lesson_flawless") if mistakes == 0 else Phrase("coach.lesson_mistakes", count=mistakes)
        self.say((phrase("coach.lesson_done", name=Phrase(f"opening.{game.lesson.id}.name")), result, Phrase("coach.lesson_next")), None)
        self.react("excited", 4.0)
        self.app.sound("success")
        if game.board.move_stack:
            self.board_view.celebrate(game.board.peek().to_square)

    def continue_after_lesson(self) -> None:
        game = self.game
        if game is None or self.phase != "lesson_done":
            return
        game.continue_after_lesson()
        self.say((Phrase("coach.lesson_continue"),), None)
        self.next_turn()

    # ---------------------------------------------------------------- coach's move
    def begin_trainer_turn(self) -> None:
        game = self.game
        assert game is not None
        self.phase = "trainer"
        self.turn_started = self.clock
        self.board_view.interactive = False
        board = game.board
        if game.lesson_active:
            expected = game.lesson_expected()
            if expected is not None:
                self.schedule(LESSON_REPLY, partial(self._play_trainer, expected, "lesson"))
                return
        book = book_moves(board)
        if book and len(board.move_stack) < BOOK_PLIES:
            ucis = list(book)
            uci = self.rng.choices(ucis, weights=[book[u] for u in ucis], k=1)[0]
            self.schedule(MIN_THINK, partial(self._play_trainer, chess.Move.from_uci(uci), "book"))
            return
        fen = board.fen()
        if self.trainer_ref is None or self.trainer_ref.fen != fen:
            self.queue(_Job("ref", fen, COACH_DEPTH - 1, POST_TIME, 1, partial(self._on_ref, fen)))
        s = self.strength
        self.queue(_Job("play", fen, s.depth, s.time_ms, s.multi_pv, partial(self._on_play, fen)))

    def _on_ref(self, fen: str, info: SearchInfo | None) -> None:
        game = self.game
        if game is None or info is None or not info.depth or game.board.fen() != fen:
            return
        self.trainer_ref = _TrainerRef(fen, score_for(info.score, game.board.turn), info.best_move or None)

    def _on_play(self, fen: str, info: SearchInfo | None) -> None:
        game = self.game
        if game is None or self.phase != "trainer" or game.board.fen() != fen:
            return
        board = game.board
        legal = [m.uci() for m in board.legal_moves]
        if not legal:
            return
        lines = [(line.move, score_for(line.score, board.turn)) for line in info.multi_pv] if info is not None else []
        uci = choose_move(lines, legal, self.strength, self.rng)
        delay = max(0.0, self.turn_started + MIN_THINK - self.clock)
        self.schedule(delay, partial(self._play_trainer, chess.Move.from_uci(uci), "engine"))

    def _play_trainer(self, move: chess.Move, source: str) -> None:
        game = self.game
        if game is None or game.over or self.phase != "trainer" or game.player_to_move:
            return
        self.go_live()
        board_before = game.board.copy()
        if source in ("lesson", "book"):
            found = move_comment(board_before, move)
            record = game.push(move, False, classification="book", accuracy=100.0)
            record.comment = book_comment(board_before, move, game.opening_id(), comment_key(*found) if found else None, trainer=True)
        else:
            record = game.push(move, False)
            record.comment = trainer_comment(board_before, move)
            ref = self.trainer_ref
            if game.board.is_checkmate():
                record.classification, record.accuracy = "best", 100.0
                record.score = MATE if board_before.turn == chess.WHITE else -MATE
            elif ref is not None and ref.fen == board_before.fen():
                self.pending_grade = (record, ref)
        self.trainer_ref = None
        self._show_move(board_before, move)
        self.say_side(record.comment)
        self.next_turn()

    def _grade_trainer_move(self, fen: str, info: SearchInfo | None) -> None:
        """Evaluates the coach's move once the evaluation after it is known (analysis on the player's turn)."""
        pending = self.pending_grade
        if pending is None or info is None or not info.depth:
            return
        record, ref = pending
        after = chess.Board(record.fen_before)
        after.push(record.move)
        if after.fen() != fen:
            return
        self.pending_grade = None
        value = score_for(info.score, after.turn) * -1  # evaluation from the coach's perspective
        is_best = record.uci == ref.best_uci
        drop = 0.0 if is_best else win_drop(ref.value, value)
        record.classification = classify(drop, is_best=is_best)
        record.accuracy = move_accuracy(drop)
        record.score = info.score.value

    # ---------------------------------------------------------------- coach's help
    def hint(self) -> None:
        game = self.game
        if game is None or self.phase != "player" or game.over or self.view_index is not None:
            return
        if game.lesson_active:
            expected = game.lesson_expected()
            if expected is None:
                return
            fen = game.board.fen()
            self.arrow = (expected, frozenset({fen}), HINT_ARROW)
            self.board_view.hint_square = expected.from_square
            self.say((phrase("coach.lesson_hint", move=San(fen, expected.uci())),), None)
            return
        game.record_hint()
        if game.board.fen() in self.analyses:
            self._show_hint()
        else:
            self.hint_pending = True
            self.say((Phrase("coach.hint_wait"),), None)
            self.ensure_analysis(game.board.fen())

    def _show_hint(self) -> None:
        game = self.game
        assert game is not None
        fen = game.board.fen()
        info = self.analyses.get(fen)
        if info is None or not info.best_move:
            return
        move = chess.Move.from_uci(info.best_move)
        self.arrow = (move, frozenset({fen}), HINT_ARROW)
        self.board_view.hint_square = move.from_square
        self.say((phrase("coach.hint", move=San(fen, info.best_move)),), None)
        self.react("happy", 1.5)

    def take_back(self) -> None:
        game = self.game
        if game is None or self.phase not in ("player", "paused") or game.lesson_active or not game.can_take_back():
            return
        self.timers.clear()
        self._reset_engine()
        self.go_live()
        shown = game.board.copy()
        undone = game.take_back()
        self.judge = None
        self.pending_grade = None
        self.trainer_ref = None
        self.hint_pending = False
        self.board_view.feedback = None
        self.board_view.hint_square = None
        first = shown.copy()
        first.pop()
        self.board_view.set_position(first, first.peek() if first.move_stack else None, undo=undone[0])
        self.play_sound(first, undone[0])
        if len(undone) > 1:
            final = game.board.copy()

            def second() -> None:
                self.board_view.set_position(final, final.peek() if final.move_stack else None, undo=undone[1])
                self.play_sound(final, undone[1])

            self.schedule(0.28, second)
        fen = game.board.fen()
        info = self.analyses.get(fen)
        if info is not None and info.best_move:
            self.arrow = (chess.Move.from_uci(info.best_move), frozenset({fen}), BEST_ARROW)
        self.say((Phrase("coach.takeback"),), None)
        self.react("neutral", 0.5)
        self.side = ()
        self.phase = "waiting"
        self.schedule(0.3 * len(undone), self.begin_player_turn)

    # ---------------------------------------------------------------- end of game
    def ask_resign(self) -> None:
        if self.in_progress() and self.game is not None and not self.game.lesson_active:
            self.confirm = (tx("coach.resign_confirm"), self._resign, "coach.resign_yes")

    def _resign(self) -> None:
        if self.game is None or self.game.over:
            return
        self.timers.clear()
        self.game.resign()
        self.finish()

    def leave_game(self) -> None:
        """The "Menu" button: abandoning a started game counts as resigning (from 5 moves on)."""
        game = self.game
        if game is not None and game.abandon_counts():
            self.confirm = (tx("coach.abandon_confirm"), self._abandon, "coach.abandon_yes")
            return
        self.abandon_silently()
        self.app.go("coach")

    def abandon_silently(self) -> None:
        self.timers.clear()
        self._reset_engine()
        if self.game is not None and not self.game.over:
            self.phase = "idle"

    def abandon_and_record(self) -> None:
        """Starting a new game from the menu: the current one (from 5 moves on) counts as resigned."""
        game = self.game
        if game is not None and not game.over and game.abandon_counts():
            game.resign()
            self._record()
        self.abandon_silently()

    def _abandon(self) -> None:
        game = self.game
        if game is not None and not game.over:
            game.resign()
            self._record()
        self.abandon_silently()
        self.app.go("coach")

    def finish(self) -> None:
        game = self.game
        if game is None or self.phase == "over":
            return
        self.phase = "over"
        self._reset_engine()
        self.board_view.interactive = False
        self.arrow = None
        self._fill_scores(game)
        change = self._record() if game.counts_for_rating() and not game.recorded else None
        result = game.result or "draw"
        reason = Phrase(f"coach.reason.{game.reason}") if game.reason else Phrase("")
        self.say((reason, Phrase(f"coach.end.{result}")), None)
        if result == "win":
            self.react("excited", 5.0)
            self.app.sound("success")
            if game.board.move_stack:
                self.board_view.celebrate(game.board.peek().to_square)
        else:
            self.react("happy" if result == "loss" else "neutral", 4.0)
        self.summary = _Summary(self.clock + SUMMARY_DELAY, change, change is not None)

    def _record(self) -> LevelChange | None:
        game = self.game
        if game is None or game.recorded or game.result is None:
            return None
        game.recorded = True
        self._fill_scores(game)
        self.played_at = time.time()
        coach = self.app.profile.coach
        change = coach.record(
            trainer_elo=game.elo,
            adaptive=game.adaptive,
            color="white" if game.player_color == chess.WHITE else "black",
            result=game.result,
            score=game.score(),
            accuracy=game.accuracy(True),
            trainer_accuracy=game.accuracy(False),
            moves=game.player_moves(),
            opening=game.opening_id(),
            helps=game.takebacks + game.hints,
            plies=encode_plies(game.records),
            start_fen=game.start_fen,
            reason=game.reason,
        )
        self.app.save()
        self.app.on_rating_change(RatingChange(change.rating_before, change.rating_after, change.rating_after - change.rating_before, game.score(), coach.rating.rd))
        return change

    def _fill_scores(self, game: CoachGame) -> None:
        """Evaluations of moves the coach did not judge (e.g. its book moves) from the analyses made during the game."""
        board = chess.Board(game.start_fen)
        for record in game.records:
            board.push(record.move)
            if record.score is None:
                info = self.analyses.get(board.fen())
                if info is not None and info.depth:
                    record.score = info.score.value

    # ================================================================ saved games
    def open_archived(self, index: int) -> bool:
        """Opens a saved game in the review: board at the start, move list with badges, comments, graph."""
        coach = self.app.profile.coach
        if not coach.reviewable(index):
            return False
        saved = coach.games[index]
        records = decode_plies(saved.start_fen, saved.plies)
        if records is None:
            return False
        color = chess.WHITE if saved.color == "white" else chess.BLACK
        self.start_review(saved, color, records)
        return True

    def start_review(self, saved: CoachGameRecord, color: chess.Color, records: list[MoveRecord]) -> None:
        self._reset_engine()
        self.timers.clear()
        self.settings = (color, saved.trainer_elo, saved.adaptive, None)
        self.strength = strength_for(saved.trainer_elo)
        game = CoachGame(color, saved.trainer_elo, adaptive=saved.adaptive, start_fen=saved.start_fen)
        for record in records:
            game.board.push(record.move)
            game.records.append(record)
        game.result = saved.result if saved.result in ("win", "loss", "draw") else "draw"  # type: ignore[assignment]
        game.reason = saved.reason  # type: ignore[assignment]
        game.recorded = True
        self.game = game
        self.game_seq += 1
        self.analyses.clear()
        self.judge = None
        self.trainer_ref = None
        self.pending_grade = None
        self.hint_pending = False
        self.arrow = None
        self.confirm = None
        self.notice = None
        self.archived = saved
        self.played_at = saved.timestamp
        self.summary = _Summary(-1.0, archived=saved)
        self.side = ()
        self.phase = "over"
        bv = self.board_view
        bv.orientation = color
        bv.player_color = color
        bv.interactive = False
        bv.feedback = None
        bv.arrows = []
        bv.hint_square = None
        bv.set_position(game.board, game.board.peek() if game.board.move_stack else None, animate=False)
        self.view_index = None
        self._restore_live_badge()
        self.say((Phrase(f"coach.reason.{game.reason}") if game.reason else Phrase(""), Phrase(f"coach.end.{game.result}")), None)
        self.react("neutral", 0.0)
        if game.records:
            self.jump_to(0)

    # ================================================================ PGN
    def pgn(self) -> str:
        """PGN of the finished game (cached - the snapshot is built many times per second)."""
        assert self.game is not None
        key = (self.game_seq, get_language())
        if self._pgn_cache is None or self._pgn_cache[0] != key:
            self._pgn_cache = (key, game_pgn(self.game, self.played_at))
        return self._pgn_cache[1]

    def save_pgn(self) -> None:
        if self.game is None or not self.game.over:
            return
        folder = Path.home() / "Downloads"
        if not folder.is_dir():
            folder = data_dir() / "games"
        path = folder / pgn_filename(self.played_at)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path.write_text(self.pgn(), encoding="utf-8")
        except OSError:
            self.show_notice(tx("coach.pgn.save_failed"))
            return
        self.show_notice(tx("coach.pgn.saved", path=str(path)))

    def show_notice(self, text: Text) -> None:
        self.notice = (text, self.clock + NOTICE_TIME)

    def open_summary(self) -> None:
        if self.game is not None and self.game.over:
            if self.summary is None:
                self.summary = _Summary(self.clock)
            self.summary.opened_at = self.clock

    def close_summary(self) -> None:
        if self.summary is not None:
            self.summary.opened_at = -1.0

    def summary_visible(self) -> bool:
        return self.summary is not None and 0 <= self.summary.opened_at <= self.clock

    # ================================================================ browsing moves (◀ ▶)
    def view_board(self, index: int) -> chess.Board:
        assert self.game is not None
        board = chess.Board(self.game.start_fen)
        for move in self.game.board.move_stack[:index]:
            board.push(move)
        return board

    def can_navigate(self) -> bool:
        return self.game is not None and bool(self.game.board.move_stack) and self.phase not in ("intro", "lesson_wrong") and not self.summary_visible()

    def go_live(self) -> None:
        if self.view_index is None or self.game is None:
            return
        self.view_index = None
        board = self.game.board
        self.board_view.set_position(board, board.peek() if board.move_stack else None, animate=False)
        self._restore_live_badge()

    def _restore_live_badge(self) -> None:
        game = self.game
        self.board_view.feedback = None
        if game is None or not game.records:
            return
        last = game.records[-1]
        if last.by_player and last.classification is not None:
            self.board_view.show_badge(last.move.to_square, last.classification, effect=False)

    def step_view(self, delta: int) -> None:
        game = self.game
        if game is None or not self.can_navigate():
            return
        total = len(game.board.move_stack)
        current = total if self.view_index is None else self.view_index
        self.jump_to(max(0, min(total, current + delta)))

    def jump_to(self, index: int) -> None:
        game = self.game
        if game is None or not self.can_navigate():
            return
        stack = game.board.move_stack
        total = len(stack)
        index = max(0, min(total, index))
        current = total if self.view_index is None else self.view_index
        if index == current:
            return
        if index == current + 1:
            before = self.view_board(current)
            self._show_move(before, stack[current])
        elif index == current - 1:
            board = self.view_board(index)
            self.board_view.set_position(board, board.peek() if board.move_stack else None, undo=stack[index])
            self.play_sound(board, stack[index])
        else:
            board = self.view_board(index)
            self.board_view.set_position(board, board.peek() if board.move_stack else None, animate=False)
        self.view_index = None if index == total else index
        self.board_view.feedback = None
        if self.view_index is None:
            self._restore_live_badge()
        elif index > 0:
            record = game.records[index - 1]
            if record.classification is not None:
                self.board_view.show_badge(record.move.to_square, record.classification, effect=False)
        self.board_view.interactive = self.view_index is None and self.phase == "player"

    def viewed_record(self) -> MoveRecord | None:
        if self.game is None or self.view_index is None or self.view_index == 0:
            return None
        return self.game.records[self.view_index - 1]

    # ================================================================ actions from the browser
    def action(self, name: str, data: dict[str, Any]) -> None:
        if self.confirm is not None:
            if name == "confirm_yes":
                action = self.confirm[1]
                self.confirm = None
                action()
            elif name == "confirm_no":
                self.confirm = None
            return
        if self.summary_visible():
            if name == "review":
                self.close_summary()
            elif name == "rematch":
                self.rematch()
            elif name == "menu":
                self.app.go("coach")
            elif name == "pgn_save":
                self.save_pgn()
            elif name == "pgn_copied":
                self.show_notice(tx("coach.pgn.copied"))
            return
        handlers: dict[str, Callable[[], None]] = {
            "hint": self.hint,
            "takeback": self.take_back,
            "resign": self.ask_resign,
            "menu": self.leave_game,
            "rematch": self.rematch,
            "summary": self.open_summary,
            "retry": self.take_back,
            "continue": self.continue_after_pause,
            "play_on": self.continue_after_lesson,
            "repeat": self.rematch,
            "other": lambda: self.app.go("coach"),
            "pgn_save": self.save_pgn,
            "pgn_copied": lambda: self.show_notice(tx("coach.pgn.copied")),
        }
        if name == "move":
            self.board_view.play(str(data.get("uci", "")))
        elif name == "step":
            delta = data.get("delta")
            self.step_view(max(-1, min(1, delta)) if isinstance(delta, int) and not isinstance(delta, bool) else 0)
        elif name == "jump":
            index = data.get("index")
            if isinstance(index, int) and not isinstance(index, bool):
                self.jump_to(index)
        elif name in handlers:
            handlers[name]()

    # ================================================================ update
    def update(self, dt: float) -> None:
        super().update(dt)
        game = self.game
        if game is None:
            return
        # Arrows: the better move when browsing the game, or the coach's live hint / suggestion.
        visible_fen = self.board_view.board.fen()
        arrows: list[tuple[chess.Square, chess.Square, str]] = []
        record = self.viewed_record()
        if record is not None:
            if record.best_uci and record.classification in WEAK:
                best = chess.Move.from_uci(record.best_uci)
                arrows.append((best.from_square, best.to_square, BEST_ARROW_REVIEW))
        elif self.arrow is not None and visible_fen in self.arrow[1]:
            move, _, color = self.arrow
            arrows.append((move.from_square, move.to_square, color))
        self.board_view.arrows = arrows

    # ================================================================ snapshot
    def _controls(self) -> list[dict[str, Any]]:
        game = self.game
        if game is None:
            return []
        live = self.view_index is None

        def button(name: str, key: str, short: str, enabled: bool = True, style: str = "secondary") -> dict[str, Any]:
            return {"id": name, "label": t(key), "short": t(short), "enabled": enabled, "style": style}

        if game.over:
            return [
                button("summary", "coach.btn.summary", "coach.btn.summary_short"),
                button("rematch", "coach.btn.rematch", "coach.btn.rematch", style="primary"),
                button("menu", "coach.btn.menu", "coach.btn.menu"),
            ]
        if game.lesson_active or self.phase == "lesson_done":
            return [
                button("hint", "coach.btn.hint", "coach.btn.hint", self.phase == "player" and live),
                button("menu", "coach.btn.end_lesson", "coach.btn.end_lesson"),
            ]
        return [
            button("hint", "coach.btn.hint", "coach.btn.hint", self.phase == "player" and live),
            button("takeback", "coach.btn.takeback", "coach.btn.takeback_short", self.phase in ("player", "paused") and game.can_take_back()),
            button("resign", "coach.btn.resign", "coach.btn.resign_short", self.phase not in ("intro", "over")),
            button("menu", "coach.btn.menu", "coach.btn.menu"),
        ]

    def _card_buttons(self) -> list[dict[str, Any]]:
        if self.phase == "paused" and self.view_index is None:
            return [
                {"id": "retry", "label": t("coach.btn.retry"), "style": "primary"},
                {"id": "continue", "label": t("coach.btn.continue"), "style": "secondary"},
            ]
        if self.phase == "lesson_done":
            return [
                {"id": "play_on", "label": t("coach.btn.play_on"), "style": "primary"},
                {"id": "repeat", "label": t("coach.btn.repeat"), "style": "secondary"},
                {"id": "other", "label": t("coach.btn.other"), "style": "secondary"},
            ]
        return []

    def _subtitle(self, game: CoachGame) -> str:
        if game.lesson is not None and (game.lesson_active or self.phase == "lesson_done"):
            done, total = game.lesson_progress()
            return t("coach.lesson_progress", i=done, n=total, m=game.lesson_mistakes)
        if game.adaptive:
            return t("coach.trainer_adaptive", elo=game.elo)
        return t("coach.trainer_elo", elo=game.elo, level=t(describe_level(game.elo)))

    def _strips(self, game: CoachGame) -> list[dict[str, Any]]:
        """Player bars above and below the board: who plays, whose turn it is, captured pieces, material advantage."""
        board = self.board_view.board
        player = game.player_color
        top_is_player = self.board_view.orientation != player
        material = {c: sum(_VALUES[p] * len(board.pieces(p, c)) for p in _VALUES) for c in (chess.WHITE, chess.BLACK)}
        coach = self.app.profile.coach
        strips = []
        for is_player in (top_is_player, not top_is_player):
            color = player if is_player else not player
            if is_player:
                name = t("coach.you")
                detail = t("coach.player_level", elo=coach.level) if coach.level is not None else t("coach.player_calibration", n=coach.calibration_progress())
            else:
                name = t("coach.name")
                detail = t("coach.adaptive_short", elo=game.elo) if game.adaptive else f"({game.elo})"
            captured = []
            for piece_type in _PIECE_ORDER:
                count = len(board.pieces(piece_type, not color))
                captured += [chess.piece_symbol(piece_type)] * max(0, _START_COUNT[piece_type] - count)
            strips.append(
                {
                    "player": is_player,
                    "name": name,
                    "detail": detail,
                    "toMove": board.turn == color and not game.over,
                    "capturedColor": "white" if color != chess.WHITE else "black",
                    "captured": captured,
                    "diff": material[color] - material[not color],
                }
            )
        return strips

    def _moves(self, game: CoachGame) -> dict[str, Any]:
        records = game.records
        offset = 1 if records and not chess.Board(records[0].fen_before).turn else 0  # game starting with Black to move
        current = (len(records) if self.view_index is None else self.view_index) - 1
        return {
            "first": chess.Board(game.start_fen).fullmove_number,
            "offset": offset,
            "current": current,
            "list": [{"san": uci_san(r.fen_before, r.uci), "cls": r.classification, "player": r.by_player} for r in records],
        }

    def _summary(self, game: CoachGame) -> dict[str, Any] | None:
        summary = self.summary
        if summary is None or not self.summary_visible():
            return None
        coach = self.app.profile.coach
        change = summary.change
        lines: list[dict[str, str]] = []
        if summary.archived is not None:
            saved = summary.archived
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(saved.timestamp))
            delta = round(saved.rating_after - saved.rating_before)
            lines.append({"text": t("coach.archive.played", date=when, delta=f"{delta:+d}"), "color": "soft"})
        elif not summary.counted:
            lines.append({"text": t("coach.summary.not_counted"), "color": "muted"})
        elif change is not None and change.calibrated_now and coach.level is not None:
            lines.append({"text": t("coach.summary.calibrated", elo=coach.level), "color": "accent"})
        elif change is not None and change.level_before is not None and change.level_after != change.level_before:
            lines.append({"text": t("coach.summary.level_changed", before=change.level_before, after=change.level_after), "color": "accent"})
        elif coach.level is not None:
            lines.append({"text": tn("coach.summary.level", coach.games_to_update(), elo=coach.level), "color": "soft"})
        else:
            lines.append({"text": t("coach.summary.calibration", n=coach.calibration_progress(), total=CALIBRATION_GAMES), "color": "soft"})
        helps = game.takebacks + game.hints
        if helps and summary.counted and summary.archived is None:
            lines.append({"text": t("coach.summary.helps", n=helps, score=fmt_decimal(game.score(), 1)), "color": "muted"})
        counts_you, counts_trainer = game.counts(True), game.counts(False)
        result = game.result or "draw"

        def accuracy(player: bool) -> str:
            value = game.accuracy(player)
            return "—" if value is None else f"{fmt_decimal(value, 1)}%"

        return {
            "result": result,
            "title": t(f"coach.result.{result}"),
            "reason": t(f"coach.reason.{game.reason}") if game.reason else "",
            "accuracy": [{"label": t("coach.you"), "value": accuracy(True)}, {"label": t("coach.name"), "value": accuracy(False)}],
            "rows": [{"cls": cls, "you": counts_you[cls], "trainer": counts_trainer[cls]} for cls in CLASSES if counts_you[cls] or counts_trainer[cls]],
            "lines": lines,
        }

    def _review(self, game: CoachGame) -> dict[str, Any] | None:
        """After the game: the evaluation graph (White's winning chance after every ply) and the PGN."""
        if not game.over or not game.records:
            return None
        current = len(game.records) if self.view_index is None else self.view_index
        return {"evals": eval_curve(game.records), "current": current, "pgn": self.pgn(), "archived": self.archived is not None}

    def _eval(self, game: CoachGame) -> dict[str, Any]:
        """The evaluation bar: the engine's view of the position on the board (its analysis, or the score of the move
        that led there). ``None`` while it is not known yet — the bar then stays where it was."""
        current = len(game.records) if self.view_index is None else self.view_index
        fen = game.records[current].fen_before if current < len(game.records) else game.board.fen()
        info = self.analyses.get(fen)
        score = info.score if info is not None else None
        if score is None and 0 < current <= len(game.records):
            value = game.records[current - 1].score
            score = to_white_score(value, WHITE) if value is not None else None
        return {"score": brain.score_json(score), "whiteBottom": game.player_color == chess.WHITE}

    def _notice(self) -> str | None:
        if self.notice is None or self.clock > self.notice[1]:
            return None
        return self.notice[0]()

    def _comment(self) -> dict[str, Any]:
        record = self.viewed_record()
        if record is not None:
            return {"text": render_comment(record.comment), "cls": record.classification if record.by_player else None, "seq": -1}
        return {"text": render_comment(self.main), "cls": self.main_cls, "seq": self.main_seq}

    def _side(self) -> dict[str, Any] | None:
        if self.view_index is not None:
            return None
        if self.phase in ("judging", "trainer"):
            return {"text": t("coach.analyzing" if self.phase == "judging" else "coach.thinking"), "busy": True, "threat": False}
        if not self.side:
            return None
        return {"text": render_comment(self.side), "busy": False, "threat": any(p.key.startswith("coach.threat") for p in self.side)}

    def snapshot(self) -> dict[str, Any]:
        game = self.game
        if game is None:
            return {}
        navigable = self.can_navigate()
        total = len(game.board.move_stack)
        current = total if self.view_index is None else self.view_index
        name_id = game.opening_id()
        return {
            "game": self.game_seq,
            "board": self.board_view.snapshot(),
            "expression": self.expression(),
            "strips": self._strips(game),
            "card": {
                "subtitle": self._subtitle(game),
                "opening": opening_name(name_id) if name_id else "",
                "comment": self._comment(),
                "side": self._side(),
                "buttons": self._card_buttons(),
            },
            "controls": self._controls(),
            "nav": {"prev": navigable and current > 0, "next": navigable and self.view_index is not None},
            "moves": self._moves(game),
            "eval": self._eval(game),
            "summary": self._summary(game),
            "review": self._review(game),
            "notice": self._notice(),
            "confirm": {"text": self.confirm[0](), "yes": t(self.confirm[2])} if self.confirm is not None else None,
        }
