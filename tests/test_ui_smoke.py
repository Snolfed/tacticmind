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


def test_brilliant_move_and_buttons(app) -> None:  # type: ignore[no-untyped-def]
    """Poświęcenie w zadaniu pokazuje „!!”, a „Następne zadanie” pojawia się dopiero po rozwiązaniu."""
    from taktykai.puzzles.loader import Puzzle
    from taktykai.puzzles.session import PuzzleSession

    app.go("play")
    run(app, 1.2)
    play = app.screens["play"]
    # Podmieniamy zadanie na 00LNB: 1. Wxa6+! bxa6 2. Wa7# (poświęcenie wieży).
    puzzle = Puzzle("00LNB", "kr6/1pR4p/p4R2/n2r4/P3p3/4B3/6PP/6K1 b - - 0 38", ("d5d3", "f6a6", "b7a6", "c7a7"), 1074, 80, ("mateIn2", "sacrifice"))
    play.session = PuzzleSession(puzzle)
    play.board_view.orientation = play.board_view.player_color = puzzle.player_color
    play._play_intro()
    run(app, 0.4)
    assert play.btn_hint.visible and play.btn_solution.visible
    assert not play.btn_next.visible and not play.btn_retry.visible
    assert play.board_view.last_move is not None  # ruch przeciwnika jest podświetlony
    play.on_player_move(play.session.expected_move)
    assert play.board_view.feedback is not None and play.board_view.feedback[1] == "brilliant"
    assert play.message[0]() == "Genialny ruch!!"
    while play.session.status.value in ("player", "opponent"):
        if play.session.status.value == "player":
            play.on_player_move(play.session.expected_move)
        run(app, 0.8)
    run(app, 0.2)
    assert play.session.finished
    assert play.btn_next.visible and play.btn_next.enabled
    assert not play.btn_hint.visible and not play.btn_solution.visible


def test_move_navigation_during_puzzle(app) -> None:  # type: ignore[no-untyped-def]
    """◀ ▶ w trakcie zadania: cofanie do wcześniejszych pozycji i powrót do bieżącej."""
    import chess

    from taktykai.puzzles.loader import Puzzle
    from taktykai.puzzles.session import PuzzleSession

    app.go("play")
    run(app, 1.2)
    play = app.screens["play"]
    puzzle = Puzzle("00LNB", "kr6/1pR4p/p4R2/n2r4/P3p3/4B3/6PP/6K1 b - - 0 38", ("d5d3", "f6a6", "b7a6", "c7a7"), 1074, 80, ("mateIn2",))
    play.timers.clear()
    play.session = PuzzleSession(puzzle)
    play.board_view.orientation = play.board_view.player_color = puzzle.player_color
    play._play_intro()
    play.on_player_move(chess.Move.from_uci("f6a6"))
    run(app, 1.8)  # odpowiedź przeciwnika bxa6
    live_fen = play.session.board.fen()
    assert play.btn_prev_pos.visible and play.btn_prev_pos.enabled and not play.btn_next_pos.enabled

    play.step_view(-1)  # przed bxa6
    run(app, 0.3)
    assert play.view_index == 2 and not play.board_view.interactive
    assert play.board_view.board.piece_at(chess.A6) == chess.Piece(chess.ROOK, chess.WHITE)
    play.step_view(-1)
    play.step_view(-1)  # pozycja początkowa zadania (przed ruchem przeciwnika)
    run(app, 0.1)
    assert play.view_index == 0 and not play.btn_prev_pos.enabled and play.btn_next_pos.enabled
    play.hint()  # na starszej pozycji podpowiedź jest niedostępna (i nie zabiera nagrody)
    run(app, 0.1)
    assert not play.btn_hint.enabled and play.board_view.hint_square is None and not play.session.hint_used

    for _ in range(3):
        play.step_view(1)
    run(app, 0.3)
    assert play.view_index is None and play.board_view.board.fen() == live_fen
    assert play.board_view.interactive and play.btn_hint.enabled
    play.on_player_move(chess.Move.from_uci("c7a7"))
    run(app, 0.3)
    assert play.session.finished


