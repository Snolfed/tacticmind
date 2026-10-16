"""Interfejs w przeglądarce: logika ekranów bez pygame, migawki stanu, serwer HTTP i tryb ``--server`` (Tauri)."""

from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import chess
import pytest

from tacticmind.web.core import DEFAULT_SETTINGS, WebApp, load_settings
from tacticmind.web.server import TacticMindServer, strings_payload

ROOT = Path(__file__).resolve().parent.parent


class StubEngine:
    """Silnik, który nic nie liczy — do testów serwera (bez osobnego procesu)."""

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
    raise AssertionError(f"warunek niespełniony w {timeout} s; stan: {json.dumps(state)[:600]}")


def test_settings_file_is_validated(home: Path) -> None:
    path = home / "ui_settings.json"
    assert load_settings(path) == DEFAULT_SETTINGS  # brak pliku
    path.write_text("{to nie json", encoding="utf-8")
    assert load_settings(path) == DEFAULT_SETTINGS
    path.write_text(json.dumps({"showFps": "tak", "fpsLimit": 999}), encoding="utf-8")
    assert load_settings(path) == DEFAULT_SETTINGS
    path.write_text(json.dumps({"showFps": True, "fpsLimit": 144}), encoding="utf-8")
    assert load_settings(path) == {"showFps": True, "fpsLimit": 144}


def test_settings_actions_are_saved(home: Path) -> None:
    app = WebApp(engine=StubEngine())  # type: ignore[arg-type]
    app.dispatch({"type": "settings", "showFps": True, "fpsLimit": 240})
    app.dispatch({"type": "settings", "fpsLimit": 75})  # spoza listy — ignorujemy
    assert view(app)["settings"] == {"showFps": True, "fpsLimit": 240}
    assert load_settings(home / "ui_settings.json") == {"showFps": True, "fpsLimit": 240}
    app.dispatch({"type": "sound", "volume": 0.3})
    app.dispatch({"type": "language", "code": "en"})
    state = view(app)
    assert state["topbar"]["volume"] == pytest.approx(0.3)
    assert state["lang"] == "en"
    app.dispatch({"type": "language", "code": "xx"})  # nieznany język — bez zmian
    assert view(app)["lang"] == "en"
    app.stop()


def test_navigation_and_snapshots(home: Path) -> None:
    app = WebApp(engine=StubEngine())  # type: ignore[arg-type]
    assert view(app)["screen"] == "home"
    app.dispatch({"type": "go", "screen": "coach_game"})  # nie ma jeszcze partii
    assert view(app)["screen"] == "home"
    for screen in ("play", "coach", "stats", "howto", "home"):
        app.dispatch({"type": "go", "screen": screen})
        state = view(app)
        assert state["screen"] == screen
        assert state["view"] is not None
    # Akcja dla ekranu, który nie jest otwarty, nic nie robi.
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
        assert state["view"]["brain"]["candidates"] is None  # tryb ukryty
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
        # Cofnięcie podglądu partii strzałką ◀ i powrót.
        app.dispatch({"type": "screen", "screen": "coach_game", "name": "step", "data": {"delta": -1}})
        assert view(app)["view"]["moves"]["current"] == 0
        app.dispatch({"type": "screen", "screen": "coach_game", "name": "jump", "data": {"index": 2}})
        assert view(app)["view"]["moves"]["current"] == 1
        # Nielegalny ruch jest ignorowany.
        before = view(app)["view"]["board"]["seq"]
        app.dispatch({"type": "screen", "screen": "coach_game", "name": "move", "data": {"uci": "e1e5"}})
        assert view(app)["view"]["board"]["seq"] == before
    finally:
        app.stop()


# ---------------------------------------------------------------------------- serwer HTTP


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
    status, headers, _ = request(server, "GET", "/fonts/NotoSans-Regular.ttf")
    assert status == 200 and headers["content-type"] == "font/ttf"


def test_server_rejects_foreign_requests(server: TacticMindServer) -> None:
    action = json.dumps({"type": "go", "screen": "stats"}).encode()
    # Bez nagłówka X-TacticMind (np. formularz z innej strony) — odmowa.
    status, _, _ = request(server, "POST", "/api/action", action, {"Content-Type": "application/json"})
    assert status == 403
    # Obcy nagłówek Host (DNS rebinding) — odmowa.
    status, _, _ = request(server, "GET", "/api/state", headers={"Host": "evil.example:80"})
    assert status == 403
    # Wyjście poza katalog fontów — brak pliku.
    status, _, body = request(server, "GET", "/fonts/../../web/core.py")
    assert status == 404
    assert b"class WebApp" not in body
    status, _, _ = request(server, "GET", "/fonts/nie-ma-takiego.ttf")
    assert status == 404
    _, _, body = request(server, "GET", "/../web/core.py")
    assert b"class WebApp" not in body
    status, _, _ = request(server, "POST", "/api/action", b"[1, 2]", {"X-TacticMind": "1", "Content-Type": "application/json"})
    assert status == 400
    status, _, _ = request(server, "POST", "/api/action", b"{zly json", {"X-TacticMind": "1"})
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


@pytest.mark.skipif(sys.platform == "win32", reason="zamykanie stdin działa tu inaczej")
def test_server_mode_for_tauri(home: Path) -> None:
    """``main.py --server`` (tak uruchamia go okno Tauri): wypisuje adres i kończy się po zamknięciu stdin."""
    env = {**os.environ, "TACTICMIND_HOME": str(home)}
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "main.py"), "--server", "--port", "0"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
    )
    try:
        assert process.stdout is not None and process.stdin is not None
        line = process.stdout.readline().strip()
        assert line.startswith("TACTICMIND_URL=http://127.0.0.1:")
        port = int(line.rsplit(":", 1)[1].strip("/"))
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/api/state")
        assert json.loads(conn.getresponse().read())["screen"] == "home"
        conn.close()
        process.stdin.close()
        assert process.wait(timeout=15) == 0
    finally:
        if process.poll() is None:
            process.kill()


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
    assert not model.play("b7b8")  # promocja wymaga figury
    assert model.play("b7b8n") and played == ["b7b8n"]
    model.player_color = chess.BLACK  # nie nasz ruch — ruchy odrzucane, bez listy legalnych
    assert not model.play("e1e2")
    assert model.snapshot()["legal"] == []
    model.shake()
    model.celebrate(chess.E4)
    assert events == [{"type": "shake", "board": "test"}, {"type": "celebrate", "board": "test", "square": "e4"}]
