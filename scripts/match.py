"""Engine-vs-engine match — measuring the strength (Elo) of the TacticMind engine.

A player is a UCI engine command (e.g. ``tacticmind/engine/native/build/tmengine``, ``stockfish``)
or ``python`` — the old pure-Python engine (``engine/search.py``). Each opening
from the list is played twice, with colors swapped.

Examples::

    python scripts/build_engine.py                     # builds, among others, the tmengine UCI program
    # new engine (C + NNUE) against the old one (Python), 1 s per move:
    python scripts/match.py --a tacticmind/engine/native/build/tmengine --b python --movetime 1000 --games 40
    # against Stockfish limited to 2600 Elo, time control 10 s + 0.1 s:
    python scripts/match.py --a tacticmind/engine/native/build/tmengine --b stockfish \\
        --b-option UCI_LimitStrength=true --b-option UCI_Elo=2600 --tc 10+0.1 --games 100 --concurrency 4

Output: points, Elo difference with a 95% confidence interval (logistic model).
"""

from __future__ import annotations

import argparse
import contextlib
import math
import shlex
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import chess
import chess.engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Short, popular openings (UCI) so the games differ.
OPENINGS = [
    "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6",
    "e2e4 e7e5 g1f3 b8c6 f1c4 f8c5",
    "e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4 g8f6",
    "e2e4 c7c5 g1f3 b8c6 d2d4 c5d4 f3d4",
    "e2e4 c7c5 b1c3 b8c6 g2g3",
    "e2e4 e7e6 d2d4 d7d5 b1c3 g8f6",
    "e2e4 e7e6 d2d4 d7d5 e4e5 c7c5",
    "e2e4 c7c6 d2d4 d7d5 e4e5 c8f5",
    "e2e4 c7c6 d2d4 d7d5 b1c3 d5e4 c3e4",
    "e2e4 d7d6 d2d4 g8f6 b1c3 g7g6",
    "e2e4 d7d5 e4d5 d8d5 b1c3 d5a5",
    "e2e4 g8f6 e4e5 f6d5 d2d4 d7d6",
    "d2d4 d7d5 c2c4 e7e6 b1c3 g8f6",
    "d2d4 d7d5 c2c4 c7c6 g1f3 g8f6",
    "d2d4 d7d5 c2c4 d5c4 g1f3 g8f6",
    "d2d4 g8f6 c2c4 g7g6 b1c3 f8g7 e2e4 d7d6",
    "d2d4 g8f6 c2c4 e7e6 b1c3 f8b4",
    "d2d4 g8f6 c2c4 e7e6 g1f3 b7b6",
    "d2d4 g8f6 c2c4 c7c5 d4d5 e7e6",
    "d2d4 f7f5 g2g3 g8f6 f1g2",
    "d2d4 d7d5 g1f3 g8f6 c1f4",
    "c2c4 e7e5 b1c3 g8f6 g1f3 b8c6",
    "c2c4 c7c5 g1f3 g8f6 b1c3",
    "g1f3 d7d5 g2g3 g8f6 f1g2",
    "e2e4 e7e5 f2f4 e5f4 g1f3",
    "e2e4 e7e5 g1f3 g8f6 f3e5 d7d6",
    "e2e4 e7e5 b1c3 g8f6 f2f4",
    "d2d4 g8f6 g1f3 e7e6 c1g5",
    "e2e4 b7b6 d2d4 c8b7",
    "b2b3 e7e5 c1b2 b8c6",
]


@dataclass(frozen=True)
class Player:
    spec: str
    options: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Control:
    movetime_ms: int | None
    base_s: float
    inc_s: float


def _python_move(board: chess.Board, ms: int) -> chess.Move:
    from tacticmind.engine.board import Board
    from tacticmind.engine.search import Searcher, SearchLimits

    info = Searcher().search(Board(board.fen()), SearchLimits(time_ms=ms, multi_pv=1))
    return chess.Move.from_uci(info.best_move)


def _engine_command(spec: str) -> list[str]:
    """Engine command. On Windows, shlex in POSIX mode would eat the backslashes in the path."""
    if Path(spec).exists():
        return [spec]
    if sys.platform == "win32":
        return [part.strip('"') for part in shlex.split(spec, posix=False)]
    return shlex.split(spec)


def _finished(board: chess.Board) -> tuple[bool | None, str] | None:
    """A game end that actually happened: (winner, or None for a draw, reason) or None.

    We do not use ``claim_draw=True`` — it declares a draw when the side to move *could* claim one,
    even if it has a win (e.g. mate on the hundredth half-move)."""
    if board.is_checkmate():
        return (not board.turn), "checkmate"
    if board.is_stalemate():
        return None, "stalemate"
    if board.is_insufficient_material():
        return None, "insufficient material"
    if board.is_repetition(3):
        return None, "repetition"
    if board.halfmove_clock >= 100:
        return None, "50-move rule"
    if board.fullmove_number > 300:
        return None, "move limit"
    return None


