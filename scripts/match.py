"""Mecz między silnikami — pomiar siły (Elo) silnika TacticMind.

Gracz to polecenie silnika UCI (np. ``tacticmind/engine/native/build/tmengine``, ``stockfish``)
albo ``python`` — stary silnik w czystym Pythonie (``engine/search.py``). Każde otwarcie
z listy grane jest dwa razy, z zamianą kolorów.

Przykłady::

    python scripts/build_engine.py                     # buduje m.in. program UCI tmengine
    # nowy silnik (C + NNUE) przeciw staremu (Python), 1 s na ruch:
    python scripts/match.py --a tacticmind/engine/native/build/tmengine --b python --movetime 1000 --games 40
    # przeciw Stockfishowi ograniczonemu do 2600 Elo, tempo 10 s + 0,1 s:
    python scripts/match.py --a tacticmind/engine/native/build/tmengine --b stockfish \\
        --b-option UCI_LimitStrength=true --b-option UCI_Elo=2600 --tc 10+0.1 --games 100 --concurrency 4

Wynik: punkty, różnica Elo z 95% przedziałem ufności (model logistyczny).
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

# Krótkie, popularne otwarcia (UCI), żeby partie się różniły.
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


def play_game(a: Player, b: Player, opening: str, a_white: bool, control: Control) -> tuple[float, str]:
    """Jedna partia. Zwraca (wynik gracza A: 1 / 0.5 / 0, opis zakończenia)."""
    board = chess.Board()
    for uci in opening.split():
        board.push_uci(uci)
    engines: dict[bool, chess.engine.SimpleEngine | None] = {}
    clocks = {chess.WHITE: control.base_s, chess.BLACK: control.base_s}
    try:
        for player, color in ((a, chess.WHITE if a_white else chess.BLACK), (b, chess.BLACK if a_white else chess.WHITE)):
            if player.spec == "python":
                engines[color] = None
            else:
                proc = chess.engine.SimpleEngine.popen_uci(shlex.split(player.spec))
                for name, value in player.options:
                    proc.configure({name: value})
                engines[color] = proc
        reason = ""
        while not board.is_game_over(claim_draw=True):
            eng = engines[board.turn]
            move: chess.Move | None
            if eng is None:
                ms = control.movetime_ms or int(1000 * max(0.05, clocks[board.turn] / 30 + control.inc_s))
                move = _python_move(board, ms)
            else:
                if control.movetime_ms:
                    limit = chess.engine.Limit(time=control.movetime_ms / 1000)
                else:
                    limit = chess.engine.Limit(
                        white_clock=clocks[chess.WHITE], black_clock=clocks[chess.BLACK],
                        white_inc=control.inc_s, black_inc=control.inc_s,
                    )
                t0 = time.perf_counter()
                move = eng.play(board, limit).move
                if not control.movetime_ms:
                    clocks[board.turn] -= time.perf_counter() - t0
                    if clocks[board.turn] < 0:
                        reason = "czas"
                        loser_white = board.turn == chess.WHITE
                        return (0.0 if loser_white == a_white else 1.0), reason
                    clocks[board.turn] += control.inc_s
            if move is None or move not in board.legal_moves:
                reason = "nielegalny ruch"
                return (0.0 if board.turn == (chess.WHITE if a_white else chess.BLACK) else 1.0), reason
            board.push(move)
            if board.fullmove_number > 300:
                return 0.5, "limit ruchów"
        outcome = board.outcome(claim_draw=True)
        assert outcome is not None
        reason = outcome.termination.name.lower()
        if outcome.winner is None:
            return 0.5, reason
        return (1.0 if outcome.winner == (chess.WHITE if a_white else chess.BLACK) else 0.0), reason
    finally:
        for opened in engines.values():
            if opened is not None:
                with contextlib.suppress(Exception):
                    opened.quit()


def elo_estimate(wins: int, draws: int, losses: int) -> tuple[float, float]:
    """Różnica Elo i połowa 95% przedziału ufności."""
    games = wins + draws + losses
    p = (wins + 0.5 * draws) / games
    var = max((wins + 0.25 * draws) / games - p * p, 1e-4)  # wariancja wyniku jednej partii
    se = math.sqrt(var / games)

    def to_elo(x: float) -> float:
        x = min(max(x, 1e-3), 1 - 1e-3)
        return -400 * math.log10(1 / x - 1)

    return to_elo(p), (to_elo(p + 1.96 * se) - to_elo(p - 1.96 * se)) / 2


def parse_options(values: list[str]) -> tuple[tuple[str, str], ...]:
    return tuple(tuple(v.split("=", 1)) for v in values)  # type: ignore[misc]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--a", required=True, help="gracz A: polecenie UCI albo 'python'")
    parser.add_argument("--b", required=True, help="gracz B: polecenie UCI albo 'python'")
    parser.add_argument("--a-option", action="append", default=[], help="opcja UCI gracza A, np. Hash=64")
    parser.add_argument("--b-option", action="append", default=[], help="opcja UCI gracza B, np. UCI_Elo=2600")
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--movetime", type=int, default=0, help="stały czas na ruch (ms)")
    parser.add_argument("--tc", default="10+0.1", help="tempo: sekundy+przyrost (gdy brak --movetime)")
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
            print(f"[{n}/{args.games}] A {wins}W {draws}R {losses}P  wynik {score}/{n}  Elo A−B: {elo:+.0f} ± {margin:.0f}", flush=True)
    print("zakończenia:", reasons)


if __name__ == "__main__":
    main()
