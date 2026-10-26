"""recruiters.py - Recruiters IT de LinkedIn: búsqueda, posts recientes, email de contacto y follow.

Solo lee perfiles y, como máximo, toca "Seguir a <nombre>". Nunca usa "Conectar" ni
"Enviar mensaje": el contacto es un borrador de Gmail que Adriel envía.
"""

from __future__ import annotations

import logging
import random
import re
import time
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote

from selenium import webdriver
from selenium.common.exceptions import InvalidSessionIdException, NoSuchWindowException, WebDriverException
from selenium.webdriver.common.by import By

from classifier import extract_emails, normalize_text, post_age_days
from feed import FeedPost, harvest_page, open_url

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.linkedin.com/search/results/people/?keywords={query}&geoUrn=%5B%22100446943%22%5D"
PROFILE_URL = "https://www.linkedin.com/in/{slug}/"
ACTIVITY_URL = "https://www.linkedin.com/in/{slug}/recent-activity/all/"
# El 2026-10-19 LinkedIn puso un "checkpoint" de seguridad ("tu cuenta accedió a una cantidad considerable
# de datos de perfiles") tras ~35 perfiles y 12 páginas de búsqueda por hora. Reactivado con margen: 3 perfiles
# por vuelta (~40 min), 12 por día y hasta 3 páginas de búsqueda por vuelta, con 1-2 min entre perfiles.
# Seguirlos además suma sus búsquedas al feed. 0 = desactivado.
MAX_PROFILES_PER_CYCLE = 3
MAX_PROFILES_PER_DAY = 12
MAX_FOLLOWS_PER_DAY = 12
# Las primeras páginas de cada búsqueda ya se visitaron: se avanza de página hasta hallar perfiles nuevos.
SEARCH_PAGES_PER_CYCLE = 3
MAX_SEARCH_PAGE = 10
QUERIES_PER_CYCLE = 1
RECENT_DAYS = 20
ACTIVITY_MINUTES = 0.75
CONTACT_TEXT = "Información de contacto"
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
MAILTO_JS = "return [...document.querySelectorAll('a[href^=\"mailto:\"]')].map(a => a.href.slice(7)).join(' ');"


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

    @property
    def first_name(self) -> str:
        return self.name.split()[0] if self.name else ""

    def owns_email(self, email: str) -> bool:
        """True si el email tiene su nombre o apellido; si no, es de otra persona o de la consultora
        (cv@, rrhh@, guadalupe.rodriguez@) y el saludo no lleva nombre."""
        local = _plain(email.split("@")[0])
        return any(len(part) >= 3 and part in local for part in _plain(self.name).split())


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()


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


def recent_posts(driver: webdriver.Chrome, card: RecruiterCard) -> list[FeedPost]:
    """Posts del recruiter de los últimos RECENT_DAYS días (sin antigüedad visible, se descarta)."""
    posts = harvest_page(driver, ACTIVITY_URL.format(slug=card.slug), ACTIVITY_MINUTES)
    recent = [p for p in posts if (age := post_age_days(p.text)) is not None and age <= RECENT_DAYS]
    log.info("  %s: %d posts, %d de los últimos %d días.", card.name, len(posts), len(recent), RECENT_DAYS)
    return recent


def follow(driver: webdriver.Chrome, card: RecruiterCard) -> bool:
    """Toca "Seguir a <nombre>" en el perfil ya abierto. False si no hay botón (ya lo sigue)."""
    buttons = driver.find_elements(By.CSS_SELECTOR, "button")
    target = next((b for b in buttons if (b.get_attribute("aria-label") or "").strip() == f"Seguir a {card.name}"
                   and b.is_displayed()), None)
    if target is None:
        return False
    driver.execute_script("arguments[0].click()", target)
    time.sleep(2)
    return True


def contact_email(driver: webdriver.Chrome) -> str | None:
    """Email de "Información de contacto" del perfil ya abierto (LinkedIn lo muestra como mailto)."""
    link = next((a for a in driver.find_elements(By.CSS_SELECTOR, "a")
                 if (a.text or "").strip() == CONTACT_TEXT), None)
    if link is None:
        return None
    driver.execute_script("arguments[0].click()", link)
    time.sleep(4)
    emails = extract_emails(driver.execute_script(MAILTO_JS) or "")
    return emails[0] if emails else None


def open_profile(driver: webdriver.Chrome, card: RecruiterCard) -> None:
    open_url(driver, card.profile_url)
    time.sleep(5)


def recruiter_pause() -> None:
    time.sleep(random.uniform(60, 120))


def safe_search(driver: webdriver.Chrome, query: str, page: int) -> list[RecruiterCard]:
    try:
        return search_recruiters(driver, query, page)
    except DEAD_SESSION_ERRORS:
        raise
    except WebDriverException as exc:
        log.warning("Recruiters: falló la búsqueda '%s' (%s).", query, exc.msg)
        return []
