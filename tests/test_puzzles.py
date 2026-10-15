"""Zadania: dane Lichess, przebieg rozwiązywania, alternatywne rozwiązania, notacja i myśli AI."""

import chess
import pytest

from taktykai.brain.notation import format_line, to_polish
from taktykai.brain.thoughts import ThoughtStream, describe_refutation, explain_puzzle
from taktykai.engine.board import Board
from taktykai.engine.movegen import make_legal_move, parse_uci_move
from taktykai.engine.search import Searcher, SearchLimits
from taktykai.engine.types import EngineScore
from taktykai.i18n import has, set_language
from taktykai.puzzles.loader import FULL_SET, STARTER_SET, Puzzle, load_puzzles
from taktykai.puzzles.session import PuzzleSession, Status, Verdict
from taktykai.puzzles.themes import theme_name
from taktykai.puzzles.validator import Alternative, judge_alternative


def test_starter_set_is_real_lichess_data() -> None:
    puzzles = load_puzzles(STARTER_SET)
    assert 40 <= len(puzzles) <= 60
    ratings = [p.rating for p in puzzles]
    assert min(ratings) < 800 and max(ratings) > 2400
    assert len({t for p in puzzles for t in p.themes}) > 20
    assert all(p.url.startswith("https://lichess.org/") for p in puzzles)


@pytest.mark.parametrize("path", [STARTER_SET, FULL_SET])
def test_engine_and_python_chess_agree_on_every_puzzle(path) -> None:  # type: ignore[no-untyped-def]
    """Każdy ruch każdego zadania jest legalny w naszym generatorze, a FEN-y zgadzają się z python-chess."""
    if not path.exists():
        pytest.skip("brak pełnego zestawu")
    for puzzle in load_puzzles(path):
        ours = Board(puzzle.fen)
        ref = chess.Board(puzzle.fen)
        for uci in puzzle.moves:
            move = parse_uci_move(ours, uci)
            assert move and make_legal_move(ours, move), (puzzle.id, uci)
            ref.push_uci(uci)
            # python-chess domyślnie pokazuje pole en passant tylko przy możliwym biciu; prosimy o zapis zgodny ze standardem FEN.
            assert ours.fen().split()[:4] == ref.fen(en_passant="fen").split()[:4], puzzle.id


def test_all_themes_translated() -> None:
    for code in ("pl", "en"):
        set_language(code)
        for puzzle in load_puzzles():
            for theme in puzzle.themes:
                assert has(f"theme.{theme}"), (code, theme)
    set_language("en")
    assert theme_name("fork") == "fork"
    assert theme_name("backRankMate") == "back rank mate"
    set_language("pl")
    assert theme_name("fork") == "widełki"
    assert theme_name("skewer") == "przeszycie"
    assert theme_name("mateIn2") == "mat w 2"


# Zadanie 00LNB: czarne grają Wd3, białe: Wxa6+ bxa6 Wa7# (mat w 2).
LNB = Puzzle(
    "00LNB", "kr6/1pR4p/p4R2/n2r4/P3p3/4B3/6PP/6K1 b - - 0 38", ("d5d3", "f6a6", "b7a6", "c7a7"), 1074, 80, ("mateIn2", "sacrifice")
)


def test_session_happy_path() -> None:
    clock = iter(range(100)).__next__
    session = PuzzleSession(LNB, clock=lambda: float(clock()))
    assert session.player_color == chess.WHITE
    assert session.play_intro() == chess.Move.from_uci("d5d3")
    assert session.status == Status.PLAYER
    assert session.submit(chess.Move.from_uci("f6a6")) == Verdict.CORRECT
    assert session.status == Status.OPPONENT
    assert session.opponent_reply() == chess.Move.from_uci("b7a6")
    assert session.submit(chess.Move.from_uci("c7a7")) == Verdict.SOLVED
    outcome = session.take_outcome()
    assert outcome is not None and outcome.solved and not outcome.mistake and not outcome.hint_used
    assert session.take_outcome() is None  # wynik księgujemy tylko raz


def test_session_mistake_retry_and_reveal() -> None:
    session = PuzzleSession(LNB)
    session.play_intro()
    square = session.hint()
    assert square == chess.F6
    assert session.submit(chess.Move.from_uci("g1f1")) == Verdict.NEEDS_ENGINE
    assert session.resolve(Alternative.MISTAKE, chess.Move.from_uci("d3d1")) == Verdict.MISTAKE
    assert session.status == Status.MISTAKE
    outcome = session.take_outcome()
    assert outcome is not None and outcome.mistake and not outcome.solved and outcome.hint_used
    session.retry()
    assert session.board.fen() == LNB.start_fen
    remaining = session.reveal()
    assert [m.uci() for m in remaining] == ["f6a6", "b7a6", "c7a7"]
    for move in remaining:
        session.push_revealed(move)
    assert session.board.is_checkmate()


def test_good_but_better_is_not_a_mistake() -> None:
    session = PuzzleSession(LNB)
    session.play_intro()
    session.submit(chess.Move.from_uci("c7c8"))
    assert session.resolve(Alternative.GOOD_BUT_BETTER, None) == Verdict.GOOD_BUT_BETTER
    assert session.status == Status.PLAYER and not session.mistake
    assert session.take_outcome() is None


