"""Coach game screen (also used for opening lessons).

Flow of a single turn:
 1. **Player move** — while the player is thinking, the engine analyses the position in the
    background (MultiPV 3) so it already knows the best moves. A move from opening theory is
    immediately rated as "book".
 2. **Evaluation** — if the player's move is among the top 3, its evaluation is already known;
    otherwise the engine also analyses the position after the move. The drop in winning chances
    gives the move class (best, mistake, blunder…) and the coach's comment. After a mistake or a
    blunder the game pauses: you can take the move back (an arrow shows a better one) or play on.
 3. **Coach move** — from the opening book or from a search whose strength depends on Elo
    (``coach.strength``); the coach explains what its move does and warns about its threats.

Engine requests are sent one at a time (a job queue) — the engine process computes one thing at a time.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING

import chess
import pygame

from ...brain.notation import uci_san
from ...coach.advice import Comment, Phrase, San, book_comment, phrase, player_comment, render_comment, trainer_comment
from ...coach.game import CoachGame, MoveRecord
from ...coach.openings import Opening, book_moves, comment_key, is_book_move, move_comment, opening_name
from ...coach.review import CLASSES, SERIOUS, WEAK, classify, move_accuracy, score_for, win_drop, win_percent
from ...coach.strength import choose_move, describe_level, strength_for
from ...engine.process import DoneEvent, EngineEvent, ErrorEvent
from ...engine.types import MATE, SearchInfo
from ...i18n import fmt_decimal, t, tn
from ...puzzles.validator import is_sacrifice
from ...rating.coach_profile import CALIBRATION_GAMES, LevelChange
from ...rating.profile import RatingChange
from .. import fonts, gfx, theme
from ..anim import ease_out_back, ease_out_cubic
from ..badges import COLORS, draw_badge
from ..board_view import BoardView
from ..coach_avatar import draw_coach
from ..pieces import piece_surface
from ..scale import fs, px
from ..widgets import Button, ScrollArea, card, draw_text, draw_wrapped, wrapped_height
from .base import Screen

if TYPE_CHECKING:
    from ..app import App

#: Analysis of the player's position (to rate their move and for hints).
COACH_DEPTH = 5
PRE_TIME = 1600
POST_TIME = 1000
#: The coach "thinks" at least this long (s) even if it finishes sooner — the game feels more natural.
MIN_THINK = 0.7
#: Pause between the comment on the player's move and the coach's move.
TRAINER_PAUSE = 0.35
LESSON_REPLY = 0.75
#: The coach plays from the opening book for at most this many plies.
BOOK_PLIES = 24

Text = Callable[[], str]
Arrow = tuple[chess.Move, frozenset[str], tuple[int, ...]]

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


_icons: dict[int, pygame.Surface] = {}


def _player_icon(size: int) -> pygame.Surface:
    """Round player icon: a silhouette (head and shoulders) clipped to a circle."""
    cached = _icons.get(size)
    if cached is not None:
        return cached
    ss = 4
    big = pygame.Surface((size * ss, size * ss), pygame.SRCALPHA)
    s = size * ss
    big.fill((*theme.SURFACE_3[:3], 255))
    pygame.draw.circle(big, theme.TEXT_SOFT, (s // 2, round(s * 0.4)), round(s * 0.19))
    pygame.draw.ellipse(big, theme.TEXT_SOFT, pygame.Rect(round(s * 0.18), round(s * 0.66), round(s * 0.64), round(s * 0.6)))
    mask = pygame.Surface(big.get_size(), pygame.SRCALPHA)
    pygame.draw.circle(mask, (255, 255, 255, 255), (s // 2, s // 2), s // 2)
    big.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    surf = pygame.transform.smoothscale(big, (size, size))
    _icons[size] = surf
    return surf


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
    """The coach's best evaluation in the position after the player's move — used to rate the coach's move."""

    fen: str
    value: int
    best_uci: str | None


@dataclass
class _Summary:
    opened_at: float
    change: LevelChange | None = None
    counted: bool = False
    notes: list[str] = field(default_factory=list)


