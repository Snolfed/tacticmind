"""Ekran gry: szachownica, pasek oceny, panel „Mózg AI”, przebieg zadania i ranking.

Komunikaty są przechowywane jako funkcje zwracające tekst (``Text``), a nie gotowe
napisy — dzięki temu po zmianie języka cały ekran od razu mówi w nowym języku.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

import chess
import pygame

from ...brain.notation import format_line, move_san
from ...brain.thoughts import Thought, ThoughtStream, describe_refutation, explain_puzzle
from ...engine.process import DoneEvent, EngineEvent, ErrorEvent, InfoEvent, ProgressEvent
from ...engine.types import EngineScore, SearchInfo
from ...i18n import t
from ...puzzles.session import PuzzleSession, Status, Verdict
from ...puzzles.themes import skill_themes, theme_name
from ...puzzles.validator import is_sacrifice, judge_alternative
from ...rating.profile import RatingChange
from ...rating.selector import Selection, select_next
from .. import fonts, gfx, theme
from ..anim import ease_out_back, ease_out_cubic
from ..board_view import BoardView
from ..brain_panel import BrainPanel, BrainState
from ..eval_bar import EvalBar
from ..scale import fs, is_wide, px
from ..widgets import Button, card, draw_text, draw_wrapped, wrapped_height
from .base import Screen

if TYPE_CHECKING:
    from ..app import App

OPPONENT_DELAY = 0.4  # odpowiedź przeciwnika po ok. 400 ms
INTRO_DELAY = 0.7
REVEAL_STEP = 0.75
PREVIEW_STEP = 0.8
#: Limity czasu analizy (ms). Silnik liczy w osobnym procesie, więc UI się nie przycina.
ANALYSIS_TIME = 9000
CHECK_TIME = 1600

Text = Callable[[], str]


def tx(key: str, **params: object) -> Text:
    """Tekst tłumaczony leniwie — przy każdym rysowaniu w aktualnym języku."""
    return partial(t, key, **params)


def _empty() -> str:
    return ""


@dataclass
class _Check:
    """Sprawdzanie ruchu spoza rozwiązania: najpierw (jeśli trzeba) ocena pozycji przed ruchem, potem po ruchu."""

    fen_before: str
    move: chess.Move
    stage: str  # "best" | "after"
    request: int
    best: SearchInfo | None = None


@dataclass
class _Preview:
    fen: str
    moves: list[chess.Move]
    index: int
    auto: bool
    next_step: float


class PlayScreen(Screen):
    def __init__(self, app: App) -> None:
        super().__init__(app)
        self.board_view = BoardView()
        self.board_view.on_move = self.on_player_move
        self.eval_bar = EvalBar()
        self.brain = BrainPanel(self.set_mode, self.start_preview)
        self.state = BrainState()
        self.stream = ThoughtStream()
        #: Zapis zdarzeń analizy — po zmianie języka strumień myśli jest z nich odtwarzany.
        self.thought_log: list[tuple[str, object]] = []
        self.session: PuzzleSession | None = None
        self.selection: Selection | None = None
        self.timers: list[tuple[float, Callable[[], None]]] = []
        self.clock = 0.0
        self.analysis_id: int | None = None
        self.infos: dict[str, SearchInfo] = {}
        self.key_info: SearchInfo | None = None
        self.check: _Check | None = None
        self.message: tuple[Text, tuple[int, ...]] = (_empty, theme.TEXT)
        self.message_at = 0.0
        self.detail: Text = _empty
        self.change: RatingChange | None = None
        self.preview: _Preview | None = None
        #: Przeglądana pozycja (liczba ruchów od początku zadania); None = bieżąca pozycja „na żywo”.
        self.view_index: int | None = None
        self.hint_square: chess.Square | None = None
        self.show_why = False
        self.why_at = 0.0
        self.confirm: tuple[Text, Callable[[], None]] | None = None
        self.wide = True
        # Wąski układ (jak na telefonie): cała strona przewija się w pionie.
        self.page: pygame.Surface | None = None
        self.page_h = 0
        self.scroll_y = 0.0

        self.btn_hint = Button(tx("play.btn.hint"), self.hint, size=14)
        self.btn_solution = Button(tx("play.btn.solution"), self.reveal_solution, size=14)
        self.btn_retry = Button(tx("play.btn.retry"), self.retry, size=14)
        self.btn_next = Button(tx("play.btn.next"), self.new_puzzle, style="primary", size=14)
        self.btn_why = Button(tx("play.why"), self.toggle_why, size=12, style="ghost", pill=True)
        self.btn_prev_pos = Button("", partial(self.step_view, -1), icon="left")
        self.btn_next_pos = Button("", partial(self.step_view, 1), icon="right")
        self.btn_preview_prev = Button("", partial(self.step_preview, -1), icon="left")
        self.btn_preview_next = Button("", partial(self.step_preview, 1), icon="right")
        self.btn_preview_close = Button(tx("play.preview_back"), self.stop_preview, size=13, style="primary")
        self.btn_confirm_yes = Button(tx("play.confirm_yes"), self._confirm_yes, style="danger", size=14)
        self.btn_confirm_no = Button(tx("common.cancel"), self._confirm_no, size=14)
        self.card_rect = pygame.Rect(0, 0, 0, 0)
        self.controls_rect = pygame.Rect(0, 0, 0, 0)
        self.eval_rect = pygame.Rect(0, 0, 0, 0)

    # ================================================================ cykl życia
    def enter(self) -> None:
        if self.session is None:
            self.new_puzzle()
        elif self.state.info is None and self.session.status == Status.PLAYER:
            self.analyze_current()

    def leave(self) -> None:
        self.app.engine.stop()
        self.state.running = False

    def schedule(self, delay: float, action: Callable[[], None]) -> None:
        self.timers.append((self.clock + delay, action))

    def say(self, text: Text, color: tuple[int, ...], detail: Text = _empty) -> None:
        self.message = (text, color)
        self.message_at = self.clock
        self.detail = detail

    def on_language_change(self) -> None:
        """Odtwarza strumień myśli i wyjaśnienie w nowym języku (pozostałe teksty są leniwe)."""
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

    # ================================================================ zadanie
    def new_puzzle(self) -> None:
        session = self.session
        if session is not None and session.outcome is None and session.status not in (Status.INTRO,):
            # Pominięcie zadania w trakcie = porażka (żeby nie dało się „przeskakiwać” trudnych zadań).
            session.forfeit()
            self.apply_outcome()
        self.timers.clear()
        self.preview = None
        self.check = None
        self.view_index = None
        self.show_why = False
        self.change = None
        self.selection = select_next(self.app.puzzles, self.app.profile)
        puzzle = self.selection.puzzle
        self.session = PuzzleSession(puzzle)
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
        bv.clear_drawings()
        bv.set_position(self.session.board, None, animate=False)
        self.eval_bar.white_bottom = puzzle.player_color == chess.WHITE
        self.eval_bar.reset()
        self.state = BrainState(mode="hidden", fen=puzzle.fen)
        self.brain.reset()
        self.stream.reset(puzzle.fen)
        self.analysis_id = None
        self.app.engine.stop()
        self.say(tx("play.opponent_moving"), theme.MUTED)
        self.schedule(INTRO_DELAY, self._play_intro)

    def _play_intro(self) -> None:
        assert self.session is not None
        board_before = self.session.board.copy()
        move = self.session.play_intro()
        self._show_move(board_before, move)
        self.board_view.interactive = True
        key = "play.find_white" if self.session.player_color == chess.WHITE else "play.find_black"
        self.say(tx(key), theme.TEXT)
        self.analyze_current()

    def _show_move(self, board_before: chess.Board, move: chess.Move, animate: bool = True) -> None:
        """Pokazuje ruch na szachownicy i odtwarza odpowiedni dźwięk."""
        board_after = board_before.copy()
        board_after.push(move)
        self.board_view.set_position(board_after, move, animate)
        self._play_move_sound(board_before, move)

    def _play_move_sound(self, board_before: chess.Board, move: chess.Move) -> None:
        """Dźwięk ruchu (także przy cofaniu ◀): szach, promocja, roszada, bicie albo zwykły ruch."""
        board_after = board_before.copy()
        board_after.push(move)
        if board_after.is_check():
            self.app.sounds.play("check")
        elif move.promotion:
            self.app.sounds.play("promote")
        elif board_before.is_castling(move):
            self.app.sounds.play("castle")
        else:
            self.app.sounds.play("capture" if board_before.is_capture(move) else "move")

    # ================================================================ ruch gracza
    def on_player_move(self, move: chess.Move) -> None:
        session = self.session
        if session is None or session.status != Status.PLAYER:
            return
        board_before = session.board.copy()
        self.hint_square = None
        verdict = session.submit(move)
        if verdict in (Verdict.CORRECT, Verdict.SOLVED, Verdict.SOLVED_ALT_MATE):
            # Poprawny ruch, który oddaje materiał, to „genialny ruch” (!!), jak na chess.com.
            brilliant = is_sacrifice(board_before, move)
            self._show_move(board_before, move)
            self.board_view.show_feedback(move.to_square, True, brilliant)
            if brilliant:
                self.app.sounds.play("brilliant")
            if verdict == Verdict.CORRECT:
                if brilliant:
                    self.say(tx("play.brilliant"), theme.BRILLIANT)
                else:
                    self.say(tx("play.best_move"), theme.ACCENT)
                self.board_view.interactive = False
                # Po genialnym ruchu przeciwnik „zastanawia się” dłużej, żeby było widać „!!”.
                delay = OPPONENT_DELAY + (0.9 if brilliant else 0.2)
                self.schedule(delay, partial(self._opponent_reply, brilliant))
            else:
                self.on_solved(verdict == Verdict.SOLVED_ALT_MATE, move.to_square, brilliant)
        elif verdict == Verdict.NEEDS_ENGINE:
            self._show_move(board_before, move)
            self.board_view.interactive = False
            self.say(tx("play.checking"), theme.MUTED)
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
        key, color = ("play.brilliant_continue", theme.BRILLIANT) if after_brilliant else ("play.best_continue", theme.ACCENT)
        self.say(tx(key), color, lambda: t("play.opponent_replied", move=_san_now(board_before, move, san)))
        self.analyze_current()

    # ---------------------------------------------------------------- ruch spoza rozwiązania
    def start_check(self, fen_before: str, move: chess.Move) -> None:
        best = self.infos.get(fen_before)
        if best is not None and best.depth >= 3:
            # Jeśli ruch jest wśród 3 linii MultiPV, mamy jego dokładną ocenę z tej samej głębokości.
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
            self.say(tx("play.good_but_better"), theme.AMBER, tx("play.not_a_mistake"))
            self.analyze_current()
            return
        # Błąd: ✗ na polu docelowym, potrząśnięcie szachownicą, odpowiedź przeciwnika wyliczona przez silnik.
        self.board_view.show_feedback(move.to_square, False)
        self.board_view.shake()
        self.app.sounds.play("error")
        reply_uci = session.refutation.uci() if session.refutation else None
        self.say(tx("play.wrong"), theme.RED, partial(describe_refutation, fen_before, move.uci(), reply_uci, after))
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

    # ---------------------------------------------------------------- koniec zadania
    def on_solved(self, alternative_mate: bool, square: chess.Square, brilliant: bool = False) -> None:
        assert self.session is not None
        if not brilliant:
            self.app.sounds.play("success")
        self.board_view.interactive = False
        first_try = self.session.outcome is not None and self.session.outcome.solved
        if first_try:
            self.board_view.celebrate(square)
        key = "play.solved" if first_try else "play.solved_after_mistake"
        if brilliant and first_try:
            key = "play.solved_brilliant"
        color = theme.BRILLIANT if brilliant and first_try else theme.ACCENT
        self.say(tx(key), color, tx("play.alt_mate") if alternative_mate else _empty)
        self.apply_outcome()
        self._finish()

    def _finish(self) -> None:
        assert self.session is not None
        self.state.mode = "full"
        self.state.explanation = explain_puzzle(self.session.puzzle, self.key_info)
        # Wyjaśnienie od początku (zamiast przewijać na koniec strumienia myśli).
        self.brain.tab = "thoughts"
        self.brain.scroll.scroll_to_top()
        self._go_live()
        self.analyze_current()

    def apply_outcome(self) -> None:
        session = self.session
        if session is None or self.selection is None:
            return
        outcome = session.take_outcome()
        if outcome is None:
            return
        change = self.app.profile.apply(session.puzzle, outcome, self.selection.mode)
        self.change = change
        self.app.topbar.on_rating_change(change)
        self.app.save()

    def hint(self) -> None:
        session = self.session
        if session is None or session.status != Status.PLAYER or self.view_index is not None:
            return
        rated = session.outcome is None
        square = session.hint()
        if square is None:
            return
        self.hint_square = square
        if self.state.mode == "hidden":
            self.state.mode = "hint"
        self.say(tx("play.hint"), theme.VIOLET, tx("play.hint_penalty") if rated else _empty)

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
        self.say(tx("play.try_again"), theme.TEXT, tx("play.try_again_detail"))
        self.analyze_current()

    def reveal_solution(self) -> None:
        session = self.session
        if session is None or session.finished or session.status == Status.INTRO:
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
        self.say(tx("play.solution"), theme.MUTED, partial(format_line, fen, ucis, None))
        for i, move in enumerate(moves):
            self.schedule(0.35 + i * REVEAL_STEP, partial(self._reveal_step, move))
        self.schedule(0.35 + len(moves) * REVEAL_STEP, self._finish)

    def _reveal_step(self, move: chess.Move) -> None:
        assert self.session is not None
        self._go_live()
        board_before = self.session.board.copy()
        self.session.push_revealed(move)
        self._show_move(board_before, move)

    # ================================================================ tryby panelu
    def set_mode(self, mode: str) -> None:
        session = self.session
        if session is None:
            return
        if mode == "hint":
            if session.status == Status.PLAYER:
                self.hint()
            else:
                self.state.mode = "hint"
            return
        if mode == "full" and session.outcome is None and session.status not in (Status.INTRO,):
            self.confirm = (tx("play.full_confirm"), self._forfeit_to_full)
            return
        self.state.mode = mode

    def _forfeit_to_full(self) -> None:
        assert self.session is not None
        self.session.forfeit()
        self.apply_outcome()
        self.state.mode = "full"
        self.say(tx("play.full_on"), theme.MUTED, tx("play.full_on_detail"))

    def _confirm_yes(self) -> None:
        if self.confirm:
            action = self.confirm[1]
            self.confirm = None
            action()

    def _confirm_no(self) -> None:
        self.confirm = None

    def toggle_why(self) -> None:
        self.show_why = not self.show_why
        self.why_at = self.clock

    # ================================================================ analiza silnika
    def current_board(self) -> chess.Board:
        """Pozycja widoczna na szachownicy (na żywo albo przeglądana po zadaniu)."""
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

    # ================================================================ podgląd wariantu
    def start_preview(self, index: int) -> None:
        info = self.state.info
        if info is None or index >= len(info.multi_pv):
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
            self._play_move_sound(board, undone)
        preview.index = new_index

    def stop_preview(self) -> None:
        if self.preview is None or self.session is None:
            return
        self.preview = None
        board = self.current_board()
        self.board_view.set_position(board, board.peek() if board.move_stack else None, animate=False)
        self.board_view.interactive = self.view_index is None and self.session.status == Status.PLAYER

    # ================================================================ cofanie się po ruchach (◀ ▶)
    def can_navigate(self) -> bool:
        """Ruchy można przeglądać w trakcie zadania i po nim — ale nie, gdy silnik sprawdza ruch albo trwa podgląd."""
        session = self.session
        if session is None or self.preview is not None or not session.board.move_stack:
            return False
        return session.status not in (Status.INTRO, Status.CHECKING)

    def _go_live(self, board: chess.Board | None = None) -> None:
        """Powrót z przeglądanej pozycji do bieżącej (przed każdym nowym ruchem na szachownicy)."""
        if self.view_index is None or self.session is None:
            return
        self.view_index = None
        live = board if board is not None else self.session.board
        self.board_view.set_position(live, live.peek() if live.move_stack else None, animate=False)

    def step_view(self, delta: int) -> None:
        """◀ / ▶: cofa albo przewija o jeden ruch. W trakcie zadania na starszej pozycji nie da się ruszyć;
        ▶ do końca wraca do bieżącej pozycji i znów można grać."""
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
            self._play_move_sound(board, undone)
        self.board_view.feedback = None
        live = self.view_index is None
        self.board_view.interactive = live and session.status == Status.PLAYER
        # Po zadaniu silnik analizuje oglądaną pozycję; w trakcie zadania liczy dalej bieżącą.
        if session.finished:
            self.analyze_current()

    # ================================================================ układ
    def layout(self, rect: pygame.Rect) -> None:
        super().layout(rect)
        g = px(18)
        w, h = rect.size
        self.wide = is_wide(*self.app.screen.get_size())
        controls_h = px(46)
        card_h = px(178)
        if self.wide:
            eval_w = px(22)
            panel_w = max(px(380), min(px(560), int(w * 0.36)))
            size = min(h - 2 * g - controls_h - px(14), w - panel_w - eval_w - 4 * g - px(12))
            size = max(px(240), size - size % 8)
            by = rect.y + g
            self.eval_rect = pygame.Rect(rect.x + g, by, eval_w, size)
            bx = self.eval_rect.right + px(12)
            self.board_view.rect = pygame.Rect(bx, by, size, size)
            self.eval_bar.horizontal = False
            self.controls_rect = pygame.Rect(bx, by + size + px(14), size, controls_h)
            col_x = bx + size + 2 * g
            col_w = rect.right - g - col_x
            self.card_rect = pygame.Rect(col_x, by, col_w, card_h)
            self.brain.rect = pygame.Rect(col_x, self.card_rect.bottom + px(14), col_w, rect.bottom - g - self.card_rect.bottom - px(14))
        else:
            # Współrzędne strony (0, 0 = lewy górny róg obszaru pod paskiem); strona jest przewijana.
            size = min(w - 2 * g, int(h * 0.68))
            size = max(px(200), size - size % 8)
            bx = (w - size) // 2
            by = g
            self.eval_rect = pygame.Rect(bx, by, size, px(18))
            self.eval_bar.horizontal = True
            self.board_view.rect = pygame.Rect(bx, by + px(26), size, size)
            self.controls_rect = pygame.Rect(g, self.board_view.rect.bottom + px(12), w - 2 * g, controls_h)
            self.card_rect = pygame.Rect(g, self.controls_rect.bottom + px(14), w - 2 * g, card_h)
            self.brain.rect = pygame.Rect(g, self.card_rect.bottom + px(14), w - 2 * g, max(px(600), h - px(80)))
            self.page_h = self.brain.rect.bottom + g
            self.scroll_y = min(self.scroll_y, max(0, self.page_h - h))
        self._layout_controls()

    def _layout_controls(self) -> None:
        """Pokazujemy tylko przyciski, które mają teraz sens: w trakcie zadania „Podpowiedź” i „Pokaż
        rozwiązanie” (po błędzie także „Spróbuj ponownie”), a „Następne zadanie” dopiero po jego zakończeniu."""
        r = self.controls_rect
        session = self.session
        finished = session is not None and session.finished
        self.btn_hint.visible = not finished
        self.btn_solution.visible = not finished
        self.btn_retry.visible = not finished and session is not None and session.status == Status.MISTAKE
        self.btn_next.visible = finished
        controls = [
            (self.btn_hint, "play.btn.hint", "play.btn.hint"),
            (self.btn_solution, "play.btn.solution", "play.btn.solution_short"),
            (self.btn_retry, "play.btn.retry", "play.btn.retry_short"),
            (self.btn_next, "play.btn.next", "play.btn.next_short"),
        ]
        visible = [entry for entry in controls if entry[0].visible]
        buttons = [button for button, _, _ in visible]
        nav_w = 0
        self.btn_prev_pos.visible = self.btn_next_pos.visible = session is not None and session.status != Status.INTRO
        if self.btn_prev_pos.visible:
            nav_w = 2 * r.height + px(16)
            self.btn_prev_pos.rect = pygame.Rect(r.x, r.y, r.height, r.height)
            self.btn_next_pos.rect = pygame.Rect(r.x + r.height + px(6), r.y, r.height, r.height)
        gap = px(8)
        avail = r.width - nav_w - (len(buttons) - 1) * gap
        long_labels = [long_key for _, long_key, _ in visible]
        short_labels = [short_key for _, _, short_key in visible]
        widths = [fonts.text_size(t(key), fs(14), "bold")[0] + px(26) for key in long_labels]
        keys = long_labels if sum(widths) <= avail else short_labels
        for button, key in zip(buttons, keys):
            button.label = tx(key)
        widths = [fonts.text_size(t(key), fs(14), "bold")[0] + px(26) for key in keys]
        extra = (avail - sum(widths)) / len(buttons)
        x = r.x + nav_w
        for button, bw in zip(buttons, widths):
            width = max(px(40), int(bw + extra))
            button.rect = pygame.Rect(x, r.y, width, r.height)
            x += width + gap

    # ================================================================ zdarzenia
    def _to_page(self, pos: tuple[int, int]) -> tuple[int, int]:
        return (pos[0] - self.rect.x, pos[1] - self.rect.y + int(self.scroll_y))

    def handle(self, event: pygame.event.Event) -> None:
        if self.confirm is not None:
            self.btn_confirm_yes.handle(event)
            self.btn_confirm_no.handle(event)
            return
        mouse_pos: tuple[int, int] | None = None
        if not self.wide:
            # Przeliczenie pozycji myszy na współrzędne przewijanej strony.
            mouse_pos = self._to_page(pygame.mouse.get_pos())
            if event.type == pygame.MOUSEWHEEL and not self.brain.wants_wheel(mouse_pos):
                max_scroll = max(0, self.page_h - self.rect.height)
                self.scroll_y = max(0.0, min(max_scroll, self.scroll_y - event.y * px(60)))
                return
            if hasattr(event, "pos"):
                event = pygame.event.Event(event.type, {**event.dict, "pos": self._to_page(event.pos)})
        if self.show_why and event.type == pygame.MOUSEBUTTONDOWN:
            self.show_why = False
            if self.btn_why.rect.collidepoint(event.pos):
                return
        if self.preview is not None:
            for button in (self.btn_preview_prev, self.btn_preview_next, self.btn_preview_close):
                if button.handle(event):
                    return
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_LEFT:
                    self.step_preview(-1)
                elif event.key == pygame.K_RIGHT:
                    self.step_preview(1)
                elif event.key == pygame.K_ESCAPE:
                    self.stop_preview()
                return
        elif self.board_view.handle(event):
            return
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_LEFT:
                self.step_view(-1)
            elif event.key == pygame.K_RIGHT:
                self.step_view(1)
        nav = [self.btn_prev_pos, self.btn_next_pos]
        controls = [] if self.preview is not None else [self.btn_hint, self.btn_solution, self.btn_retry, self.btn_next, *nav]
        for button in [*controls, self.btn_why]:
            if button.handle(event):
                return
        self.brain.handle(event, self.state, mouse_pos)

    # ================================================================ aktualizacja
    def update(self, dt: float) -> None:
        self.clock += dt
        due = [timer for timer in self.timers if timer[0] <= self.clock]
        if due:
            self.timers = [timer for timer in self.timers if timer[0] > self.clock]
            for _, action in due:
                action()
        self.board_view.update(dt)
        self.eval_bar.update(dt)

        # Automatyczne odtwarzanie wariantu w podglądzie.
        preview = self.preview
        if preview is not None and preview.auto and self.clock >= preview.next_step:
            if preview.index < len(preview.moves):
                board, _ = self._preview_board(preview.index)
                self._show_move(board, preview.moves[preview.index])
                preview.index += 1
                preview.next_step = self.clock + PREVIEW_STEP
            else:
                preview.auto = False

        session = self.session
        if session is None:
            return
        reveal = self.state.reveal
        info = self.state.info
        visible_fen = self.board_view.board.fen()
        self.eval_bar.hidden = not reveal
        if reveal and info is not None and self.preview is None and info.fen == visible_fen:
            self.eval_bar.set_score(info.score)
            arrows: list[tuple[chess.Square, chess.Square, tuple[int, ...]]] = []
            for line, color in zip(info.multi_pv[:3], theme.ENGINE_ARROWS):
                move = chess.Move.from_uci(line.move)
                arrows.append((move.from_square, move.to_square, color))
            self.board_view.arrows = arrows
        else:
            if reveal and info is not None and info.terminal and info.fen == visible_fen:
                self.eval_bar.set_score(info.score)
            self.board_view.arrows = []

        status = session.status
        self.btn_hint.enabled = status == Status.PLAYER and self.preview is None and self.view_index is None
        self.btn_solution.enabled = not session.finished and status not in (Status.INTRO, Status.CHECKING, Status.OPPONENT)
        self.btn_retry.enabled = status == Status.MISTAKE
        self.btn_next.enabled = session.finished
        navigable = self.can_navigate()
        current = len(session.board.move_stack) if self.view_index is None else self.view_index
        self.btn_prev_pos.enabled = navigable and current > 0
        self.btn_next_pos.enabled = navigable and self.view_index is not None
        # Podpowiedź widać tylko na bieżącej pozycji.
        self.board_view.hint_square = self.hint_square if self.view_index is None else None
        self._layout_controls()

    # ================================================================ rysowanie
    def draw(self, screen: pygame.Surface) -> None:
        surface = screen
        if not self.wide:
            size = (self.rect.width, self.page_h)
            if self.page is None or self.page.get_size() != size:
                self.page = pygame.Surface(size)
            self.page.blit(gfx.background(screen.get_size()), (0, -self.rect.y))
            surface = self.page
        self.eval_bar.draw(surface, self.eval_rect)
        self.board_view.draw(surface)
        if self.preview is not None:
            self._draw_preview_bar(surface)
        else:
            for button in [self.btn_hint, self.btn_solution, self.btn_retry, self.btn_next]:
                button.draw(surface)
            self.btn_prev_pos.draw(surface)
            self.btn_next_pos.draw(surface)
        self._draw_card(surface)
        self.brain.draw(surface, self.state)
        if self.show_why:
            self._draw_why(surface)
        if not self.wide and self.page is not None:
            screen.blit(self.page, self.rect.topleft, pygame.Rect(0, int(self.scroll_y), self.rect.width, self.rect.height))
            if self.page_h > self.rect.height:
                ratio = self.rect.height / self.page_h
                h = max(px(30), int(self.rect.height * ratio))
                y = self.rect.y + int((self.rect.height - h) * self.scroll_y / max(1, self.page_h - self.rect.height))
                gfx.rrect(screen, (*theme.BORDER[:3], 220), pygame.Rect(self.rect.right - px(6), y, px(4), h), px(2))
        if self.confirm is not None:
            self._draw_confirm(screen)

    def _draw_card(self, surface: pygame.Surface) -> None:
        r = self.card_rect
        card(surface, r)
        session = self.session
        if session is None:
            return
        pad = px(18)
        x, y, w = r.x + pad, r.y + px(14), r.width - 2 * pad
        puzzle = session.puzzle
        finished = session.outcome is not None or session.finished
        side = t("side.white") if session.player_color == chess.WHITE else t("side.black")
        # Znaczek koloru gracza
        gfx.circle(surface, (236, 239, 246) if session.player_color == chess.WHITE else (14, 16, 26), (x + px(6), y + px(9)), px(6))
        gfx.circle(surface, theme.BORDER, (x + px(6), y + px(9)), px(6), max(1, px(1)))
        rating_text = t("play.rating", rating=puzzle.rating) if finished else t("play.rating_hidden")
        rating_w = min(w // 2, fonts.text_size(rating_text, fs(13), "bold")[0] + px(4))
        draw_text(surface, rating_text, (r.right - pad, y), fs(13), theme.TEXT if finished else theme.DIM, "bold", "topright", max_width=rating_w)
        draw_text(surface, t("play.title", side=side), (x + px(18), y), fs(13), theme.MUTED, "bold", max_width=w - rating_w - px(30))
        y += px(26)

        # Komunikat: wyskakuje przy zmianie, zawsze mieści się w dwóch liniach.
        text_fn, color = self.message
        appear = ease_out_back((self.clock - self.message_at) / 0.35, 1.4)
        slide = round((1 - min(1.0, appear)) * px(8))
        message_h = px(52)
        draw_wrapped(surface, text_fn(), pygame.Rect(x, y + slide, w, message_h), fs(19), color, "bold", px(2), shrink=True)
        y += message_h + px(2)
        detail = self.detail()
        bottom = r.bottom - px(40)
        if detail:
            draw_wrapped(surface, detail, pygame.Rect(x, y, w, max(px(18), bottom - y - px(2))), fs(13), theme.TEXT_SOFT, "regular", px(2))

        # Dolny wiersz: motywy i zmiana rankingu albo „Dlaczego to zadanie?”
        if finished:
            themes = [theme_name(th) for th in skill_themes(puzzle.themes) if th != "mate"]
            delta_w = px(70)
            if themes:
                text = t("play.themes", themes=", ".join(themes))
                draw_text(surface, text, (x, bottom + px(17)), fs(12), theme.MUTED, "regular", "midleft", max_width=w - delta_w)
            if self.change is not None:
                delta = round(self.change.delta)
                label = f"+{delta}" if delta >= 0 else f"−{abs(delta)}"
                draw_text(surface, label, (r.right - pad, bottom + px(17)), fs(20), theme.ACCENT if delta >= 0 else theme.RED, "bold", "midright")
            self.btn_why.visible = False
        else:
            why_w = min(w, fonts.text_size(t("play.why"), fs(12), "bold")[0] + px(26))
            self.btn_why.rect = pygame.Rect(x - px(8), bottom + px(2), why_w, px(30))
            self.btn_why.visible = True
            self.btn_why.draw(surface)

    def _draw_why(self, surface: pygame.Surface) -> None:
        selection = self.selection
        if selection is None:
            return
        appear = ease_out_cubic((self.clock - self.why_at) / 0.25)
        width = min(px(440), self.card_rect.width)
        lines = selection.reason_texts()
        inner_w = width - px(44)
        body_h = sum(wrapped_height(line, inner_w, fs(13)) + px(6) for line in lines)
        height = px(52) + body_h
        rect = pygame.Rect(self.card_rect.x, self.btn_why.rect.bottom + px(6), width, height)
        limit = self.rect.bottom if self.wide else self.page_h
        if rect.bottom > limit:
            rect.bottom = self.btn_why.rect.top - px(6)
        rect.y += round((1 - appear) * px(10))
        card(surface, rect, color=theme.SURFACE_2)
        draw_text(surface, t("play.why"), (rect.x + px(18), rect.y + px(14)), fs(15), theme.TEXT, "bold", max_width=width - px(36))
        y = rect.y + px(44)
        for line in lines:
            gfx.circle(surface, theme.VIOLET, (rect.x + px(22), y + px(9)), px(3))
            y += draw_wrapped(surface, line, pygame.Rect(rect.x + px(32), y, inner_w, px(200)), fs(13), theme.TEXT_SOFT) + px(6)

    def _draw_preview_bar(self, surface: pygame.Surface) -> None:
        """Pasek podglądu wariantu — w miejscu przycisków pod szachownicą (nie zasłania figur)."""
        preview = self.preview
        assert preview is not None
        bar = self.controls_rect
        card(surface, bar, px(12), theme.SURFACE_2, elevated=False)
        buttons_w = px(42) * 2 + px(96) + px(24)
        text_w = bar.width - buttons_w - px(16)
        line = format_line(preview.fen, [m.uci() for m in preview.moves], None)
        draw_text(surface, t("play.preview", i=preview.index, n=len(preview.moves)), (bar.x + px(12), bar.y + px(4)), fs(11), theme.MUTED, max_width=text_w)
        draw_text(surface, line, (bar.x + px(12), bar.y + px(20)), fs(13), theme.TEXT, "bold", max_width=text_w)
        y = bar.y + (bar.height - px(32)) // 2
        self.btn_preview_prev.rect = pygame.Rect(bar.right - buttons_w + px(8), y, px(42), px(32))
        self.btn_preview_next.rect = pygame.Rect(self.btn_preview_prev.rect.right + px(4), y, px(42), px(32))
        self.btn_preview_close.rect = pygame.Rect(self.btn_preview_next.rect.right + px(6), y, px(90), px(32))
        for button in (self.btn_preview_prev, self.btn_preview_next, self.btn_preview_close):
            button.draw(surface)

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
        self.btn_confirm_no.rect = pygame.Rect(rect.x + px(24), rect.bottom - px(64), button_w, px(42))
        self.btn_confirm_yes.rect = pygame.Rect(self.btn_confirm_no.rect.right + px(12), rect.bottom - px(64), button_w, px(42))
        self.btn_confirm_yes.draw(surface)
        self.btn_confirm_no.draw(surface)


def _san_now(board_before: chess.Board, move: chess.Move, fallback: str) -> str:
    """SAN ruchu w bieżącym języku (po zmianie języka zmieniają się litery figur)."""
    try:
        return move_san(board_before, move)
    except (ValueError, AssertionError):
        return fallback
