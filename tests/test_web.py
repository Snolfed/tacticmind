"""Interface: screen logic, state snapshots, the HTTP server and the game window (without a real window)."""

from __future__ import annotations

import http.client
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import chess
import pytest

from tacticmind.web.core import DEFAULT_SETTINGS, WebApp, load_settings
from tacticmind.web.server import TacticMindServer, strings_payload


class StubEngine:
    """An engine that computes nothing — for server tests (no separate process)."""

    def __init__(self) -> None:
        self.requests = 0

    def analyze(self, *args: Any, **kwargs: Any) -> int:
        self.requests += 1
        return self.requests

    def compare(self, *args: Any, **kwargs: Any) -> int:
        return self.analyze()

    def stop(self) -> None:
        pass

    def poll(self) -> list[Any]:
        return []

    def close(self) -> None:
        pass


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("TACTICMIND_HOME", str(tmp_path))
    return tmp_path


def run(app: WebApp, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.tick()
        time.sleep(0.02)


def view(app: WebApp) -> dict[str, Any]:
    state: dict[str, Any] = json.loads(app.state_message())
    return state


def wait_until(app: WebApp, condition: Any, timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run(app, 0.1)
        state = view(app)
        if condition(state):
            return state
    raise AssertionError(f"condition not met within {timeout} s; state: {json.dumps(state)[:600]}")


def test_settings_file_is_validated(home: Path) -> None:
    path = home / "ui_settings.json"
    assert load_settings(path) == DEFAULT_SETTINGS  # no file
    path.write_text("{not json", encoding="utf-8")
    assert load_settings(path) == DEFAULT_SETTINGS
    path.write_text(json.dumps({"showFps": "yes", "fpsLimit": 999}), encoding="utf-8")
    assert load_settings(path) == DEFAULT_SETTINGS
    path.write_text(json.dumps({"showFps": True, "fpsLimit": 144}), encoding="utf-8")
    assert load_settings(path) == {**DEFAULT_SETTINGS, "showFps": True, "fpsLimit": 144}
    path.write_text(json.dumps({"theme": "light", "board": "slate"}), encoding="utf-8")
    assert load_settings(path) == {**DEFAULT_SETTINGS, "theme": "light", "board": "slate"}
    path.write_text(json.dumps({"theme": "neon", "board": 3}), encoding="utf-8")
    assert load_settings(path) == DEFAULT_SETTINGS
    path.write_text(json.dumps({"coachEval": False}), encoding="utf-8")
    assert load_settings(path) == {**DEFAULT_SETTINGS, "coachEval": False}
    path.write_text(json.dumps({"coachEval": 0}), encoding="utf-8")
    assert load_settings(path) == DEFAULT_SETTINGS


def test_settings_actions_are_saved(home: Path) -> None:
    app = WebApp(engine=StubEngine())  # type: ignore[arg-type]
    app.dispatch({"type": "settings", "showFps": True, "fpsLimit": 240})
    app.dispatch({"type": "settings", "fpsLimit": 75})  # not in the list — ignored
    app.dispatch({"type": "settings", "theme": "light", "board": "terracotta"})
    app.dispatch({"type": "settings", "theme": "neon", "board": "marble"})  # unknown — ignored
    app.dispatch({"type": "settings", "coachEval": False})
    expected = {"showFps": True, "fpsLimit": 240, "theme": "light", "board": "terracotta", "coachEval": False}
    assert view(app)["settings"] == expected
    assert load_settings(home / "ui_settings.json") == expected
    app.dispatch({"type": "sound", "volume": 0.3})
    app.dispatch({"type": "language", "code": "en"})
    state = view(app)
    assert state["topbar"]["volume"] == pytest.approx(0.3)
    assert state["lang"] == "en"
    app.dispatch({"type": "language", "code": "xx"})  # unknown language — no change
    assert view(app)["lang"] == "en"
    app.stop()


def test_navigation_and_snapshots(home: Path) -> None:
    app = WebApp(engine=StubEngine())  # type: ignore[arg-type]
    assert view(app)["screen"] == "home"
    app.dispatch({"type": "go", "screen": "coach_game"})  # there is no game yet
    assert view(app)["screen"] == "home"
    for screen in ("play", "coach", "stats", "howto", "home"):
        app.dispatch({"type": "go", "screen": screen})
        state = view(app)
        assert state["screen"] == screen
        assert state["view"] is not None
    # An action for a screen that is not open does nothing.
    app.dispatch({"type": "screen", "screen": "stats", "name": "reset"})
    app.dispatch({"type": "go", "screen": "stats"})
    assert view(app)["view"]["confirm"] is False
    app.dispatch({"type": "screen", "screen": "stats", "name": "system", "data": {"system": "elo"}})
    assert view(app)["view"]["system"] == "elo"
    app.stop()


def test_puzzle_solved_through_actions(home: Path) -> None:
    app = WebApp(persist=False)
    try:
        app.dispatch({"type": "go", "screen": "play"})
        state = wait_until(app, lambda s: s["view"].get("board", {}).get("interactive"))
        board = state["view"]["board"]
        assert board["legal"] and board["fen"]
        assert state["view"]["brain"]["candidates"] is None  # hidden mode
        fx: list[dict[str, Any]] = []
        subscriber = app.subscribe()
        play = app.screens["play"]
        session = play.session  # type: ignore[attr-defined]
        for _ in range(12):
            if session.finished:
                break
            if session.status.value == "player":
                app.dispatch({"type": "screen", "screen": "play", "name": "move", "data": {"uci": session.expected_move.uci()}})
            run(app, 0.6)
        assert session.finished
        state = wait_until(app, lambda s: s["view"]["card"]["finished"])
        assert state["view"]["buttons"]["next"]["visible"]
        assert state["topbar"]["delta"] is not None and state["topbar"]["delta"] > 0
        while not subscriber.empty():
            message = subscriber.get()
            if message and message.startswith("event: fx"):
                fx += json.loads(message.split("data: ", 1)[1])
        assert {"type": "sound", "name": "success"} in fx
        assert any(event["type"] == "celebrate" and event["board"] == "play" for event in fx)
        app.dispatch({"type": "screen", "screen": "play", "name": "next"})
        state = wait_until(app, lambda s: s["view"]["card"]["finished"] is False)
    finally:
        app.stop()


def test_coach_game_through_actions(home: Path) -> None:
    app = WebApp(persist=False)
    try:
        app.dispatch({"type": "go", "screen": "coach"})
        app.dispatch({"type": "screen", "screen": "coach", "name": "color", "data": {"color": "white"}})
        app.dispatch({"type": "screen", "screen": "coach", "name": "play"})
        state = wait_until(app, lambda s: s["screen"] == "coach_game" and s["view"]["board"]["interactive"])
        assert state["view"]["board"]["orientation"] == "white"
        assert [strip["player"] for strip in state["view"]["strips"]] == [False, True]
        app.dispatch({"type": "screen", "screen": "coach_game", "name": "move", "data": {"uci": "e2e4"}})
        state = wait_until(app, lambda s: len(s["view"]["moves"]["list"]) == 2 and s["view"]["board"]["interactive"], 40)
        first = state["view"]["moves"]["list"][0]
        assert first["san"] == "e4" and first["player"] and first["cls"]
        assert state["view"]["card"]["comment"]["text"]
        # The evaluation bar: the engine's analysis of the position on the board, from White's side.
        state = wait_until(app, lambda s: s["view"]["eval"]["score"] is not None, 20)
        assert state["view"]["eval"]["whiteBottom"] and abs(state["view"]["eval"]["score"]["value"]) < 300
        # Stepping back through the game with the ◀ arrow and returning.
        app.dispatch({"type": "screen", "screen": "coach_game", "name": "step", "data": {"delta": -1}})
        assert view(app)["view"]["moves"]["current"] == 0
        app.dispatch({"type": "screen", "screen": "coach_game", "name": "jump", "data": {"index": 2}})
        assert view(app)["view"]["moves"]["current"] == 1
        assert view(app)["view"]["eval"]["score"] is not None  # after 1. e4: the score of the judged move
        # An illegal move is ignored.
        before = view(app)["view"]["board"]["seq"]
        app.dispatch({"type": "screen", "screen": "coach_game", "name": "move", "data": {"uci": "e1e5"}})
        assert view(app)["view"]["board"]["seq"] == before
    finally:
        app.stop()


# ---------------------------------------------------------------------------- HTTP server


@pytest.fixture
def server(home: Path) -> Any:
    import threading

    app = WebApp(engine=StubEngine())  # type: ignore[arg-type]
    srv = TacticMindServer(app, 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    app.stop()


def request(srv: TacticMindServer, method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, {k.lower(): v for k, v in response.getheaders()}, data


def test_server_serves_page_strings_and_state(server: TacticMindServer) -> None:
    status, headers, body = request(server, "GET", "/")
    assert status == 200 and headers["content-type"].startswith("text/html")
    assert b"TacticMind" in body
    status, _, body = request(server, "GET", "/api/strings")
    assert status == 200
    payload = json.loads(body)
    assert payload == json.loads(json.dumps(strings_payload()))
    assert payload["languages"]["pl"]["strings"]["nav.play"] == "Zadania"
    status, _, body = request(server, "GET", "/api/state")
    assert status == 200 and json.loads(body)["screen"] == "home"
    status, headers, _ = request(server, "GET", "/fonts/NotoSans-Regular.woff2")
    assert status == 200 and headers["content-type"] == "font/woff2"


def test_server_rejects_foreign_requests(server: TacticMindServer) -> None:
    action = json.dumps({"type": "go", "screen": "stats"}).encode()
    # Without the X-TacticMind header (e.g. a form from another page) — rejected.
    status, _, _ = request(server, "POST", "/api/action", action, {"Content-Type": "application/json"})
    assert status == 403
    # A foreign Host header (DNS rebinding) — rejected.
    status, _, _ = request(server, "GET", "/api/state", headers={"Host": "evil.example:80"})
    assert status == 403
    # Escaping the fonts directory — no file.
    status, _, body = request(server, "GET", "/fonts/../../web/core.py")
    assert status == 404
    assert b"class WebApp" not in body
    status, _, _ = request(server, "GET", "/fonts/no-such-file.woff2")
    assert status == 404
    _, _, body = request(server, "GET", "/../web/core.py")
    assert b"class WebApp" not in body
    status, _, _ = request(server, "POST", "/api/action", b"[1, 2]", {"X-TacticMind": "1", "Content-Type": "application/json"})
    assert status == 400
    status, _, _ = request(server, "POST", "/api/action", b"{bad json", {"X-TacticMind": "1"})
    assert status == 400
    status, _, _ = request(server, "POST", "/api/action", action, {"X-TacticMind": "1", "Content-Type": "application/json"})
    assert status == 204
    assert server.app.current_name == "stats"


def test_server_event_stream_sends_state(server: TacticMindServer) -> None:
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request("GET", "/api/events")
    response = conn.getresponse()
    assert response.status == 200
    assert response.getheader("Content-Type", "").startswith("text/event-stream")
    lines = []
    while not any(line.startswith(b"data: ") for line in lines):
        lines.append(response.fp.readline())
    data = next(line for line in lines if line.startswith(b"data: "))
    assert json.loads(data[6:])["screen"] == "home"
    assert server.app.clients == 1
    conn.close()


def test_window_shows_the_game_and_closing_it_ends_the_game(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``python main.py``: the server starts, the window opens on its address, and closing the window stops everything."""
    from tacticmind.web import app as launcher
    from tacticmind.web import window

    opened: dict[str, Any] = {}

    class FakeWindow:
        def __init__(self) -> None:
            self.toggles = 0

        def toggle_fullscreen(self) -> None:
            self.toggles += 1

    def create_window(title: str, url: str, **options: Any) -> FakeWindow:
        opened.update(title=title, url=url, options=options, window=FakeWindow())
        return opened["window"]

    def start(**options: Any) -> None:
        """The window is "open" until this returns: the game must already be served at its address."""
        opened["start"] = options
        port = int(opened["url"].rsplit(":", 1)[1].strip("/"))
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/api/state")
        opened["screen"] = json.loads(conn.getresponse().read())["screen"]
        conn.close()
        api = opened["options"]["js_api"]
        opened["fullscreen"] = [api.is_fullscreen(), api.toggle_fullscreen(), api.toggle_fullscreen()]

    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(create_window=create_window, start=start))
    monkeypatch.setattr(window, "check", lambda: None)
    monkeypatch.setattr(window, "find_browser", lambda: None)  # no Chromium: the pywebview window
    monkeypatch.setattr(launcher, "WebApp", lambda: WebApp(engine=StubEngine()))  # type: ignore[arg-type]
    launcher.main([])

    assert opened["title"] == "TacticMind"
    assert opened["url"].startswith("http://127.0.0.1:")
    assert opened["screen"] == "home"
    assert opened["options"]["background_color"] == window.BACKGROUND
    assert Path(opened["start"]["icon"]).is_file()
    assert opened["fullscreen"] == [False, True, False]
    assert opened["window"].toggles == 2


def test_without_the_window_the_game_explains_what_to_install(home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from tacticmind.web import app as launcher
    from tacticmind.web import window

    monkeypatch.setitem(sys.modules, "webview", None)  # pywebview not installed
    monkeypatch.setattr(window, "find_browser", lambda: None)  # and no Chromium-based browser
    assert window.check() == window.MISSING_PYWEBVIEW
    monkeypatch.setattr(window, "check", lambda: "no window here")
    started: list[bool] = []
    monkeypatch.setattr(launcher, "WebApp", lambda: started.append(True))
    with pytest.raises(SystemExit) as exit_info:
        launcher.main([])
    assert exit_info.value.code == 1
    assert "no window here" in capsys.readouterr().err
    assert not started  # nothing starts in the background


FAKE_BROWSER = """#!/bin/sh
# Records how it was started, fetches the page like the real window would, then "closes".
printf '%s\\n' "$@" > "$(dirname "$0")/args.txt"
for arg in "$@"; do
  case "$arg" in --app=*) "{python}" -c "import sys, urllib.request; urllib.request.urlopen(sys.argv[1] + 'api/state').read()" "${{arg#--app=}}" ;; esac
done
"""


def fake_browser(folder: Path) -> Path:
    browser = folder / "fake-browser"
    browser.write_text(FAKE_BROWSER.format(python=sys.executable))
    browser.chmod(0o755)
    return browser


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the app window of a browser is used on Linux")
def test_on_linux_the_game_opens_in_an_app_window_of_a_chromium_browser(home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """WebKitGTK and Qt WebEngine stop at 60 FPS with the NVIDIA driver; Chromium follows the monitor."""
    from tacticmind.web import app as launcher
    from tacticmind.web import window

    tools = tmp_path / "tools"
    tools.mkdir()
    browser = fake_browser(tools)
    monkeypatch.setenv(window.BROWSER_VARIABLE, str(browser))
    monkeypatch.delenv(window.WINDOW_VARIABLE, raising=False)
    monkeypatch.setitem(sys.modules, "webview", None)  # pywebview is not needed then
    assert window.find_browser() == str(browser)
    assert window.check() is None
    monkeypatch.setattr(launcher, "WebApp", lambda: WebApp(engine=StubEngine()))  # type: ignore[arg-type]
    launcher.main([])  # returns once the "window" closes

    args = (tools / "args.txt").read_text().splitlines()
    assert args[0].startswith("--app=http://127.0.0.1:")
    assert f"--user-data-dir={home / 'window'}" in args  # the game's own browser profile
    assert "--no-first-run" in args

    monkeypatch.setenv(window.WINDOW_VARIABLE, "webview")  # the player can keep the pywebview window
    assert window.find_browser() is None


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the app window of a browser is used on Linux")
def test_a_second_game_gets_its_own_browser_profile(home: Path, tmp_path: Path) -> None:
    """With the profile already open, the browser would hand the window to the first game and exit at once."""
    from tacticmind.web import window

    tools = tmp_path / "tools"
    tools.mkdir()
    browser = fake_browser(tools)
    profile = home / "window"
    profile.mkdir()
    (profile / "SingletonLock").symlink_to(f"host-{os.getpid()}")  # a running browser has it open
    assert window._profile_in_use(profile)
    window.show_in_browser(str(browser), "http://127.0.0.1:1/")
    used = next(arg for arg in (tools / "args.txt").read_text().splitlines() if arg.startswith("--user-data-dir="))
    spare = Path(used.split("=", 1)[1])
    assert spare != profile
    assert not spare.exists()  # removed after the game


@pytest.mark.skipif(not hasattr(signal, "SIGHUP"), reason="POSIX signals")
def test_killing_the_game_closes_its_browser_window(home: Path, tmp_path: Path) -> None:
    """Closing the terminal or `kill` must not leave the window open on a dead server."""
    from tacticmind.web import window

    browser = tmp_path / "slow-browser"
    browser.write_text(f"#!/bin/sh\necho $$ > {tmp_path / 'pid'}\nexec sleep 30\n")
    browser.chmod(0o755)
    before = signal.getsignal(signal.SIGTERM)
    killer = threading.Timer(1.0, os.kill, (os.getpid(), signal.SIGTERM))
    killer.start()
    with pytest.raises(SystemExit):
        window.show_in_browser(str(browser), "http://127.0.0.1:1/")
    killer.join()
    pid = int((tmp_path / "pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)  # the browser was closed (and reaped) with the game
    assert signal.getsignal(signal.SIGTERM) == before


def test_nvidia_under_wayland_turns_off_explicit_sync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Otherwise WebKitGTK's window dies at once: "Error 71 (Protocol error) dispatching to Wayland display"."""
    from tacticmind.web import window

    driver = tmp_path / "version"
    monkeypatch.setattr(window, "NVIDIA_DRIVER", driver)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.delenv("GDK_BACKEND", raising=False)
    monkeypatch.delenv("__NV_DISABLE_EXPLICIT_SYNC", raising=False)
    monkeypatch.delenv("WEBKIT_DISABLE_DMABUF_RENDERER", raising=False)
    window._avoid_nvidia_wayland_crash()  # no NVIDIA driver: nothing changes
    assert "__NV_DISABLE_EXPLICIT_SYNC" not in os.environ
    driver.write_text("NVRM version: NVIDIA UNIX x86_64 Kernel Module  580.178.04")
    monkeypatch.setenv("GDK_BACKEND", "x11")
    window._avoid_nvidia_wayland_crash()  # X11 session or backend: not affected
    assert "__NV_DISABLE_EXPLICIT_SYNC" not in os.environ
    monkeypatch.delenv("GDK_BACKEND")
    window._avoid_nvidia_wayland_crash()
    assert os.environ["__NV_DISABLE_EXPLICIT_SYNC"] == "1"
    assert "WEBKIT_DISABLE_DMABUF_RENDERER" not in os.environ  # the fast renderer stays on
    monkeypatch.setenv("__NV_DISABLE_EXPLICIT_SYNC", "0")
    window._avoid_nvidia_wayland_crash()  # the player's own choice wins
    assert os.environ["__NV_DISABLE_EXPLICIT_SYNC"] == "0"


def test_board_snapshot_offers_premoves_while_the_opponent_thinks(home: Path) -> None:
    from tacticmind.web.board import BoardModel, premove_targets

    model = BoardModel("test", lambda event: None)
    board = chess.Board()
    board.push_san("e4")
    model.set_position(board, animate=False)
    assert model.snapshot()["premoves"] == []  # only in a live game
    model.premoves = True
    premoves = model.snapshot()["premoves"]
    assert "d2d4" in premoves and "g1f3" in premoves and "e7e5" not in premoves
    # A pawn may pre-capture where a piece could arrive; promotions are listed once.
    moves = premove_targets("4k3/1P6/8/8/8/8/8/4K3 b - - 0 1")
    assert "b7b8" in moves and "b7a8" in moves and "b7c8" in moves and "b7b8q" not in moves
    model.board.push_san("e5")  # the player's turn: a normal move, not a pre-move
    assert model.snapshot()["premoves"] == []


def test_board_snapshot_promotion_and_legality(home: Path) -> None:
    from tacticmind.web.board import BoardModel

    events: list[dict[str, Any]] = []
    model = BoardModel("test", events.append)
    played: list[str] = []
    model.on_move = lambda move: played.append(move.uci())
    model.set_position(chess.Board("4k3/1P6/8/8/8/8/8/4K3 w - - 0 1"), animate=False)
    model.interactive = True
    snapshot = model.snapshot()
    assert "b7b8q" in snapshot["legal"] and "b7b8n" in snapshot["legal"]
    assert snapshot["anim"] == "none" and snapshot["interactive"]
    assert not model.play("b7b8")  # a promotion requires a piece
    assert model.play("b7b8n") and played == ["b7b8n"]
    model.player_color = chess.BLACK  # not our turn — moves rejected, no legal-move list
    assert not model.play("e1e2")
    assert model.snapshot()["legal"] == []
    assert model.snapshot()["premoves"] == []
    model.shake()
    model.celebrate(chess.E4)
    assert events == [{"type": "shake", "board": "test"}, {"type": "celebrate", "board": "test", "square": "e4"}]
