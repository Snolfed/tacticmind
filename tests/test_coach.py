"""Gra z trenerem: książka otwarć, siła gry wg Elo, ocena ruchów, wyjaśnienia, przebieg partii i „Twój poziom”."""

import random
import re

import chess
import pytest

from tacticmind.coach import advice, openings, review, strength
from tacticmind.coach.game import CoachGame
from tacticmind.engine.types import MATE
from tacticmind.i18n import en, pl, set_language
from tacticmind.rating.coach_profile import CALIBRATION_GAMES, UPDATE_EVERY, CoachProfile, level_from_rating
from tacticmind.rating.profile import PlayerProfile


def _moves(sans: str) -> list[chess.Move]:
    board = chess.Board()
    moves = []
    for san in sans.split():
        move = board.parse_san(san)
        moves.append(move)
        board.push(move)
    return moves


# ---------------------------------------------------------------- książka otwarć
@pytest.mark.parametrize("opening", openings.OPENINGS, ids=lambda o: o.id)
def test_every_lesson_line_is_legal_and_explained(opening: openings.Opening) -> None:
    ucis = openings.line_ucis(opening.id)
    board = chess.Board()
    for uci in ucis:
        move = chess.Move.from_uci(uci)
        assert move in board.legal_moves
        board.push(move)
    assert 1 <= opening.name_from <= len(ucis)
    for strings in (pl.STRINGS, en.STRINGS):
        for key in ("name", "desc", *(str(ply) for ply in range(1, len(ucis) + 1))):
            assert f"opening.{opening.id}.{key}" in strings
    # Po całej linii partia nosi nazwę tego otwarcia (gambit hetmański z ...e6 to dokładniej „odrzucony”).
    assert openings.opening_at(board.move_stack) == {"queens_gambit": "qgd"}.get(opening.id, opening.id)


def test_opening_names_and_transpositions() -> None:
    assert openings.opening_at(_moves("e4 c5")) == "sicilian"
    assert openings.opening_at(_moves("e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6")) == "sicilian_najdorf"
    assert openings.opening_at(_moves("e4 e5 Nf3 Nc6 Bc4 Nf6")) == "two_knights"
    # Gambit hetmański odrzucony nie wraca do ogólnej nazwy w dalszych ruchach linii.
    assert openings.opening_at(_moves("d4 d5 c4 e6 Nc3 Nf6 Bg5")) == "qgd"
    # Transpozycja: 1. Sf3 Sc6 2. e4 e5 to ta sama pozycja co 1. e4 e5 2. Sf3 Sc6 — partia otwarta, nie Réti.
    assert openings.opening_at(_moves("Nf3 Nc6 e4 e5 Bb5")) == "ruy_lopez"
    assert openings.opening_at(_moves("a3")) is None


def test_book_moves() -> None:
    assert set(openings.book_moves(chess.Board())) == {"e2e4", "d2d4", "c2c4"}
    board = chess.Board()
    for move in _moves("e4 e5 Nf3 Nc6"):
        board.push(move)
    assert {"f1c4", "f1b5", "d2d4"} <= set(openings.book_moves(board))
    assert openings.is_book_move(board, chess.Move.from_uci("f1b5"))
    assert not openings.is_book_move(board, chess.Move.from_uci("h2h4"))
    opening_id, ply = openings.move_comment(board, chess.Move.from_uci("f1b5")) or ("", 0)
    assert (opening_id, ply) == ("ruy_lopez", 5)


# ---------------------------------------------------------------- siła gry
def test_strength_grows_with_elo() -> None:
    levels = [strength.strength_for(elo) for elo in range(strength.ELO_MIN, strength.ELO_MAX + 1, 100)]
    for weaker, stronger in zip(levels, levels[1:]):
        assert stronger.depth >= weaker.depth
        assert stronger.time_ms >= weaker.time_ms
        assert stronger.temperature <= weaker.temperature
        assert stronger.blunder <= weaker.blunder
    assert levels[-1].blunder == 0
    assert strength.strength_for(50).elo == strength.ELO_MIN
    assert strength.strength_for(5000).elo == strength.ELO_MAX


