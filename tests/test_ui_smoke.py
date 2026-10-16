"""UI smoke test: the game, run without a window (SDL dummy), solves a puzzle and makes a mistake.

Checks that the whole flow works together: the puzzle screen, the engine process, checking a move
outside the solution, rating, saving the profile, statistics and the "How does the AI work?" page.
"""

import os
import time

import pytest

from tacticmind.brain.demo import alphabeta_demo, build_demo_tree, minimax_demo
from tacticmind.i18n import set_language


def test_alpha_beta_demo_tree() -> None:
    set_language("pl")
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
    monkeypatch.setenv("TACTICMIND_HOME", str(tmp_path))
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    from tacticmind.ui.app import App

    application = App((1280, 800))
    yield application
    application.shutdown()


def run(app, seconds: float) -> None:  # type: ignore[no-untyped-def]
    # Game time flows as in the real loop (actual time between frames), not a fixed 1/60 s
    # per frame — otherwise the puzzle intro might not finish on a slower machine.
    last = time.monotonic()
    end = last + seconds
    while last < end:
        time.sleep(0.005)
        current = time.monotonic()
        app.frame(min(current - last, 0.1))
        last = current


def test_play_solve_and_mistake(app) -> None:  # type: ignore[no-untyped-def]
    app.set_language("pl")
    app.go("play")
    run(app, 1.2)
    play = app.screens["play"]
    session = play.session
    assert session.status.value == "player"

    # The reference solution.
    while session.status.value in ("player", "opponent"):
        if session.status.value == "player":
            play.on_player_move(session.expected_move)
        run(app, 0.8)
    assert session.status.value == "solved"
    assert play.change is not None and play.change.delta > 0
    assert app.profile.games == 1 and app.profile.streak == 1
    assert play.state.mode == "full" and play.state.explanation

    # Next puzzle and a wrong move: the engine has to compute the opponent's reply.
    play.new_puzzle()
    run(app, 1.2)
    session = play.session
    expected = session.expected_move
    wrong = next(m for m in session.board.legal_moves if m != expected and not session.board.gives_check(m))
    play.on_player_move(wrong)
    deadline = time.monotonic() + 20
    while session.status.value == "checking" and time.monotonic() < deadline:
        run(app, 0.2)
    assert session.status.value in ("mistake", "player")  # a mistake, or "good move, but there is a better one"
    if session.status.value == "mistake":
        assert app.profile.games == 2 and app.profile.fail_streak == 1
        assert play.message[0]() == "Niestety, to nie to"
        # Language change mid-puzzle: messages and the stream of thought switch to English immediately.
        app.set_language("en")
        assert play.message[0]() == "Sorry, that's not it"
        assert all("Głębokość" not in thought.text for thought in play.state.thoughts)
        app.set_language("pl")
        play.retry()
        assert session.status.value == "player"

    # The remaining screens render without errors in both languages.
    for code in ("en", "pl"):
        app.set_language(code)
        for name in ("stats", "howto", "home"):
            app.go(name)
            run(app, 0.2)
    assert app.profile.language == "pl"


