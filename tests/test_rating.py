"""Elo, Glicko-2, wynik zadania, model gracza i profil."""

import math

import pytest

from taktykai.puzzles.loader import Puzzle
from taktykai.puzzles.session import PuzzleOutcome
from taktykai.rating import elo, glicko2
from taktykai.rating.player_model import PlayerModel
from taktykai.rating.profile import PlayerProfile, load_profile, puzzle_score, save_profile


def test_expected_score_examples() -> None:
    assert elo.expected_score(1500, 1500) == pytest.approx(0.5)
    # Różnica 400 punktów = szanse 10:1.
    assert elo.expected_score(1600, 1200) == pytest.approx(10 / 11)
    assert elo.expected_score(1200, 1600) == pytest.approx(1 / 11)
    # Zadanie o 100 łatwiejsze niż gracz ≈ 64% szans (stąd cel R − 100 dla „strefy flow”).
    assert elo.expected_score(1500, 1400) == pytest.approx(0.6401, abs=1e-4)


def test_rating_delta_examples() -> None:
    # ΔR = K · (S − E)
    assert elo.rating_delta(1500, 1500, 1.0, 32) == pytest.approx(16.0)
    assert elo.rating_delta(1500, 1500, 0.0, 32) == pytest.approx(-16.0)
    assert elo.rating_delta(1500, 1500, 0.5, 32) == pytest.approx(0.0)
    assert elo.rating_delta(1200, 1600, 1.0, 20) == pytest.approx(20 * (1 - 1 / 11))


def test_k_factor_schedule() -> None:
    assert [elo.k_factor(n) for n in (0, 9, 10, 49, 50, 200)] == [60, 60, 32, 32, 20, 20]


def test_update_elo_uses_calibration_k() -> None:
    new, delta = elo.update_elo(1200, 1200, 1.0, games_played=0)
    assert delta == pytest.approx(30.0)  # K=60, E=0.5
    assert new == pytest.approx(1230.0)


def test_target_rating_inverts_expected_score() -> None:
    target = elo.target_rating_for(1500, 0.65)
    assert elo.expected_score(1500, target) == pytest.approx(0.65)
    assert target == pytest.approx(1392.4, abs=0.5)


def test_glicko2_paper_example() -> None:
    """Przykład z artykułu Glickmana: 1500/200/0.06 kontra trzech przeciwników."""
    player = glicko2.Glicko2Rating(1500, 200, 0.06)
    result = glicko2.update(player, [(1400, 30, 1.0), (1550, 100, 0.0), (1700, 300, 0.0)])
    assert result.rating == pytest.approx(1464.06, abs=0.01)
    assert result.rd == pytest.approx(151.52, abs=0.01)
    assert result.volatility == pytest.approx(0.05999, abs=1e-5)


def test_glicko2_uncertainty_shrinks() -> None:
    player = glicko2.Glicko2Rating()
    for _ in range(10):
        player = glicko2.update(player, [(1200, 80, 0.5)])
    assert player.rd < 200
    assert player.rating == pytest.approx(1200, abs=1)


def outcome(solved: bool = True, mistake: bool = False, hint: bool = False, revealed: bool = False, t: float = 20.0) -> PuzzleOutcome:
    return PuzzleOutcome(solved=solved, mistake=mistake, hint_used=hint, revealed=revealed, time_s=t)


def test_puzzle_score_rules() -> None:
    assert puzzle_score(outcome(), None) == 1.0
    assert puzzle_score(outcome(hint=True), None) == 0.5
    assert puzzle_score(outcome(solved=False, mistake=True), None) == 0.0
    assert puzzle_score(outcome(solved=False, revealed=True), None) == 0.0
    # Kara za czas: powyżej 3× średniej, maksymalnie −0.2.
    assert puzzle_score(outcome(t=29), 10.0) == 1.0
    assert puzzle_score(outcome(t=45), 10.0) == pytest.approx(0.9)
    assert puzzle_score(outcome(t=1000), 10.0) == pytest.approx(0.8)
    assert puzzle_score(outcome(hint=True, t=1000), 10.0) == pytest.approx(0.3)


def make_puzzle(pid: str, rating: int, themes: tuple[str, ...] = ("fork",)) -> Puzzle:
    return Puzzle(pid, "6k1/5ppp/8/8/8/8/5PPP/3R2K1 b - - 0 1", ("g8h8", "d1d8"), rating, 75, themes)


def test_profile_apply_streaks_and_model() -> None:
    profile = PlayerProfile(system="elo")
    change = profile.apply(make_puzzle("a", 1200), outcome())
    assert change.delta == pytest.approx(30.0)
    assert profile.streak == 1 and profile.games == 1
    profile.apply(make_puzzle("b", 1200, ("pin",)), outcome(solved=False, mistake=True))
    assert profile.streak == 0 and profile.fail_streak == 1 and profile.best_streak == 1
    assert profile.model.rate("pin") == 0.0
    assert profile.model.rate("fork") == 1.0
    assert profile.seen == ["a", "b"]


def test_profile_glicko_shows_uncertainty() -> None:
    profile = PlayerProfile(system="glicko")
    assert profile.rd == 350
    profile.apply(make_puzzle("a", 1300), outcome())
    assert profile.rating > 1200
    assert profile.rd is not None and profile.rd < 350


def test_profile_roundtrip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    profile = PlayerProfile()
    profile.apply(make_puzzle("a", 1250, ("fork", "short")), outcome())
    path = tmp_path / "profile.json"
    save_profile(profile, path)
    loaded = load_profile(path)
    assert loaded.to_json() == profile.to_json()
    assert load_profile(tmp_path / "missing.json").games == 0


def test_player_model_weakest() -> None:
    model = PlayerModel()
    for _ in range(4):
        model.record(["fork", "short"], True, 1.0)
    for success in (False, False, True):
        model.record(["pin"], success, 1.0 if success else 0.0)
    model.record(["skewer"], False, 0.0)  # za mało prób, żeby uznać za słabą stronę
    weakest = model.weakest()
    assert weakest[0][0] == "pin"
    assert math.isclose(weakest[0][1], 1 / 3)
    assert all(theme != "short" for theme, _ in weakest)  # motywy „meta” nie są śledzone
    assert "skewer" not in [t for t, _ in weakest]
