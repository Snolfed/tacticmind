"""Saved games with the coach: comments and moves in JSON, the evaluation graph, PGN, the game list and the review."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import chess
import pytest

from tacticmind.coach.advice import Features, Line, Material, PieceName, San, Score, phrase, render_comment
from tacticmind.coach.archive import decode_comment, decode_plies, encode_comment, encode_plies, eval_curve, game_pgn, read_pgn
from tacticmind.coach.game import CoachGame, MoveRecord
from tacticmind.engine.types import MATE
from tacticmind.i18n import set_language
from tacticmind.rating.coach_profile import ARCHIVE_LIMIT, CoachProfile
from tacticmind.web.core import WebApp
from tacticmind.web.screens.coach_game import CoachGameScreen

from .test_web import StubEngine, view


@pytest.fixture(autouse=True)
def english() -> Any:
    set_language("en")
    yield
    set_language("en")


def _scholars_mate() -> CoachGame:
    """The player (White) mates in 4; moves have classes, evaluations and comments like in a real game."""
    game = CoachGame(chess.WHITE, 800)
    fen = chess.STARTING_FEN
    ucis = ["e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6", "h5f7"]
    classes = ["book", "book", "best", "good", "inaccuracy", "blunder", "best"]
    scores = [None, None, 40, 45, 10, 900, MATE]
    for i, uci in enumerate(ucis):
        record = game.push(chess.Move.from_uci(uci), i % 2 == 0, classification=classes[i], accuracy=100.0 - i, score=scores[i])
        if record.by_player:
            record.comment = (phrase("coach.lesson_hint", move=San(fen, uci)),)
        fen = game.board.fen()
    game.records[4].best_uci = "b1c3"
    return game


def test_comment_survives_json() -> None:
    fen = chess.STARTING_FEN
    comment = (
        phrase("coach.lesson_hint", move=San(fen, "e2e4")),
        phrase("coach.lesson_hint", move=Line(fen, ("e2e4", "e7e5"))),
        phrase("coach.lesson_hint", move=Features((phrase("coach.lesson_hint", move=PieceName(chess.KNIGHT)),))),
        phrase("coach.lesson_hint", move=Material(3)),
        phrase("coach.lesson_hint", move=Score(-150)),
    )
    stored = json.loads(json.dumps(encode_comment(comment)))
    assert decode_comment(stored) == comment
    set_language("pl")
    assert render_comment(decode_comment(stored)) == render_comment(comment)  # still follows the language
    assert decode_comment("garbage") == ()


def test_plies_round_trip_and_damaged_moves() -> None:
    game = _scholars_mate()
    plies = json.loads(json.dumps(encode_plies(game.records)))
    records = decode_plies(chess.STARTING_FEN, plies)
    assert records is not None
    assert [r.uci for r in records] == [r.uci for r in game.records]
    assert [r.classification for r in records] == [r.classification for r in game.records]
    assert [r.score for r in records] == [r.score for r in game.records]
    assert records[4].best_uci == "b1c3" and records[0].fen_before == chess.STARTING_FEN
    assert render_comment(records[0].comment) == render_comment(game.records[0].comment)
    plies[2]["uci"] = "e1e8"  # illegal
    assert decode_plies(chess.STARTING_FEN, plies) is None
    assert decode_plies(chess.STARTING_FEN, None) is None


def test_eval_curve_keeps_the_last_value_for_book_moves() -> None:
    curve = eval_curve(_scholars_mate().records)
    assert len(curve) == 8
    assert curve[:3] == [50.0, 50.0, 50.0]
    assert 50 < curve[3] < 60
    assert curve[-1] == 100.0


def test_pgn_export() -> None:
    game = _scholars_mate()
    game.result, game.reason = "win", "checkmate"
    text = game_pgn(game, 0.0)
    parsed = read_pgn(text)
    assert parsed is not None
    assert parsed.headers["Result"] == "1-0"
    assert parsed.headers["White"] == "You" and parsed.headers["Black"].endswith("(800)")
    moves = list(parsed.mainline())
    assert [node.move.uci() for node in moves] == [r.uci for r in game.records]
    assert chess.pgn.NAG_BLUNDER in moves[5].nags and chess.pgn.NAG_DUBIOUS_MOVE in moves[4].nags
    assert moves[5].eval() is not None and moves[5].eval().white().score() == 900
    assert "Qxf7#" in text and "1-0" in text


def test_profile_keeps_moves_of_the_newest_games() -> None:
    profile = CoachProfile()
    plies = encode_plies(_scholars_mate().records)
    for _ in range(ARCHIVE_LIMIT + 2):
        profile.record(800, False, "white", "win", 1.0, 90.0, 70.0, 4, None, 0, plies=plies, reason="checkmate")
    assert not profile.reviewable(0) and not profile.reviewable(1)
    assert profile.reviewable(2) and profile.reviewable(ARCHIVE_LIMIT + 1)
    loaded = CoachProfile.from_json(json.loads(json.dumps(profile.to_json())))
    assert loaded.games[-1].plies == plies and loaded.games[-1].reason == "checkmate"
    # A profile from before the review: games without moves still load.
    old = profile.to_json()
    for g in old["games"]:  # type: ignore[union-attr]
        del g["plies"], g["start_fen"], g["reason"]
    loaded = CoachProfile.from_json(old)
    assert len(loaded.games) == ARCHIVE_LIMIT + 2 and not loaded.reviewable(ARCHIVE_LIMIT + 1)


def test_review_of_a_saved_game(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TACTICMIND_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "Downloads").mkdir()
    app = WebApp(engine=StubEngine(), persist=False)  # type: ignore[arg-type]
    try:
        screen = app.screens["coach_game"]
        assert isinstance(screen, CoachGameScreen)
        # A finished game, recorded like at the end of a real game.
        screen.start(chess.WHITE, 800, False, None)
        played = _scholars_mate()
        screen.game.records = played.records  # type: ignore[union-attr]
        screen.game.board = played.board  # type: ignore[union-attr]
        screen.game.result, screen.game.reason = "win", "checkmate"  # type: ignore[union-attr]
        screen.finish()
        assert app.profile.coach.reviewable(0)

        app.dispatch({"type": "go", "screen": "coach"})
        games = view(app)["view"]["games"]
        assert games[0]["index"] == 0 and games[0]["reviewable"] and games[0]["result"] == "win"

        screen.start(chess.BLACK, 1200, False, None)  # a new game, not started yet (does not need confirmation)
        app.dispatch({"type": "screen", "screen": "coach", "name": "review_game", "data": {"index": 0}})
        state = view(app)
        assert state["screen"] == "coach_game"
        v = state["view"]
        assert v["summary"] is None and v["moves"]["current"] == -1  # the review starts at the initial position
        assert len(v["moves"]["list"]) == 7 and v["moves"]["list"][5]["cls"] == "blunder"
        assert v["review"]["archived"] and len(v["review"]["evals"]) == 8 and v["review"]["current"] == 0
        assert "Qxf7#" in v["review"]["pgn"]
        assert v["board"]["orientation"] == "white"
        app.dispatch({"type": "screen", "screen": "coach_game", "name": "jump", "data": {"index": 5}})
        app.tick()
        v = view(app)["view"]
        assert v["review"]["current"] == 5 and v["card"]["comment"]["cls"] == "inaccuracy"
        assert len(v["board"]["arrows"]) == 1  # the better move

        app.dispatch({"type": "screen", "screen": "coach_game", "name": "pgn_save"})
        files = list((tmp_path / "Downloads").glob("tacticmind-*.pgn"))
        assert len(files) == 1 and "Qxf7#" in files[0].read_text(encoding="utf-8")
        assert view(app)["view"]["notice"].startswith("Saved")

        app.dispatch({"type": "screen", "screen": "coach_game", "name": "summary"})
        summary = view(app)["view"]["summary"]
        assert summary["title"] and summary["lines"][0]["text"].startswith("Played")
        assert len(app.profile.coach.games) == 1  # opening the review does not record the game again
    finally:
        app.stop()


def test_old_game_cannot_be_opened() -> None:
    app = WebApp(engine=StubEngine(), persist=False)  # type: ignore[arg-type]
    try:
        app.profile.coach.record(800, False, "white", "win", 1.0, None, None, 10, None, 0)
        app.dispatch({"type": "go", "screen": "coach"})
        assert view(app)["view"]["games"][0]["reviewable"] is False
        app.dispatch({"type": "screen", "screen": "coach", "name": "review_game", "data": {"index": 0}})
        assert view(app)["screen"] == "coach"
    finally:
        app.stop()


def test_move_record_score_defaults_to_none() -> None:
    assert MoveRecord(chess.STARTING_FEN, "e2e4", True).score is None