def test_brilliant_move_and_buttons(app) -> None:  # type: ignore[no-untyped-def]
    """A sacrifice in a puzzle shows "!!", and "Next puzzle" appears only after solving it."""
    from tacticmind.puzzles.loader import Puzzle
    from tacticmind.puzzles.session import PuzzleSession

    app.set_language("pl")
    app.go("play")
    run(app, 1.2)
    play = app.screens["play"]
    # Swap the puzzle for 00LNB: 1. Rxa6+! bxa6 2. Ra7# (a rook sacrifice).
    puzzle = Puzzle("00LNB", "kr6/1pR4p/p4R2/n2r4/P3p3/4B3/6PP/6K1 b - - 0 38", ("d5d3", "f6a6", "b7a6", "c7a7"), 1074, 80, ("mateIn2", "sacrifice"))
    play.session = PuzzleSession(puzzle)
    play.board_view.orientation = play.board_view.player_color = puzzle.player_color
    play._play_intro()
    run(app, 0.4)
    assert play.btn_hint.visible and play.btn_solution.visible
    assert not play.btn_next.visible and not play.btn_retry.visible
    assert play.board_view.last_move is not None  # the opponent's move is highlighted
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
    """◀ ▶ during a puzzle: stepping back to earlier positions and returning to the current one."""
    import chess

    from tacticmind.puzzles.loader import Puzzle
    from tacticmind.puzzles.session import PuzzleSession

    app.go("play")
    run(app, 1.2)
    play = app.screens["play"]
    puzzle = Puzzle("00LNB", "kr6/1pR4p/p4R2/n2r4/P3p3/4B3/6PP/6K1 b - - 0 38", ("d5d3", "f6a6", "b7a6", "c7a7"), 1074, 80, ("mateIn2",))
    play.timers.clear()
    play.session = PuzzleSession(puzzle)
    play.board_view.orientation = play.board_view.player_color = puzzle.player_color
    play._play_intro()
    play.on_player_move(chess.Move.from_uci("f6a6"))
    run(app, 1.8)  # opponent's reply bxa6
    live_fen = play.session.board.fen()
    assert play.btn_prev_pos.visible and play.btn_prev_pos.enabled and not play.btn_next_pos.enabled

    play.step_view(-1)  # before bxa6
    run(app, 0.3)
    assert play.view_index == 2 and not play.board_view.interactive
    assert play.board_view.board.piece_at(chess.A6) == chess.Piece(chess.ROOK, chess.WHITE)
    play.step_view(-1)
    play.step_view(-1)  # the puzzle's starting position (before the opponent's move)
    run(app, 0.1)
    assert play.view_index == 0 and not play.btn_prev_pos.enabled and play.btn_next_pos.enabled
    play.hint()  # in an earlier position the hint is unavailable (and does not cost the reward)
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
    """Sounds also work when the system opens audio in stereo (previously they were disabled then)."""
    import pygame

    from tacticmind.ui.sounds import build_sounds

    samples = build_sounds(22050)
    assert set(samples) >= {"move", "capture", "check", "castle", "promote", "success", "brilliant", "error"}
    assert all(max(abs(x) for x in data) > 0.05 for data in samples.values())
    assert pygame.mixer.get_init() is not None and pygame.mixer.get_init()[2] == 2
    deadline = time.monotonic() + 15
    while not app.sounds.available and time.monotonic() < deadline:  # background synthesis
        time.sleep(0.05)
    assert app.sounds.available
    app.sounds.play("move")


def test_drag_deadzone(app) -> None:  # type: ignore[no-untyped-def]
    """A slight mouse twitch while clicking does not pick up the piece; only a clear movement starts a drag."""
    import pygame

    app.go("play")
    run(app, 1.2)
    play = app.screens["play"]
    view = play.board_view
    view.interactive = True
    piece_square = next(sq for sq, p in view.board.piece_map().items() if p.color == view.player_color and view.legal_targets(sq))
    rect = view.square_rect(piece_square)
    near_edge = (rect.x + 3, rect.y + 3)  # click right at the edge of the square
    view.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=near_edge, button=1))
    view.handle(pygame.event.Event(pygame.MOUSEMOTION, pos=(near_edge[0] + 4, near_edge[1] + 3), rel=(4, 3), buttons=(1, 0, 0)))
    assert not view.drag_moved and view.selected == piece_square
    view.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(near_edge[0] + 4, near_edge[1] + 3), button=1))
    assert view.selected == piece_square  # a plain click = selection (click-click)
    far = (near_edge[0] + int(view.drag_deadzone()) + 6, near_edge[1])
    view.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=near_edge, button=1))
    view.handle(pygame.event.Event(pygame.MOUSEMOTION, pos=far, rel=(20, 0), buttons=(1, 0, 0)))
    assert view.drag_moved
    view.handle(pygame.event.Event(pygame.MOUSEMOTION, pos=far, rel=(0, 0), buttons=(0, 0, 0)))  # released outside the window
    assert view.drag_square is None and view.selected == piece_square  # the piece returns and stays selected


def test_undo_animation_restores_captured_piece(app) -> None:  # type: ignore[no-untyped-def]
    """◀ undoes a move with animation: the piece returns to its start square and the captured piece fades back in."""
    import chess
    import pygame

    from tacticmind.ui.board_view import BoardView

    view = BoardView()
    before = chess.Board("rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
    capture = chess.Move.from_uci("e4d5")
    after = before.copy()
    after.push(capture)
    view.set_position(after, capture, animate=False)
    view.set_position(before, None, undo=capture)
    assert view.anim is not None and view.anim.restore
    assert view.anim.pieces[0][1:] == (chess.D5, chess.E4)  # the pawn slides from d5 back to e4
    assert view.anim.captured == (chess.Piece(chess.PAWN, chess.BLACK), chess.D5)
    view.update(0.1)
    view.draw(pygame.Surface((600, 600)))  # drawing during the undo animation raises no errors


def test_volume_slider_and_fullscreen(app) -> None:  # type: ignore[no-untyped-def]
    """The volume slider changes and remembers the volume; F11 toggles fullscreen."""
    import pygame

    from tacticmind.rating.profile import load_profile

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
    assert abs(load_profile().volume - app.profile.volume) < 1e-6  # saved to disk
    windowed = app.screen.get_size()
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F11, mod=0, unicode="", scancode=0))
    run(app, 0.1)
    assert app.fullscreen
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F11, mod=0, unicode="", scancode=0))
    run(app, 0.1)
    assert not app.fullscreen and app.screen.get_size() == windowed


