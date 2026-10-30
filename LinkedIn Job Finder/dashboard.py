"""dashboard.py - Panel local para manejar el Job Finder sin la terminal.

    python3 dashboard.py          # sirve en http://localhost:8765
    python3 dashboard.py --open   # además abre el navegador (lo usa el ícono del menú)

Solo escucha en 127.0.0.1. Nunca envía mails: el loop sigue dejando borradores en Gmail.
"""

from __future__ import annotations

import argparse
import json
import logging
import webbrowser
from collections.abc import Callable
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import dashboard_data as data
from config import BASE_DIR
from loop_control import LoopMode, find_loop_pid, start_loop, stop_loop

HOST = "127.0.0.1"
PORT = 8765
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
# Header propio: un sitio externo no puede mandarlo sin preflight CORS, que este servidor no responde.
CSRF_HEADER = "X-Job-Finder"
PAGE = BASE_DIR / "dashboard.html"
MAX_BODY_BYTES = 4096
DEFAULT_LIMIT = 50

log = logging.getLogger("dashboard")
Handler = Callable[[dict[str, Any]], tuple[HTTPStatus, Any]]


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


def _limit(params: dict[str, Any]) -> int:
    try:
        return max(1, min(int(params.get("limit", DEFAULT_LIMIT)), 500))
    except (TypeError, ValueError) as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "limit inválido") from exc


def get_status(_params: dict[str, Any]) -> tuple[HTTPStatus, Any]:
    payload = asdict(data.status_snapshot()) | {"running": find_loop_pid() is not None,
                                                "searches": len(data.list_searches()),
                                                "other_sources": data.other_sources_count()}
    return HTTPStatus.OK, payload


def get_csv(name: str) -> Handler:
    return lambda params: (HTTPStatus.OK, data.read_csv_rows(name, _limit(params)))


def get_drafts(params: dict[str, Any]) -> tuple[HTTPStatus, Any]:
    return HTTPStatus.OK, data.read_drafts(_limit(params))


def get_log(params: dict[str, Any]) -> tuple[HTTPStatus, Any]:
    return HTTPStatus.OK, data.important_log(_limit(params))


def get_searches(_params: dict[str, Any]) -> tuple[HTTPStatus, Any]:
    return HTTPStatus.OK, data.list_searches()


def post_start(params: dict[str, Any]) -> tuple[HTTPStatus, Any]:
    try:
        mode = LoopMode(params.get("mode", LoopMode.CONTINUOUS.value))
    except ValueError as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, "modo inválido") from exc
    if find_loop_pid() is not None:
        raise ApiError(HTTPStatus.CONFLICT, "El loop ya está corriendo.")
    return HTTPStatus.ACCEPTED, {"pid": start_loop(mode), "mode": mode.value}


def post_stop(_params: dict[str, Any]) -> tuple[HTTPStatus, Any]:
    if not stop_loop():
        raise ApiError(HTTPStatus.GATEWAY_TIMEOUT, "El loop no terminó a tiempo; probá de nuevo.")
    return HTTPStatus.OK, {"running": False}


def post_search(params: dict[str, Any]) -> tuple[HTTPStatus, Any]:
    try:
        added = data.add_search(str(params.get("query", "")))
    except ValueError as exc:
        raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
    if not added:
        raise ApiError(HTTPStatus.CONFLICT, "Esa búsqueda ya existe.")
    return HTTPStatus.CREATED, data.list_searches()


def delete_search(params: dict[str, Any]) -> tuple[HTTPStatus, Any]:
    if not data.remove_search(str(params.get("query", ""))):
        raise ApiError(HTTPStatus.NOT_FOUND, "No encontré esa búsqueda.")
    return HTTPStatus.OK, data.list_searches()


ROUTES: dict[tuple[str, str], Handler] = {
    ("GET", "/api/status"): get_status,
    ("GET", "/api/drafts"): get_drafts,
    ("GET", "/api/jobs"): get_csv("empleos_linkedin.csv"),
    ("GET", "/api/leads"): get_csv("contactar_linkedin.csv"),
    ("GET", "/api/log"): get_log,
    ("GET", "/api/searches"): get_searches,
    ("POST", "/api/loop/start"): post_start,
    ("POST", "/api/loop/stop"): post_stop,
    ("POST", "/api/searches"): post_search,
    ("DELETE", "/api/searches"): delete_search,
}


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "JobFinderDashboard"

    def do_GET(self) -> None:  # noqa: N802 (nombre impuesto por http.server)
        if urlparse(self.path).path == "/":
            self._send_page()
            return
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        url = urlparse(self.path)
        handler = ROUTES.get((method, url.path))
        try:
            self._check_request(method, handler)
            params = self._read_params(method, url.query)
            status, payload = handler(params)
        except ApiError as exc:
            status, payload = exc.status, {"error": str(exc)}
        self._send_json(status, payload)

    def _check_request(self, method: str, handler: Handler | None) -> None:
        if self.headers.get("Host") not in ALLOWED_HOSTS:
            raise ApiError(HTTPStatus.FORBIDDEN, "Host no permitido.")
        if handler is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "Ruta inexistente.")
        if method != "GET" and self.headers.get(CSRF_HEADER) != "1":
            raise ApiError(HTTPStatus.FORBIDDEN, "Falta el header del dashboard.")

    def _read_params(self, method: str, query: str) -> dict[str, Any]:
        if method == "GET":
            return {key: values[-1] for key, values in parse_qs(query).items()}
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Pedido demasiado grande.")
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "JSON inválido.") from exc
        if not isinstance(body, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Se esperaba un objeto JSON.")
        return body

    def _send_page(self) -> None:
        if self.headers.get("Host") not in ALLOWED_HOSTS:
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "Host no permitido."})
            return
        self._send(HTTPStatus.OK, "text/html; charset=utf-8", PAGE.read_bytes())

    def _send_json(self, status: HTTPStatus, payload: Any) -> None:
        self._send(status, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode())

    def _send(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        log.debug(fmt, *args)


def main() -> None:
    parser = argparse.ArgumentParser(description="Dashboard local del LinkedIn Job Finder")
    parser.add_argument("--open", action="store_true", help="abre el navegador")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    url = f"http://localhost:{PORT}/"
    try:
        server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    except OSError:
        log.info("El dashboard ya estaba abierto en %s", url)  # otro ícono lo levantó antes
        if args.open:
            webbrowser.open(url)
        return
    log.info("Dashboard en %s", url)
    if args.open:
        webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
