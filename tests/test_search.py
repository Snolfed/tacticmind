"""Testy wyszukiwania: maty w 1, 2 i 3, MultiPV, statystyki, minimaks vs alfa-beta."""

import pytest

from tacticmind.engine.board import Board
from tacticmind.engine.compare import compare_algorithms, run_variant
from tacticmind.engine.constants import START_FEN
from tacticmind.engine.evaluation import evaluate_white, explain
from tacticmind.engine.movegen import parse_uci_move
from tacticmind.engine.search import Searcher, SearchLimits, find_best_move
from tacticmind.engine.types import EngineScore, format_score, to_white_score


def after_first_move(fen: str, first_move: str) -> Board:
    """Pozycja z zadania Lichess: FEN przed ruchem przeciwnika + pierwszy ruch z listy."""
    board = Board(fen)
    move = parse_uci_move(board, first_move)
    assert move != 0
    board.make_move(move)
    return Board(board.fen())


def mate_for_side_to_move(board: Board, mate_in: int | None) -> int | None:
    """Mat z perspektywy strony na ruchu (dodatni = to my matujemy)."""
    if mate_in is None:
        return None
    return mate_in if board.side == 0 else -mate_in


MATE_CASES = [
    ("mat w 1: mat na ostatniej linii", lambda: Board("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"), 1, "d1d8"),
    (
        "mat w 1: mat szewski",
        lambda: Board("r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"),
        1,
        "h5f7",
    ),
    ("mat w 1: Lichess 001cr", lambda: after_first_move("8/3B2pp/p5k1/2p3P1/1p1p1K2/8/1P6/8 b - - 0 38", "c5c4"), 1, "d7e8"),
    (
        "mat w 2: poświęcenie hetmana (Hd8+ Gxd8 We8#)",
        lambda: Board("r1b2k1r/ppp1bppp/8/1B1Q4/5q2/2P5/PPP2PPP/R3R1K1 w - - 1 1"),
        2,
        "d5d8",
    ),
    ("mat w 2: Lichess 00CtS", lambda: after_first_move("Q5k1/5q2/p2p4/b1p1pr2/P7/6P1/4KP1R/8 b - - 3 38", "g8g7"), 2, "a8h8"),
    (
        "mat w 2: Lichess 00LNB (czarne matują)",
        lambda: after_first_move("kr6/1pR4p/p4R2/n2r4/P3p3/4B3/6PP/6K1 b - - 0 38", "d5d3"),
        2,
        "f6a6",
    ),
    (
        "mat w 3: Lichess 00Pr6",
        lambda: after_first_move("r1b2rk1/p4ppp/2p5/6q1/2p3P1/3P1Q1P/PPP5/1K2RR2 b - - 0 17", "c4d3"),
        3,
        "f3f7",
    ),
    (
        "mat w 3: Lichess 005wy (czarne)",
        lambda: after_first_move("1r6/pp2kpp1/2n1p1n1/3p2PQ/5P2/2PqP3/PP1N4/2KR3R w - - 3 27", "h5h7"),
        3,
        "c6b4",
    ),
    (
        "mat w 3: Lichess 00NHK",
        lambda: after_first_move("r1b2rk1/1p2b1p1/pqn1p1P1/3pP3/1P1P4/P1N1P3/6P1/R2QK2R b KQ - 0 17", "c6e5"),
        3,
        "h1h8",
    ),
]


@pytest.mark.parametrize("name, make_board, mate, best", MATE_CASES, ids=[c[0] for c in MATE_CASES])
def test_finds_mate(name: str, make_board, mate: int, best: str) -> None:  # type: ignore[no-untyped-def]
    board = make_board()
    # Mat w N ruchów to 2N-1 półruchów — tyle wystarcza pełnemu przeszukaniu.
    info = find_best_move(board, max_depth=2 * mate - 1, time_ms=60_000)
    assert mate_for_side_to_move(board, info.mate_in) == mate
    assert info.best_move == best
    assert info.pv[0] == best


