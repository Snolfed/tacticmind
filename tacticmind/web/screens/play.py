"""Puzzle screen.

The puzzle flow, engine checking of moves outside the solution, rating, line preview
and move browsing (◀ ▶). Messages are functions
returning text (``Text``), so after a language change the snapshot speaks the new language immediately.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Any, Literal

import chess

from ...brain.notation import format_line, move_san
from ...brain.thoughts import Thought, ThoughtStream, describe_refutation, explain_puzzle
from ...engine.process import DoneEvent, EngineEvent, ErrorEvent, InfoEvent, ProgressEvent
from ...engine.types import EngineScore, SearchInfo
from ...i18n import t, tn
from ...puzzles.session import PuzzleOutcome, PuzzleSession, Status, Verdict
from ...puzzles.themes import skill_themes, theme_name
from ...puzzles.validator import is_sacrifice, judge_alternative
from ...rating.profile import RUSH_VARIANTS, RatingChange
from ...rating.selector import Selection, select_next, select_review, select_rush
from .. import brain
from ..board import BoardModel
from ..colors import ENGINE_ARROWS
from .base import WebScreen

if TYPE_CHECKING:
    from ..core import WebApp

OPPONENT_DELAY = 0.4  # opponent's reply after ~400 ms
INTRO_DELAY = 0.7
REVEAL_STEP = 0.75
PREVIEW_STEP = 0.8
#: Analysis time limits (ms). The engine runs in a separate process, so the UI does not stutter.
ANALYSIS_TIME = 9000
CHECK_TIME = 1600
#: Puzzle Rush: mistakes that end the run, and pauses before the next puzzle (after a success / after a mistake).
RUSH_STRIKES = 3
RUSH_NEXT = 0.6
RUSH_AFTER_MISTAKE = 1.6
#: Themes offered for theme training need at least this many puzzles in the set.
MIN_THEME_PUZZLES = 15
NOTICE_TIME = 4.0

Text = Callable[[], str]
Training = Literal["rated", "theme", "review", "rush"]


def tx(key: str, **params: object) -> Text:
    """Lazily translated text — in the current language at every snapshot."""
    return partial(t, key, **params)


def _empty() -> str:
    return ""


@dataclass
class _Check:
    """Checking a move outside the solution: first (if needed) the evaluation before the move, then after it."""

    fen_before: str
    move: chess.Move
    stage: str  # "best" | "after"
    request: int
    best: SearchInfo | None = None


@dataclass
class _Rush:
    """A Puzzle Rush run: puzzles get harder, 3 mistakes (or the clock) end it. Times are on the screen clock."""

    minutes: int  # 0 = Survival (no clock)
    ends_at: float | None = None  # set when the first puzzle starts
    index: int = 0
    solved: int = 0
    strikes: int = 0
    used: set[str] = field(default_factory=set)
    results: list[tuple[int, bool]] = field(default_factory=list)  # (puzzle rating, solved)
    over: str | None = None  # "time" | "strikes" | "stopped"
    record: bool = False
    best_before: int = 0

    def seconds_left(self, clock: float) -> int | None:
        if self.ends_at is None:
            return None if self.minutes == 0 else self.minutes * 60
        return max(0, int(self.ends_at - clock + 0.999))


@dataclass
class _Preview:
    fen: str
    moves: list[chess.Move]
    index: int
    auto: bool
    next_step: float


class PlayScreen(WebScreen):
    def __init__(self, app: WebApp) -> None:
        super().__init__(app)
        self.board_view = BoardModel("play", app.fx)
        self.board_view.on_move = self.on_player_move
        self.state = brain.BrainState()
        self.stream = ThoughtStream()
        #: Log of analysis events — after a language change the thought stream is rebuilt from it.
        self.thought_log: list[tuple[str, object]] = []
        self.session: PuzzleSession | None = None
        self.selection: Selection | None = None
        self.analysis_id: int | None = None
        self.infos: dict[str, SearchInfo] = {}
        self.key_info: SearchInfo | None = None
        self.check: _Check | None = None
        self.message: tuple[Text, str] = (_empty, "text")
        self.message_seq = 0
        self.detail: Text = _empty
        self.change: RatingChange | None = None
        self.preview: _Preview | None = None
        #: Browsed position (number of moves from the start of the puzzle); None = the current "live" position.
        self.view_index: int | None = None
        self.hint_square: chess.Square | None = None
        self.confirm: tuple[Text, Callable[[], None], str] | None = None  # text, action, "yes" button key
        self.eval_score: EngineScore | None = None
        self.eval_hidden = True
        #: Puzzle number — when it changes, the interface resets the panel scroll and thought animations.
        self.puzzle_seq = 0
        self.explain_seq = 0
        #: Puzzle mode: rated (adaptive), one theme, review of failed puzzles or Puzzle Rush.
        self.training: Training = "rated"
        self.theme: str | None = None
        self.rush: _Rush | None = None
        self.notice: tuple[Text, float] | None = None
        counts = Counter(th for p in app.puzzles for th in skill_themes(p.themes))
        self.theme_counts = {th: n for th, n in counts.items() if n >= MIN_THEME_PUZZLES}

    # ================================================================ lifecycle
    def enter(self) -> None:
        if self.session is None:
            self.new_puzzle()
        elif self.state.info is None and self.session.status == Status.PLAYER:
            self.analyze_current()

    def leave(self) -> None:
        self.app.engine.stop()
        self.state.running = False

    def say(self, text: Text, color: str, detail: Text = _empty) -> None:
        self.message = (text, color)
        self.message_seq += 1
        self.detail = detail

    def on_language_change(self) -> None:
        """Rebuilds the thought stream and the explanation in the new language (other texts are lazy)."""
        stream = ThoughtStream(self.session.puzzle.fen if self.session else chess.STARTING_FEN)
        thoughts: list[Thought] = []
        for kind, data in self.thought_log:
            if kind == "info" and isinstance(data, SearchInfo):
                thoughts.extend(stream.on_info(data))
            elif kind == "done" and isinstance(data, SearchInfo):
                done = stream.on_done(data)
                if done:
                    thoughts.append(done)
            elif kind == "newpos" and isinstance(data, tuple):
                thoughts.append(self._new_position_thought(*data))
        self.stream = stream
        self.state.thoughts = thoughts
        if self.session is not None and self.state.explanation:
            self.state.explanation = explain_puzzle(self.session.puzzle, self.key_info)

    # ================================================================ puzzle
    def _rated_pending(self) -> bool:
        """A rated puzzle has started and has no result yet (leaving it counts as a loss)."""
        session = self.session
        return (
            self.training in ("rated", "theme")
            and session is not None
            and session.outcome is None
            and not session.finished
            and session.status not in (Status.INTRO,)
        )

    def _select(self) -> Selection:
        profile = self.app.profile
        if self.training == "review":
            selection = select_review(self.app.puzzles, profile)
            if selection is not None:
                return selection
            self.training = "rated"
            self.show_notice(tx("training.review_done"))
        if self.training == "rush" and self.rush is not None:
            selection = select_rush(self.app.puzzles, self.rush.index, self.rush.used, self.app.rng)
            self.rush.index += 1
            self.rush.used.add(selection.puzzle.id)
            return selection
        theme = self.theme if self.training == "theme" else None
        return select_next(self.app.puzzles, profile, self.app.rng, theme=theme)

    def new_puzzle(self) -> None:
        if self._rated_pending():
            # Skipping a puzzle midway = a loss (so hard puzzles cannot be "skipped over").
            assert self.session is not None
            self.session.forfeit()
            self.apply_outcome()
        self.timers.clear()
        self.preview = None
        self.check = None
        self.view_index = None
        self.change = None
        self.selection = self._select()
        puzzle = self.selection.puzzle
        self.session = PuzzleSession(puzzle)
        self.puzzle_seq += 1
        self.infos.clear()
        self.key_info = None
        self.thought_log = []
        bv = self.board_view
        bv.orientation = puzzle.player_color
        bv.player_color = puzzle.player_color
        bv.interactive = False
        self.hint_square = None
        bv.feedback = None
        bv.arrows = []
        bv.set_position(self.session.board, None, animate=False)
        self.eval_score = None
        self.state = brain.BrainState(mode="hidden", fen=puzzle.fen)
        self.stream.reset(puzzle.fen)
        self.analysis_id = None
        self.app.engine.stop()
        self.say(tx("play.opponent_moving"), "muted")
        self.schedule(INTRO_DELAY, self._play_intro)

    def _play_intro(self) -> None:
        assert self.session is not None
        board_before = self.session.board.copy()
        move = self.session.play_intro()
        self._show_move(board_before, move)
        self.board_view.interactive = True
        key = "play.find_white" if self.session.player_color == chess.WHITE else "play.find_black"
        self.say(tx(key), "text")
        rush = self.rush
        if self.training == "rush" and rush is not None and rush.ends_at is None and rush.minutes:
            rush.ends_at = self.clock + rush.minutes * 60  # the clock starts with the first puzzle
        self.analyze_current()

    # ================================================================ puzzle modes
    def set_training(self, kind: str, theme: str | None = None, minutes: int | None = None) -> None:
        """Switches the puzzle mode; a started rated puzzle then counts as unsolved (after confirmation)."""
        if kind not in ("rated", "theme", "review", "rush"):
            return
        if kind == "theme" and theme not in self.theme_counts:
            return
        if kind == "review" and not self.app.profile.review:
            return
        if kind == "rush" and minutes not in RUSH_VARIANTS:
            return

        def switch() -> None:
            if self._rated_pending():
                assert self.session is not None
                self.session.forfeit()
                self.apply_outcome()
            self.training = kind  # type: ignore[assignment]
            self.theme = theme if kind == "theme" else None
            self.rush = None
            if kind == "rush":
                assert minutes is not None
                self.rush = _Rush(minutes, best_before=self.app.profile.rush_best.get(str(minutes), 0))
            self.new_puzzle()

        if self._rated_pending():
            self.confirm = (tx("training.mode_confirm"), switch, "training.mode_yes")
        else:
            switch()

    def _rush_result(self, outcome: PuzzleOutcome) -> None:
        rush = self.rush
        session = self.session
        if rush is None or rush.over is not None or session is None:
            return
        success = outcome.solved and not outcome.hint_used and not outcome.revealed
        rush.results.append((session.puzzle.rating, success))
        if success:
            rush.solved += 1
            self.schedule(RUSH_NEXT, self.new_puzzle)
            return
        rush.strikes += 1
        if rush.strikes >= RUSH_STRIKES:
            self.schedule(RUSH_AFTER_MISTAKE, partial(self.end_rush, "strikes"))
        else:
            self.schedule(RUSH_AFTER_MISTAKE, self.new_puzzle)

    def end_rush(self, reason: str) -> None:
        rush = self.rush
        if rush is None or rush.over is not None:
            return
        rush.over = reason
        self.timers.clear()
        self.app.engine.stop()
        self.state.running = False
        self.board_view.interactive = False
        rush.record = self.app.profile.record_rush(rush.minutes, rush.solved)
        self.app.save()
        self.app.sound("success" if rush.solved else "error")

    def show_notice(self, text: Text) -> None:
        self.notice = (text, self.clock + NOTICE_TIME)

    def _show_move(self, board_before: chess.Board, move: chess.Move, animate: bool = True) -> None:
        """Shows the move on the board and plays the matching sound."""
        board_after = board_before.copy()
        board_after.push(move)
        self.board_view.set_position(board_after, move, animate)
        self.play_sound(board_before, move)

    # ================================================================ player move
    def on_player_move(self, move: chess.Move) -> None:
        session = self.session
        if session is None or session.status != Status.PLAYER or self.view_index is not None or self.preview is not None:
            return
        board_before = session.board.copy()
        self.hint_square = None
        verdict = session.submit(move)
        if verdict in (Verdict.CORRECT, Verdict.SOLVED, Verdict.SOLVED_ALT_MATE):
            # A correct move that gives up material is a "brilliant move" (!!), as on chess.com.
            brilliant = is_sacrifice(board_before, move)
            self._show_move(board_before, move)
            self.board_view.show_feedback(move.to_square, True, brilliant)
            if brilliant:
                self.app.sound("brilliant")
            if verdict == Verdict.CORRECT:
                if brilliant:
                    self.say(tx("play.brilliant"), "brilliant")
                else:
                    self.say(tx("play.best_move"), "accent")
                self.board_view.interactive = False
                # After a brilliant move the opponent "thinks" longer so the "!!" stays visible.
                delay = OPPONENT_DELAY + (0.9 if brilliant else 0.2)
                self.schedule(delay, partial(self._opponent_reply, brilliant))
            else:
                self.on_solved(verdict == Verdict.SOLVED_ALT_MATE, move.to_square, brilliant)
        elif verdict == Verdict.NEEDS_ENGINE:
            self._show_move(board_before, move)
            self.board_view.interactive = False
            self.say(tx("play.checking"), "muted")
            self.start_check(board_before.fen(), move)

    def _opponent_reply(self, after_brilliant: bool = False) -> None:
        session = self.session
        if session is None or session.status != Status.OPPONENT:
            return
        self._go_live()
        board_before = session.board.copy()
        move = session.opponent_reply()
        self._show_move(board_before, move)
        self.board_view.feedback = None
        self.board_view.interactive = True
        san = move_san(board_before, move)
        key, color = ("play.brilliant_continue", "brilliant") if after_brilliant else ("play.best_continue", "accent")
        self.say(tx(key), color, lambda: t("play.opponent_replied", move=_san_now(board_before, move, san)))
        self.analyze_current()

    # ---------------------------------------------------------------- move outside the solution
    def start_check(self, fen_before: str, move: chess.Move) -> None:
        best = self.infos.get(fen_before)
        if best is not None and best.depth >= 3:
            # If the move is among the 3 MultiPV lines, we have its exact evaluation from the same depth.
            for line in best.multi_pv:
                if line.move == move.uci():
                    reply = line.pv[1] if len(line.pv) > 1 else None
                    self.finish_check(fen_before, move, best.score, line.score, reply)
                    return
        board = chess.Board(fen_before)
        if best is None:
            request = self.app.engine.analyze(fen_before, time_ms=CHECK_TIME, multi_pv=1)
            self.check = _Check(fen_before, move, "best", request)
        else:
            board.push(move)
            request = self.app.engine.analyze(board.fen(), time_ms=CHECK_TIME, multi_pv=1)
            self.check = _Check(fen_before, move, "after", request, best)
        self.analysis_id = None
        self.state.running = True

    def _on_check_event(self, event: EngineEvent) -> None:
        check = self.check
        assert check is not None
        if isinstance(event, ProgressEvent):
            self.state.progress = event.progress
            return
        if isinstance(event, ErrorEvent):
            self.check = None
            self.finish_check(check.fen_before, check.move, EngineScore(0, None, 0), EngineScore(0, None, 0), None)
            return
        if not isinstance(event, DoneEvent):
            return
        info = event.info
        if check.stage == "best":
            board = chess.Board(check.fen_before)
            board.push(check.move)
            request = self.app.engine.analyze(board.fen(), time_ms=CHECK_TIME, multi_pv=1)
            self.check = _Check(check.fen_before, check.move, "after", request, info)
            return
        self.check = None
        best = check.best.score if check.best is not None else info.score
        after = EngineScore(None, 0, info.score.value) if info.terminal == "checkmate" else info.score
        self.finish_check(check.fen_before, check.move, best, after, info.best_move or None)

    def finish_check(self, fen_before: str, move: chess.Move, best: EngineScore, after: EngineScore, reply: str | None) -> None:
        session = self.session
        if session is None or session.status != Status.CHECKING:
            return
        alternative = judge_alternative(best, after, session.player_color)
        refutation = chess.Move.from_uci(reply) if reply else None
        verdict = session.resolve(alternative, refutation)
        self.state.running = False
        if verdict == Verdict.GOOD_BUT_BETTER:
            last = session.board.peek() if session.board.move_stack else None
            self.board_view.set_position(session.board, last, animate=False)
            self.board_view.interactive = True
            self.say(tx("play.good_but_better"), "amber", tx("play.not_a_mistake"))
            self.analyze_current()
            return
        # Mistake: ✗ on the target square, a board shake, the opponent's reply computed by the engine.
        self.board_view.show_feedback(move.to_square, False)
        self.board_view.shake()
        self.app.sound("error")
        reply_uci = session.refutation.uci() if session.refutation else None
        self.say(tx("play.wrong"), "red", partial(describe_refutation, fen_before, move.uci(), reply_uci, after))
        self.apply_outcome()
        self.state.mode = "full"
        if session.refutation is not None:
            board_before = chess.Board(fen_before)
            board_before.push(move)
            self.schedule(0.55, partial(self._show_refutation, board_before, session.refutation))
        else:
            self.analyze_current()

    def _show_refutation(self, board_before: chess.Board, move: chess.Move) -> None:
        if self.session is None or self.session.status != Status.MISTAKE:
            return
        self._go_live(board_before)
        self._show_move(board_before, move)
        self.analyze_current()

    # ---------------------------------------------------------------- end of puzzle
    def on_solved(self, alternative_mate: bool, square: chess.Square, brilliant: bool = False) -> None:
        assert self.session is not None
        if not brilliant:
            self.app.sound("success")
        self.board_view.interactive = False
        first_try = self.session.outcome is not None and self.session.outcome.solved
        if first_try:
            self.board_view.celebrate(square)
        key = "play.solved" if first_try else "play.solved_after_mistake"
        if brilliant and first_try:
            key = "play.solved_brilliant"
        color = "brilliant" if brilliant and first_try else "accent"
        self.say(tx(key), color, tx("play.alt_mate") if alternative_mate else _empty)
        self.apply_outcome()
        self._finish()

    def _finish(self) -> None:
        assert self.session is not None
        self.state.mode = "full"
        self.state.explanation = explain_puzzle(self.session.puzzle, self.key_info)
        self.explain_seq += 1  # the interface shows the explanation from the start
        self._go_live()
        self.analyze_current()

    def apply_outcome(self) -> None:
        session = self.session
        if session is None or self.selection is None:
            return
        outcome = session.take_outcome()
        if outcome is None:
            return
        if self.training == "rush":
            self._rush_result(outcome)
            return
        if self.training == "review":
            # Unrated: only a clean solution (no mistake, no hint) takes the puzzle out of the queue.
            self.app.profile.review_result(session.puzzle.id, outcome.solved and not outcome.hint_used)
            self.app.save()
            return
        change = self.app.profile.apply(session.puzzle, outcome, self.selection.mode)
        self.change = change
        self.app.on_rating_change(change)
        self.app.save()

    def hint(self) -> None:
        session = self.session
        if session is None or session.status != Status.PLAYER or self.view_index is not None:
            return
        rated = session.outcome is None and self.training in ("rated", "theme")
        square = session.hint()
        if square is None:
            return
        self.hint_square = square
        if self.state.mode == "hidden":
            self.state.mode = "hint"
        self.say(tx("play.hint"), "violet", tx("play.hint_penalty") if rated else _empty)

    def retry(self) -> None:
        session = self.session
        if session is None or session.status != Status.MISTAKE:
            return
        session.retry()
        self.view_index = None
        last = session.board.peek() if session.board.move_stack else None
        self.board_view.set_position(session.board, last, animate=False)
        self.board_view.feedback = None
        self.board_view.interactive = True
        self.state.mode = "hidden"
        self.say(tx("play.try_again"), "text", tx("play.try_again_detail"))
        self.analyze_current()

    def reveal_solution(self) -> None:
        session = self.session
        if session is None or session.finished or session.status in (Status.INTRO, Status.CHECKING, Status.OPPONENT):
            return
        self.timers.clear()
        moves = session.reveal()
        self.view_index = None
        self.apply_outcome()
        last = session.board.peek() if session.board.move_stack else None
        self.board_view.set_position(session.board, last, animate=False)
        self.board_view.feedback = None
        self.hint_square = None
        self.board_view.interactive = False
        fen = session.board.fen()
        ucis = [m.uci() for m in moves]
        self.say(tx("play.solution"), "muted", partial(format_line, fen, ucis, None))
        for i, move in enumerate(moves):
            self.schedule(0.35 + i * REVEAL_STEP, partial(self._reveal_step, move))
        self.schedule(0.35 + len(moves) * REVEAL_STEP, self._finish)

    def _reveal_step(self, move: chess.Move) -> None:
        assert self.session is not None
        self._go_live()
        board_before = self.session.board.copy()
        self.session.push_revealed(move)
        self._show_move(board_before, move)

    # ================================================================ panel modes
    def set_mode(self, mode: str) -> None:
        session = self.session
        if session is None or mode not in ("hidden", "hint", "full"):
            return
        if mode == "hint":
            if session.status == Status.PLAYER:
                self.hint()
            else:
                self.state.mode = "hint"
            return
        if mode == "full" and session.outcome is None and session.status not in (Status.INTRO,):
            self.confirm = (tx("play.full_confirm"), self._forfeit_to_full, "play.confirm_yes")
            return
        self.state.mode = mode

    def _forfeit_to_full(self) -> None:
        assert self.session is not None
        self.session.forfeit()
        self.apply_outcome()
        self.state.mode = "full"
        self.say(tx("play.full_on"), "muted", tx("play.full_on_detail"))

    # ================================================================ engine analysis
    def current_board(self) -> chess.Board:
        """The position visible on the board (live or browsed)."""
        assert self.session is not None
        board = self.session.board
        if self.view_index is None or self.view_index >= len(board.move_stack):
            return board
        view = chess.Board(self.session.puzzle.fen)
        for move in board.move_stack[: self.view_index]:
            view.push(move)
        return view

    @staticmethod
    def _new_position_thought(fen_before: str | None, move_uci: str | None) -> Thought:
        if fen_before and move_uci:
            board = chess.Board(fen_before)
            return Thought(t("play.new_position", move=move_san(board, chess.Move.from_uci(move_uci))), "info", 0)
        return Thought(t("play.new_position_plain"), "info", 0)

    def analyze_current(self) -> None:
        if self.session is None:
            return
        board = self.current_board()
        fen = board.fen()
        self.state.fen = fen
        self.state.progress = None
        self.state.info = self.infos.get(fen)
        if self.state.thoughts and self.stream.fen != fen:
            data: tuple[str | None, str | None] = (None, None)
            if board.move_stack:
                before = board.copy()
                last = before.pop()
                data = (before.fen(), last.uci())
            self.thought_log.append(("newpos", data))
            self.state.thoughts.append(self._new_position_thought(*data))
        self.stream.reset(fen)
        self.analysis_id = self.app.engine.analyze(fen, time_ms=ANALYSIS_TIME, multi_pv=3)
        self.state.running = True

    def on_engine(self, event: EngineEvent) -> None:
        if self.check is not None and event.id == self.check.request:
            self._on_check_event(event)
            return
        if event.id != self.analysis_id:
            return
        if isinstance(event, ProgressEvent):
            self.state.progress = event.progress
        elif isinstance(event, InfoEvent):
            info = event.info
            self.state.info = info
            self.infos[info.fen] = info
            if self.session is not None and info.fen == self.session.puzzle.start_fen:
                self.key_info = info
            self.thought_log.append(("info", info))
            self.state.thoughts.extend(self.stream.on_info(info))
        elif isinstance(event, DoneEvent):
            info = event.info
            self.state.running = False
            if info.depth:
                self.state.info = info
                self.infos[info.fen] = info
            if not event.stopped:
                self.thought_log.append(("done", info))
                done = self.stream.on_done(info)
                if done:
                    self.state.thoughts.append(done)
            if info.terminal:
                self.state.info = info
        elif isinstance(event, ErrorEvent):
            self.state.running = False
            self.state.status_note = t("play.engine_error", msg=event.message)

    # ================================================================ line preview
    def start_preview(self, index: int) -> None:
        info = self.state.info
        if info is None or not self.state.reveal or not 0 <= index < len(info.multi_pv):
            return
        moves = [chess.Move.from_uci(u) for u in info.multi_pv[index].pv]
        self.preview = _Preview(info.fen, moves, 0, True, self.clock + 0.3)
        self.board_view.set_position(chess.Board(info.fen), None, animate=False)
        self.board_view.interactive = False

    def _preview_board(self, upto: int) -> tuple[chess.Board, chess.Move | None]:
        assert self.preview is not None
        board = chess.Board(self.preview.fen)
        last = None
        for move in self.preview.moves[:upto]:
            last = move
            board.push(move)
        return board, last

    def step_preview(self, delta: int) -> None:
        preview = self.preview
        if preview is None:
            return
        preview.auto = False
        new_index = max(0, min(len(preview.moves), preview.index + delta))
        if new_index == preview.index:
            return
        if delta > 0:
            board, _ = self._preview_board(preview.index)
            self._show_move(board, preview.moves[preview.index])
        else:
            board, last = self._preview_board(new_index)
            undone = preview.moves[new_index]
            self.board_view.set_position(board, last, undo=undone)
            self.play_sound(board, undone)
        preview.index = new_index

    def stop_preview(self) -> None:
        if self.preview is None or self.session is None:
            return
        self.preview = None
        board = self.current_board()
        self.board_view.set_position(board, board.peek() if board.move_stack else None, animate=False)
        self.board_view.interactive = self.view_index is None and self.session.status == Status.PLAYER

    # ================================================================ stepping through moves (◀ ▶)
    def can_navigate(self) -> bool:
        """Moves can be browsed during the puzzle and after it — but not while the engine checks a move or a preview runs."""
        session = self.session
        if session is None or self.preview is not None or not session.board.move_stack:
            return False
        return session.status not in (Status.INTRO, Status.CHECKING)

    def _go_live(self, board: chess.Board | None = None) -> None:
        """Return from the browsed position to the current one (before every new move on the board)."""
        if self.view_index is None or self.session is None:
            return
        self.view_index = None
        live = board if board is not None else self.session.board
        self.board_view.set_position(live, live.peek() if live.move_stack else None, animate=False)

    def step_view(self, delta: int) -> None:
        """◀ / ▶: steps back or forward one move. You cannot move in an older position;
        ▶ to the end returns to the current position and play can continue."""
        session = self.session
        if session is None or not self.can_navigate():
            return
        stack = session.board.move_stack
        total = len(stack)
        current = total if self.view_index is None else self.view_index
        new_index = max(0, min(total, current + delta))
        if new_index == current:
            return
        if delta > 0:
            before = self.current_board()
            self.view_index = None if new_index == total else new_index
            self._show_move(before, stack[new_index - 1])
        else:
            undone = stack[new_index]
            self.view_index = new_index
            board = self.current_board()
            self.board_view.set_position(board, board.peek() if board.move_stack else None, undo=undone)
            self.play_sound(board, undone)
        self.board_view.feedback = None
        live = self.view_index is None
        self.board_view.interactive = live and session.status == Status.PLAYER
        # After the puzzle the engine analyses the viewed position; during the puzzle it keeps analysing the current one.
        if session.finished:
            self.analyze_current()

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
        if name == "move":
            if self.preview is None:
                self.board_view.play(str(data.get("uci", "")))
        elif name == "hint":
            if self.preview is None:
                self.hint()
        elif name == "solution":
            if self.preview is None:
                self.reveal_solution()
        elif name == "retry":
            if self.preview is None:
                self.retry()
        elif name == "next":
            session = self.session
            if self.preview is None and session is not None and session.finished:
                self.new_puzzle()
        elif name == "step":
            delta = _delta(data)
            if self.preview is not None:
                self.step_preview(delta)
            else:
                self.step_view(delta)
        elif name == "mode":
            self.set_mode(str(data.get("mode", "")))
        elif name == "preview":
            self.start_preview(_int(data.get("index"), -1))
        elif name == "preview_close":
            self.stop_preview()
        elif name == "training":
            theme = data.get("theme")
            minutes = data.get("minutes")
            self.set_training(
                str(data.get("kind", "")),
                theme if isinstance(theme, str) else None,
                minutes if isinstance(minutes, int) and not isinstance(minutes, bool) else None,
            )
        elif name == "rush_stop":
            if self.training == "rush" and self.rush is not None and self.rush.results:
                self.end_rush("stopped")
            elif self.training == "rush":
                self.set_training("rated")
        elif name == "rush_again":
            if self.rush is not None and self.rush.over is not None:
                self.set_training("rush", minutes=self.rush.minutes)
        elif name == "rush_back" and self.training == "rush":
            self.set_training("rated")

    # ================================================================ update
    def update(self, dt: float) -> None:
        super().update(dt)
        # Automatic playback of the line in preview.
        preview = self.preview
        if preview is not None and preview.auto and self.clock >= preview.next_step:
            if preview.index < len(preview.moves):
                board, _ = self._preview_board(preview.index)
                self._show_move(board, preview.moves[preview.index])
                preview.index += 1
                preview.next_step = self.clock + PREVIEW_STEP
            else:
                preview.auto = False

        rush = self.rush
        if self.training == "rush" and rush is not None and rush.over is None and rush.ends_at is not None and self.clock >= rush.ends_at:
            self.end_rush("time")

        session = self.session
        if session is None:
            return
        reveal = self.state.reveal
        info = self.state.info
        visible_fen = self.board_view.board.fen()
        self.eval_hidden = not reveal
        if reveal and info is not None and self.preview is None and info.fen == visible_fen:
            self.eval_score = info.score
            arrows: list[tuple[chess.Square, chess.Square, str]] = []
            for line, color in zip(info.multi_pv[:3], ENGINE_ARROWS):
                move = chess.Move.from_uci(line.move)
                arrows.append((move.from_square, move.to_square, color))
            self.board_view.arrows = arrows
        else:
            if reveal and info is not None and info.terminal and info.fen == visible_fen:
                self.eval_score = info.score
            self.board_view.arrows = []
        # The hint is visible only in the current position.
        self.board_view.hint_square = self.hint_square if self.view_index is None and self.preview is None else None

    # ================================================================ snapshot
    def _buttons(self) -> dict[str, Any]:
        session = self.session
        finished = session is not None and session.finished
        status = session.status if session is not None else Status.INTRO
        no_preview = self.preview is None
        navigable = self.can_navigate()
        total = len(session.board.move_stack) if session is not None else 0
        current = total if self.view_index is None else self.view_index
        helps = self.training != "rush"  # in Puzzle Rush there are no hints, solutions or retries; the next puzzle comes by itself
        return {
            "hint": {"visible": helps and not finished, "enabled": status == Status.PLAYER and no_preview and self.view_index is None},
            "solution": {
                "visible": helps and not finished,
                "enabled": not finished and status not in (Status.INTRO, Status.CHECKING, Status.OPPONENT),
            },
            "retry": {"visible": helps and not finished and status == Status.MISTAKE, "enabled": status == Status.MISTAKE},
            "next": {"visible": helps and finished, "enabled": finished},
            "prev": {"visible": status != Status.INTRO, "enabled": navigable and current > 0},
            "fwd": {"visible": status != Status.INTRO, "enabled": navigable and self.view_index is not None},
        }

    def _card(self) -> dict[str, Any]:
        session = self.session
        assert session is not None
        puzzle = session.puzzle
        finished = session.outcome is not None or session.finished
        side = t("side.white") if session.player_color == chess.WHITE else t("side.black")
        text_fn, color = self.message
        themes = [theme_name(th) for th in skill_themes(puzzle.themes) if th != "mate"] if finished else []
        delta = round(self.change.delta) if finished and self.change is not None else None
        return {
            "side": "white" if session.player_color == chess.WHITE else "black",
            "title": t("play.title", side=side),
            "rating": t("play.rating", rating=puzzle.rating) if finished else t("play.rating_hidden"),
            "finished": finished,
            "message": text_fn(),
            "color": color,
            "messageSeq": self.message_seq,
            "detail": self.detail(),
            "themes": t("play.themes", themes=", ".join(themes)) if themes else "",
            "delta": delta,
            "why": self.selection.reason_texts() if self.selection is not None else [],
        }

    def _training(self) -> dict[str, Any]:
        profile = self.app.profile
        model = profile.model
        themes = []
        for theme, count in self.theme_counts.items():
            stat = model.stats.get(theme)
            themes.append(
                {
                    "id": theme,
                    "name": theme_name(theme),
                    "count": t("training.theme_count", n=count),
                    "stats": t("training.theme_stats", pct=round(stat.rate * 100), n=stat.attempts) if stat and stat.attempts else "",
                    "weak": stat is not None and stat.attempts >= 3 and stat.rate < 0.5,
                }
            )
        themes.sort(key=lambda item: str(item["name"]).lower())
        if self.training == "theme" and self.theme is not None:
            label = t("training.theme", theme=theme_name(self.theme))
        else:
            label = t(f"training.{self.training}")
        rush = None
        if self.training == "rush" and self.rush is not None:
            r = self.rush
            rush = {
                "minutes": r.minutes,
                "left": r.seconds_left(self.clock),
                "solved": r.solved,
                "strikes": r.strikes,
                "maxStrikes": RUSH_STRIKES,
                "best": max(r.best_before, r.solved) if r.over else r.best_before,
                "over": r.over,
                "overTitle": t(f"rush.over.{r.over}") if r.over else "",
                "result": tn("rush.result", r.solved),
                "record": r.record,
                "results": [{"rating": rating, "solved": ok} for rating, ok in r.results],
            }
        review = len(profile.review)
        return {
            "kind": self.training,
            "theme": self.theme,
            "label": label,
            "rush": rush,
            "review": review,
            "reviewLabel": tn("training.review_count", review) if review else t("training.review_empty"),
            "rushBest": {str(m): profile.rush_best.get(str(m), 0) for m in RUSH_VARIANTS},
            "themes": themes,
        }

    def snapshot(self) -> dict[str, Any]:
        session = self.session
        if session is None:
            return {}
        preview = None
        if self.preview is not None:
            p = self.preview
            preview = {
                "index": p.index,
                "total": len(p.moves),
                "label": t("play.preview", i=p.index, n=len(p.moves)),
                "line": format_line(p.fen, [m.uci() for m in p.moves], None),
            }
        return {
            "puzzle": self.puzzle_seq,
            "board": self.board_view.snapshot(),
            "eval": {
                "hidden": self.eval_hidden,
                "score": brain.score_json(self.eval_score),
                "whiteBottom": session.player_color == chess.WHITE,
            },
            "card": self._card(),
            "buttons": self._buttons(),
            "preview": preview,
            "confirm": {"text": self.confirm[0](), "yes": t(self.confirm[2])} if self.confirm is not None else None,
            "brain": brain.snapshot(self.state),
            "explainSeq": self.explain_seq,
            "training": self._training(),
            "notice": self.notice[0]() if self.notice is not None and self.clock <= self.notice[1] else None,
        }


def _san_now(board_before: chess.Board, move: chess.Move, fallback: str) -> str:
    """SAN of the move in the current language (piece letters change after a language change)."""
    try:
        return move_san(board_before, move)
    except (ValueError, AssertionError):
        return fallback


def _int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, (float, str)):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _delta(data: dict[str, Any]) -> int:
    return max(-1, min(1, _int(data.get("delta"), 0)))
