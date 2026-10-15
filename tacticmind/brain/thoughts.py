"""„Strumień myśli” AI: zdania generowane z danych wyszukiwania przez szablony (w języku interfejsu).

Nie używamy żadnego zewnętrznego modelu językowego. Każde zdanie wynika
bezpośrednio z liczb, które zwraca silnik: najlepszy ruch, ocena, wariant (PV),
odsetek odciętych gałęzi, trafienia w tablicę transpozycji. Zmiana najlepszego
ruchu między głębokościami jest wyraźnie oznaczana — to pokazuje, że AI
naprawdę „myśli” i poprawia swoje zdanie, gdy liczy głębiej.

Szablony zdań są w ``tacticmind/i18n`` (klucze ``thought.*``, ``comment.*``, ``gain.*``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import chess

from ..engine.types import EngineScore, SearchInfo, format_score
from ..i18n import fmt_decimal, fmt_int, has, t
from ..puzzles.loader import Puzzle
from ..puzzles.themes import skill_themes, theme_name
from .notation import format_line, move_san, san_list, uci_san

ThoughtKind = Literal["depth", "change", "mate", "prune", "tt", "swing", "alt", "done", "info"]

_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}


@dataclass(frozen=True)
class Thought:
    text: str
    kind: ThoughtKind
    depth: int


def material(board: chess.Board, color: chess.Color) -> int:
    """Bilans materiału (w pionach) z perspektywy ``color``."""
    total = 0
    for piece in board.piece_map().values():
        value = _VALUES[piece.piece_type]
        total += value if piece.color == color else -value
    return total


def describe_gain(gain: int) -> str | None:
    """Słowny opis zysku materialnego w pionach."""
    if gain >= 8:
        return t("gain.queen")
    if gain >= 5:
        return t("gain.rook")
    if gain >= 3:
        return t("gain.piece")
    if gain == 2:
        return t("gain.exchange")
    if gain == 1:
        return t("gain.pawn")
    return None


def line_comment(fen: str, pv: list[str]) -> str | None:
    """Komentarz do wariantu, np. „Po Kxf7 Sg5+ wygrywam hetmana.”"""
    board = chess.Board(fen)
    me = board.turn
    start = material(board, me)
    played = 0
    for uci in pv:
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            break
        board.push(move)
        played += 1
    if played < 2:
        return None
    follow = " ".join(san_list(fen, pv, 3)[1:3])  # odpowiedź przeciwnika i nasz kolejny ruch
    if board.is_checkmate():
        return t("comment.mate", line=follow)
    gain = material(board, me) - start
    text = describe_gain(gain)
    if text:
        return t("comment.gain", line=follow, gain=text)
    if gain <= -3:
        return t("comment.sacrifice", line=follow)
    return None


class ThoughtStream:
    """Zamienia kolejne wiadomości silnika (głębokość po głębokości) na zdania."""

    def __init__(self, fen: str = chess.STARTING_FEN) -> None:
        self.reset(fen)

    def reset(self, fen: str) -> None:
        self.fen = fen
        self.thoughts: list[Thought] = []
        self._best: str | None = None
        self._score: EngineScore | None = None
        self._mate_announced = False
        self._tt_announced = False

    def _say(self, text: str, kind: ThoughtKind, depth: int) -> Thought:
        thought = Thought(text, kind, depth)
        self.thoughts.append(thought)
        return thought

    def on_info(self, info: SearchInfo) -> list[Thought]:
        if info.fen != self.fen:
            self.reset(info.fen)
        new: list[Thought] = []
        d = info.depth
        if not info.best_move:
            return new
        move = uci_san(self.fen, info.best_move)
        score = format_score(info.score)
        mate = info.score.mate
        me_white = chess.Board(self.fen).turn == chess.WHITE
        my_mate = mate is not None and (mate > 0) == me_white

        if self._best is None:
            new.append(self._say(t("thought.first", d=d, move=move, score=score), "depth", d))
        elif info.best_move != self._best:
            old = uci_san(self.fen, self._best)
            if mate is not None and my_mate:
                text = t("thought.change_mate", d=d, n=abs(mate), move=move)
                self._mate_announced = True
            else:
                text = t("thought.change", d=d, move=move, score=score, old=old)
            new.append(self._say(text, "change", d))
        elif mate is not None and not self._mate_announced:
            key = "thought.mate_found" if my_mate else "thought.mated"
            self._mate_announced = True
            new.append(self._say(t(key, d=d, n=abs(mate), move=move), "mate", d))
        else:
            text = t("thought.same", d=d, move=move, score=score)
            comment = line_comment(self.fen, info.pv)
            if comment:
                text += f" {comment}"
            new.append(self._say(text, "depth", d))
            if self._score is not None and mate is None and self._score.mate is None:
                swing = info.score.value - self._score.value
                if abs(swing) >= 150:
                    new.append(self._say(t("thought.swing", old=format_score(self._score), new=score), "swing", d))

        # Bliska alternatywa z MultiPV.
        if len(info.multi_pv) > 1 and mate is None:
            second = info.multi_pv[1]
            if abs(second.score.value - info.score.value) <= 25:
                alt = uci_san(self.fen, second.move)
                new.append(self._say(t("thought.alt", move=alt, score=format_score(second.score)), "alt", d))

        if d >= 3 and (d == 3 or d % 3 == 0) and info.pruned_percent > 0:
            new.append(self._say(t("thought.prune", pct=round(info.pruned_percent)), "prune", d))
        if d >= 4 and not self._tt_announced and info.tt_hits > 0:
            self._tt_announced = True
            new.append(self._say(t("thought.tt", n=fmt_int(info.tt_hits)), "tt", d))

        self._best = info.best_move
        self._score = info.score
        return new

    def on_done(self, info: SearchInfo) -> Thought | None:
        if info.terminal == "checkmate":
            return self._say(t("thought.checkmate"), "done", 0)
        if info.terminal == "stalemate":
            return self._say(t("thought.stalemate"), "done", 0)
        if not info.depth:
            return None
        text = t("thought.done", d=info.depth, nodes=fmt_int(info.nodes), secs=fmt_decimal(info.time_ms / 1000))
        return self._say(text, "done", info.depth)


# ---------------------------------------------------------------------------
# Wyjaśnienia zadania i błędów
# ---------------------------------------------------------------------------


def explain_puzzle(puzzle: Puzzle, engine_info: SearchInfo | None = None) -> list[str]:
    """Tryb „Pełny” panelu: AI tłumaczy zadanie po jego zakończeniu."""
    lines: list[str] = []
    start = puzzle.start_fen
    solution = list(puzzle.moves[1:])
    board = chess.Board(start)
    key = move_san(board, chess.Move.from_uci(solution[0]))
    lines.append(t("explain.solution", line=format_line(start, solution, None)))
    themes = skill_themes(puzzle.themes)
    mate_theme = next((th for th in themes if th.startswith("mateIn")), None)
    if mate_theme:
        lines.append(t("explain.key_mate", move=key, n=mate_theme[-1]))
    else:
        end = chess.Board(start)
        for uci in solution:
            end.push_uci(uci)
        result = describe_gain(material(end, board.turn) - material(board, board.turn))
        lines.append(t("explain.key_gain", move=key, gain=result) if result else t("explain.key", move=key))
    shown = [theme_name(th) for th in themes if not th.startswith("mateIn") and th != "mate"]
    if shown:
        lines.append(t("explain.themes", themes=", ".join(shown)))
    for theme in themes:
        if has(f"theme_expl.{theme}"):
            lines.append(t(f"theme_expl.{theme}"))
            break
    if engine_info is not None and engine_info.best_move:
        agree = engine_info.best_move == solution[0]
        verdict = t("explain.agrees") if agree else t("explain.proposes", move=uci_san(engine_info.fen, engine_info.best_move))
        lines.append(t("explain.engine", d=engine_info.depth, score=format_score(engine_info.score), verdict=verdict))
    return lines


def describe_refutation(fen_before: str, wrong_uci: str, reply_uci: str | None, after_score: EngineScore | None) -> str:
    """Komunikat po błędnym ruchu, np. „Po Wd1? przeciwnik gra Hxh2#. Mat.”"""
    board = chess.Board(fen_before)
    me = board.turn
    wrong = chess.Move.from_uci(wrong_uci)
    wrong_san = move_san(board, wrong)
    board.push(wrong)
    if reply_uci is None:
        return t("refute.generic", move=wrong_san)
    reply = chess.Move.from_uci(reply_uci)
    if reply not in board.legal_moves:
        return t("refute.short", move=wrong_san)
    reply_san = move_san(board, reply)
    before_material = material(board, me)
    board.push(reply)
    if board.is_checkmate():
        consequence = t("refute.mate")
    else:
        captured = before_material - material(board, me)
        if captured >= 3:
            consequence = t("refute.material", n=captured)
        elif after_score is not None:
            consequence = t("refute.eval", score=format_score(after_score))
        else:
            consequence = t("refute.lost")
    return t("refute.main", move=wrong_san, reply=reply_san, consequence=consequence)
