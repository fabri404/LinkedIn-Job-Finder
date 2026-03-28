"""
jobs/services.py

Three consolidated service classes that replace the original scraper.py,
detector.py, and the duplicated analyze_if_job_posting in scraper.py.

  JobAnalyzer     — pure scoring/analysis logic (no Selenium, fully testable)
  DetectorService — email extraction + language detection + relevance check
  ScraperService  — Selenium orchestration: login, scroll, collect, filter
"""
from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

from django.conf import settings
from django.utils import timezone

if TYPE_CHECKING:
    from selenium.webdriver import Chrome

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Constants (previously split across detector.py and scraper.py)
# ─────────────────────────────────────────────────────────────────────────────

SPANISH_MARKERS: list[str] = [
    "busco", "buscamos", "incorporar", "sumate", "equipo", "empresa",
    "oportunidad", "laboral", "puesto", "vacante", "requisitos",
    "experiencia", "conocimientos", "desarrollador", "programador",
    "enviar", "postularse", "interesados", "contacto", "trabajo",
    "remoto", "presencial", "híbrido", "sueldo", "salario",
]

ENGLISH_MARKERS: list[str] = [
    "hiring", "looking for", "position", "role", "team", "company",
    "opportunity", "requirements", "experience", "developer", "engineer",
    "apply", "remote", "onsite", "hybrid", "salary", "job", "opening",
    "candidate", "we are", "join us", "send your",
]

EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

BLACKLIST_DOMAINS: list[str] = [
    "example.com", "test.com", "linkedin.com", "facebook.com",
    "twitter.com", "instagram.com", "google.com", "sentry.io",
]

SCORE_THRESHOLD = 3  # minimum score to mark a job as verified


# ─────────────────────────────────────────────────────────────────────────────
# JobAnalyzer — scoring logic consolidated from scraper.py + detector.py
# ─────────────────────────────────────────────────────────────────────────────

