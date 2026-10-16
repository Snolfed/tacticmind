"""Lokalny serwer HTTP interfejsu (tylko biblioteka standardowa, nasłuch wyłącznie na 127.0.0.1).

Adresy:
 - ``GET /`` i pliki interfejsu — zbudowany interfejs w TypeScript (``tacticmind/web/static``),
 - ``GET /fonts/…`` — fonty Noto z ``tacticmind/assets/fonts``,
 - ``GET /api/strings`` — tłumaczenia wszystkich języków (interfejs sam formatuje stałe napisy),
 - ``GET /api/events`` — strumień Server-Sent Events: ``state`` (migawka stanu) i ``fx`` (dźwięki, efekty),
 - ``POST /api/action`` — akcja z przeglądarki (JSON).

Ochrona przed innymi stronami w przeglądarce: akcje wymagają nagłówka ``X-TacticMind`` (inna strona
nie może go wysłać bez zgody CORS, której serwer nie daje), a nagłówek ``Host`` musi wskazywać
na ten komputer (chroni przed „DNS rebinding”).
"""

from __future__ import annotations

import json
import mimetypes
import queue
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .. import i18n
from .core import WebApp

STATIC_DIR = Path(__file__).resolve().parent / "static"
FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
DEFAULT_PORT = 8517
_ALLOWED_HOSTS = ("127.0.0.1", "localhost", "tauri.localhost")
MAX_BODY = 64 * 1024

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("image/svg+xml", ".svg")

_MISSING_BUILD = """<!doctype html><meta charset="utf-8"><title>TacticMind</title>
<body style="font-family:sans-serif;background:#0f111a;color:#eef1f8;padding:40px">
<h1>TacticMind</h1><p>Brak zbudowanego interfejsu w <code>tacticmind/web/static</code>.</p>
<p>Zbuduj go poleceniem <code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code>.</p></body>"""


def strings_payload() -> dict[str, Any]:
    return {
        "default": i18n.DEFAULT_LANGUAGE,
        "languages": {code: {"name": name, "strings": module.STRINGS} for code, (name, module) in i18n.LANGUAGES.items()},
    }


class _Handler(BaseHTTPRequestHandler):
    server: TacticMindServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 — nazwa z BaseHTTPRequestHandler
        """Bez logowania każdego zapytania w konsoli."""

    # ------------------------------------------------------------ pomocnicze
    def _host_ok(self) -> bool:
        host = self.headers.get("Host", "")
        name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        return name in _ALLOWED_HOSTS or name == "[::1]"

    def _send(self, status: int, body: bytes, content_type: str, cache: str = "no-cache") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data: object, status: int = 200) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    # ------------------------------------------------------------ GET
    def do_HEAD(self) -> None:  # noqa: N802 — nazwa z BaseHTTPRequestHandler
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
            return
        path = urlsplit(self.path).path
        if path == "/api/events":
            self._events()
        elif path == "/api/strings":
            self._json(strings_payload())
        elif path == "/api/state":
            self._send(200, self.server.app.state_message().encode("utf-8"), "application/json; charset=utf-8")
        elif path.startswith("/fonts/"):
            if not self._file(FONTS_DIR, path[len("/fonts/") :], "public, max-age=86400"):
                self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
        else:
            self._static(path)

    def _file(self, root: Path, relative: str, cache: str) -> bool:
        target = (root / relative).resolve()
        if root.resolve() not in target.parents or not target.is_file():
            return False
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "image/svg+xml", "application/json"):
            content_type += "; charset=utf-8"
        self._send(200, target.read_bytes(), content_type, cache)
        return True

    def _static(self, path: str) -> None:
        relative = path.lstrip("/") or "index.html"
        cache = "public, max-age=31536000, immutable" if relative.startswith("assets/") else "no-cache"
        if self._file(STATIC_DIR, relative, cache):
            return
        if relative.startswith(("assets/", "pieces/", "api/")):
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
            return
        if not self._file(STATIC_DIR, "index.html", "no-cache"):
            self._send(200, _MISSING_BUILD.encode("utf-8"), "text/html; charset=utf-8")

    def _events(self) -> None:
        """Strumień SSE: migawki stanu i zdarzenia ``fx`` aż do rozłączenia karty."""
        app = self.server.app
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.close_connection = True
        subscriber = app.subscribe()
        try:
            self.wfile.write(b"retry: 500\n\n")
            while True:
                try:
                    message = subscriber.get(timeout=15)
                except queue.Empty:
                    message = ": ping\n\n"  # utrzymanie połączenia
                if message is None:
                    break
                self.wfile.write(message.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            app.unsubscribe(subscriber)

    # ------------------------------------------------------------ POST
    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok() or self.headers.get("X-TacticMind") != "1":
            self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
            return
        if urlsplit(self.path).path != "/api/action":
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= MAX_BODY:
            self._send(HTTPStatus.BAD_REQUEST, b"bad request", "text/plain")
            return
        try:
            action = json.loads(self.rfile.read(length))
        except ValueError:
            self._send(HTTPStatus.BAD_REQUEST, b"bad json", "text/plain")
            return
        if not isinstance(action, dict):
            self._send(HTTPStatus.BAD_REQUEST, b"bad action", "text/plain")
            return
        self.server.app.dispatch(action)
        self._send(HTTPStatus.NO_CONTENT, b"", "text/plain")


class TacticMindServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, app: WebApp, port: int = DEFAULT_PORT) -> None:
        self.app = app
        try:
            super().__init__(("127.0.0.1", port), _Handler)
        except OSError:
            if port == 0:
                raise
            # Port zajęty (np. druga kopia gry) — bierzemy dowolny wolny.
            super().__init__(("127.0.0.1", 0), _Handler)

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0
