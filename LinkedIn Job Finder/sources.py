"""sources.py - Qué páginas se scrollean en cada vuelta y en qué orden.

Primero unas pocas búsquedas de publicaciones (las que traen "enviá tu CV a <email>"), después
algunos grupos y páginas de empresa y al final un tramo del feed. Búsquedas y páginas rotan entre
vueltas: cuántas entran en cada una lo decide pacing.Pacer.cycle_plan (menos de noche).
"""

from __future__ import annotations

from dataclasses import dataclass

from config import RunSettings
from feed import FEED_URL
from jobs import queries_for_cycle
from pacing import CyclePlan

CONTENT_SEARCH_MARKER = "/search/results/content"
# Colectas seguidas sin un post nuevo antes de abandonar la página. Las búsquedas vienen
# ordenadas por fecha: si arriba todo está visto, abajo también.
SEARCH_IDLE_LIMIT = 3
PAGE_IDLE_LIMIT = 6
# Un solo tramo de feed por vuelta, como quien lo mira un rato y sigue.
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


def plan_sources(channels: list[str], run: RunSettings, plan: CyclePlan) -> list[Source]:
    """`plan.content_searches` búsquedas y `plan.pages` grupos/empresas (ventanas rotativas) y un tramo de feed."""
    minutes = run.channel_scroll_minutes
    searches = _window([url for url in channels if is_content_search(url)], plan.rotation, plan.content_searches)
    pages = _window([url for url in channels if not is_content_search(url)], plan.rotation, plan.pages)
    feed = Source(FEED_URL, min(run.scroll_minutes, FEED_SEGMENT_MINUTES), PAGE_IDLE_LIMIT)
    return ([Source(url, minutes, SEARCH_IDLE_LIMIT) for url in searches]
            + [Source(url, minutes, PAGE_IDLE_LIMIT) for url in pages] + [feed])


def _window(urls: list[str], rotation: int, size: int) -> list[str]:
    return queries_for_cycle(urls, rotation, size) if size > 0 else []