def test_app_icon_and_wide_pieces(app) -> None:  # type: ignore[no-untyped-def]
    """Window icon (a pawn) and the widened king and queen symbols."""
    import chess

    from tacticmind.ui.icon import app_icon
    from tacticmind.ui.pieces import piece_surface

    icon = app_icon(64)
    assert icon.get_size() == (64, 64)
    assert icon.get_at((0, 0)).a == 0 and icon.get_at((32, 32)).a == 255  # transparent corners, opaque centre
    king = piece_surface(chess.Piece(chess.KING, chess.WHITE), 100)
    assert 0.85 < king.get_width() / king.get_height() <= 1.1  # about 0.75 without widening — it looked squeezed
    assert king.get_width() <= 94


def test_layouts_at_many_resolutions(app) -> None:  # type: ignore[no-untyped-def]
    """All screens render at small, typical and very large resolutions."""
    import pygame

    for size in ((430, 640), (800, 600), (1280, 720), (1920, 1080), (2560, 1440)):
        app.screen = pygame.display.set_mode(size, pygame.RESIZABLE)
        app.relayout()
        for name in ("home", "play", "stats", "howto", "coach", "coach_game"):
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
    right_drag(g1, f3)  # knight arrow (L shape)
    right_drag(e4, e4)  # square mark
    assert set(view.user_arrows) == {(chess.E2, chess.E4), (chess.G1, chess.F3)}
    assert chess.E4 in view.marks
    assert len(view.arrow_points(chess.G1, chess.F3)) == 3 and len(view.arrow_points(chess.E2, chess.E4)) == 2
    run(app, 0.1)  # drawing arrows raises no errors
    right_drag(e2, e4)  # the same arrow a second time = removal
    assert (chess.E2, chess.E4) not in view.user_arrows
    view.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=e2, button=1))  # a left click clears the drawings
    assert not view.user_arrows and not view.marks


# ---------------------------------------------------------------------------
# Coach game
# ---------------------------------------------------------------------------
def _wait_phase(app, screen, phases, limit: float = 30.0) -> str:  # type: ignore[no-untyped-def]
    end = time.monotonic() + limit
    while time.monotonic() < end and screen.phase not in phases:
        app.frame(1 / 60)
        time.sleep(0.003)
    return str(screen.phase)


@pytest.fixture
def fast_coach(monkeypatch):  # type: ignore[no-untyped-def]
    """Shorter coach pauses (in the game they exist so moves and comments can be seen)."""
    from tacticmind.ui.screens import coach_game

    monkeypatch.setattr(coach_game, "MIN_THINK", 0.05)
    monkeypatch.setattr(coach_game, "TRAINER_PAUSE", 0.05)
    monkeypatch.setattr(coach_game, "LESSON_REPLY", 0.05)
    monkeypatch.setattr(coach_game, "PRE_TIME", 600)
    monkeypatch.setattr(coach_game, "POST_TIME", 500)
    return coach_game