def play_game(a: Player, b: Player, opening: str, a_white: bool, control: Control) -> tuple[float, str]:
    """One game. Returns (player A's score: 1 / 0.5 / 0, description of the ending)."""
    board = chess.Board()
    for uci in opening.split():
        board.push_uci(uci)
    a_color = chess.WHITE if a_white else chess.BLACK
    engines: dict[bool, chess.engine.SimpleEngine | None] = {}
    clocks = {chess.WHITE: control.base_s, chess.BLACK: control.base_s}

    def loss_of(color: bool, reason: str) -> tuple[float, str]:
        return (0.0 if color == a_color else 1.0), reason

    try:
        for player, color in ((a, a_color), (b, not a_color)):
            if player.spec == "python":
                engines[color] = None
            else:
                proc = chess.engine.SimpleEngine.popen_uci(_engine_command(player.spec))
                for name, value in player.options:
                    proc.configure({name: value})
                engines[color] = proc
        while (end := _finished(board)) is None:
            eng = engines[board.turn]
            move: chess.Move | None
            t0 = time.perf_counter()
            try:
                if eng is None:
                    if control.movetime_ms:
                        ms = control.movetime_ms
                    else:
                        ms = int(1000 * max(0.02, clocks[board.turn] / 30 + control.inc_s * 0.75))
                    move = _python_move(board, ms)
                else:
                    if control.movetime_ms:
                        limit = chess.engine.Limit(time=control.movetime_ms / 1000)
                    else:
                        limit = chess.engine.Limit(
                            white_clock=clocks[chess.WHITE], black_clock=clocks[chess.BLACK],
                            white_inc=control.inc_s, black_inc=control.inc_s,
                        )
                    move = eng.play(board, limit).move
            except (chess.engine.EngineError, chess.engine.EngineTerminatedError, ValueError):
                # python-chess reports an illegal bestmove as EngineError — that is a loss, not the end of the match.
                return loss_of(board.turn, "illegal move / engine crash")
            if not control.movetime_ms:
                clocks[board.turn] -= time.perf_counter() - t0
                if clocks[board.turn] < 0:
                    # Running out of time is a draw if the opponent cannot possibly mate (FIDE 6.9).
                    if board.has_insufficient_material(not board.turn):
                        return 0.5, "time / insufficient material"
                    return loss_of(board.turn, "time")
                clocks[board.turn] += control.inc_s
            if move is None or move not in board.legal_moves:
                return loss_of(board.turn, "illegal move")
            board.push(move)
        winner, reason = end
        if winner is None:
            return 0.5, reason
        return (1.0 if winner == a_color else 0.0), reason
    finally:
        for opened in engines.values():
            if opened is not None:
                with contextlib.suppress(Exception):
                    opened.quit()


def elo_estimate(wins: int, draws: int, losses: int) -> tuple[float, float]:
    """Elo difference and half of the 95% confidence interval."""
    games = wins + draws + losses
    p = (wins + 0.5 * draws) / games
    var = max((wins + 0.25 * draws) / games - p * p, 1e-4)  # variance of a single game's score
    se = math.sqrt(var / games)

    def to_elo(x: float) -> float:
        x = min(max(x, 1e-3), 1 - 1e-3)
        return -400 * math.log10(1 / x - 1)

    return to_elo(p), (to_elo(p + 1.96 * se) - to_elo(p - 1.96 * se)) / 2


def parse_options(values: list[str]) -> tuple[tuple[str, str], ...]:
    return tuple(tuple(v.split("=", 1)) for v in values)  # type: ignore[misc]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--a", required=True, help="player A: UCI command or 'python'")
    parser.add_argument("--b", required=True, help="player B: UCI command or 'python'")
    parser.add_argument("--a-option", action="append", default=[], help="UCI option for player A, e.g. Hash=64")
    parser.add_argument("--b-option", action="append", default=[], help="UCI option for player B, e.g. UCI_Elo=2600")
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--movetime", type=int, default=0, help="fixed time per move (ms)")
    parser.add_argument("--tc", default="10+0.1", help="time control: seconds+increment (when --movetime is not given)")
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()

    a = Player(args.a, parse_options(args.a_option))
    b = Player(args.b, parse_options(args.b_option))
    base, _, inc = args.tc.partition("+")
    control = Control(args.movetime or None, float(base), float(inc or 0))
    jobs = []
    for i in range(args.games):
        opening = OPENINGS[(i // 2) % len(OPENINGS)]
        jobs.append((opening, i % 2 == 0))

    score = 0.0
    wins = draws = losses = 0
    reasons: dict[str, int] = {}
    with ProcessPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(play_game, a, b, opening, a_white, control) for opening, a_white in jobs]
        for n, fut in enumerate(as_completed(futures), 1):
            result, reason = fut.result()
            score += result
            wins += result == 1.0
            draws += result == 0.5
            losses += result == 0.0
            reasons[reason] = reasons.get(reason, 0) + 1
            elo, margin = elo_estimate(wins, draws, losses)
            print(f"[{n}/{args.games}] A {wins}W {draws}D {losses}L  score {score}/{n}  Elo A−B: {elo:+.0f} ± {margin:.0f}", flush=True)
    print("endings:", reasons)


if __name__ == "__main__":
    main()