class JobAnalyzer:
    """
    Analyses raw post text and returns a score + reasons.

    This is the single authoritative implementation of analyze_if_job_posting.
    The duplicate that previously lived in scraper.py has been removed.
    """

    # ── Positive indicator lists ──────────────────────────────────────────────

    HIRING_PHRASES: list[str] = [
        "estamos buscando", "estamos en la búsqueda", "nos encontramos en búsqueda",
        "buscamos incorporar", "buscamos sumar", "sumate a", "sumate al equipo",
        "unite a", "unite al equipo", "se busca", "se requiere",
        "incorporar a nuestro equipo", "para nuestro equipo",
        "sumarse a nuestro equipo", "sumarse al equipo",
        "seguimos creciendo", "seguimos sumando",
        "we are looking for", "we're looking for", "we are hiring",
        "looking to hire", "join our team", "join us",
        "estamos buscando talento", "buscando talento",
    ]

    REQUIREMENT_HEADERS: list[str] = [
        "requisitos", "requisitos excluyentes", "requisitos deseables",
        "requirements", "what we're looking for", "perfil buscado",
        "perfil ideal", "que buscamos", "qué buscamos", "lo que buscamos",
        "skills required", "must have", "nice to have",
        "conocimientos en", "experiencia en", "experiencia con",
    ]

    APPLY_PHRASES: list[str] = [
        "enviá tu cv", "envia tu cv", "enviar cv", "enviar tu cv",
        "enviános tu cv", "envianos tu cv", "envíanos tu cv",
        "postulate", "postularse", "postularte",
        "aplicar a", "apply at", "apply to", "apply now",
        "send your cv", "send your resume", "envía tu currículum",
        "escribinos a", "contactanos a", "contactate a",
        "escríbeme por dm", "escribime por dm", "dejame tu contacto",
        "déjame tu contacto", "contacto en los comentarios",
        "escribime al", "escríbeme al",
        "mandá tu cv", "manda tu cv",
    ]

    POSITION_INDICATORS: list[str] = [
        "posiciones abiertas", "vacantes disponibles", "búsquedas abiertas",
        "posiciones disponibles", "roles abiertos", "open positions",
        "oportunidades abiertas",
    ]

    JOB_TITLES: list[str] = [
        "desarrollador", "developer", "qa", "tester", "líder técnico",
        "tech lead", "analyst", "analista", "engineer", "ingeniero",
        "devops", "fullstack", "full stack", "frontend", "backend",
        "diseñador", "designer", "data", "scrum", "project manager",
        "capacitador", "arquitecto", "dba", "sysadmin", "cloud",
        "ssr", "sr", " jr", "junior", "trainee", "semi senior", "senior",
    ]

    CONVOCATORIA_PHRASES: list[str] = [
        "convocatoria", "búsqueda laboral", "busqueda laboral",
        "oportunidad laboral", "vacante", "puesto",
    ]

    MODALITY_PHRASES: list[str] = [
        "modalidad híbrida", "modalidad remota", "modalidad presencial",
        "100% remoto", "remote position", "hybrid",
        "lunes a viernes", "jornada completa", "full time", "part time",
        "medio tiempo", "jornada parcial",
    ]

    TASK_PHRASES: list[str] = [
        "vas a hacer", "qué vas a hacer", "responsabilidades",
        "tareas", "funciones", "tu rol", "your role",
        "what you'll do", "responsibilities", "day to day",
        "principales funciones",
    ]

    BENEFIT_PHRASES: list[str] = [
        "beneficios", "ofrecemos", "we offer", "sueldo", "salario",
        "remuneración", "prepaga", "obra social", "capacitación",
        "plan de carrera",
    ]

    # ── Negative indicator lists ──────────────────────────────────────────────

    PLATFORM_NAMES: list[str] = [
        "remotive", "flexjobs", "upwork", "workana", "remote ok",
        "freelancer.com", "fiverr", "toptal", "indeed", "glassdoor",
        "computrabajo", "zonajobs", "bumeran",
    ]

    ENGAGEMENT_PHRASES: list[str] = [
        "si te resulta útil", "seguime", "hacé clic en seguir",
        "compartilo", "comparte esto", "dale like", "guardá este post",
        "te invito a seguir", "sígueme", "follow me",
        "¿cansado de", "dream team", "el mundo sea tu escritorio",
        "tip:", "tips para", "consejos para",
        "guarda este post", "save this post",
    ]

    RHETORICAL_PHRASES: list[str] = [
        "¿dónde conseguir", "¿cómo conseguir", "¿querés saber",
        "¿sabías que", "¿te gustaría", "¿cansado de",
    ]

    LIST_EMOJIS: list[str] = ["◾", "◽", "▶️", "🔗", "💡"]

    # ── Public API ────────────────────────────────────────────────────────────

    def analyze(self, text: str) -> dict:
        """
        Score a post text.

        Returns:
            {
                "is_job": bool,
                "score": int,
                "reasons": list[str],
                "emails": list[str],
                "language": str,   # "es" | "en"
            }
        """
        text_lower = text.lower()
        score = 0
        reasons: list[str] = []

        score, reasons = self._apply_positive_signals(text, text_lower, score, reasons)
        score, reasons = self._apply_negative_signals(text, text_lower, score, reasons)

        emails = DetectorService.extract_emails(text)
        language = DetectorService.detect_language(text)

        return {
            "is_job": score >= SCORE_THRESHOLD,
            "score": score,
            "reasons": reasons,
            "emails": emails,
            "language": language,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _apply_positive_signals(
        self, text: str, text_lower: str, score: int, reasons: list[str]
    ) -> tuple[int, list[str]]:
        # Hiring phrase (+3)
        for phrase in self.HIRING_PHRASES:
            if phrase in text_lower:
                score += 3
                reasons.append(f"+3 hiring phrase: '{phrase}'")
                break

        # Requirements section (+3)
        for header in self.REQUIREMENT_HEADERS:
            if header in text_lower:
                score += 3
                reasons.append(f"+3 requirements section: '{header}'")
                break

        # Application phrase (+3)
        for phrase in self.APPLY_PHRASES:
            if phrase in text_lower:
                score += 3
                reasons.append(f"+3 application phrase: '{phrase}'")
                break

        # Real email present (+2)
        raw = EMAIL_PATTERN.findall(text)
        real_emails = [
            e for e in raw
            if not any(d in e.lower() for d in BLACKLIST_DOMAINS)
        ]
        if real_emails:
            score += 2
            reasons.append(f"+2 contact email: {real_emails[0]}")

        # Position list (+3)
        for phrase in self.POSITION_INDICATORS:
            if phrase in text_lower:
                score += 3
                reasons.append(f"+3 position list: '{phrase}'")
                break

        # Multiple job titles (+2)
        title_matches = sum(1 for t in self.JOB_TITLES if t in text_lower)
        if title_matches >= 3:
            score += 2
            reasons.append(f"+2 multiple job titles ({title_matches})")

        # Convocatoria word (+2)
        for phrase in self.CONVOCATORIA_PHRASES:
            if phrase in text_lower:
                score += 2
                reasons.append(f"+2 convocatoria: '{phrase}'")
                break

        # Work modality (+2)
        if any(p in text_lower for p in self.MODALITY_PHRASES):
            score += 2
            reasons.append("+2 work modality mentioned")

        # Task description (+2)
        for phrase in self.TASK_PHRASES:
            if phrase in text_lower:
                score += 2
                reasons.append(f"+2 describes tasks: '{phrase}'")
                break

        # Benefits / salary (+1)
        for phrase in self.BENEFIT_PHRASES:
            if phrase in text_lower:
                score += 1
                reasons.append(f"+1 benefits/salary: '{phrase}'")
                break

        return score, reasons

    def _apply_negative_signals(
        self, text: str, text_lower: str, score: int, reasons: list[str]
    ) -> tuple[int, list[str]]:
        # Multiple platform names (-4)
        platform_count = sum(1 for p in self.PLATFORM_NAMES if p in text_lower)
        if platform_count >= 2:
            score -= 4
            reasons.append(f"-4 platform list ({platform_count} platforms)")

        # Many external links — only penalise if not a real position list (-3)
        url_count = len(re.findall(r"https?://\S+", text))
        has_position_list = any(p in text_lower for p in self.POSITION_INDICATORS)
        has_shorturl = "shorturl" in text_lower or "lnkd.in" in text_lower
        if url_count >= 3 and not has_position_list and not has_shorturl:
            score -= 3
            reasons.append(f"-3 many external links ({url_count})")

        # Engagement phrases (-2 each)
        engagement_count = sum(1 for p in self.ENGAGEMENT_PHRASES if p in text_lower)
        if engagement_count >= 1:
            score -= 2 * engagement_count
            reasons.append(f"-{2 * engagement_count} engagement phrases ({engagement_count})")

        # Rhetorical question (-2)
        for phrase in self.RHETORICAL_PHRASES:
            if phrase in text_lower:
                score -= 2
                reasons.append(f"-2 rhetorical question: '{phrase}'")
                break

        # Excessive decorative emojis (-2)
        emoji_count = sum(text.count(e) for e in self.LIST_EMOJIS)
        if emoji_count >= 5:
            score -= 2
            reasons.append(f"-2 excessive decorative emojis ({emoji_count})")

        return score, reasons


# ─────────────────────────────────────────────────────────────────────────────
# DetectorService — email extraction + language detection
# (consolidates detector.py)
# ─────────────────────────────────────────────────────────────────────────────

class DetectorService:
    """Stateless helpers for email extraction and language detection."""

    @staticmethod
    def extract_emails(text: str) -> list[str]:
        """Extract valid recruiter emails from text, filtering blacklisted domains."""
        raw_emails = EMAIL_PATTERN.findall(text)
        valid: list[str] = []
        for email in raw_emails:
            email = email.lower().strip().rstrip(".")
            domain = email.split("@")[1] if "@" in email else ""
            if domain and domain not in BLACKLIST_DOMAINS:
                valid.append(email)
        return list(set(valid))

    @staticmethod
    def detect_language(text: str) -> str:
        """Return 'es' or 'en' based on marker counts. Defaults to 'es'."""
        text_lower = text.lower()
        es_score = sum(1 for word in SPANISH_MARKERS if word in text_lower)
        en_score = sum(1 for word in ENGLISH_MARKERS if word in text_lower)
        return "en" if en_score > es_score else "es"

    @staticmethod
    def is_relevant(text: str, keywords: list[str], min_matches: int = 1) -> bool:
        """True if text contains at least min_matches keywords (word-boundary aware)."""
        if not keywords:
            return False
        text_lower = text.lower()
        matches = sum(
            1 for kw in keywords
            if re.search(rf"\b{re.escape(kw)}\b", text_lower)
        )
        return matches >= min_matches


# ─────────────────────────────────────────────────────────────────────────────
# ScraperService — Selenium orchestration (migrated from scraper.py)
# ─────────────────────────────────────────────────────────────────────────────

class ScraperService:
    """
    Manages the full scraping pipeline.

    Two modes:
      - "jobs" (default): keyword → LinkedIn Jobs Search → collect job cards
      - "feed" (legacy):  login → scroll feed → collect posts → keyword filter

    Operates on a SearchSession model instance so progress is persisted.
    """

    def __init__(self, session_id: int) -> None:
        from apps.jobs.models import SearchSession
        self.session = SearchSession.objects.get(pk=session_id)
        self.analyzer = JobAnalyzer()

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self) -> None:
        """Execute the full pipeline and update the session record."""
        from apps.jobs.models import SearchSession

        self.session.status = SearchSession.Status.RUNNING
        self.session.save(update_fields=["status"])

        try:
            keywords = self._load_keywords()

            self.session.search_keywords = ", ".join(keywords)
            self.session.save(update_fields=["search_keywords"])

            driver = self._create_driver()
            try:
                if not self._login(driver):
                    raise RuntimeError("LinkedIn login failed.")

                if self.session.search_mode == "jobs":
                    self._run_jobs_search(driver, keywords)
                else:
                    self._run_feed_scan(driver, keywords)

                self.session.status = SearchSession.Status.COMPLETED

            finally:
                driver.quit()
                if hasattr(self, '_display'):
                    self._display.stop()

        except Exception:
            self.session.status = SearchSession.Status.FAILED
            raise

        finally:
            self.session.finished_at = timezone.now()
            self.session.save(update_fields=[
                "status", "finished_at", "total_found", "total_verified",
                "search_keywords",
            ])

    # ── Jobs Search mode (NEW — primary) ─────────────────────────────────────

    def _run_jobs_search(self, driver: "Chrome", keywords: list[str]) -> None:
        """Navigate to LinkedIn Jobs Search for each keyword and collect job cards."""
        import random

        seen_urls = self._get_seen_urls()
        unique_jobs: dict[str, dict] = {}
        max_pages = 3

        for keyword in keywords:
            logger.info("[ScraperService] Buscando keyword: '%s'", keyword)
            for page in range(max_pages):
                start = page * 25
                url = self.build_search_url(keyword, start=start)
                logger.info("[ScraperService] Navegando a: %s", url)

                driver.get(url)
                time.sleep(random.uniform(3, 5))

                self._scroll_job_results(driver)

                cards = self._collect_job_cards(driver)
                logger.info(
                    "[ScraperService] keyword='%s' page=%d cards=%d",
                    keyword, page + 1, len(cards),
                )

                for card in cards:
                    card["search_keyword"] = keyword
                    card_url = card.get("url", "")
                    if card_url and card_url not in seen_urls and card_url not in unique_jobs:
                        unique_jobs[card_url] = card

                if len(cards) < 5:
                    break

                time.sleep(random.uniform(2, 4))

        logger.info("[ScraperService] Total jobs únicos encontrados: %d", len(unique_jobs))

        self.session.total_found = len(unique_jobs)
        verified_count = 0

        for post in unique_jobs.values():
            text = post.get("text", "")
            analysis = self.analyzer.analyze(text)
            self._save_job(post, analysis)
            if analysis["is_job"]:
                verified_count += 1

        self.session.total_verified = verified_count

    # ── Feed Scan mode (LEGACY — fallback) ───────────────────────────────────

    def _run_feed_scan(self, driver: "Chrome", keywords: list[str]) -> None:
        """Legacy mode: scroll the general feed and post-filter by keywords."""
        min_matches = getattr(settings, "MIN_KEYWORDS_MATCH", 1)

        self._refresh_feed(driver)
        self._scroll_feed(driver, self.session.scroll_duration)
        self._expand_posts(driver)

        raw_posts = self._collect_posts(driver)
        logger.info("[ScraperService] Feed posts colectados: %d", len(raw_posts))

        seen_urls = self._get_seen_urls()
        new_posts = [p for p in raw_posts if p["url"] not in seen_urls]
        logger.info("[ScraperService] Posts nuevos: %d", len(new_posts))

        relevant = [
            p for p in new_posts
            if DetectorService.is_relevant(p["text"], keywords, min_matches)
        ]
        logger.info("[ScraperService] Posts relevantes: %d", len(relevant))

        self.session.total_found = len(relevant)
        verified_count = 0

        for post in relevant:
            analysis = self.analyzer.analyze(post["text"])
            self._save_job(post, analysis)
            if analysis["is_job"]:
                verified_count += 1

        self.session.total_verified = verified_count

    # ── URL building ─────────────────────────────────────────────────────────

    @staticmethod
    def build_search_url(keyword: str, start: int = 0) -> str:
        """Build a LinkedIn Jobs Search URL (remote, last week)."""
        from urllib.parse import quote_plus
        kw_encoded = quote_plus(keyword)
        return (
            f"https://www.linkedin.com/jobs/search/"
            f"?keywords={kw_encoded}&f_WT=2&f_TPR=r604800&start={start}"
        )

    # ── Jobs Search helpers ──────────────────────────────────────────────────

    def _scroll_job_results(self, driver: "Chrome") -> None:
        """Scroll down job search results to load more cards."""
        for _ in range(5):
            driver.execute_script("window.scrollBy(0, 600);")
            time.sleep(1)

    def _collect_job_cards(self, driver: "Chrome") -> list[dict]:
        """Extract structured job data from LinkedIn Jobs search results page."""
        cards_data = driver.execute_script("""
            const results = [];
            const seenUrls = new Set();

            // Strategy 1: job card containers (LinkedIn Jobs page)
            const selectors = [
                '.job-card-container',
                '.jobs-search-results__list-item',
                'li[class*="jobs-search"]',
                '[data-occludable-job-id]',
            ];

            let cards = [];
            for (const sel of selectors) {
                cards = document.querySelectorAll(sel);
                if (cards.length > 0) break;
            }

            cards.forEach(card => {
                // Extract URL
                const linkEl = card.querySelector('a[href*="/jobs/view/"]');
                if (!linkEl) return;
                const url = (linkEl.href || '').split('?')[0];
                if (!url || seenUrls.has(url)) return;
                seenUrls.add(url);

                // Extract title
                const titleEl = card.querySelector(
                    'a[class*="job-card-list__title"], ' +
                    '[class*="job-card-list__title"], ' +
                    'a[class*="job-card-container__link"]'
                );
                const title = (titleEl ? titleEl.innerText : linkEl.innerText || '').trim();

                // Extract company
                const companyEl = card.querySelector(
                    '[class*="job-card-container__primary-description"], ' +
                    '[class*="job-card-container__company"], ' +
                    '[class*="artdeco-entity-lockup__subtitle"]'
                );
                const company = companyEl ? companyEl.innerText.trim() : '';

                // Extract location
                const locationEl = card.querySelector(
                    '[class*="job-card-container__metadata-item"], ' +
                    '[class*="job-card-container__metadata-wrapper"], ' +
                    '[class*="artdeco-entity-lockup__caption"]'
                );
                const location = locationEl ? locationEl.innerText.trim() : '';

                // Full text from card
                const text = (card.innerText || '').trim();

                results.push({ url, title, company, location, text });
            });

            // Strategy 2: fallback — find all links to /jobs/view/
            if (results.length === 0) {
                const jobLinks = document.querySelectorAll('a[href*="/jobs/view/"]');
                jobLinks.forEach(link => {
                    const url = (link.href || '').split('?')[0];
                    if (!url || seenUrls.has(url)) return;
                    seenUrls.add(url);

                    // Walk up to find a container
                    let container = link.parentElement;
                    for (let i = 0; i < 8 && container; i++) {
                        const text = (container.innerText || '').trim();
                        if (text.length > 50) {
                            const title = (link.innerText || '').trim();
                            results.push({ url, title, company: '', location: '', text });
                            break;
                        }
                        container = container.parentElement;
                    }
                });
            }

            return results;
        """)
        return cards_data or []

    # ── Private helpers ───────────────────────────────────────────────────────

    def _load_keywords(self) -> list[str]:
        from apps.keywords.models import Keyword
        return list(
            Keyword.objects.filter(is_active=True).values_list("word", flat=True)
        )

    def _get_seen_urls(self) -> set[str]:
        from apps.jobs.models import Job
        return set(Job.objects.values_list("url", flat=True))

    def _save_job(self, post: dict, analysis: dict) -> None:
        from apps.jobs.models import Job
        Job.objects.get_or_create(
            url=post["url"],
            defaults={
                "session": self.session,
                "title": post.get("title", "")[:300],
                "company": post.get("company", "")[:200],
                "location": post.get("location", "")[:200],
                "search_keyword": post.get("search_keyword", "")[:100],
                "text_preview": post.get("text", "")[:2000],
                "score": analysis["score"],
                "is_verified": analysis["is_job"],
                "emails_extracted": analysis["emails"],
            },
        )

    def _create_driver(self) -> "Chrome":
        import os
        from pyvirtualdisplay import Display
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service

        # Display virtual para que Chrome corra sin headless (igual que el scraper original)
        display = Display(visible=False, size=(1920, 1080))
        display.start()
        self._display = display

        options = Options()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-extensions")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        chrome_bin = os.environ.get("CHROME_BIN", "/usr/bin/chromium")
        chromedriver_path = os.environ.get("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")
        options.binary_location = chrome_bin

        driver = webdriver.Chrome(
            service=Service(chromedriver_path),
            options=options,
        )
        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        return driver

    def _login(self, driver: "Chrome") -> bool:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        logger.info("[*] Iniciando sesión en LinkedIn...")
        driver.get("https://www.linkedin.com/login")
        time.sleep(3)
        try:
            user_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "username"))
            )
            user_input.clear()
            user_input.send_keys(settings.LINKEDIN_USER)

            pass_input = driver.find_element(By.ID, "password")
            pass_input.clear()
            pass_input.send_keys(settings.LINKEDIN_PASS)

            driver.find_element(By.XPATH, '//button[@type="submit"]').click()
            time.sleep(5)

            # Si LinkedIn pide verificación, esperar hasta que el usuario la complete
            if "checkpoint" in driver.current_url or "challenge" in driver.current_url:
                logger.warning("[!] LinkedIn pide verificación. Completá el captcha en el navegador.")
                # Esperar hasta 3 minutos a que pase la verificación
                for _ in range(36):
                    time.sleep(5)
                    if "feed" in driver.current_url:
                        break

            if "feed" in driver.current_url:
                logger.info("[OK] Login exitoso.")
                return True
            else:
                logger.warning("[WARN] URL actual tras login: %s", driver.current_url)
                return False

        except Exception as e:
            logger.error("[ERROR] Login falló: %s", e)
            return False

    def _refresh_feed(self, driver: "Chrome") -> None:
        driver.get("https://www.linkedin.com/feed/")
        time.sleep(3)
        driver.refresh()
        time.sleep(4)

    def _expand_posts(self, driver: "Chrome") -> None:
        driver.execute_script("""
            document.querySelectorAll('button').forEach(btn => {
                const text = (btn.innerText || '').toLowerCase();
                if (text.includes('ver más') || text.includes('see more') || text.includes('…más')) {
                    try { btn.click(); } catch(e) {}
                }
            });
        """)
        time.sleep(1)

    def _scroll_feed(self, driver: "Chrome", duration: int) -> None:
        """
        Scrollea el feed paso a paso (viewport por viewport) para que los
        intersection observers de LinkedIn carguen los posts al entrar al
        viewport. Saltar directo al final del documento no los activa, lo que
        resulta en muy pocos posts en modo headless.
        """
        end_time = time.time() + duration
        viewport_h = driver.execute_script("return window.innerHeight") or 900
        scroll_step = int(viewport_h * 0.8)   # avanzar 80% del viewport por paso
        current_pos = 0

        while time.time() < end_time:
            current_pos += scroll_step
            driver.execute_script(f"window.scrollTo({{top: {current_pos}, behavior: 'smooth'}});")
            time.sleep(1.5)

            # Si llegamos al final, hacer una pausa larga y reiniciar para que
            # LinkedIn cargue más contenido
            page_h = driver.execute_script("return document.body.scrollHeight")
            if current_pos >= page_h - viewport_h:
                time.sleep(3)
                current_pos = 0  # volver arriba para re-recorrer el nuevo contenido

    def _collect_posts(self, driver: "Chrome") -> list[dict]:
        posts_data = driver.execute_script("""
            const results = [];
            const seenUrls = new Set();

            // Strategy 1: find all links pointing to LinkedIn activities/posts
            const postLinks = document.querySelectorAll(
                'a[href*="/feed/update/"], a[href*="/posts/"]'
            );

            postLinks.forEach(link => {
                const url = (link.href || '').split('?')[0];
                if (!url || seenUrls.has(url)) return;

                // Walk up to find the post container (has the full post text)
                let container = link.parentElement;
                for (let i = 0; i < 10 && container; i++) {
                    const text = (container.innerText || '').trim();
                    if (text.length > 150) {
                        seenUrls.add(url);
                        results.push({ url, text });
                        break;
                    }
                    container = container.parentElement;
                }
            });

            // Strategy 2: fallback — any element with data-urn containing activity
            if (results.length === 0) {
                document.querySelectorAll('[data-urn]').forEach(el => {
                    const urn = el.getAttribute('data-urn') || '';
                    if (!urn.includes('activity')) return;
                    const activityId = urn.split(':').pop();
                    if (!activityId) return;
                    const url = 'https://www.linkedin.com/feed/update/urn:li:activity:' + activityId;
                    if (seenUrls.has(url)) return;
                    const text = (el.innerText || '').trim();
                    if (text.length > 150) {
                        seenUrls.add(url);
                        results.push({ url, text });
                    }
                });
            }

            return results;
        """)
        return posts_data or []