def test_alternative_mate_solves_puzzle() -> None:
    # Pozycja z dwoma matami w 1: Wd8# (wzorzec) i Hg7#? — tu: wzorzec d1d8, alternatywa h6g7.
    puzzle = Puzzle("alt", "6k1/5p1p/5PpQ/8/8/8/5PPP/3R2K1 b - - 0 1", ("g8f8", "h6g7"), 1000, 80, ("mateIn1",))
    session = PuzzleSession(puzzle)
    session.play_intro()
    board = session.board
    alternatives = [m for m in board.legal_moves if m.uci() != "h6g7" and board.gives_check(m)]
    mates = []
    for move in alternatives:
        board.push(move)
        if board.is_checkmate():
            mates.append(move)
        board.pop()
    assert mates, "pozycja testowa powinna mieć drugiego mata"
    assert session.submit(mates[0]) == Verdict.SOLVED_ALT_MATE
    outcome = session.take_outcome()
    assert outcome is not None and outcome.solved


def test_judge_alternative_rules() -> None:
    best = EngineScore(650, None, 650)
    assert judge_alternative(best, EngineScore(620, None, 620), chess.WHITE) == Alternative.GOOD_BUT_BETTER
    assert judge_alternative(best, EngineScore(560, None, 560), chess.WHITE) == Alternative.MISTAKE
    assert judge_alternative(EngineScore(250, None, 250), EngineScore(240, None, 240), chess.WHITE) == Alternative.MISTAKE
    # Z perspektywy czarnych znak się odwraca.
    assert judge_alternative(EngineScore(-650, None, -650), EngineScore(-640, None, -640), chess.BLACK) == Alternative.GOOD_BUT_BETTER
    # Mat w 3 zamiast mata w 2: dobry ruch, ale jest lepszy.
    assert judge_alternative(EngineScore(None, 2, 31997), EngineScore(None, 3, 31995), chess.WHITE) == Alternative.GOOD_BUT_BETTER


def test_polish_notation() -> None:
    assert to_polish("Qxf7+") == "Hxf7+"
    assert to_polish("Nf3") == "Sf3"
    assert to_polish("Bb5") == "Gb5"
    assert to_polish("Rd8#") == "Wd8#"
    assert to_polish("exd8=Q+") == "exd8=H+"
    assert to_polish("O-O-O") == "O-O-O"
    fen = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
    assert format_line(fen, ["f3f7"]) == "1. Hxf7#"
    assert format_line(LNB.start_fen, ["f6a6", "b7a6", "c7a7"]) == "1. Wxa6+ bxa6 2. Wa7#"
    black_fen = "kr6/1pR4p/p4R2/n2r4/P3p3/4B3/6PP/6K1 b - - 0 38"
    assert format_line(black_fen, ["d5d3", "f6a6"]) == "1... Wd3 2. Wxa6+"


def test_thought_stream_from_real_search() -> None:
    fen = LNB.start_fen
    stream = ThoughtStream(fen)
    infos = []
    Searcher().search(Board(fen), SearchLimits(max_depth=4, time_ms=30_000, multi_pv=3), infos.append)
    for info in infos:
        stream.on_info(info)
    texts = [t.text for t in stream.thoughts]
    assert texts[0].startswith("Głębokość 1:")
    assert any("mata w 2" in t for t in texts)
    assert any("Wxa6+" in t for t in texts)
    assert any("alfa-beta pomijam" in t for t in texts)


def test_thought_stream_marks_change_of_mind() -> None:
    from taktykai.engine.types import SearchInfo

    def info(depth: int, move: str, cp: int) -> SearchInfo:
        score = EngineScore(cp, None, cp)
        return SearchInfo(0, LNB.start_fen, depth, depth, cp, None, score, move, [move], [], 10, 5, 100, 1, 0, 50.0, 10, [])

    stream = ThoughtStream(LNB.start_fen)
    stream.on_info(info(1, "c7c8", 300))
    changed = stream.on_info(info(2, "f6a6", 900))
    assert changed[0].kind == "change"
    assert changed[0].text.startswith("Zmieniam zdanie!")


def test_explanations() -> None:
    lines = explain_puzzle(LNB)
    assert lines[0] == "Rozwiązanie: 1. Wxa6+ bxa6 2. Wa7#"
    assert any("mata w 2" in line for line in lines)
    assert any("poświęcenie" in line for line in lines)
    text = describe_refutation(LNB.start_fen, "g1f1", "d3d1", None)
    assert text.startswith("Po Kf1? przeciwnik gra")


def test_sacrifice_detection() -> None:
    """Genialny ruch (!!) = poprawny ruch, który oddaje figurę."""
    from taktykai.puzzles.validator import is_sacrifice, sacrifice_loss

    # 00LNB: Wxa6+ — wieża za piona (bxa6).
    board = chess.Board(LNB.start_fen)
    assert is_sacrifice(board, chess.Move.from_uci("f6a6")) and sacrifice_loss(board, chess.Move.from_uci("f6a6")) == 4
    # Hd8+ Gxd8 — poświęcenie hetmana.
    board = chess.Board("r1b2k1r/ppp1bppp/8/1B1Q4/5q2/2P5/PPP2PPP/R3R1K1 w - - 1 1")
    assert is_sacrifice(board, chess.Move.from_uci("d5d8"))
    # Mat szewski: hetmana nie da się zbić — to nie poświęcenie.
    board = chess.Board("r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4")
    assert not is_sacrifice(board, chess.Move.from_uci("h5f7"))
    # Zwykły ruch i równa wymiana.
    assert not is_sacrifice(chess.Board(), chess.Move.from_uci("g1f3"))
    board = chess.Board("rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
    assert not is_sacrifice(board, chess.Move.from_uci("e4d5"))
    # Skoczek za piona bronionego skoczkiem (Sxe5 Sxe5) — to już jest poświęcenie figury.
    board = chess.Board("r1bqkb1r/pppp1ppp/2n2n2/4p3/4P3/2N2N2/PPPP1PPP/R1BQKB1R w KQkq - 4 4")
    assert is_sacrifice(board, chess.Move.from_uci("f3e5"))
