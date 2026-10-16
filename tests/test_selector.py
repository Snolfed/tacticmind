"""Puzzle selector: flow zone, frustration guard, bonus, weak themes, no repeats."""

import random

from tacticmind.i18n import set_language
from tacticmind.puzzles.loader import Puzzle
from tacticmind.rating.profile import PlayerProfile, PuzzleRecord
from tacticmind.rating.selector import FLOW_OFFSET, FLOW_SPREAD, select_next

THEMES = ["fork", "pin", "skewer", "mateIn2", "deflection", "attraction", "sacrifice", "discoveredAttack"]


def synthetic_puzzles() -> list[Puzzle]:
    """Puzzles every 5 rating points from 600–2800, with rotating themes."""
    return [
        Puzzle(f"p{r}", "6k1/5ppp/8/8/8/8/5PPP/3R2K1 b - - 0 1", ("g8h8", "d1d8"), r, 75, (THEMES[(r // 5) % len(THEMES)], "short"))
        for r in range(600, 2800, 5)
    ]


def profile_with(rating: float, **kwargs: int) -> PlayerProfile:
    profile = PlayerProfile(system="elo", elo_rating=rating, games=30)
    for key, value in kwargs.items():
        setattr(profile, key, value)
    return profile


def test_selector_hits_flow_window() -> None:
    set_language("pl")
    puzzles = synthetic_puzzles()
    rng = random.Random(1)
    for rating in (800, 1200, 1500, 2100):
        profile = profile_with(rating)
        for _ in range(100):
            selection = select_next(puzzles, profile, rng)
            low = rating + FLOW_OFFSET - FLOW_SPREAD - 25
            high = rating + FLOW_OFFSET + FLOW_SPREAD + 25
            assert low <= selection.puzzle.rating <= high, (rating, selection.puzzle.rating)
            assert selection.mode == "flow"
            assert 0.45 < selection.expected < 0.85
            assert selection.reasons and "celuję" in selection.reason_texts()[0]


def test_easier_after_three_failures() -> None:
    selection = select_next(synthetic_puzzles(), profile_with(1500, fail_streak=3), random.Random(2))
    assert selection.mode == "easier"
    assert selection.puzzle.rating <= 1500 - 250
    assert selection.expected > 0.8


def test_bonus_after_five_successes() -> None:
    selection = select_next(synthetic_puzzles(), profile_with(1500, streak=5), random.Random(3))
    assert selection.mode == "bonus"
    assert 1650 <= selection.puzzle.rating <= 1750


def test_no_repeats() -> None:
    puzzles = synthetic_puzzles()
    profile = profile_with(1500)
    rng = random.Random(4)
    chosen = set()
    for _ in range(40):
        selection = select_next(puzzles, profile, rng)
        assert selection.puzzle.id not in chosen
        chosen.add(selection.puzzle.id)
        profile.seen.append(selection.puzzle.id)


def test_weak_theme_gets_priority() -> None:
    set_language("pl")
    profile = profile_with(1500)
    for success in (False, False, False, True):
        profile.model.record(["pin"], success, float(success))
    for _ in range(6):
        profile.model.record(["fork"], True, 1.0)
    rng = random.Random(5)
    picks = [select_next(synthetic_puzzles(), profile, rng) for _ in range(300)]
    weakness = [s for s in picks if s.mode == "weakness"]
    assert 0.2 < len(weakness) / len(picks) < 0.4  # ~30% of puzzles
    assert all("pin" in s.puzzle.themes for s in weakness)
    assert any("słaba strona" in reason for reason in weakness[0].reason_texts())


def test_theme_variety() -> None:
    profile = profile_with(1500)
    profile.history = [
        PuzzleRecord(f"h{i}", 1400, ["fork"], 1.0, True, False, 10.0, 1500, 1500, None, "flow", 0.0) for i in range(3)
    ]
    rng = random.Random(6)
    picks = [select_next(synthetic_puzzles(), profile, rng) for _ in range(50)]
    assert sum("fork" in s.puzzle.themes for s in picks) < 10