def test_terminal_positions() -> None:
    stalemate = find_best_move("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    assert stalemate.terminal == "stalemate"
    assert stalemate.score_cp == 0
    mated = find_best_move("3R3k/6pp/8/8/8/8/8/6K1 b - - 0 1")
    assert mated.terminal == "checkmate"
    assert mated.mate_in == 0


def test_prefers_faster_mate() -> None:
    """Białe mogą zamatować od razu albo zbić wieżę; szybszy mat ma wyższą ocenę."""
    info = find_best_move("6k1/5ppp/8/8/8/8/r4PPP/3R2K1 w - - 0 1", max_depth=4)
    assert info.mate_in == 1
    assert info.best_move == "d1d8"


def test_wins_hanging_queen() -> None:
    info = find_best_move("rnb1kbnr/pppp1ppp/8/4p1q1/3P4/2N5/PPP1PPPP/R1BQKBNR w KQkq - 0 3", max_depth=3)
    assert info.best_move == "c1g5"


def test_multipv_stats_and_tree() -> None:
    fen = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"
    board = Board(fen)
    depths: list[int] = []
    info = Searcher().search(
        board, SearchLimits(max_depth=4, time_ms=60_000, multi_pv=3, record_tree=True), lambda i: depths.append(i.depth)
    )
    assert depths == [1, 2, 3, 4]
    assert len(info.multi_pv) == 3
    values = [line.score.value for line in info.multi_pv]
    assert values == sorted(values, reverse=True)
    assert len({line.move for line in info.multi_pv}) == 3
    assert info.nodes > 0 and info.cutoffs > 0 and info.tt_hits > 0
    assert 0 < info.pruned_percent < 100
    assert info.tree and any(child.pruned for node in info.tree for child in node.children)
    assert board.fen() == fen  # plansza wraca do pozycji wyjściowej


def test_stop_restores_board() -> None:
    fen = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
    board = Board(fen)
    searcher = Searcher()
    calls = {"n": 0}

    def should_stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 15  # przerwij po ok. 15 tys. węzłów, w środku głębszej iteracji

    searcher.should_stop = should_stop
    info = searcher.search(board, SearchLimits(max_depth=10, time_ms=60_000, multi_pv=3))
    assert board.fen() == fen
    assert info.depth >= 1 and info.best_move


def test_score_formatting() -> None:
    assert format_score(EngineScore(150, None, 150)) == "+1.5"
    assert format_score(EngineScore(-30, None, -30)) == "-0.3"
    assert format_score(EngineScore(0, None, 0)) == "0.0"
    assert format_score(to_white_score(32000 - 5, 0)) == "M3"
    assert format_score(to_white_score(32000 - 2, 1)) == "-M1"


def test_evaluation_symmetry_and_breakdown() -> None:
    assert evaluate_white(Board(START_FEN)) == 0
    # Lustrzane odbicie pozycji (zamiana kolorów) zmienia znak oceny.
    fen = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"
    mirrored = "rnbqkb1r/pppp1ppp/5n2/4p3/4P3/2N5/PPPP1PPP/R1BQKBNR b KQkq - 2 3"
    assert evaluate_white(Board(fen)) == -evaluate_white(Board(mirrored))
    parts = explain(Board("4k3/8/8/8/8/8/8/3QK3 w - - 0 1"))
    assert parts.material > 900 and parts.total == evaluate_white(Board("4k3/8/8/8/8/8/8/3QK3 w - - 0 1"))
    assert evaluate_white(Board("4k3/8/8/8/8/8/8/2N1K3 w - - 0 1")) == 0  # brak materiału do mata


POSITIONS = [
    "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
]


@pytest.mark.parametrize("fen", POSITIONS)
def test_alpha_beta_matches_minimax_with_fewer_nodes(fen: str) -> None:
    for depth in (1, 2, 3):
        result = compare_algorithms(fen, depth, include_minimax=True)
        minimax = result.minimax
        assert minimax is not None
        assert result.alpha_beta.score == minimax.score
        assert result.alpha_beta_ordered.score == minimax.score
        assert result.alpha_beta.best_move == minimax.best_move
        if depth >= 2:
            assert result.alpha_beta.nodes < minimax.nodes
            assert result.alpha_beta_ordered.nodes < minimax.nodes


def test_move_ordering_saves_nodes() -> None:
    result = compare_algorithms(POSITIONS[1], 3, include_minimax=False)
    assert result.alpha_beta_ordered.score == result.alpha_beta.score
    assert result.alpha_beta_ordered.nodes < result.alpha_beta.nodes


def test_minimax_visits_full_tree() -> None:
    """Na głębokości 2 z pozycji startowej: 1 korzeń + 20 + 400 węzłów (jak perft)."""
    assert run_variant(START_FEN, 2, "minimax").nodes == 1 + 20 + 400