def test_strong_trainer_plays_best_weak_trainer_varies() -> None:
    lines = [("e2e4", 40), ("d2d4", 35), ("a2a3", -60), ("g2g4", -150)]
    legal = [m for m, _ in lines] + ["h2h3", "b1a3"]
    rng = random.Random(7)
    strong = strength.strength_for(2000)
    picks = [strength.choose_move(lines, legal, strong, rng) for _ in range(200)]
    assert all(p in ("e2e4", "d2d4") for p in picks)
    weak = strength.strength_for(400)
    picks = [strength.choose_move(lines, legal, weak, rng) for _ in range(400)]
    assert len(set(picks)) >= 5  # losuje spośród wielu ruchów, także słabych
    # Ruch prowadzący do mata nigdy nie przegrywa z gorszym ruchem u silnego trenera.
    mate_lines = [("d1h5", MATE - 1), ("e2e4", 30)]
    assert all(strength.choose_move(mate_lines, legal, strong, rng) == "d1h5" for _ in range(50))


# ---------------------------------------------------------------- ocena ruchów
def test_win_percent_and_accuracy() -> None:
    assert review.win_percent(0) == pytest.approx(50)
    assert review.win_percent(300) == pytest.approx(75.1, abs=0.5)
    assert review.win_percent(MATE - 3) == 100
    assert review.win_percent(-(MATE - 3)) == 0
    assert review.move_accuracy(0) == pytest.approx(100, abs=0.01)
    assert review.move_accuracy(30) < 30
    assert review.win_drop(100, 300) == 0


@pytest.mark.parametrize(
    ("drop", "expected"),
    [(0.0, "excellent"), (1.9, "excellent"), (4.0, "good"), (8.0, "inaccuracy"), (15.0, "mistake"), (35.0, "blunder")],
)
def test_classification_thresholds(drop: float, expected: str) -> None:
    assert review.classify(drop, is_best=False) == expected


def test_special_classes() -> None:
    assert review.classify(0, is_best=True) == "best"
    assert review.classify(0, is_best=True, second_drop=20) == "great"
    assert review.classify(0, is_best=True, second_drop=20, recapture=True) == "best"
    assert review.classify(0, is_best=True, sacrifice=True, win_before=70) == "brilliant"
    assert review.classify(0, is_best=True, sacrifice=True, win_before=99) == "best"  # już i tak wygrane
    # Poświęcenie prowadzące do mata jest genialne, jeśli bez niego pozycja nie była wygrana…
    assert review.classify(0, is_best=True, sacrifice=True, win_before=100, second_drop=40) == "brilliant"
    # …ale nie, gdy inne ruchy też wygrywają.
    assert review.classify(0, is_best=True, sacrifice=True, win_before=100, second_drop=1) == "best"
    assert review.classify(0, is_best=True, sacrifice=True, win_before=55, second_drop=30) == "brilliant"
    assert review.classify(30, is_best=False, book=True) == "book"


# ---------------------------------------------------------------- wyjaśnienia
@pytest.fixture(autouse=True)
def _polish() -> object:
    set_language("pl")
    yield None
    set_language("pl")


def test_features_of_moves() -> None:
    board = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3")
    text = advice.render(advice.move_features(board, chess.Move.from_uci("f1c4"), "you"))
    assert text == "rozwijasz gońca"
    castle = chess.Board("4k3/8/8/8/8/8/8/R3K2R w KQ - 0 1")
    assert advice.render(advice.move_features(castle, chess.Move.from_uci("e1g1"), "me")) == "robię roszadę, chowając króla"
    knight = chess.Board("4k3/8/8/3q1r2/8/8/8/4KN2 w - - 0 1")
    text = advice.render(advice.move_features(knight, chess.Move.from_uci("f1e3"), "me"))
    assert "widełki" in text and "hetmana" in text and "wieżę" in text
    set_language("en")
    assert "fork" in advice.render(advice.move_features(knight, chess.Move.from_uci("f1e3"), "me"))