def test_coach_game_blunder_takeback_and_summary(app, fast_coach) -> None:  # type: ignore[no-untyped-def]
    """Book move, blunder (pause and a better-move arrow), takeback, resignation and summary."""
    import chess

    app.start_coach_game(chess.WHITE, 1200, False, None)
    screen = app.screens["coach_game"]
    assert _wait_phase(app, screen, ("player",)) == "player"
    screen.on_player_move(chess.Move.from_uci("d2d4"))
    assert _wait_phase(app, screen, ("player",)) == "player"
    game = screen.game
    assert game.records[0].classification == "book" and not game.records[1].by_player
    # Queen onto a square attacked by a minor piece or a pawn = blunder.
    screen.on_player_move(chess.Move.from_uci("d1d3"))
    if _wait_phase(app, screen, ("player", "paused")) == "paused":
        screen.continue_after_pause()
        _wait_phase(app, screen, ("player",))
    board = game.board
    blunder = None
    for move in board.legal_moves:
        if board.piece_type_at(move.from_square) == chess.QUEEN and not board.is_capture(move):
            after = board.copy()
            after.push(move)
            if any(after.piece_type_at(sq) in (chess.PAWN, chess.KNIGHT, chess.BISHOP) for sq in after.attackers(after.turn, move.to_square)):
                blunder = move
                break
    assert blunder is not None
    before = len(game.records)
    screen.on_player_move(blunder)
    assert _wait_phase(app, screen, ("paused",)) == "paused"
    record = game.records[-1]
    assert record.classification in ("mistake", "blunder") and record.best_uci
    assert screen.arrow is not None and screen.board_view.arrows  # better-move arrow
    run(app, 0.3)
    screen.take_back()
    assert _wait_phase(app, screen, ("player",)) == "player"
    assert len(game.records) == before and game.takebacks == 1
    screen.ask_resign()
    assert screen.confirm is not None
    screen._confirm_yes()
    run(app, 1.2)
    assert game.result == "loss" and screen.summary_visible()
    assert len(app.profile.coach.games) == 1 and app.profile.coach.games[0].helps == 1
    assert app.profile.coach.games[0].score == 0


def test_coach_lesson_wrong_move_then_full_line(app, fast_coach) -> None:  # type: ignore[no-untyped-def]
    import chess

    from tacticmind.coach.openings import line_ucis, opening_by_id

    app.start_coach_game(chess.WHITE, 800, False, opening_by_id("italian"))
    screen = app.screens["coach_game"]
    _wait_phase(app, screen, ("player",))
    screen.on_player_move(chess.Move.from_uci("a2a3"))  # off the line
    assert screen.phase == "lesson_wrong"
    assert _wait_phase(app, screen, ("player",)) == "player"
    game = screen.game
    assert game.lesson_mistakes == 1 and not game.board.move_stack
    line = line_ucis("italian")
    while _wait_phase(app, screen, ("player", "lesson_done")) == "player":
        screen.on_player_move(chess.Move.from_uci(line[len(game.board.move_stack)]))
    assert game.lesson_complete()
    assert app.profile.coach.stars("italian") == 1  # completed, but with a mistake
    screen.continue_after_lesson()
    assert game.playing and not game.lesson_active
    # After the lesson (12 plies) the game continues: White to move again.
    assert _wait_phase(app, screen, ("player",)) == "player" and game.player_to_move


def test_coach_menu_and_avatar(app) -> None:  # type: ignore[no-untyped-def]
    import pygame

    from tacticmind.ui.coach_avatar import EXPRESSIONS, coach_portrait

    for expression in EXPRESSIONS:
        portrait = coach_portrait(96, expression)
        assert portrait.get_size() == (96, 96)
        assert portrait.get_at((1, 1)).a == 0 and portrait.get_at((48, 48)).a == 255  # round
    app.go("coach")
    run(app, 0.3)
    menu = app.screens["coach"]
    slider = menu.slider
    x = slider.rect.x + slider.rect.width  # end of the slider = 2000
    menu.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(x, slider.rect.centery), button=1))
    menu.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(x, slider.rect.centery), button=1))
    assert app.profile.coach.elo == 2000
    assert not menu.level_button.enabled  # "Your level" locked until calibration is finished
    opening, row = menu.rows[0]
    menu.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=row.center, button=1))
    run(app, 0.2)
    assert app.current_name == "coach_game"
    game = app.screens["coach_game"].game
    assert game.lesson is opening and game.elo == 2000


def test_settings_panel_fps(app) -> None:  # type: ignore[no-untyped-def]
    """The gear opens settings: the FPS limit changes on click, F3 toggles the counter, Esc closes."""
    import pygame

    app.go("stats")
    run(app, 0.3)
    app.topbar.settings.on_click()
    run(app, 0.3)
    assert app.settings.open
    target = app.settings.fps_limit._segment(2)  # "144"
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=target.center, button=1))
    run(app, 0.1)
    assert app.profile.fps_limit == 144
    assert app.settings.open  # a click inside the popup does not close it
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F3, mod=0, unicode=""))
    run(app, 0.1)
    assert app.profile.show_fps and app.fps.fps > 0
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0, unicode=""))
    run(app, 0.1)
    assert not app.settings.open
