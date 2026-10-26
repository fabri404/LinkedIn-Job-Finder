"""jobs.py - Lee la sección Empleos de LinkedIn por sus endpoints públicos (sin sesión).

No usa el Chrome del loop: son pedidos HTTP a /jobs-guest/, el mismo HTML que ve
alguien sin cuenta. Avisos de las últimas 24 horas según la preferencia de Adriel:
Córdoba con cualquier modalidad, el resto de Argentina y Chile, Paraguay, Colombia, España
y México solo remotos.
"""

from __future__ import annotations

import html
import logging
import random
import re
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
VIEW_URL = "https://www.linkedin.com/jobs/view/{job_id}/"
ARGENTINA_GEO_ID = "100446943"
LAST_24_HOURS = "r86400"
PAGES_PER_QUERY = 2
PAGE_SIZE = 10
# LinkedIn sin sesión responde 429 tras unos pocos pedidos seguidos: pocas búsquedas por
# vuelta (rotando), pocas descripciones, y si igual corta, una hora sin pedirle nada.
# Las vueltas ahora duran minutos y no horas: pocas búsquedas por vuelta ya recorren todas varias veces al día.
QUERIES_PER_CYCLE = 3
LOCAL_QUERIES_PER_CYCLE = 2
REMOTE_WORKPLACE = "2"  # f_WT de LinkedIn: 1 presencial, 2 remoto, 3 híbrido
MAX_DETAILS_PER_CYCLE = 10
COOLDOWN_AFTER_429_S = 60 * 60
TIMEOUT_S = 20
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/141.0 Safari/537.36")
# 429, timeouts y cortes de red: se reintenta en la próxima vuelta.
FETCH_ERRORS = (URLError, TimeoutError, ConnectionError)

CARD_PATTERN = re.compile(r'data-entity-urn="urn:li:jobPosting:(\d+)"(.*?)</li>', re.S)
TITLE_PATTERN = re.compile(r"base-search-card__title[^>]*>(.*?)</h3>", re.S)
COMPANY_PATTERN = re.compile(r"base-search-card__subtitle[^>]*>(.*?)</h4>", re.S)
LOCATION_PATTERN = re.compile(r"job-search-card__location[^>]*>(.*?)</span>", re.S)
DESCRIPTION_PATTERN = re.compile(r"show-more-less-html__markup[^>]*>(.*?)</div>", re.S)


@dataclass(frozen=True)
class SearchScope:
    """Dónde buscar: por geoId para países (el nombre "México" trae avisos de EE.UU.) o por nombre
    para Córdoba (verificado: el nombre devuelve solo avisos de Córdoba)."""

    label: str
    remote_only: bool
    geo_id: str = ""
    location: str = ""


# De Córdoba hacia afuera: Córdoba con cualquier modalidad, después el resto de Argentina solo remoto.
LOCAL_SCOPES = (
    SearchScope("Córdoba", remote_only=False, location="Córdoba, Argentina"),
    SearchScope("Argentina remoto", remote_only=True, geo_id=ARGENTINA_GEO_ID),
)
FOREIGN_SCOPES = (
    SearchScope("Chile remoto", remote_only=True, geo_id="104621616"),
    SearchScope("Paraguay remoto", remote_only=True, geo_id="104065273"),
    SearchScope("Colombia remoto", remote_only=True, geo_id="100876405"),
    SearchScope("España remoto", remote_only=True, geo_id="105646813"),
    SearchScope("México remoto", remote_only=True, geo_id="103323778"),
)


@dataclass(frozen=True)
class JobCard:
    job_id: str
    title: str
    company: str
    location: str

    @property
    def key(self) -> str:
        return f"job:{self.job_id}"

    @property
    def url(self) -> str:
        return VIEW_URL.format(job_id=self.job_id)