def test_comment_for_blunder_names_the_better_move_and_the_loss() -> None:
    # Po 3. Sg5? białe tracą skoczka po Hxg5; lepszy był rozwój (Sc3).
    board = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3")
    comment = advice.player_comment(
        board, chess.Move.from_uci("f3g5"), "blunder", "b1c3", ["b1c3", "g8f6"], 20, -320, ["d8g5", "d2d4", "g5h4"]
    )
    text = advice.render_comment(comment)
    assert "Hxg5" in text and "tracisz figurę" in text
    assert "Lepsze było Sc3" in text and "rozwija skoczka" in text
    assert "spada z +0,2 na -3,2" in text
    set_language("en")
    text = advice.render_comment(comment)
    assert "Qxg5" in text and "you lose a piece" in text and "Better was Nc3" in text


def test_comment_for_missed_and_allowed_mate() -> None:
    board = chess.Board("r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4")
    comment = advice.player_comment(board, chess.Move.from_uci("d2d3"), "blunder", "h5f7", ["h5f7"], MATE - 1, -900, ["f6h5"])
    assert "Był mat w jednym ruchu: Hxf7#!" in advice.render_comment(comment)
    # Mat szewski: po 3... Sf6?? białe grają Hxf7#.
    allowed = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3")
    comment = advice.player_comment(allowed, chess.Move.from_uci("g8f6"), "blunder", "g7g6", ["g7g6"], 20, -(MATE - 1), ["h5f7"])
    assert "przeciwnik daje mata: 1. Hxf7#" in advice.render_comment(comment)


def test_trainer_warns_about_threats() -> None:
    board = chess.Board("rnbqkbnr/pppp1ppp/8/4p3/2B1P3/8/PPPP1PPP/RNBQK1NR w KQkq - 0 2")
    text = advice.render_comment(advice.trainer_comment(board, chess.Move.from_uci("d1h5")))
    assert text.startswith("Gram Hh5") and "grożę matem" in text


def test_book_comment_uses_lesson_text() -> None:
    board = chess.Board()
    comment = advice.book_comment(board, chess.Move.from_uci("e2e4"), "kings_pawn", "opening.italian.1", trainer=False)
    text = advice.render_comment(comment)
    assert text.startswith("Ruch z teorii — Debiut piona królewskiego.") and "centrum" in text


def test_every_comment_key_exists_in_both_languages() -> None:
    for strings in (pl.STRINGS, en.STRINGS):
        for kind in ("mate", "castle", "promote", "capture", "check", "fork", "attack", "escape", "defend", "develop", "center", "open_file", "improve", "pawn"):
            for person in ("you", "me", "it"):
                assert f"feat.{kind}.{person}" in strings
        for cls in review.CLASSES:
            assert f"cls.{cls}" in strings
    # Polskie i angielskie szablony mają te same pola {…} (sprawdza też test_i18n — tu dla pewności dla nowych kluczy).
    for key, text in pl.STRINGS.items():
        if key.startswith(("feat.", "coach.")):
            english = en.STRINGS.get(key) or en.STRINGS[re.sub(r"\.(one|few)$", ".many", key)]
            assert set(re.findall(r"{(\w+)}", text)) == set(re.findall(r"{(\w+)}", english)), key


