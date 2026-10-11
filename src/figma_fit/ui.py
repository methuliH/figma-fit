"""A local browser page for trying figma-fit: paste a link, pick a budget, see the result.

Serves on 127.0.0.1 only. Every API call must carry the per-session key that
is baked into the page, and the Host header must be this server, so another
website open in the browser cannot drive it (and spend the Figma token).
A token typed into the page is kept in memory only.
"""

from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import Any

from figma_fit.figma import (
    FigmaAPIError,
    FigmaAuthError,
    FigmaClient,
    FigmaRateLimitError,
    nodes_from_body,
)
from figma_fit.fit import BudgetError, fit_nodes
from figma_fit.samples import load_sample
from figma_fit.server import DEFAULT_BUDGET
from figma_fit.url import FigmaURLError, parse_figma_url

KEY_HEADER = "X-Figma-Fit-Key"
MAX_BODY = 64 * 1024 * 1024  # a saved capture of a huge file is a few MB


class UIError(Exception):
    def __init__(self, message: str, code: str = "error") -> None:
        super().__init__(message)
        self.code = code


class App:
    """What the page can ask for. Holds one Figma client, so fetches are cached."""

    def __init__(self, client_factory: Callable[[], FigmaClient] = FigmaClient.from_env) -> None:
        self._client_factory = client_factory
        self._client: FigmaClient | None = None
        self._lock = threading.Lock()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"has_token": self._has_token()}

    def fit(self, request: dict[str, Any]) -> dict[str, Any]:
        budget = request.get("budget", DEFAULT_BUDGET)
        if not isinstance(budget, int) or isinstance(budget, bool):
            raise UIError("budget must be a whole number")
        source = request.get("source")
        with self._lock:
            if source == "sample":
                nodes = load_sample()
            elif source == "capture":
                capture = request.get("capture")
                if not isinstance(capture, dict):
                    raise UIError("that file is not a saved Figma API response")
                nodes = nodes_from_body(str(request.get("name") or "capture"), capture)
                if not nodes:
                    raise UIError("that file has no Figma nodes in it")
            elif source == "link":
                token = request.get("token")
                if token:
                    self._set_token(str(token))
                ref = parse_figma_url(str(request.get("url") or ""))
                client = self._get_client()
                nodes = client.fetch_nodes(
                    ref.file_key, [ref.node_id], refresh=bool(request.get("refresh"))
                )
            else:
                raise UIError(f"unknown source {source!r}")
            result = fit_nodes(nodes, budget)

        report, _, body = result.text.partition("\n")
        return {
            "status": result.status,
            "tokens": result.tokens,
            "budget": result.budget,
            "original_tokens": result.original_tokens,
            "notes": [
                {
                    "pass": n.pass_name,
                    "removed": n.removed,
                    "before": n.tokens_before,
                    "after": n.tokens_after,
                }
                for n in result.notes
            ],
            "report": report,
            "body": json.loads(body) if body.startswith("{") else None,
            "text": result.text,
        }

    def _has_token(self) -> bool:
        if self._client is not None:
            return True
        try:
            self._client = self._client_factory()
        except FigmaAuthError:
            return False
        return True

    def _get_client(self) -> FigmaClient:
        if not self._has_token():
            raise UIError("add a Figma token to fetch links", code="needs_token")
        assert self._client is not None
        return self._client

    def _set_token(self, token: str) -> None:
        if self._client is not None:
            self._client.close()
        self._client = FigmaClient(token)


def make_server(app: App, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    key = secrets.token_urlsafe(24)
    page = files("figma_fit").joinpath("web/index.html").read_text(encoding="utf-8")
    page_bytes = page.replace("__FIGMA_FIT_KEY__", key).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        server_version = "figma-fit"

        def do_GET(self) -> None:
            if not self._host_ok():
                return self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
            if self.path in ("/", "/index.html"):
                return self._send(HTTPStatus.OK, page_bytes, "text/html; charset=utf-8")
            if self.path == "/api/status" and self._key_ok():
                return self._json(HTTPStatus.OK, app.status())
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")

        def do_POST(self) -> None:
            if not self._host_ok() or not self._key_ok():
                return self._json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            if self.path != "/api/fit":
                return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "file too big"})
            try:
                request = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(request, dict):
                    raise UIError("bad request")
                return self._json(HTTPStatus.OK, app.fit(request))
            except UIError as e:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": str(e), "code": e.code})
            except FigmaRateLimitError as e:
                wait = f" Try again in {e.retry_after}s." if e.retry_after else ""
                message = f"Figma rate limit reached.{wait} Some plans allow only a few a month."
                return self._json(HTTPStatus.BAD_REQUEST, {"error": message, "code": "rate_limit"})
            except FigmaAuthError as e:
                return self._json(
                    HTTPStatus.BAD_REQUEST, {"error": e.message, "code": "needs_token"}
                )
            except (FigmaAPIError, FigmaURLError, BudgetError, ValueError) as e:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": str(e), "code": "error"})

        def _host_ok(self) -> bool:
            port = self.server.server_address[1]
            return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

        def _key_ok(self) -> bool:
            return secrets.compare_digest(self.headers.get(KEY_HEADER, ""), key)

        def _json(self, status: HTTPStatus, data: dict[str, Any]) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass  # keep the terminal quiet; it shows the URL to open

    return ThreadingHTTPServer((host, port), Handler)


def run(port: int = 0, open_browser: bool = True) -> None:
    server = make_server(App(), port=port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"figma-fit is running at {url}  (Ctrl+C to stop)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