class CoachGameScreen(Screen):
    def __init__(self, app: App) -> None:
        super().__init__(app)
        self.board_view = BoardView()
        self.board_view.on_move = self.on_player_move
        self.game: CoachGame | None = None
        self.settings: tuple[chess.Color, int, bool, Opening | None] = (chess.WHITE, 800, False, None)
        self.strength = strength_for(800)
        self.rng = random.Random()
        self.clock = 0.0
        self.timers: list[tuple[float, Callable[[], None]]] = []
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
        self.main_at = 0.0
        self.side: Comment = ()
        self.side_at = 0.0
        self.reaction = "neutral"
        self.reaction_until = 0.0
        self.arrow: Arrow | None = None
        self.view_index: int | None = None
        self.summary: _Summary | None = None
        self.confirm: tuple[Text, Callable[[], None], str] | None = None
        self.wide = True
        self.page: pygame.Surface | None = None
        self.page_h = 0
        self.scroll_y = 0.0
        self.moves_scroll = ScrollArea(stick_to_bottom=True)
        self.move_cells: list[tuple[int, pygame.Rect]] = []

        self.btn_prev = Button("", partial(self.step_view, -1), icon="left")
        self.btn_next = Button("", partial(self.step_view, 1), icon="right")
        self.btn_hint = Button(tx("coach.btn.hint"), self.hint, size=14)
        self.btn_takeback = Button(tx("coach.btn.takeback"), self.take_back, size=14)
        self.btn_resign = Button(tx("coach.btn.resign"), self.ask_resign, size=14)
        self.btn_menu = Button(tx("coach.btn.menu"), self.leave_game, size=14)
        self.btn_rematch = Button(tx("coach.btn.rematch"), self.rematch, style="primary", size=14)
        self.btn_summary = Button(tx("coach.btn.summary"), self.open_summary, size=14)
        # Buttons in the coach card (pause after a mistake, end of lesson).
        self.btn_retry = Button(tx("coach.btn.retry"), self.take_back, style="primary", size=13)
        self.btn_continue = Button(tx("coach.btn.continue"), self.continue_after_pause, size=13)
        self.btn_play_on = Button(tx("coach.btn.play_on"), self.continue_after_lesson, style="primary", size=13)
        self.btn_repeat = Button(tx("coach.btn.repeat"), self.rematch, size=13)
        self.btn_other = Button(tx("coach.btn.other"), partial(app.go, "coach"), size=13)
        # Summary and confirmations.
        self.btn_review = Button(tx("coach.btn.review"), self.close_summary, size=14)
        self.btn_sum_rematch = Button(tx("coach.btn.rematch"), self.rematch, style="primary", size=14)
        self.btn_sum_menu = Button(tx("coach.btn.menu"), partial(app.go, "coach"), size=14)
        self.btn_yes = Button(tx("coach.resign_yes"), self._confirm_yes, style="danger", size=14)
        self.btn_no = Button(tx("common.cancel"), self._confirm_no, size=14)

        self.top_strip = pygame.Rect(0, 0, 0, 0)
        self.bottom_strip = pygame.Rect(0, 0, 0, 0)
        self.controls_rect = pygame.Rect(0, 0, 0, 0)
        self.card_rect = pygame.Rect(0, 0, 0, 0)
        self.moves_rect = pygame.Rect(0, 0, 0, 0)

    # ================================================================ start and lifecycle
    def start(self, color: chess.Color, elo: int, adaptive: bool, lesson: Opening | None) -> None:
        self._reset_engine()
        self.timers.clear()
        self.settings = (color, elo, adaptive, lesson)
        self.game = CoachGame(color, elo, adaptive=adaptive, lesson=lesson)
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
        self.side = ()
        bv = self.board_view
        bv.orientation = color
        bv.player_color = color
        bv.interactive = False
        bv.feedback = None
        bv.arrows = []
        bv.hint_square = None
        bv.clear_drawings()
        bv.set_position(self.game.board, None, animate=False)
        if lesson is not None:
            self.say((phrase("coach.lesson_intro", name=Phrase(f"opening.{lesson.id}.name")), Phrase(f"opening.{lesson.id}.desc")))
        else:
            side = "coach.intro_white" if color == chess.WHITE else "coach.intro_black"
            self.say((phrase("coach.game_intro", elo=elo), Phrase(side)))
        self.react("happy", 3.0)
        self.phase = "intro"
        self.moves_scroll.scroll_to_top()
        self.moves_scroll.stick_to_bottom = True
        self.schedule(0.9, self.next_turn)

    def rematch(self) -> None:
        color, elo, adaptive, lesson = self.settings
        if lesson is None and adaptive and self.app.profile.coach.level is not None:
            elo = self.app.profile.coach.level  # "Your level" may have just changed
        self.start(color, elo, adaptive, lesson)

    def enter(self) -> None:
        if self.job is not None:
            # Back on the screen: restart the interrupted engine job.
            self.jobs.insert(0, self.job)
            self.job = None
            self.job_id = None
        self._pump()

    def leave(self) -> None:
        self.app.engine.stop()

    def schedule(self, delay: float, action: Callable[[], None]) -> None:
        self.timers.append((self.clock + delay, action))

    def in_progress(self) -> bool:
        return self.game is not None and not self.game.over and self.phase != "idle"

    # ================================================================ coach comments and expression
    def say(self, comment: Comment, cls: str | None = None) -> None:
        self.main = comment
        self.main_cls = cls
        self.main_at = self.clock

    def say_side(self, comment: Comment) -> None:
        self.side = comment
        self.side_at = self.clock

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
        self._play_move_sound(board_before, move)

    def _play_move_sound(self, board_before: chess.Board, move: chess.Move) -> None:
        after = board_before.copy(stack=False)
        after.push(move)
        if after.is_check():
            self.app.sounds.play("check")
        elif move.promotion:
            self.app.sounds.play("promote")
        elif board_before.is_castling(move):
            self.app.sounds.play("castle")
        else:
            self.app.sounds.play("capture" if board_before.is_capture(move) else "move")

    # ---------------------------------------------------------------- player move
    def on_player_move(self, move: chess.Move) -> None:
        game = self.game
        if game is None or self.phase != "player" or game.over or not game.player_to_move:
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
        score = info.score
        played = score_for(score, judge.board.turn)
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
        recapture = last is not None and board.is_capture(move) and move.to_square == last.to_square
        cls = classify(
            drop, is_best=is_best, sacrifice=is_sacrifice(board, move), second_drop=second, win_before=win_percent(best_value), recapture=recapture
        )
        record.classification = cls
        record.accuracy = move_accuracy(drop)
        record.best_uci = None if is_best else best.move
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
                self.app.sounds.play("brilliant")
            elif cls in SERIOUS:
                self.app.sounds.play("error")
        if game.over:
            self.phase = "waiting"
            self.schedule(0.6, self.next_turn)
            return
        if cls in SERIOUS:
            self.phase = "paused"
            if record.best_uci:
                after = board.copy(stack=False)
                after.push(move)
                self.arrow = (chess.Move.from_uci(record.best_uci), frozenset({board.fen(), after.fen()}), (*COLORS["best"][:3], 210))
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
        self.app.sounds.play("error")
        self.say((first, Phrase(key)), None)
        self.react("concerned")
        self.arrow = (expected, frozenset({fen}), (*theme.ACCENT[:3], 200))
        self.board_view.interactive = False
        self.phase = "lesson_wrong"
        self.schedule(0.95, partial(self._undo_lesson_move, board_before, move))

    def _undo_lesson_move(self, board_before: chess.Board, move: chess.Move) -> None:
        if self.game is None or self.phase != "lesson_wrong":
            return
        self.board_view.set_position(board_before, board_before.peek() if board_before.move_stack else None, undo=move)
        self._play_move_sound(board_before, move)
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
        self.app.sounds.play("success")
        if game.board.move_stack:
            self.board_view.celebrate(game.board.peek().to_square)

    def continue_after_lesson(self) -> None:
        game = self.game
        if game is None or self.phase != "lesson_done":
            return
        game.continue_after_lesson()
        self.say((Phrase("coach.lesson_continue"),), None)
        self.next_turn()

    # ---------------------------------------------------------------- coach move
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
            elif ref is not None and ref.fen == board_before.fen():
                self.pending_grade = (record, ref)
        self.trainer_ref = None
        self._show_move(board_before, move)
        self.say_side(record.comment)
        self.next_turn()

    def _grade_trainer_move(self, fen: str, info: SearchInfo | None) -> None:
        """Rates the coach's move once the evaluation of the position after it is known (analysis on the player's turn)."""
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

    # ---------------------------------------------------------------- coach help
    def hint(self) -> None:
        game = self.game
        if game is None or self.phase != "player" or game.over or self.view_index is not None:
            return
        if game.lesson_active:
            expected = game.lesson_expected()
            if expected is None:
                return
            fen = game.board.fen()
            self.arrow = (expected, frozenset({fen}), (*theme.VIOLET[:3], 210))
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
        self.arrow = (move, frozenset({fen}), (*theme.VIOLET[:3], 210))
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
        self._play_move_sound(first, undone[0])
        if len(undone) > 1:
            final = game.board.copy()

            def second() -> None:
                self.board_view.set_position(final, final.peek() if final.move_stack else None, undo=undone[1])
                self._play_move_sound(final, undone[1])

            self.schedule(0.28, second)
        fen = game.board.fen()
        info = self.analyses.get(fen)
        if info is not None and info.best_move:
            self.arrow = (chess.Move.from_uci(info.best_move), frozenset({fen}), (*COLORS["best"][:3], 210))
        self.say((Phrase("coach.takeback"),), None)
        self.react("neutral", 0.5)
        self.side = ()
        self.phase = "waiting"
        self.schedule(0.3 * len(undone), self.begin_player_turn)

    # ---------------------------------------------------------------- game over
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
        """The "Menu" button: abandoning a started game counts as resigning (from move 5)."""
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
        """Starting a new game from the menu: the current one (from move 5) counts as resigned."""
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
        change = self._record() if game.counts_for_rating() and not game.recorded else None
        result = game.result or "draw"
        reason = Phrase(f"coach.reason.{game.reason}") if game.reason else Phrase("")
        self.say((reason, Phrase(f"coach.end.{result}")), None)
        if result == "win":
            self.react("excited", 5.0)
            self.app.sounds.play("success")
            if game.board.move_stack:
                self.board_view.celebrate(game.board.peek().to_square)
        else:
            self.react("happy" if result == "loss" else "neutral", 4.0)
        self.summary = _Summary(self.clock + 0.9, change, change is not None)

    def _record(self) -> LevelChange | None:
        game = self.game
        if game is None or game.recorded or game.result is None:
            return None
        game.recorded = True
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
        )
        self.app.save()
        self.app.topbar.on_rating_change(RatingChange(change.rating_before, change.rating_after, change.rating_after - change.rating_before, game.score(), coach.rating.rd))
        return change

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

    def _confirm_yes(self) -> None:
        if self.confirm is not None:
            action = self.confirm[1]
            self.confirm = None
            action()

    def _confirm_no(self) -> None:
        self.confirm = None

    # ================================================================ move browsing (◀ ▶)
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
        current = total if self.view_index is None else self.view_index
        if index == current:
            return
        if index == current + 1:
            before = self.view_board(current)
            self._show_move(before, stack[current])
        elif index == current - 1:
            board = self.view_board(index)
            self.board_view.set_position(board, board.peek() if board.move_stack else None, undo=stack[index])
            self._play_move_sound(board, stack[index])
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

    # ================================================================ layout
    def layout(self, rect: pygame.Rect) -> None:
        super().layout(rect)
        g = px(18)
        w, h = rect.size
        strip_h = px(36)
        controls_h = px(46)
        self.wide = w >= px(860) and w > h * 0.95
        if self.wide:
            panel_w = max(px(360), min(px(520), int(w * 0.36)))
            left_w = w - panel_w - 3 * g
            size = min(h - 2 * g - 2 * strip_h - px(8) - controls_h - px(12), left_w)
            size = max(px(240), size - size % 8)
            bx = rect.x + g + (left_w - size) // 2
            top = rect.y + g
            col_x = rect.right - g - panel_w
            card_h = min(px(400), int((h - 2 * g) * 0.56))
            self.card_rect = pygame.Rect(col_x, top, panel_w, card_h)
            self.moves_rect = pygame.Rect(col_x, self.card_rect.bottom + px(14), panel_w, rect.bottom - g - self.card_rect.bottom - px(14))
        else:
            size = min(w - 2 * g, int(h * 0.62))
            size = max(px(200), size - size % 8)
            bx = (w - size) // 2
            top = g
        self.top_strip = pygame.Rect(bx, top, size, strip_h)
        self.board_view.rect = pygame.Rect(bx, self.top_strip.bottom + px(4), size, size)
        self.bottom_strip = pygame.Rect(bx, self.board_view.rect.bottom + px(4), size, strip_h)
        self.controls_rect = pygame.Rect(bx, self.bottom_strip.bottom + px(8), size, controls_h)
        if not self.wide:
            self.controls_rect = pygame.Rect(g, self.bottom_strip.bottom + px(8), w - 2 * g, controls_h)
            self.card_rect = pygame.Rect(g, self.controls_rect.bottom + px(14), w - 2 * g, px(360))
            self.moves_rect = pygame.Rect(g, self.card_rect.bottom + px(14), w - 2 * g, px(280))
            self.page_h = self.moves_rect.bottom + g
            self.scroll_y = min(self.scroll_y, max(0, self.page_h - h))
        self._layout_controls()

    def _controls(self) -> list[tuple[Button, str, str]]:
        game = self.game
        if game is None:
            return []
        if game.over:
            return [(self.btn_summary, "coach.btn.summary", "coach.btn.summary_short"), (self.btn_rematch, "coach.btn.rematch", "coach.btn.rematch"), (self.btn_menu, "coach.btn.menu", "coach.btn.menu")]
        if game.lesson_active or self.phase == "lesson_done":
            return [(self.btn_hint, "coach.btn.hint", "coach.btn.hint"), (self.btn_menu, "coach.btn.end_lesson", "coach.btn.end_lesson")]
        return [
            (self.btn_hint, "coach.btn.hint", "coach.btn.hint"),
            (self.btn_takeback, "coach.btn.takeback", "coach.btn.takeback_short"),
            (self.btn_resign, "coach.btn.resign", "coach.btn.resign_short"),
            (self.btn_menu, "coach.btn.menu", "coach.btn.menu"),
        ]

    def _layout_controls(self) -> None:
        r = self.controls_rect
        controls = self._controls()
        for button in (self.btn_hint, self.btn_takeback, self.btn_resign, self.btn_menu, self.btn_rematch, self.btn_summary):
            button.visible = any(button is entry[0] for entry in controls)
        nav_w = 2 * r.height + px(16)
        self.btn_prev.rect = pygame.Rect(r.x, r.y, r.height, r.height)
        self.btn_next.rect = pygame.Rect(r.x + r.height + px(6), r.y, r.height, r.height)
        if not controls:
            return
        gap = px(8)
        avail = r.width - nav_w - (len(controls) - 1) * gap
        long_keys = [entry[1] for entry in controls]
        widths = [fonts.text_size(t(key), fs(14), "bold")[0] + px(24) for key in long_keys]
        keys = long_keys if sum(widths) <= avail else [entry[2] for entry in controls]
        widths = [fonts.text_size(t(key), fs(14), "bold")[0] + px(24) for key in keys]
        extra = (avail - sum(widths)) / len(controls)
        x = r.x + nav_w
        for (button, _, _), key, bw in zip(controls, keys, widths):
            button.label = tx(key)
            width = max(px(40), int(bw + extra))
            button.rect = pygame.Rect(x, r.y, width, r.height)
            x += width + gap

    # ================================================================ events
    def _to_page(self, pos: tuple[int, int]) -> tuple[int, int]:
        return (pos[0] - self.rect.x, pos[1] - self.rect.y + int(self.scroll_y))

    def handle(self, event: pygame.event.Event) -> None:
        if self.confirm is not None:
            self.btn_yes.handle(event)
            self.btn_no.handle(event)
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.confirm = None
            return
        if self.summary_visible():
            for button in (self.btn_review, self.btn_sum_rematch, self.btn_sum_menu):
                if button.handle(event):
                    return
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_RETURN):
                self.close_summary()
            return
        mouse = pygame.mouse.get_pos()
        if not self.wide:
            mouse = self._to_page(mouse)
            if event.type == pygame.MOUSEWHEEL and not self.moves_scroll.rect.collidepoint(mouse):
                max_scroll = max(0, self.page_h - self.rect.height)
                self.scroll_y = max(0.0, min(max_scroll, self.scroll_y - event.y * px(60)))
                return
            if hasattr(event, "pos"):
                event = pygame.event.Event(event.type, {**event.dict, "pos": self._to_page(event.pos)})
        if self.moves_scroll.handle(event, mouse):
            return
        if self.board_view.handle(event):
            return
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_LEFT:
                self.step_view(-1)
            elif event.key == pygame.K_RIGHT:
                self.step_view(1)
        buttons = [self.btn_prev, self.btn_next, self.btn_hint, self.btn_takeback, self.btn_resign, self.btn_menu, self.btn_rematch, self.btn_summary]
        buttons += self._card_buttons()
        for button in buttons:
            if button.handle(event):
                return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for index, rect in self.move_cells:
                if rect.collidepoint(event.pos) and self.moves_scroll.rect.collidepoint(event.pos):
                    self.jump_to(index)
                    return

    def _card_buttons(self) -> list[Button]:
        if self.phase == "paused" and self.view_index is None:
            return [self.btn_retry, self.btn_continue]
        if self.phase == "lesson_done":
            return [self.btn_play_on, self.btn_repeat, self.btn_other]
        return []

    # ================================================================ update
    def update(self, dt: float) -> None:
        self.clock += dt
        due = [timer for timer in self.timers if timer[0] <= self.clock]
        if due:
            self.timers = [timer for timer in self.timers if timer[0] > self.clock]
            for _, action in due:
                action()
        self.board_view.update(dt)
        if not self.wide:
            self.scroll_y = min(self.scroll_y, max(0, self.page_h - self.rect.height))
        game = self.game
        if game is None:
            return
        # Arrows: the better move when browsing the game, or a live hint / coach suggestion.
        visible_fen = self.board_view.board.fen()
        arrows: list[tuple[chess.Square, chess.Square, tuple[int, ...]]] = []
        record = self.viewed_record()
        if record is not None:
            if record.best_uci and record.classification in WEAK:
                best = chess.Move.from_uci(record.best_uci)
                arrows.append((best.from_square, best.to_square, (*COLORS["best"][:3], 200)))
        elif self.arrow is not None and visible_fen in self.arrow[1]:
            move, _, color = self.arrow
            arrows.append((move.from_square, move.to_square, color))
        self.board_view.arrows = arrows
        live = self.view_index is None
        self.btn_hint.enabled = self.phase == "player" and live
        self.btn_takeback.enabled = self.phase in ("player", "paused") and game.can_take_back() and not game.lesson_active
        self.btn_resign.enabled = self.phase not in ("intro", "over") and not game.over
        navigable = self.can_navigate()
        current = len(game.board.move_stack) if self.view_index is None else self.view_index
        self.btn_prev.enabled = navigable and current > 0
        self.btn_next.enabled = navigable and self.view_index is not None
        self._layout_controls()

    # ================================================================ drawing
    def draw(self, screen: pygame.Surface) -> None:
        surface = screen
        if not self.wide:
            size = (self.rect.width, self.page_h)
            if self.page is None or self.page.get_size() != size:
                self.page = pygame.Surface(size)
            self.page.blit(gfx.background(screen.get_size()), (0, -self.rect.y))
            surface = self.page
        game = self.game
        self.board_view.draw(surface)
        if game is not None:
            self._draw_strips(surface, game)
        self.btn_prev.draw(surface)
        self.btn_next.draw(surface)
        for button, _, _ in self._controls():
            button.draw(surface)
        self._draw_coach_card(surface)
        self._draw_moves(surface)
        if not self.wide and self.page is not None:
            screen.blit(self.page, self.rect.topleft, pygame.Rect(0, int(self.scroll_y), self.rect.width, self.rect.height))
            if self.page_h > self.rect.height:
                ratio = self.rect.height / self.page_h
                h = max(px(30), int(self.rect.height * ratio))
                y = self.rect.y + int((self.rect.height - h) * self.scroll_y / max(1, self.page_h - self.rect.height))
                gfx.rrect(screen, (*theme.BORDER[:3], 220), pygame.Rect(self.rect.right - px(6), y, px(4), h), px(2))
        if self.summary_visible():
            self._draw_summary(screen)
        if self.confirm is not None:
            self._draw_confirm(screen)

    # ---------------------------------------------------------------- player bars
    def _captured(self, board: chess.Board, color: chess.Color) -> list[chess.PieceType]:
        """Pieces of ``color`` missing from the board (captured by the opponent)."""
        missing = []
        for piece_type in _PIECE_ORDER:
            count = len(board.pieces(piece_type, color))
            missing += [piece_type] * max(0, _START_COUNT[piece_type] - count)
        return missing

    def _draw_strips(self, surface: pygame.Surface, game: CoachGame) -> None:
        board = self.board_view.board
        player = game.player_color
        top_is_player = self.board_view.orientation != player
        material = {c: sum(_VALUES[p] * len(board.pieces(p, c)) for p in _VALUES) for c in (chess.WHITE, chess.BLACK)}
        for rect, is_player in ((self.top_strip, top_is_player), (self.bottom_strip, not top_is_player)):
            color = player if is_player else not player
            to_move = board.turn == color and not game.over
            x = rect.x + px(2)
            cy = rect.centery
            icon = rect.height - px(4)
            if is_player:
                gfx.circle(surface, theme.BORDER, (x + icon // 2, cy), icon // 2 + max(1, px(1)))
                surface.blit(_player_icon(icon), (x, cy - icon // 2))
                name = t("coach.you")
                coach = self.app.profile.coach
                detail = t("coach.player_level", elo=coach.level) if coach.level is not None else t("coach.player_calibration", n=coach.calibration_progress())
            else:
                draw_coach(surface, (x + icon // 2, cy), icon, self.expression(), (self.clock % 4.2) < 0.13, theme.VIOLET if to_move else theme.BORDER)
                name = t("coach.name")
                detail = t("coach.adaptive_short", elo=game.elo) if game.adaptive else f"({game.elo})"
            tx_ = x + icon + px(10)
            label = draw_text(surface, name, (tx_, cy), fs(14), theme.TEXT, "bold", "midleft", max_width=rect.width // 3)
            info = draw_text(surface, detail, (label.right + px(8), cy), fs(12), theme.MUTED, "regular", "midleft", max_width=rect.width // 4)
            if to_move:
                gfx.circle(surface, theme.ACCENT, (info.right + px(10), cy), px(4))
            # The opponent's captured pieces and material advantage.
            captured = self._captured(board, not color)
            size = px(22)
            cx: float = rect.right - px(4)
            diff = material[color] - material[not color]
            if diff > 0:
                diff_rect = draw_text(surface, f"+{diff}", (cx, cy), fs(13), theme.TEXT_SOFT, "bold", "midright")
                cx = diff_rect.x - px(6)
            for piece_type in reversed(captured):
                img = piece_surface(chess.Piece(piece_type, not color), size)
                cx -= img.get_width() * 0.62
                if cx < info.right + px(24):
                    break
                surface.blit(img, img.get_rect(midleft=(round(cx), cy)))

    # ---------------------------------------------------------------- coach card
    def _shown_comment(self) -> tuple[Comment, str | None, float]:
        record = self.viewed_record()
        if record is not None:
            return record.comment, record.classification if record.by_player else None, -10.0
        return self.main, self.main_cls, self.main_at

    def _subtitle(self) -> str:
        game = self.game
        if game is None:
            return ""
        if game.lesson is not None and (game.lesson_active or self.phase == "lesson_done"):
            done, total = game.lesson_progress()
            return t("coach.lesson_progress", i=done, n=total, m=game.lesson_mistakes)
        if game.adaptive:
            return t("coach.trainer_adaptive", elo=game.elo)
        return t("coach.trainer_elo", elo=game.elo, level=t(describe_level(game.elo)))

    def _draw_coach_card(self, surface: pygame.Surface) -> None:
        r = self.card_rect
        card(surface, r)
        game = self.game
        if game is None:
            return
        pad = px(16)
        avatar = px(66)
        bob = round(-px(3) * max(0.0, 1 - (self.clock - self.main_at) / 0.3))
        center = (r.x + pad + avatar // 2, r.y + pad + avatar // 2 + bob)
        draw_coach(surface, center, avatar, self.expression(), (self.clock % 4.2) < 0.13, theme.ACCENT)
        x = r.x + pad + avatar + px(14)
        w = r.right - pad - x
        draw_text(surface, t("coach.name"), (x, r.y + pad + px(4)), fs(18), theme.TEXT, "bold", max_width=w)
        draw_text(surface, self._subtitle(), (x, r.y + pad + px(30)), fs(12), theme.MUTED, max_width=w)
        name_id = game.opening_id()
        if name_id:
            draw_text(surface, opening_name(name_id), (x, r.y + pad + px(48)), fs(12), COLORS["book"], "bold", max_width=w)

        buttons = self._card_buttons()
        buttons_h = px(40) + px(12) if buttons else 0
        side_text = self._side_text()
        side_h = 0
        inner_w = r.width - 2 * pad - px(24)
        if side_text:
            side_h = min(px(96), wrapped_height(side_text, inner_w - px(14), fs(13)) + px(18))
        bubble = pygame.Rect(r.x + pad, r.y + pad + avatar + px(12), r.width - 2 * pad, 0)
        bubble.height = r.bottom - pad - buttons_h - (side_h + px(8) if side_h else 0) - bubble.y
        comment, cls, at = self._shown_comment()
        appear = ease_out_back((self.clock - at) / 0.35, 1.3) if at >= 0 else 1.0
        gfx.rrect(surface, theme.SURFACE_2, bubble, px(14))
        tail = [(bubble.x + px(26), bubble.y), (bubble.x + px(34), bubble.y - px(10)), (bubble.x + px(44), bubble.y)]
        gfx.polygon(surface, theme.SURFACE_2, tail)
        ty = bubble.y + px(12)
        if cls is not None:
            badge_r = px(11)
            draw_badge(surface, (bubble.x + px(14) + badge_r, ty + badge_r), badge_r, cls, appear)
            draw_text(surface, t(f"cls.{cls}"), (bubble.x + px(22) + 2 * badge_r, ty + badge_r), fs(15), COLORS.get(cls, theme.TEXT), "bold", "midleft", max_width=bubble.width // 2)
            ty += 2 * badge_r + px(8)
        slide = round((1 - min(1.0, appear)) * px(6))
        text = render_comment(comment)
        text_rect = pygame.Rect(bubble.x + px(14), ty + slide, bubble.width - px(28), bubble.bottom - px(10) - ty)
        if text and text_rect.height > px(12):
            draw_wrapped(surface, text, text_rect, fs(15), theme.TEXT, shrink=True)
        if side_h:
            side = pygame.Rect(bubble.x, bubble.bottom + px(8), bubble.width, side_h)
            gfx.rrect(surface, (*theme.VIOLET[:3], 26), side, px(12))
            gfx.circle(surface, theme.VIOLET, (side.x + px(14), side.y + px(16)), px(4))
            color = theme.AMBER if any(p.key.startswith("coach.threat") for p in self.side) and self.view_index is None else theme.TEXT_SOFT
            draw_wrapped(surface, side_text, side.inflate(-px(40), -px(14)).move(px(10), 0), fs(13), color, shrink=True)
        if buttons:
            bw = (r.width - 2 * pad - (len(buttons) - 1) * px(8)) // len(buttons)
            for i, button in enumerate(buttons):
                button.rect = pygame.Rect(r.x + pad + i * (bw + px(8)), r.bottom - pad - px(40), bw, px(40))
                button.draw(surface)

    def _side_text(self) -> str:
        if self.view_index is not None:
            return ""
        if self.phase in ("judging", "trainer"):
            dots = "." * (1 + int(self.clock * 3) % 3)
            key = "coach.analyzing" if self.phase == "judging" else "coach.thinking"
            return t(key) + dots
        return render_comment(self.side) if self.side else ""

    # ---------------------------------------------------------------- move list
    def _draw_moves(self, surface: pygame.Surface) -> None:
        r = self.moves_rect
        card(surface, r)
        game = self.game
        pad = px(16)
        draw_text(surface, t("coach.moves"), (r.x + pad, r.y + px(14)), fs(15), theme.TEXT, "bold", max_width=r.width - 2 * pad)
        area = pygame.Rect(r.x + px(8), r.y + px(44), r.width - px(16), r.height - px(52))
        self.moves_scroll.rect = area
        self.move_cells = []
        if game is None:
            return
        records = game.records
        row_h = px(30)
        offset = 1 if records and not chess.Board(records[0].fen_before).turn else 0  # game starting with Black to move
        rows = (len(records) + offset + 1) // 2
        self.moves_scroll.content_height = rows * row_h
        self.moves_scroll.follow()
        clip = surface.get_clip()
        surface.set_clip(area)
        first_move = chess.Board(game.start_fen).fullmove_number
        current = (len(records) if self.view_index is None else self.view_index) - 1
        col_w = (area.width - px(46)) // 2
        for row in range(rows):
            y = area.y + row * row_h - int(self.moves_scroll.offset)
            if y + row_h < area.y or y > area.bottom:
                continue
            if row % 2 == 0:
                gfx.rrect(surface, (*theme.SURFACE_2[:3], 120), pygame.Rect(area.x, y, area.width, row_h), px(6))
            draw_text(surface, f"{first_move + row}.", (area.x + px(10), y + row_h // 2), fs(13), theme.DIM, "bold", "midleft")
            for col in range(2):
                index = row * 2 + col - offset
                if not 0 <= index < len(records):
                    continue
                record = records[index]
                cell = pygame.Rect(area.x + px(44) + col * col_w, y + px(2), col_w - px(6), row_h - px(4))
                self.move_cells.append((index + 1, cell))
                if index == current:
                    gfx.rrect(surface, (*theme.ACCENT[:3], 60), cell, px(6))
                bx = cell.x + px(4)
                if record.classification is not None:
                    draw_badge(surface, (cell.x + px(12), cell.centery), px(8), record.classification)
                    bx = cell.x + px(26)
                san = uci_san(record.fen_before, record.uci)
                draw_text(surface, san, (bx, cell.centery), fs(14), theme.TEXT if record.by_player else theme.TEXT_SOFT, "bold" if record.by_player else "regular", "midleft", max_width=cell.right - bx)
        surface.set_clip(clip)
        self.moves_scroll.draw_scrollbar(surface)

    # ---------------------------------------------------------------- game summary
    def _summary_lines(self) -> list[tuple[str, tuple[int, ...]]]:
        game = self.game
        assert game is not None and self.summary is not None
        coach = self.app.profile.coach
        change = self.summary.change
        lines: list[tuple[str, tuple[int, ...]]] = []
        if not self.summary.counted:
            lines.append((t("coach.summary.not_counted"), theme.MUTED))
        elif change is not None and change.calibrated_now and coach.level is not None:
            lines.append((t("coach.summary.calibrated", elo=coach.level), theme.ACCENT))
        elif change is not None and change.level_before is not None and change.level_after != change.level_before:
            lines.append((t("coach.summary.level_changed", before=change.level_before, after=change.level_after), theme.ACCENT))
        elif coach.level is not None:
            lines.append((tn("coach.summary.level", coach.games_to_update(), elo=coach.level), theme.TEXT_SOFT))
        else:
            lines.append((t("coach.summary.calibration", n=coach.calibration_progress(), total=CALIBRATION_GAMES), theme.TEXT_SOFT))
        helps = game.takebacks + game.hints
        if helps and self.summary.counted:
            lines.append((t("coach.summary.helps", n=helps, score=fmt_decimal(game.score(), 1)), theme.MUTED))
        return lines

    def _draw_summary(self, screen: pygame.Surface) -> None:
        game = self.game
        assert game is not None and self.summary is not None
        appear = ease_out_cubic((self.clock - self.summary.opened_at) / 0.3)
        shade = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        shade.fill((5, 6, 12, int(170 * appear)))
        screen.blit(shade, (0, 0))
        width = min(px(560), screen.get_width() - px(32))
        lines = self._summary_lines()
        inner = width - px(48)
        lines_h = sum(wrapped_height(text, inner, fs(13)) + px(4) for text, _ in lines)
        rows = [cls for cls in CLASSES if game.counts(True)[cls] or game.counts(False)[cls]]
        height = px(196) + len(rows) * px(26) + lines_h + px(78)
        height = min(height, screen.get_height() - px(24))
        rect = pygame.Rect(0, 0, width, height)
        rect.center = screen.get_rect().center
        rect.y += round((1 - appear) * px(16))
        card(screen, rect, color=theme.SURFACE_2)
        result = game.result or "draw"
        expression = "excited" if result == "win" else "happy" if result == "loss" else "neutral"
        avatar = px(76)
        draw_coach(screen, (rect.x + px(24) + avatar // 2, rect.y + px(22) + avatar // 2), avatar, expression, (self.clock % 4.2) < 0.13, theme.ACCENT)
        tx_ = rect.x + px(24) + avatar + px(16)
        color = theme.ACCENT if result == "win" else theme.RED if result == "loss" else theme.AMBER
        draw_text(screen, t(f"coach.result.{result}"), (tx_, rect.y + px(26)), fs(26), color, "bold", max_width=rect.right - px(24) - tx_)
        if game.reason:
            draw_text(screen, t(f"coach.reason.{game.reason}"), (tx_, rect.y + px(64)), fs(14), theme.TEXT_SOFT, max_width=rect.right - px(24) - tx_)
        # Accuracy: You / Coach.
        y = rect.y + px(116)
        col_w = (width - px(48)) // 2
        for i, (label, player) in enumerate(((t("coach.you"), True), (t("coach.name"), False))):
            cx = rect.x + px(24) + i * col_w
            accuracy = game.accuracy(player)
            draw_text(screen, label, (cx + col_w // 2, y), fs(13), theme.MUTED, "bold", "midtop", max_width=col_w - px(10))
            value = "—" if accuracy is None else f"{fmt_decimal(accuracy, 1)}%"
            draw_text(screen, value, (cx + col_w // 2, y + px(20)), fs(28), theme.TEXT, "bold", "midtop", max_width=col_w - px(10))
        draw_text(screen, t("coach.summary.accuracy"), (rect.centerx, y + px(58)), fs(11), theme.DIM, anchor="midtop")
        y += px(80)
        counts_you, counts_trainer = game.counts(True), game.counts(False)
        for cls in rows:
            cy = y + px(13)
            draw_text(screen, str(counts_you[cls]), (rect.x + px(24) + col_w // 2 - px(70), cy), fs(15), theme.TEXT, "bold", "center")
            draw_badge(screen, (rect.centerx - px(80), cy), px(10), cls)
            draw_text(screen, t(f"cls.{cls}"), (rect.centerx - px(64), cy), fs(13), COLORS[cls], "bold", "midleft", max_width=px(140))
            draw_text(screen, str(counts_trainer[cls]), (rect.x + px(24) + col_w + col_w // 2 + px(70), cy), fs(15), theme.TEXT_SOFT, "bold", "center")
            y += px(26)
        y += px(8)
        for text, line_color in lines:
            y += draw_wrapped(screen, text, pygame.Rect(rect.x + px(24), y, inner, px(60)), fs(13), line_color) + px(4)
        button_w = (width - px(48) - 2 * px(10)) // 3
        by = rect.bottom - px(62)
        for i, button in enumerate((self.btn_review, self.btn_sum_rematch, self.btn_sum_menu)):
            button.rect = pygame.Rect(rect.x + px(24) + i * (button_w + px(10)), by, button_w, px(42))
            button.draw(screen)

    def _draw_confirm(self, surface: pygame.Surface) -> None:
        assert self.confirm is not None
        shade = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        shade.fill((5, 6, 12, 170))
        surface.blit(shade, (0, 0))
        width = min(px(480), surface.get_width() - px(40))
        text = self.confirm[0]()
        text_h = wrapped_height(text, width - px(48), fs(16))
        rect = pygame.Rect(0, 0, width, text_h + px(120))
        rect.center = surface.get_rect().center
        card(surface, rect, color=theme.SURFACE_2)
        draw_wrapped(surface, text, pygame.Rect(rect.x + px(24), rect.y + px(24), width - px(48), text_h), fs(16), theme.TEXT)
        button_w = (width - px(48) - px(12)) // 2
        self.btn_no.rect = pygame.Rect(rect.x + px(24), rect.bottom - px(64), button_w, px(42))
        self.btn_yes.rect = pygame.Rect(self.btn_no.rect.right + px(12), rect.bottom - px(64), button_w, px(42))
        self.btn_yes.label = tx(self.confirm[2])
        self.btn_yes.draw(surface)
        self.btn_no.draw(surface)
