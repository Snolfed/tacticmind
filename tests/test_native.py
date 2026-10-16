"""Silnik w C (bitboardy + NNUE): perft, maty, MultiPV, drzewo, przerwanie, symetria oceny.

Testy są pomijane, gdy biblioteki nie da się zbudować (brak kompilatora C).
"""

import pytest

from tacticmind.engine.board import Board
from tacticmind.engine.csearch import CSearcher, make_searcher
from tacticmind.engine.native import NET_PATH, load
from tacticmind.engine.search import SearchLimits

from .test_search import MATE_CASES, mate_for_side_to_move

LIB = load()
pytestmark = pytest.mark.skipif(LIB is None, reason="silnik w C niedostępny (brak kompilatora)")

PERFT = [
    ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 5, 4_865_609),
    ("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 4, 4_085_603),
    ("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 5, 674_624),
    ("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", 4, 422_333),
    ("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", 4, 2_103_487),
]


def searcher() -> CSearcher:
    assert LIB is not None
    return CSearcher(LIB)


@pytest.mark.parametrize("fen, depth, nodes", PERFT)
def test_perft(fen: str, depth: int, nodes: int) -> None:
    assert LIB is not None
    assert LIB.lib.tm_perft(fen.encode(), depth) == nodes


@pytest.mark.parametrize("name, make_board, mate, best", MATE_CASES, ids=[c[0] for c in MATE_CASES])
def test_finds_mate(name: str, make_board, mate: int, best: str) -> None:  # type: ignore[no-untyped-def]
    board = make_board()
    info = searcher().search(board, SearchLimits(max_depth=30, time_ms=30_000))
    assert mate_for_side_to_move(board, info.mate_in) == mate
    assert info.best_move == best
    assert info.pv[0] == best


def test_terminal_positions() -> None:
    stalemate = searcher().search("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", SearchLimits(time_ms=1000))
    assert stalemate.terminal == "stalemate" and stalemate.score_cp == 0
    mated = searcher().search("3R3k/6pp/8/8/8/8/8/6K1 b - - 0 1", SearchLimits(time_ms=1000))
    assert mated.terminal == "checkmate" and mated.mate_in == 0


def test_wins_hanging_queen() -> None:
    info = searcher().search(
        "rnb1kbnr/pppp1ppp/8/4p1q1/3P4/2N5/PPP1PPPP/R1BQKBNR w KQkq - 0 3", SearchLimits(max_depth=8, time_ms=10_000)
    )
    assert info.best_move == "c1g5"


def test_mate_beats_fifty_move_rule() -> None:
    # Mat w setnym półruchu kończy partię matem, nie remisem — silnik nie może go oddać.
    info = searcher().search("7k/8/6K1/8/8/8/8/R7 w - - 99 120", SearchLimits(max_depth=6, time_ms=10_000))
    assert info.best_move == "a1a8" and info.mate_in == 1
    # Obrona: czarne nie mogą wejść w mata, licząc na remis z reguły 50 ruchów.
    info = searcher().search("6k1/8/6K1/8/8/8/8/R7 b - - 98 120", SearchLimits(max_depth=6, time_ms=10_000))
    assert info.best_move == "g8f8"


def test_impossible_en_passant_square_is_ignored() -> None:
    # Pole e6 z FEN, choć nie ma czarnego piona na e5 — bicie w przelocie byłoby niemożliwe.
    assert LIB is not None
    bogus = LIB.lib.tm_perft(b"4k3/8/8/3P4/8/8/8/4K3 w - e6 0 1", 3)
    assert bogus == LIB.lib.tm_perft(b"4k3/8/8/3P4/8/8/8/4K3 w - - 0 1", 3)


def test_multipv_stats_and_tree() -> None:
    fen = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"
    depths: list[int] = []
    info = searcher().search(
        Board(fen), SearchLimits(max_depth=8, time_ms=60_000, multi_pv=3, record_tree=True), lambda i: depths.append(i.depth)
    )
    assert depths == list(range(1, 9))
    assert len(info.multi_pv) == 3
    values = [line.score.value for line in info.multi_pv]
    assert values == sorted(values, reverse=True)
    assert len({line.move for line in info.multi_pv}) == 3
    assert all(line.pv[0] == line.move for line in info.multi_pv)
    assert len(info.pv) >= 4
    assert info.nodes > 0 and info.cutoffs > 0 and info.tt_hits > 0 and info.qnodes > 0
    assert 0 < info.pruned_percent < 100
    assert info.tree and any(child.pruned for node in info.tree for child in node.children)
    assert info.tree[0].move == info.best_move


def test_stop_and_progress() -> None:
    s = searcher()
    calls = {"n": 0, "progress": 0}

    def should_stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 10  # ok. 200 ms

    def on_progress(_p: object) -> None:
        calls["progress"] += 1

    s.should_stop = should_stop
    s.on_progress = on_progress
    info = s.search(
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", SearchLimits(max_depth=60, time_ms=60_000)
    )
    assert s.stopped and info.depth >= 1 and info.best_move
    assert calls["progress"] >= 1


def test_nnue_eval_is_color_symmetric() -> None:
    assert LIB is not None
    fen = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"
    mirrored = "rnbqkb1r/pppp1ppp/5n2/4p3/4P3/2N5/PPPP1PPP/R1BQKBNR b KQkq - 2 3"
    for nnue in (0, 1):
        assert LIB.lib.tm_eval(fen.encode(), nnue) == LIB.lib.tm_eval(mirrored.encode(), nnue)


def test_network_is_shipped_and_sane() -> None:
    assert LIB is not None
    assert NET_PATH.exists() and LIB.nnue
    up_queen = LIB.lib.tm_eval(b"4k3/8/8/8/8/8/8/3QK3 w - - 0 1", 1)
    assert up_queen > 500
    assert abs(LIB.lib.tm_eval(b"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 1)) < 80


def test_make_searcher_prefers_c() -> None:
    assert isinstance(make_searcher(), CSearcher)
