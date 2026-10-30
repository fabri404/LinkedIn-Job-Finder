"""recruiters.py - Sigue a recruiters IT de Argentina desde la búsqueda de personas.

Solo toca "Seguir a <nombre>" en la tarjeta del resultado: no abre perfiles, actividad ni
"Información de contacto". Abrir perfiles en serie provocó dos checkpoints el 19/10 y el del
28/10/2026 ("tu cuenta accedió a una cantidad considerable de datos de perfiles"). Nunca usa
"Conectar" ni "Enviar mensaje". Los topes por día viven en pacing.py.
"""

from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass
from urllib.parse import quote

from selenium import webdriver
from selenium.common.exceptions import InvalidSessionIdException, NoSuchWindowException, WebDriverException
from selenium.webdriver.common.by import By

from classifier import normalize_text
from feed import open_url

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.linkedin.com/search/results/people/?keywords={query}&geoUrn=%5B%22100446943%22%5D"
PROFILE_URL = "https://www.linkedin.com/in/{slug}/"
MAX_SEARCH_PAGE = 10
# Entre un follow y el siguiente, sin salir de la página de resultados.
FOLLOW_PAUSE_MINUTES = (2.0, 5.0)
# Chrome cerrado (p. ej. tras suspender la notebook): se propaga para que el loop abra otro.
DEAD_SESSION_ERRORS = (InvalidSessionIdException, NoSuchWindowException)

RECRUITER_TITLE = re.compile(
    r"recruit|reclut|talent acquisition|adquisici[oó]n de talento|talent partner|selecci[oó]n|headhunt|"
    r"sourc|rr\.?\s?hh|recursos humanos|human resources|people partner",
    re.IGNORECASE,
)
IT_TITLE = re.compile(r"\bit\b|\bti\b|tech|tecnolog|sistemas|software|developer|desarroll|digital", re.IGNORECASE)
# Link principal de cada resultado: "Rocio Gonzalez • 2º Talent Partner | IT Recruiter"
# (los demás links de la tarjeta son contactos en común, sin el "• 2º").
CARD_TEXT = re.compile(r"^(?P<name>.+?)\s*•\s*\S+\s*(?P<headline>.*)$")
PEOPLE_JS = r"""
return [...document.querySelectorAll('a[href*="/in/"]')].map(a => {
  const slug = (a.href.match(/\/in\/([^/?#]+)/) || [])[1];
  return [slug || '', (a.innerText || '').replace(/\s+/g, ' ').trim()];
}).filter(([slug, text]) => slug && text.includes('•'));
"""


@dataclass(frozen=True)
class RecruiterCard:
    slug: str
    name: str
    headline: str

    @property
    def key(self) -> str:
        return f"recruiter:{self.slug}"

    @property
    def profile_url(self) -> str:
        return PROFILE_URL.format(slug=self.slug)


def is_it_recruiter(headline: str) -> bool:
    return bool(RECRUITER_TITLE.search(headline) and IT_TITLE.search(headline))


def parse_card(slug: str, text: str) -> RecruiterCard | None:
    match = CARD_TEXT.match(normalize_text(text))
    if not match:
        return None
    return RecruiterCard(slug, match.group("name").strip(), match.group("headline").strip())


def parse_people(rows: list[list[str]]) -> list[RecruiterCard]:
    """Recruiters IT de una página de resultados, sin repetir."""
    cards: dict[str, RecruiterCard] = {}
    for slug, text in rows:
        card = parse_card(slug, text)
        if card and slug not in cards and is_it_recruiter(card.headline):
            cards[slug] = card
    return list(cards.values())


def search_recruiters(driver: webdriver.Chrome, query: str, page: int) -> list[RecruiterCard]:
    """Recruiters IT de la página `page` de resultados de `query`."""
    open_url(driver, f"{SEARCH_URL.format(query=quote(query))}&page={page}")
    time.sleep(5)
    for _ in range(3):
        driver.execute_script("window.scrollBy(0, 900)")
        time.sleep(1.5)
    cards = parse_people(driver.execute_script(PEOPLE_JS) or [])
    log.info("Recruiters '%s' (página %d): %d perfiles IT.", query, page, len(cards))
    return cards


def follow(driver: webdriver.Chrome, card: RecruiterCard) -> bool:
    """Toca "Seguir a <nombre>" en la página abierta (resultados de búsqueda). False si no hay botón
    (ya lo sigue, o la tarjeta solo ofrece "Conectar")."""
    buttons = driver.find_elements(By.CSS_SELECTOR, "button")
    target = next((b for b in buttons if (b.get_attribute("aria-label") or "").strip() == f"Seguir a {card.name}"
                   and b.is_displayed()), None)
    if target is None:
        return False
    driver.execute_script("arguments[0].click()", target)
    time.sleep(2)
    return True


def follow_pause() -> None:
    time.sleep(random.uniform(*FOLLOW_PAUSE_MINUTES) * 60)


def safe_search(driver: webdriver.Chrome, query: str, page: int) -> list[RecruiterCard]:
    try:
        return search_recruiters(driver, query, page)
    except DEAD_SESSION_ERRORS:
        raise
    except WebDriverException as exc:
        log.warning("Recruiters: falló la búsqueda '%s' (%s).", query, exc.msg)
        return []
