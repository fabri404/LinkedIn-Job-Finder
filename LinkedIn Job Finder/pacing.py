"""pacing.py - Cuánto navega el loop por LinkedIn y cuánto descansa entre vueltas.

El 28/10/2026 LinkedIn restringió la cuenta después de ~1.100 páginas en un día, 130 por hora a las
4 de la mañana y búsquedas que seguían aunque devolvían 0 resultados. El ritmo de acá apunta a ≤ 150
páginas por día: vueltas chicas, pausas largas, noches casi quietas y frenos ante las señales de
bloqueo. Contadores y enfriamientos viven en state.json (Store.counters / Store.marks): un reinicio
no los vuelve a cero.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from feed import is_linkedin_url
from store import Store

NIGHT_HOURLY_PAGES = 8
DAY_CONTENT_SEARCHES, DAY_PAGES = 6, 3
NIGHT_CONTENT_SEARCHES, NIGHT_PAGES = 2, 0
# Solicitud sencilla: como mucho 3 por hora y 10–20 min entre una y otra.
EASY_APPLY_PER_HOUR = 3
EASY_APPLY_GAP_MINUTES = (10.0, 20.0)
FOLLOWS_PER_DAY = 3
PEOPLE_SEARCHES_PER_DAY = 1
# Tras una restricción o un checkpoint: una semana a mitad de ritmo, menos solicitudes y sin follows.
WARMUP = timedelta(days=7)
WARMUP_FACTOR = 0.5
WARMUP_EASY_APPLY_LIMIT = 10
# Búsquedas de publicaciones vacías seguidas = LinkedIn las bloqueó en silencio (28/10 desde la 1 AM).
EMPTY_SEARCHES_LIMIT = 5
SEARCH_COOLDOWN = timedelta(hours=12)
REPEATED_SEARCH_COOLDOWN = timedelta(hours=24)
REPEAT_WINDOW = timedelta(hours=48)
# Cada 3 o 4 vueltas de día, un descanso largo, como quien cierra la pestaña y vuelve más tarde.
LONG_BREAK_AFTER = (3, 4)
LONG_BREAK_MINUTES = (90.0, 180.0)
MAX_IDLE_PAUSE_MINUTES = 90.0
PAUSE_SIGMA = 0.25

CONTENT_SEARCH = "content_search"
JOBS = "jobs"
RESTRICTED_AT = "restricted_at"
SEARCH_BLOCKED_AT = "search_blocked_at"
NEXT_EASY_APPLY_AT = "next_easy_apply_at"
EMPTY_SEARCHES = "empty_searches"
CYCLES_SINCE_BREAK = "cycles_since_break"


@dataclass(frozen=True)
class PaceSettings:
    active_start: int = 8
    active_end: int = 23
    daily_pages: int = 120
    hourly_pages: int = 25
    day_pause_minutes: tuple[float, float] = (25.0, 50.0)
    night_pause_minutes: tuple[float, float] = (120.0, 180.0)
    easy_apply_daily_limit: int = 25


@dataclass(frozen=True)
class CyclePlan:
    """Qué recorre una vuelta: cuántas búsquedas de publicaciones y grupos/empresas (rotando)."""

    rotation: int
    content_searches: int
    pages: int


class Pacer:
    def __init__(self, store: Store, settings: PaceSettings, now: Callable[[], datetime] = datetime.now) -> None:
        self.store = store
        self.settings = settings
        self.now = now

    # ── Horario y calentamiento ────────────────────────────────────────────────

    def is_night(self) -> bool:
        hour = self.now().hour
        return not self.settings.active_start <= hour < self.settings.active_end

    def in_warmup(self) -> bool:
        restricted = self.store.marks.get(RESTRICTED_AT)
        return restricted is not None and self._ts() - restricted < WARMUP.total_seconds()

    def mark_restricted(self) -> None:
        self.store.marks[RESTRICTED_AT] = self._ts()

    # ── Presupuesto de páginas con sesión ──────────────────────────────────────

    def count_page(self, url: str) -> None:
        if not is_linkedin_url(url):
            return
        self.store.count(self._day_key("pages"))
        self.store.count(self._hour_key("pages"))

    def pages_left(self) -> int:
        hour_used = self.store.counter(self._hour_key("pages"))
        if self.is_night():
            return NIGHT_HOURLY_PAGES - hour_used
        factor = WARMUP_FACTOR if self.in_warmup() else 1.0
        day_left = int(self.settings.daily_pages * factor) - self.store.counter(self._day_key("pages"))
        return min(day_left, int(self.settings.hourly_pages * factor) - hour_used)

    def has_page_budget(self) -> bool:
        return self.pages_left() > 0

    def cycle_plan(self, rotation: int) -> CyclePlan:
        night = self.is_night()
        searches = NIGHT_CONTENT_SEARCHES if night else DAY_CONTENT_SEARCHES
        if self.cooling(CONTENT_SEARCH):
            searches = 0
        return CyclePlan(rotation, searches, NIGHT_PAGES if night else DAY_PAGES)

    # ── Enfriamientos ──────────────────────────────────────────────────────────

    def cooling(self, name: str) -> bool:
        return self._ts() < self.store.marks.get(f"cooldown:{name}", 0.0)

    def start_cooldown(self, name: str, length: timedelta) -> datetime:
        until = self._ts() + length.total_seconds()
        self.store.marks[f"cooldown:{name}"] = until
        return datetime.fromtimestamp(until)

    def record_search_result(self, posts: int) -> datetime | None:
        """Cuenta búsquedas vacías seguidas; a la quinta, pausa las búsquedas (12 h, o 24 h si se repite).
        Devuelve hasta cuándo, o None si no hubo que frenar."""
        if posts:
            self.store.counters[EMPTY_SEARCHES] = 0
            return None
        if self.store.count(EMPTY_SEARCHES) < EMPTY_SEARCHES_LIMIT:
            return None
        self.store.counters[EMPTY_SEARCHES] = 0
        last_block = self.store.marks.get(SEARCH_BLOCKED_AT, 0.0)
        repeated = self._ts() - last_block < REPEAT_WINDOW.total_seconds()
        self.store.marks[SEARCH_BLOCKED_AT] = self._ts()
        return self.start_cooldown(CONTENT_SEARCH, REPEATED_SEARCH_COOLDOWN if repeated else SEARCH_COOLDOWN)

    # ── Solicitud sencilla ─────────────────────────────────────────────────────

    def easy_apply_limit(self) -> int:
        limit = self.settings.easy_apply_daily_limit
        return min(limit, WARMUP_EASY_APPLY_LIMIT) if self.in_warmup() else limit

    def may_easy_apply(self, sent_today: int) -> bool:
        """De día, bajo el cupo diario y por hora, y pasado el intervalo desde la última."""
        if self.is_night() or sent_today >= self.easy_apply_limit() or not self.has_page_budget():
            return False
        if self.store.counter(self._hour_key("easy_apply")) >= EASY_APPLY_PER_HOUR:
            return False
        return self._ts() >= self.store.marks.get(NEXT_EASY_APPLY_AT, 0.0)

    def record_easy_apply(self) -> None:
        self.store.count(self._hour_key("easy_apply"))
        self.store.marks[NEXT_EASY_APPLY_AT] = self._ts() + random.uniform(*EASY_APPLY_GAP_MINUTES) * 60

    # ── Recruiters: solo "Seguir" ──────────────────────────────────────────────

    def may_follow(self) -> bool:
        if self.is_night() or self.in_warmup() or not self.has_page_budget():
            return False
        return self.store.counter(self._day_key("follows")) < FOLLOWS_PER_DAY

    def record_follow(self) -> None:
        self.store.count(self._day_key("follows"))

    def may_search_people(self) -> bool:
        return self.may_follow() and self.store.counter(self._day_key("people_search")) < PEOPLE_SEARCHES_PER_DAY

    def record_people_search(self) -> None:
        self.store.count(self._day_key("people_search"))

    # ── Pausa entre vueltas ────────────────────────────────────────────────────

    def next_pause_minutes(self, idle_cycles: int) -> float:
        """Noche: 2–3 h. Día: lognormal dentro del rango (más larga si no hubo novedades), un descanso
        largo cada 3–4 vueltas y, si se agotó el presupuesto de la hora, hasta la hora siguiente."""
        if self.is_night():
            return random.uniform(*self.settings.night_pause_minutes)
        if self._long_break_due():
            self.store.counters[CYCLES_SINCE_BREAK] = 0
            return random.uniform(*LONG_BREAK_MINUTES)
        pause = min(MAX_IDLE_PAUSE_MINUTES, self._day_pause() * 2 ** min(idle_cycles, 2))
        if not self.has_page_budget():
            pause = max(pause, self._minutes_to_next_hour() + random.uniform(5, 15))
        return pause

    def _long_break_due(self) -> bool:
        cycles = self.store.count(CYCLES_SINCE_BREAK)
        low, high = LONG_BREAK_AFTER
        return cycles >= high or (cycles >= low and random.random() < 0.5)

    def _day_pause(self) -> float:
        low, high = self.settings.day_pause_minutes
        median = math.sqrt(low * high)
        return min(high, max(low, random.lognormvariate(math.log(median), PAUSE_SIGMA)))

    def _minutes_to_next_hour(self) -> float:
        now = self.now()
        next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return (next_hour - now).total_seconds() / 60

    # ── Claves ─────────────────────────────────────────────────────────────────

    def _ts(self) -> float:
        return self.now().timestamp()

    def _day_key(self, name: str) -> str:
        return f"{name}:{self.now():%Y-%m-%d}"

    def _hour_key(self, name: str) -> str:
        return f"{name}:{self.now():%Y-%m-%dT%H}"
