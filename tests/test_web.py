"""Interface: screen logic, state snapshots, the HTTP server and the game window (without a real window)."""

from __future__ import annotations

import http.client
import json
import os
import sys
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
    assert load_settings(path) == {"showFps": True, "fpsLimit": 144}


def test_settings_actions_are_saved(home: Path) -> None:
    app = WebApp(engine=StubEngine())  # type: ignore[arg-type]
    app.dispatch({"type": "settings", "showFps": True, "fpsLimit": 240})
    app.dispatch({"type": "settings", "fpsLimit": 75})  # not in the list — ignored
    assert view(app)["settings"] == {"showFps": True, "fpsLimit": 240}
    assert load_settings(home / "ui_settings.json") == {"showFps": True, "fpsLimit": 240}
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
        # Stepping back through the game with the ◀ arrow and returning.
        app.dispatch({"type": "screen", "screen": "coach_game", "name": "step", "data": {"delta": -1}})
        assert view(app)["view"]["moves"]["current"] == 0
        app.dispatch({"type": "screen", "screen": "coach_game", "name": "jump", "data": {"index": 2}})
        assert view(app)["view"]["moves"]["current"] == 1
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
    assert window.check() == window.MISSING_PYWEBVIEW
    monkeypatch.setattr(window, "check", lambda: "no window here")
    started: list[bool] = []
    monkeypatch.setattr(launcher, "WebApp", lambda: started.append(True))
    with pytest.raises(SystemExit) as exit_info:
        launcher.main([])
    assert exit_info.value.code == 1
    assert "no window here" in capsys.readouterr().err
    assert not started  # nothing starts in the background


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
    model.shake()
    model.celebrate(chess.E4)
    assert events == [{"type": "shake", "board": "test"}, {"type": "celebrate", "board": "test", "square": "e4"}]