def html_to_text(fragment: str) -> str:
    """HTML → texto plano, con un salto de línea por párrafo o ítem de lista."""
    fragment = re.sub(r"<br\s*/?>|</(?:p|li|ul|ol|h\d)>", "\n", fragment)
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def _first_text(pattern: re.Pattern[str], source: str) -> str:
    match = pattern.search(source)
    return html_to_text(match.group(1)) if match else ""


def parse_cards(page: str) -> list[JobCard]:
    return [
        JobCard(job_id, _first_text(TITLE_PATTERN, body), _first_text(COMPANY_PATTERN, body),
                _first_text(LOCATION_PATTERN, body))
        for job_id, body in CARD_PATTERN.findall(page)
    ]


def parse_description(page: str) -> str:
    return _first_text(DESCRIPTION_PATTERN, page)


def _get(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "es-AR,es;q=0.9"})
    with urlopen(request, timeout=TIMEOUT_S) as response:
        return response.read().decode("utf-8", errors="replace")


def polite_pause() -> None:
    time.sleep(random.uniform(3.0, 6.0))


def detail_pause() -> None:
    time.sleep(random.uniform(10.0, 20.0))


def is_rate_limited(exc: Exception) -> bool:
    return isinstance(exc, HTTPError) and exc.code == 429


def queries_for_cycle(queries: list[str], cycle: int, per_cycle: int = QUERIES_PER_CYCLE) -> list[str]:
    """Ventana rotativa de `per_cycle` búsquedas: en N vueltas se recorren todas."""
    if len(queries) <= per_cycle:
        return queries
    start = (cycle * per_cycle) % len(queries)
    return (queries[start:] + queries[:start])[:per_cycle]


def searches_for_cycle(queries: list[str], cycle: int) -> list[tuple[str, SearchScope]]:
    """LOCAL_QUERIES_PER_CYCLE búsquedas en Argentina (remoto) y en Córdoba, más una remota en uno de
    los países preferidos; búsquedas y países rotan entre vueltas."""
    local = [(query, scope) for query in queries_for_cycle(queries, cycle, LOCAL_QUERIES_PER_CYCLE)
             for scope in LOCAL_SCOPES]
    if not queries:
        return local
    return local + [(queries[cycle % len(queries)], FOREIGN_SCOPES[cycle % len(FOREIGN_SCOPES)])]


def search_params(query: str, scope: SearchScope, page: int) -> dict[str, str | int]:
    # f_AL: solo Solicitud sencilla (lo que se puede postular solo); sortBy=DD: lo más nuevo primero.
    params: dict[str, str | int] = {"keywords": query, "f_TPR": LAST_24_HOURS, "f_AL": "true",
                                    "sortBy": "DD", "start": page * PAGE_SIZE}
    if scope.geo_id:
        params["geoId"] = scope.geo_id
    if scope.location:
        params["location"] = scope.location
    if scope.remote_only:
        params["f_WT"] = REMOTE_WORKPLACE
    return params


def search_cards(query: str, scope: SearchScope = LOCAL_SCOPES[0]) -> list[JobCard]:
    """Avisos de las últimas 24 h para `query` en `scope`, hasta PAGES_PER_QUERY páginas. Los de una
    búsqueda remota llevan "Remoto" en la ubicación para que el filtro de modalidad lo sepa."""
    cards: list[JobCard] = []
    for page in range(PAGES_PER_QUERY):
        found = parse_cards(_get(f"{SEARCH_URL}?{urlencode(search_params(query, scope, page))}"))
        if scope.remote_only:
            found = [JobCard(c.job_id, c.title, c.company, f"{c.location} · Remoto") for c in found]
        log.info("Empleos '%s' (%s) página %d: %d avisos.", query, scope.label, page + 1, len(found))
        cards += found
        if len(found) < PAGE_SIZE:
            break
        polite_pause()
    return cards


def fetch_description(card: JobCard) -> str:
    return parse_description(_get(DETAIL_URL.format(job_id=card.job_id)))
