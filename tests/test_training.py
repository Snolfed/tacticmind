"""Puzzle modes: theme training, review of failed puzzles and Puzzle Rush (selection, profile and the puzzle screen)."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest

from tacticmind.puzzles.loader import load_puzzles
from tacticmind.puzzles.session import PuzzleOutcome
from tacticmind.rating.profile import REVIEW_LIMIT, PlayerProfile
from tacticmind.rating.selector import RUSH_START, RUSH_STEP, select_next, select_review, select_rush
from tacticmind.web.core import WebApp
from tacticmind.web.screens.play import PlayScreen

from .test_web import StubEngine, run, view

PUZZLES = load_puzzles()
FAIL = PuzzleOutcome(solved=False, mistake=True, hint_used=False, revealed=False, time_s=10.0)
SOLVED = PuzzleOutcome(solved=True, mistake=False, hint_used=False, revealed=False, time_s=10.0)


def test_theme_training_draws_only_that_theme() -> None:
    profile = PlayerProfile()
    rng = random.Random(1)
    for _ in range(20):
        selection = select_next(PUZZLES, profile, rng, theme="fork")
        assert "fork" in selection.puzzle.themes
        assert selection.mode in ("theme", "bonus")  # a streak still brings a bonus puzzle, from the same theme
        assert any(reason.key == "reason.theme" for reason in selection.reasons)
        profile.apply(selection.puzzle, SOLVED, selection.mode)


def test_review_queue() -> None:
    profile = PlayerProfile()
    a, b, c = PUZZLES[:3]
    profile.apply(a, FAIL)
    profile.apply(b, SOLVED)
    profile.apply(c, FAIL)
    assert profile.review == [a.id, c.id]
    selection = select_review(PUZZLES, profile)
    assert selection is not None and selection.puzzle.id == a.id and selection.mode == "review"
    profile.review_result(a.id, False)  # failed again: to the end of the queue
    assert profile.review == [c.id, a.id]
    profile.review_result(c.id, True)
    assert profile.review == [a.id]
    profile.review_result(a.id, True)
    assert select_review(PUZZLES, profile) is None
    # Puzzles that are no longer in the set drop out of the queue.
    profile.review = ["no-such-id", b.id]
    selection = select_review(PUZZLES, profile)
    assert selection is not None and selection.puzzle.id == b.id and profile.review == [b.id]
    for puzzle in PUZZLES[: REVIEW_LIMIT + 5]:
        profile.add_to_review(puzzle.id)
    assert len(profile.review) == REVIEW_LIMIT


def test_review_queue_from_old_profile_history() -> None:
    profile = PlayerProfile()
    a, b = PUZZLES[:2]
    profile.apply(a, FAIL)
    profile.apply(b, FAIL)
    profile.apply(a, SOLVED)  # solved later: no longer waiting
    data = json.loads(json.dumps(profile.to_json()))
    del data["review"], data["rush_best"]
    assert PlayerProfile.from_json(data).review == [b.id]
    profile.record_rush(3, 12)
    loaded = PlayerProfile.from_json(json.loads(json.dumps(profile.to_json())))
    assert loaded.review == [b.id] and loaded.rush_best == {"3": 12}


def test_rush_selection_gets_harder_without_repeats() -> None:
    used: set[str] = set()
    ratings = []
    rng = random.Random(2)
    for index in range(30):
        selection = select_rush(PUZZLES, index, used, rng)
        assert selection.puzzle.id not in used and selection.mode == "rush"
        used.add(selection.puzzle.id)
        ratings.append(selection.puzzle.rating)
        assert abs(selection.puzzle.rating - (RUSH_START + RUSH_STEP * index)) < 150
    assert ratings[-1] > ratings[0] + 1000


def test_rush_best_score() -> None:
    profile = PlayerProfile()
    assert profile.record_rush(5, 7)
    assert not profile.record_rush(5, 6)
    assert profile.record_rush(5, 9) and profile.rush_best["5"] == 9


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("TACTICMIND_HOME", str(tmp_path))
    app = WebApp(engine=StubEngine(), persist=False)  # type: ignore[arg-type]
    app.dispatch({"type": "go", "screen": "play"})
    run(app, 1.0)
    yield app
    app.stop()


def _screen(app: WebApp) -> PlayScreen:
    screen = app.screens["play"]
    assert isinstance(screen, PlayScreen)
    return screen


def _act(app: WebApp, name: str, **data: object) -> None:
    app.dispatch({"type": "screen", "screen": "play", "name": name, "data": data})


def _solve(app: WebApp) -> None:
    session = _screen(app).session
    assert session is not None
    for _ in range(12):
        if session.finished:
            return
        if session.status.value == "player":
            _act(app, "move", uci=session.expected_move.uci())
        run(app, 0.5)


def test_switching_to_a_theme_asks_when_a_rated_puzzle_is_running(app: WebApp) -> None:
    screen = _screen(app)
    first = screen.session
    assert first is not None and first.status.value == "player"
    themes = view(app)["view"]["training"]["themes"]
    assert themes and all(item["name"] for item in themes)
    _act(app, "training", kind="theme", theme="pin")
    assert view(app)["view"]["confirm"] is not None  # the started puzzle would count as a loss
    _act(app, "confirm_yes")
    run(app, 1.0)
    assert app.profile.games == 1 and app.profile.review == [first.puzzle.id]
    v = view(app)["view"]
    assert v["training"]["kind"] == "theme" and "pin" in screen.session.puzzle.themes  # type: ignore[union-attr]
    assert v["training"]["label"].startswith("Theme")


def test_review_mode_is_unrated(app: WebApp) -> None:
    screen = _screen(app)
    assert screen.session is not None
    first = screen.session.puzzle.id  # the started rated puzzle: switching counts it as failed
    failed = PUZZLES[5]
    app.profile.review = [failed.id]
    _act(app, "training", kind="review")
    _act(app, "confirm_yes")
    run(app, 1.0)
    assert app.profile.review == [failed.id, first]
    assert screen.session.puzzle.id == failed.id
    games = app.profile.games
    _solve(app)
    assert app.profile.games == games and app.profile.review == [first]  # unrated, and out of the queue
    _act(app, "next")
    run(app, 1.0)
    assert screen.session.puzzle.id == first
    _solve(app)
    _act(app, "next")
    run(app, 0.2)
    v = view(app)["view"]
    assert v["training"]["kind"] == "rated" and v["notice"]  # nothing left: back to rated puzzles


def test_puzzle_rush_run(app: WebApp) -> None:
    screen = _screen(app)
    _act(app, "training", kind="rush", minutes=3)
    _act(app, "confirm_yes")
    run(app, 1.0)
    v = view(app)["view"]
    assert v["training"]["kind"] == "rush"
    assert not v["buttons"]["hint"]["visible"] and not v["buttons"]["solution"]["visible"]
    rush = v["training"]["rush"]
    assert rush["left"] == 180 and rush["solved"] == 0 and rush["strikes"] == 0
    _solve(app)
    run(app, 1.2)  # the next puzzle comes by itself
    v = view(app)["view"]
    assert v["training"]["rush"]["solved"] == 1 and not v["card"]["finished"]
    # Three mistakes end the run (giving up via the full analysis view counts as a mistake).
    for strike in range(3):
        run(app, 0.6)
        _act(app, "mode", mode="full")
        _act(app, "confirm_yes")
        assert screen.rush is not None and screen.rush.strikes == strike + 1
        run(app, 2.0)
    v = view(app)["view"]
    rush = v["training"]["rush"]
    assert rush["over"] == "strikes" and rush["record"] and rush["best"] == 1
    assert [r["solved"] for r in rush["results"]] == [True, False, False, False]
    assert app.profile.rush_best == {"3": 1} and app.profile.games == 1  # only the rated puzzle left when switching
    _act(app, "rush_again")
    run(app, 1.0)
    assert view(app)["view"]["training"]["rush"]["solved"] == 0
    _act(app, "rush_back")
    run(app, 0.2)
    assert view(app)["view"]["training"]["kind"] == "rated"


def test_puzzle_rush_clock(app: WebApp) -> None:
    screen = _screen(app)
    _act(app, "training", kind="rush", minutes=3)
    _act(app, "confirm_yes")
    run(app, 1.0)
    assert screen.rush is not None and screen.rush.ends_at is not None
    screen.rush.ends_at = screen.clock + 0.1
    run(app, 0.3)
    v = view(app)["view"]
    assert v["training"]["rush"]["over"] == "time" and v["training"]["rush"]["left"] == 0
    assert not v["board"]["interactive"]