def test_sounds_are_generated_for_stereo_output(app) -> None:  # type: ignore[no-untyped-def]
    """Dźwięki działają także, gdy system otworzy dźwięk w stereo (wcześniej wtedy się wyłączały)."""
    import pygame

    from taktykai.ui.sounds import build_sounds

    samples = build_sounds(22050)
    assert set(samples) >= {"move", "capture", "check", "castle", "promote", "success", "brilliant", "error"}
    assert all(max(abs(x) for x in data) > 0.05 for data in samples.values())
    assert pygame.mixer.get_init() is not None and pygame.mixer.get_init()[2] == 2
    deadline = time.monotonic() + 15
    while not app.sounds.available and time.monotonic() < deadline:  # synteza w tle
        time.sleep(0.05)
    assert app.sounds.available
    app.sounds.play("move")


def test_drag_deadzone(app) -> None:  # type: ignore[no-untyped-def]
    """Drobne drgnięcie myszy przy kliknięciu nie „łapie” figury; dopiero wyraźny ruch zaczyna przeciąganie."""
    import pygame

    app.go("play")
    run(app, 1.2)
    play = app.screens["play"]
    view = play.board_view
    view.interactive = True
    piece_square = next(sq for sq, p in view.board.piece_map().items() if p.color == view.player_color and view.legal_targets(sq))
    rect = view.square_rect(piece_square)
    near_edge = (rect.x + 3, rect.y + 3)  # klik przy samej krawędzi pola
    view.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=near_edge, button=1))
    view.handle(pygame.event.Event(pygame.MOUSEMOTION, pos=(near_edge[0] + 4, near_edge[1] + 3), rel=(4, 3), buttons=(1, 0, 0)))
    assert not view.drag_moved and view.selected == piece_square
    view.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(near_edge[0] + 4, near_edge[1] + 3), button=1))
    assert view.selected == piece_square  # zwykłe kliknięcie = zaznaczenie (klik-klik)
    far = (near_edge[0] + int(view.drag_deadzone()) + 6, near_edge[1])
    view.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=near_edge, button=1))
    view.handle(pygame.event.Event(pygame.MOUSEMOTION, pos=far, rel=(20, 0), buttons=(1, 0, 0)))
    assert view.drag_moved
    view.handle(pygame.event.Event(pygame.MOUSEMOTION, pos=far, rel=(0, 0), buttons=(0, 0, 0)))  # puszczono poza oknem
    assert view.drag_square is None and view.selected == piece_square  # figura wraca, zostaje zaznaczona


def test_undo_animation_restores_captured_piece(app) -> None:  # type: ignore[no-untyped-def]
    """◀ cofa ruch z animacją: figura wraca na pole startowe, a zbita figura płynnie się pojawia."""
    import chess
    import pygame

    from taktykai.ui.board_view import BoardView

    view = BoardView()
    before = chess.Board("rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
    capture = chess.Move.from_uci("e4d5")
    after = before.copy()
    after.push(capture)
    view.set_position(after, capture, animate=False)
    view.set_position(before, None, undo=capture)
    assert view.anim is not None and view.anim.restore
    assert view.anim.pieces[0][1:] == (chess.D5, chess.E4)  # pion jedzie z d5 z powrotem na e4
    assert view.anim.captured == (chess.Piece(chess.PAWN, chess.BLACK), chess.D5)
    view.update(0.1)
    view.draw(pygame.Surface((600, 600)))  # rysowanie w trakcie animacji cofania nie zgłasza błędów


def test_volume_slider_and_fullscreen(app) -> None:  # type: ignore[no-untyped-def]
    """Suwak głośności zmienia i zapamiętuje głośność; F11 włącza i wyłącza pełny ekran."""
    import pygame

    from taktykai.rating.profile import load_profile

    bar = app.topbar
    slider = bar.volume
    run(app, 0.1)
    x = slider.rect.x + int(slider.rect.width * 0.25)
    for event in (
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(x, slider.rect.centery), button=1),
        pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(x, slider.rect.centery), button=1),
    ):
        bar.handle(event)
    assert abs(app.profile.volume - 0.25) < 0.05
    assert abs(app.sounds.volume - app.profile.volume) < 1e-6
    assert abs(load_profile().volume - app.profile.volume) < 1e-6  # zapisane na dysku
    windowed = app.screen.get_size()
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F11, mod=0, unicode="", scancode=0))
    run(app, 0.1)
    assert app.fullscreen
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F11, mod=0, unicode="", scancode=0))
    run(app, 0.1)
    assert not app.fullscreen and app.screen.get_size() == windowed


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
