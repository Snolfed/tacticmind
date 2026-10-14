"""Test „dymny” interfejsu: gra uruchomiona bez okna (SDL dummy) rozwiązuje zadanie i popełnia błąd.

Sprawdza, że cały przepływ działa razem: ekran gry, proces silnika, sprawdzanie ruchu
spoza rozwiązania, ranking, zapis profilu, statystyki i strona „Jak działa AI?”.
"""

import os
import time

import pytest

from taktykai.brain.demo import alphabeta_demo, build_demo_tree, minimax_demo


def test_alpha_beta_demo_tree() -> None:
    tree = build_demo_tree()
    full = minimax_demo(tree)
    pruned = alphabeta_demo(tree)
    assert full.value == pruned.value == 7
    assert pruned.pruned and len(pruned.visited) < len(full.visited)
    assert any(step.text().startswith("Cięcie!") for step in pruned.steps)


@pytest.fixture
def app(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    monkeypatch.setenv("TAKTYKAI_HOME", str(tmp_path))
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    from taktykai.ui.app import App

    application = App((1280, 800))
    yield application
    application.shutdown()


def run(app, seconds: float) -> None:  # type: ignore[no-untyped-def]
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.frame(1 / 60)
        time.sleep(0.005)


def test_play_solve_and_mistake(app) -> None:  # type: ignore[no-untyped-def]
    app.go("play")
    run(app, 1.2)
    play = app.screens["play"]
    session = play.session
    assert session.status.value == "player"

    # Rozwiązanie wzorcowe.
    while session.status.value in ("player", "opponent"):
        if session.status.value == "player":
            play.on_player_move(session.expected_move)
        run(app, 0.8)
    assert session.status.value == "solved"
    assert play.change is not None and play.change.delta > 0
    assert app.profile.games == 1 and app.profile.streak == 1
    assert play.state.mode == "full" and play.state.explanation

    # Następne zadanie i błędny ruch: silnik musi wyliczyć odpowiedź przeciwnika.
    play.new_puzzle()
    run(app, 1.2)
    session = play.session
    expected = session.expected_move
    wrong = next(m for m in session.board.legal_moves if m != expected and not session.board.gives_check(m))
    play.on_player_move(wrong)
    deadline = time.monotonic() + 20
    while session.status.value == "checking" and time.monotonic() < deadline:
        run(app, 0.2)
    assert session.status.value in ("mistake", "player")  # błąd albo „dobry ruch, ale jest lepszy”
    if session.status.value == "mistake":
        assert app.profile.games == 2 and app.profile.fail_streak == 1
        assert play.message[0]() == "Niestety, to nie to"
        # Zmiana języka w trakcie zadania: komunikaty i strumień myśli od razu po angielsku.
        app.set_language("en")
        assert play.message[0]() == "Sorry, that's not it"
        assert all("Głębokość" not in thought.text for thought in play.state.thoughts)
        app.set_language("pl")
        play.retry()
        assert session.status.value == "player"

    # Pozostałe ekrany rysują się bez błędów w obu językach.
    for code in ("en", "pl"):
        app.set_language(code)
        for name in ("stats", "howto", "home"):
            app.go(name)
            run(app, 0.2)
    assert app.profile.language == "pl"


def test_app_icon_and_wide_pieces(app) -> None:  # type: ignore[no-untyped-def]
    """Ikona okna (pion) i poszerzone symbole króla i hetmana."""
    import chess

    from taktykai.ui.icon import app_icon
    from taktykai.ui.pieces import piece_surface

    icon = app_icon(64)
    assert icon.get_size() == (64, 64)
    assert icon.get_at((0, 0)).a == 0 and icon.get_at((32, 32)).a == 255  # przezroczyste rogi, pełny środek
    king = piece_surface(chess.Piece(chess.KING, chess.WHITE), 100)
    assert 0.85 < king.get_width() / king.get_height() <= 1.1  # bez poszerzenia ok. 0.75 — wyglądał na ściśniętego
    assert king.get_width() <= 94


def test_layouts_at_many_resolutions(app) -> None:  # type: ignore[no-untyped-def]
    """Wszystkie ekrany rysują się przy małych, typowych i bardzo dużych rozdzielczościach."""
    import pygame

    for size in ((430, 640), (800, 600), (1280, 720), (1920, 1080), (2560, 1440)):
        app.screen = pygame.display.set_mode(size, pygame.RESIZABLE)
        app.relayout()
        for name in ("home", "play", "stats", "howto"):
            app.go(name)
            run(app, 0.15)
        play = app.screens["play"]
        board = play.board_view.rect
        assert board.width >= 160
        if play.wide:
            assert board.bottom <= size[1] and play.brain.rect.right <= size[0]


def test_right_click_arrows_and_marks(app) -> None:  # type: ignore[no-untyped-def]
    import chess
    import pygame

    app.go("play")
    run(app, 0.3)
    view = app.screens["play"].board_view
    e2, e4, g1, f3 = (view.square_rect(sq).center for sq in (chess.E2, chess.E4, chess.G1, chess.F3))

    def right_drag(a: tuple[int, int], b: tuple[int, int]) -> None:
        view.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=a, button=3))
        view.handle(pygame.event.Event(pygame.MOUSEMOTION, pos=b, rel=(0, 0), buttons=(0, 0, 1)))
        view.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=b, button=3))

    right_drag(e2, e4)
    right_drag(g1, f3)  # strzałka skoczka (litera L)
    right_drag(e4, e4)  # zaznaczenie pola
    assert set(view.user_arrows) == {(chess.E2, chess.E4), (chess.G1, chess.F3)}
    assert chess.E4 in view.marks
    assert len(view.arrow_points(chess.G1, chess.F3)) == 3 and len(view.arrow_points(chess.E2, chess.E4)) == 2
    run(app, 0.1)  # rysowanie strzałek nie zgłasza błędów
    right_drag(e2, e4)  # ta sama strzałka drugi raz = usunięcie
    assert (chess.E2, chess.E4) not in view.user_arrows
    view.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=e2, button=1))  # lewy klik czyści rysunki
    assert not view.user_arrows and not view.marks
