"""sources.py - Qué páginas se scrollean en cada vuelta y en qué orden.

Primero las búsquedas de publicaciones (las que traen "enviá tu CV a <email>"), después un
subconjunto rotativo de grupos y páginas de empresa y al final el feed: así una vuelta corta
o un reinicio no dejan sin recorrer justo las fuentes que más rinden.
"""

from __future__ import annotations

from dataclasses import dataclass

from config import RunSettings
from feed import FEED_URL
from jobs import queries_for_cycle

CONTENT_SEARCH_MARKER = "/search/results/content"
PAGES_PER_CYCLE = 8
# Colectas seguidas sin un post nuevo antes de abandonar la página. Las búsquedas vienen
# ordenadas por fecha: si arriba todo está visto, abajo también.
SEARCH_IDLE_LIMIT = 3
PAGE_IDLE_LIMIT = 6
# El DOM del feed crece varios GB al scrollear: se lee en tramos y se suelta entre uno y otro.
FEED_SEGMENT_MINUTES = 4


@dataclass(frozen=True)
class Source:
    url: str
    minutes: float
    idle_limit: int

    @property
    def is_content_search(self) -> bool:
        return is_content_search(self.url)


def is_content_search(url: str) -> bool:
    return CONTENT_SEARCH_MARKER in url


def plan_sources(channels: list[str], run: RunSettings, rotation: int) -> list[Source]:
    """Todas las búsquedas de publicaciones, PAGES_PER_CYCLE grupos/empresas rotativos y el feed."""
    minutes = run.channel_scroll_minutes
    searches = [Source(url, minutes, SEARCH_IDLE_LIMIT) for url in channels if is_content_search(url)]
    pages = [url for url in channels if not is_content_search(url)]
    rotating = [Source(url, minutes, PAGE_IDLE_LIMIT) for url in queries_for_cycle(pages, rotation, PAGES_PER_CYCLE)]
    segments = max(1, round(run.scroll_minutes / FEED_SEGMENT_MINUTES))
    feed = [Source(FEED_URL, run.scroll_minutes / segments, PAGE_IDLE_LIMIT)] * segments
    return searches + rotating + feed