# ---------------------------------------------------------------- przebieg partii
def test_lesson_flow_and_take_back() -> None:
    game = CoachGame(chess.WHITE, 1200, lesson=openings.opening_by_id("italian"))
    assert game.lesson_expected() == chess.Move.from_uci("e2e4")
    game.push(chess.Move.from_uci("e2e4"), True)
    assert game.lesson_expected() == chess.Move.from_uci("e7e5")
    game.push(chess.Move.from_uci("e7e5"), False)
    assert game.lesson_progress() == (2, 12)
    assert not game.counts_for_rating()
    for uci in openings.line_ucis("italian")[2:]:
        game.push(chess.Move.from_uci(uci), game.player_to_move)
    assert game.lesson_complete() and game.lesson_expected() is None
    game.continue_after_lesson()
    assert game.playing and not game.lesson_active
    undone = game.take_back()
    assert len(undone) == 2 and game.takebacks == 1 and game.player_to_move


def test_game_result_and_score() -> None:
    game = CoachGame(chess.WHITE, 800, start_fen="7k/8/6KQ/8/8/8/8/8 w - - 0 1")
    game.push(chess.Move.from_uci("h6g7"), True, classification="best", accuracy=100.0)
    assert game.result == "win" and game.reason == "checkmate"
    assert game.score() == 1.0
    game.hints = 2
    assert game.score() == pytest.approx(0.8)
    assert game.counts()["best"] == 1 and game.accuracy() == 100.0
    draw = CoachGame(chess.BLACK, 800, start_fen="7k/5Q2/6K1/8/8/8/8/8 w - - 0 1")
    draw.push(chess.Move.from_uci("g6h6"), False)
    assert draw.result == "draw" and draw.reason == "stalemate"
    resign = CoachGame(chess.WHITE, 800)
    resign.resign()
    assert resign.result == "loss" and resign.score() == 0


# ---------------------------------------------------------------- „Twój poziom”
def test_calibration_and_level_updates_every_five_games() -> None:
    coach = CoachProfile()
    levels = []
    for i in range(1, 21):
        change = coach.record(1000, False, "white", "win", 1.0, 80.0, 60.0, 30, None, 0)
        levels.append(coach.level)
        if i < CALIBRATION_GAMES:
            assert coach.level is None and not coach.calibrated
            assert coach.games_to_update() == CALIBRATION_GAMES - i
        if i == CALIBRATION_GAMES:
            assert change.calibrated_now and coach.level is not None
    # Poziom zmienia się tylko po 10., 15. i 20. partii.
    changes = [i + 1 for i in range(1, 20) if levels[i] != levels[i - 1]]
    assert set(changes) <= {CALIBRATION_GAMES, CALIBRATION_GAMES + UPDATE_EVERY, CALIBRATION_GAMES + 2 * UPDATE_EVERY}
    assert levels[-1] is not None and levels[-1] > 1000  # same wygrane z trenerem 1000 → wyżej niż 1000
    assert coach.games_to_update() == UPDATE_EVERY


def test_losing_lowers_the_level() -> None:
    coach = CoachProfile()
    for _ in range(CALIBRATION_GAMES):
        coach.record(1200, False, "white", "loss", 0.0, 40.0, 80.0, 30, None, 0)
    assert coach.level is not None and coach.level < 1200
    assert level_from_rating(5000) == strength.ELO_MAX and level_from_rating(-50) == strength.ELO_MIN
    assert level_from_rating(1012) == 1000 and level_from_rating(1013) == 1025


def test_opening_stars_and_profile_round_trip() -> None:
    profile = PlayerProfile()
    coach = profile.coach
    coach.record_lesson("italian", 2)
    assert coach.stars("italian") == 1
    coach.record_lesson("italian", 0)
    assert coach.stars("italian") == 2
    coach.record(900, False, "black", "draw", 0.5, 70.0, 75.0, 40, "italian", 1)
    coach.elo = 1300
    loaded = PlayerProfile.from_json(profile.to_json())
    assert loaded.coach.stars("italian") == 2
    assert len(loaded.coach.games) == 1 and loaded.coach.games[0].opening == "italian"
    assert loaded.coach.elo == 1300
    assert loaded.coach.rating == coach.rating
    # Stary profil bez danych trenera też się wczytuje.
    assert PlayerProfile.from_json({}).coach.games == []
