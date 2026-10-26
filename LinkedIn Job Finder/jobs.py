"""jobs.py - Lee la sección Empleos de LinkedIn por sus endpoints públicos (sin sesión).

No usa el Chrome del loop: son pedidos HTTP a /jobs-guest/, el mismo HTML que ve
alguien sin cuenta. Solo avisos de Argentina publicados en las últimas 24 horas.
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
QUERIES_PER_CYCLE = 3
MAX_DETAILS_PER_CYCLE = 6
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


def search_cards(query: str) -> list[JobCard]:
    """Avisos de las últimas 24 h en Argentina para `query`, hasta PAGES_PER_QUERY páginas."""
    cards: list[JobCard] = []
    for page in range(PAGES_PER_QUERY):
        params = {"keywords": query, "location": "Argentina", "geoId": ARGENTINA_GEO_ID,
                  "f_TPR": LAST_24_HOURS, "start": page * PAGE_SIZE}
        found = parse_cards(_get(f"{SEARCH_URL}?{urlencode(params)}"))
        cards += found
        if len(found) < PAGE_SIZE:
            break
        polite_pause()
    return cards


def fetch_description(card: JobCard) -> str:
    return parse_description(_get(DETAIL_URL.format(job_id=card.job_id)))
