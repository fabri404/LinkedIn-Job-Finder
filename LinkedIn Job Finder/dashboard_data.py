"""dashboard_data.py - Lo que muestra el dashboard: estado del loop, CSVs, log y búsquedas.

Solo lee los archivos que escribe el loop (data/ y channels.txt); lo único que modifica es
channels.txt, al agregar o quitar búsquedas de publicaciones.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import TypeVar
from urllib.parse import quote, unquote

from config import BASE_DIR

DATA_DIR = BASE_DIR / "data"
CHANNELS_FILE = BASE_DIR / "channels.txt"
LOG_FILE = DATA_DIR / "job_finder.log"
LOG_TAIL_BYTES = 400_000
CONTENT_SEARCH_URL = ("https://www.linkedin.com/search/results/content/?keywords={}"
                      "&datePosted=%22past-week%22&sortBy=%22date_posted%22")
KEYWORDS_PARAM = re.compile(r"/search/results/content/\?keywords=([^&]*)")
MAX_QUERY_CHARS = 120
LOG_LINE = re.compile(r"^(?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ (?P<level>[A-Z]+) (?P<msg>.*)$")
IMPORTANT_LOG = re.compile(r"BORRADOR|EMPLEO →|LINKEDIN →|RECRUITER →|ERROR|CRITICAL|checkpoint|Iniciá sesión|"
                           r"Vuelta:|Job Finder v3|Detenido|Cupo diario")
SOURCE_LOG = re.compile(r"^(?P<url>https://\S+?)(?::| trabado)")
START_MARK = "Job Finder v3"
ALERT_MARKS = ("checkpoint", "Iniciá sesión")


T = TypeVar("T")
# Último contenido leído de cada archivo, con su (mtime, tamaño): el panel pide el estado cada
# pocos segundos y la mayoría de las veces nada cambió.
_file_cache: dict[Path, tuple[tuple[int, int], object]] = {}


def _cached(path: Path, load: Callable[[], T]) -> T:
    """`load()` solo si `path` cambió desde la última lectura."""
    try:
        stat = path.stat()
    except OSError:
        return load()
    signature = (stat.st_mtime_ns, stat.st_size)
    hit = _file_cache.get(path)
    if hit is not None and hit[0] == signature:
        return hit[1]  # type: ignore[return-value]
    value = load()
    _file_cache[path] = (signature, value)
    return value


@dataclass(frozen=True)
class LogEntry:
    ts: str
    level: str
    msg: str


@dataclass(frozen=True)
class Status:
    started_at: str | None
    current_source: str | None
    last_cycle: str | None
    last_error: str | None
    alert: str | None
    drafts_today: int
    pending: int


def read_csv_rows(name: str, limit: int) -> list[dict[str, str]]:
    """Últimas `limit` filas de un CSV de data/, la más reciente primero."""
    path = DATA_DIR / name
    if not path.exists():
        return []

    def load() -> list[dict[str, str]]:
        with path.open(encoding="utf-8", newline="") as file:
            return list(csv.DictReader(file))

    return _cached(path, load)[::-1][:limit]


def _log_tail() -> list[LogEntry]:
    if not LOG_FILE.exists():
        return []
    return _cached(LOG_FILE, _read_log_tail)


def _read_log_tail() -> list[LogEntry]:
    with LOG_FILE.open("rb") as file:
        file.seek(max(0, LOG_FILE.stat().st_size - LOG_TAIL_BYTES))
        lines = file.read().decode("utf-8", errors="replace").splitlines()
    return [LogEntry(**m.groupdict()) for line in lines if (m := LOG_LINE.match(line))]


def important_log(limit: int) -> list[dict[str, str]]:
    entries = [asdict(e) for e in _log_tail() if IMPORTANT_LOG.search(e.msg)]
    return entries[::-1][:limit]


def source_label(url: str) -> str:
    """"feed", "grupo 13927947" o la búsqueda en texto ("enviar cv" desarrollador)."""
    if match := KEYWORDS_PARAM.search(url):
        return f"búsqueda: {unquote(match.group(1))}"
    if "/groups/" in url:
        return "grupo " + url.rstrip("/").rsplit("/", 1)[-1]
    if "/company/" in url:
        return "página " + url.split("/company/")[1].split("/")[0]
    return "feed" if "/feed" in url else url


def _since_last_start(entries: list[LogEntry]) -> list[LogEntry]:
    starts = [i for i, e in enumerate(entries) if START_MARK in e.msg]
    return entries[starts[-1]:] if starts else entries


def _last(entries: list[LogEntry], predicate: Callable[[LogEntry], bool]) -> LogEntry | None:
    return next((e for e in reversed(entries) if predicate(e)), None)


def _pending_count() -> int:
    path = DATA_DIR / "state.json"
    try:
        return _cached(path, lambda: len(json.loads(path.read_text(encoding="utf-8")).get("pending", [])))
    except (OSError, ValueError):
        return 0


def _drafts_on(day: date) -> int:
    rows = read_csv_rows("enviados.csv", limit=10_000)
    return sum(1 for row in rows if row.get("fecha", "").startswith(day.isoformat()))


def status_snapshot() -> Status:
    run = _since_last_start(_log_tail())
    start = _last(run, lambda e: START_MARK in e.msg)
    source = _last(run, lambda e: bool(SOURCE_LOG.match(e.msg)))
    cycle = _last(run, lambda e: e.msg.startswith("Vuelta:"))
    error = _last(run, lambda e: e.level in ("ERROR", "CRITICAL"))
    alert = _last(run, lambda e: any(mark in e.msg for mark in ALERT_MARKS))
    return Status(
        started_at=start.ts if start else None,
        current_source=source_label(SOURCE_LOG.match(source.msg).group("url")) if source else None,
        last_cycle=f"{cycle.ts} · {cycle.msg}" if cycle else None,
        last_error=f"{error.ts} · {error.msg}" if error else None,
        alert=f"{alert.ts} · {alert.msg}" if alert else None,
        drafts_today=_drafts_on(date.today()),
        pending=_pending_count(),
    )


def list_searches() -> list[str]:
    """Búsquedas de publicaciones de channels.txt, como texto."""
    lines = CHANNELS_FILE.read_text(encoding="utf-8").splitlines()
    return [unquote(m.group(1)) for line in lines if (m := KEYWORDS_PARAM.search(line))]


def clean_query(query: str) -> str:
    query = " ".join(query.split())
    if not query or len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"La búsqueda debe tener entre 1 y {MAX_QUERY_CHARS} caracteres.")
    return query


def add_search(query: str) -> bool:
    """Agrega la búsqueda (solo publicaciones de la última semana). False si ya estaba."""
    query = clean_query(query)
    if query in list_searches():
        return False
    text = CHANNELS_FILE.read_text(encoding="utf-8")
    separator = "" if text.endswith("\n") or not text else "\n"
    CHANNELS_FILE.write_text(f"{text}{separator}{CONTENT_SEARCH_URL.format(quote(query))}\n", encoding="utf-8")
    return True


def remove_search(query: str) -> bool:
    lines = CHANNELS_FILE.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if not ((m := KEYWORDS_PARAM.search(line)) and unquote(m.group(1)) == query)]
    if len(kept) == len(lines):
        return False
    CHANNELS_FILE.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return True


def other_sources_count() -> int:
    lines = CHANNELS_FILE.read_text(encoding="utf-8").splitlines()
    return sum(1 for line in lines if line.startswith("https://") and not KEYWORDS_PARAM.search(line))
