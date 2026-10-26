#!/usr/bin/env python3
"""main.py - LinkedIn Job Finder v3.

Loop 24/7: F5 al feed y a los canales → filtro → borrador en Gmail con el CV adjunto.
Los borradores los revisa y envía el usuario.

Uso:
    python3 main.py              # loop continuo, crea borradores en Gmail
    python3 main.py --once       # una sola vuelta
    python3 main.py --dry-run    # solo registra los mails en el log (estado aparte)
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import random
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

import urllib3

from selenium import webdriver
from selenium.common.exceptions import WebDriverException

from classifier import (
    JobPosting,
    evaluate_job,
    evaluate_post,
    evaluate_vacancy,
    is_dev_title,
    is_profile_title,
    post_author,
)
from composer import URL_PATTERN, Application, Outreach, compose, compose_outreach, linkedin_message, select_cv
from config import (
    BASE_DIR,
    RunSettings,
    Settings,
    load_channels,
    load_keywords,
    load_settings,
    validate_mail_settings,
)
from easy_apply import ApplyResult, EasyApplyFiller, safe_apply
from feed import FeedPost, create_driver, safe_harvest, wait_for_login
from jobs import FETCH_ERRORS as JOB_FETCH_ERRORS
from jobs import (
    COOLDOWN_AFTER_429_S,
    MAX_DETAILS_PER_CYCLE,
    JobCard,
    detail_pause,
    fetch_description,
    is_rate_limited,
    polite_pause,
    queries_for_cycle,
    search_cards,
    searches_for_cycle,
)
from mailer import AuthError, GmailDraftWriter, MailError, wait_for_gmail_login
from recruiters import QUERIES_PER_CYCLE as RECRUITER_QUERIES_PER_CYCLE
from recruiters import (
    DEAD_SESSION_ERRORS,
    MAX_FOLLOWS_PER_DAY,
    MAX_PROFILES_PER_DAY,
    MAX_SEARCH_PAGE,
    SEARCH_PAGES_PER_CYCLE,
    MAX_PROFILES_PER_CYCLE,
    RecruiterCard,
    contact_email,
    follow,
    open_profile,
    recent_posts,
    recruiter_pause,
    safe_search,
)
from relevance import relevance_score
from sources import plan_sources
from store import VETO_FILE, QueuedApplication, Store, normalize_role

log = logging.getLogger("job_finder")
# Una línea por post evaluado: va a data/audit.log para que job_finder.log (el que lee el
# dashboard) quede corto y legible.
audit = logging.getLogger("job_finder.audit")
LOG_MAX_BYTES = 2_000_000
LOG_BACKUPS = 3
# Sin nada nuevo en la vuelta, la pausa se duplica hasta este tope; con algo nuevo vuelve a la base.
MAX_PAUSE_MINUTES = 60
PREVIOUS_CONTACTS_FILE = BASE_DIR / "contactados_previos.txt"
CHECKPOINT_PATH = "/checkpoint/"
CURSOR_KEY = "source_cursor"
ROTATION_KEY = "source_rotation"

Sender = Callable[[Application], None]
SenderFactory = Callable[[webdriver.Chrome], Sender]
Applier = Callable[[str, str], ApplyResult]
ApplierFactory = Callable[[webdriver.Chrome | None], Applier]


def _no_easy_apply(_driver: webdriver.Chrome | None) -> Applier:
    return lambda _url, _cv: ApplyResult("dry-run: sin solicitud sencilla")


def easy_apply_factory(ctx: LoopContext) -> ApplierFactory:
    """Solicitud sencilla que se envía sola mientras no se llegue a EASY_APPLY_DAILY_LIMIT en el día."""
    limit = ctx.settings.run.easy_apply_daily_limit

    def may_submit() -> bool:
        return ctx.store.easy_applies_on(date.today()) < limit

    def factory(driver: webdriver.Chrome | None) -> Applier:
        filler = EasyApplyFiller(driver, may_submit)
        return lambda url, cv_path: safe_apply(filler, url, cv_path)

    return factory


class LoopContext:
    def __init__(self, settings: Settings, store: Store, make_sender: SenderFactory) -> None:
        self.settings = settings
        self.store = store
        self.make_sender = make_sender
        self.make_applier: ApplierFactory = _no_easy_apply
        self.applier: Applier = _no_easy_apply(None)
        self.keywords = load_keywords(settings.keywords_file)
        self.channels = load_channels(settings.channels_file)
        self.job_queries = load_channels(settings.job_queries_file)
        self.job_cycle = 0
        self.jobs_paused_until = 0.0
        self.current_source = 0
        self.recruiter_queries = load_channels(settings.recruiter_queries_file)
        self.recruiter_cycle = 0
        self.follows: dict[str, int] = {}
        self.allow_follow = True
        self.gmail_checked = False
        self.found_last_cycle = 0
        self.idle_cycles = 0


def _rotating_handler(path: Path) -> logging.Handler:
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    return handler


def setup_logging(settings: Settings) -> None:
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), _rotating_handler(settings.state_dir / "job_finder.log")],
    )
    audit.propagate = False
    audit.addHandler(_rotating_handler(settings.state_dir / "audit.log"))


def _preview(text: str) -> str:
    return " ".join(text.split())[:90]


def enqueue_new_posts(posts: list[FeedPost], ctx: LoopContext) -> int:
    queued = 0
    for post in posts:
        if ctx.store.is_seen(post.key):
            continue
        ctx.store.mark_seen(post.key)
        verdict, posting = evaluate_post(post.text, ctx.keywords)
        audit.info("%s %s | %s", "APTO" if verdict.accepted else "desc", verdict.reason, _preview(post.text))
        if posting is None:
            continue
        if not verdict.accepted:
            _record_post_lead(post, posting, ctx)
            continue
        audit.info("  texto: %s", " ".join(post.text.split())[:800])  # para auditar falsos aptos
        queued += _enqueue_posting(posting, post.url or post.author_url, ctx)
    ctx.store.save()
    return queued


def _record_post_lead(post: FeedPost, posting: JobPosting, ctx: LoopContext) -> None:
    """Vacante acorde sin email: queda en la lista para escribirle a quien la publicó por LinkedIn.

    Solo con un puesto IT reconocible (las páginas agregadoras y los posts de opinión no lo tienen)
    y una vez por autor y puesto: los recruiters publican el mismo aviso en varios grupos."""
    author = post_author(post.text)
    lead_key = f"lead:{normalize_role(author)}:{normalize_role(posting.role_title)}"
    if not is_dev_title(posting.role_title) or ctx.store.is_seen(lead_key):
        audit.info("  contacto por LinkedIn omitido (sin puesto IT claro o repetido): %s", author)
        return
    ctx.store.mark_seen(lead_key)
    links = " ".join(dict.fromkeys(URL_PATTERN.findall(post.text)))
    first_name = author.split()[0] if author else ""
    ctx.store.record_lead((date.today().isoformat(), author, post.author_url, posting.role_title, post.url, links,
                           linkedin_message(first_name, posting)))
    log.info("LINKEDIN → %s | %s | %s", author or "?", posting.role_title, post.author_url or post.url)


def _enqueue_posting(posting: JobPosting, post_url: str, ctx: LoopContext) -> int:
    queued = 0
    score = relevance_score(posting)
    for email in posting.emails:
        if ctx.store.is_known_recipient(email, posting.role_title):
            log.info("  ya contactado: %s", email)
            continue
        app = compose(posting, email, ctx.settings.mail.cv_dir)
        ctx.store.enqueue(QueuedApplication(app, post_url, score))
        log.info("  en cola (relevancia %d): %s | %s", score, email, posting.role_title)
        queued += 1
    return queued


def drain_queue(store: Store, run: RunSettings, sender: Sender) -> int:
    """Envía la cola respetando el cupo diario. AuthError se propaga y frena el loop."""
    sent = 0
    while store.pending:
        if store.sent_on(date.today()) >= run.daily_send_limit:
            log.warning("Cupo diario (%d) alcanzado; %d en cola.", run.daily_send_limit, len(store.pending))
            break
        item = store.pending[0]
        if store.is_vetoed(item.app.to):
            log.info("Descartado a mano (data/%s): %s", VETO_FILE, item.app.to)
            store.discard_first("descartado a mano")
            continue
        try:
            sender(item.app)
        except AuthError:
            raise
        except MailError as exc:
            log.error("No se envió a %s: %s", item.app.to, exc)
            if not exc.permanent:
                break
            store.drop_first()
            continue
        store.complete_first(datetime.now())
        sent += 1
        log.info("BORRADOR → %s | %s | %s", item.app.to, item.app.subject, item.app.cv_path.name)
        if store.pending:
            time.sleep(random.uniform(run.send_delay_min_s, run.send_delay_max_s))
    return sent


def harvest_sources(driver: webdriver.Chrome, ctx: LoopContext, drain: Callable[[], int]) -> tuple[int, int, int]:
    """Recorre las fuentes de la vuelta (`plan_sources`); devuelve (posts leídos, nuevos en cola, borradores).

    Lo encolado en cada fuente pasa a Gmail enseguida (`drain`). La fuente por la que va la vuelta
    queda en el estado: un cuelgue o un reinicio retoman desde ahí en vez de volver a empezar.
    """
    progress = ctx.store.progress
    sources = plan_sources(ctx.channels, ctx.settings.run, progress.get(ROTATION_KEY, 0))
    read = queued = sent = 0
    for index in sources_from_cursor(len(sources), progress.get(CURSOR_KEY, 0)):
        ctx.current_source = index
        posts = safe_harvest(driver, sources[index], ctx.store.is_seen)
        read += len(posts)
        progress[CURSOR_KEY] = index + 1
        new = enqueue_new_posts(posts, ctx)
        queued += new
        if new:
            sent += drain()
    progress[CURSOR_KEY] = 0
    progress[ROTATION_KEY] = progress.get(ROTATION_KEY, 0) + 1
    return read, queued, sent


def sources_from_cursor(count: int, cursor: int) -> list[int]:
    """Índices de las fuentes empezando por `cursor`: tras un cuelgue se retoma desde la
    fuente siguiente, para que una página que siempre cuelga Chrome no frene a las demás."""
    start = cursor % count if count else 0
    return list(range(start, count)) + list(range(start))


def pause_jobs_if_rate_limited(exc: Exception, ctx: LoopContext, what: str) -> None:
    """Un 429 de LinkedIn pausa la sección Empleos una hora; otro error solo corta esta vuelta."""
    if is_rate_limited(exc):
        ctx.jobs_paused_until = time.time() + COOLDOWN_AFTER_429_S
        resume = datetime.fromtimestamp(ctx.jobs_paused_until).strftime("%H:%M")
        log.warning("Empleos: LinkedIn limitó los pedidos (%s); retomo a las %s.", what, resume)
        return
    log.warning("Empleos: falló %s (%s); sigo en la próxima vuelta.", what, exc)


def new_job_cards(ctx: LoopContext) -> list[JobCard]:
    """Avisos de la sección Empleos que todavía no se evaluaron, sin repetir entre búsquedas."""
    cards: dict[str, JobCard] = {}
    searches = searches_for_cycle(ctx.job_queries, ctx.job_cycle)
    ctx.job_cycle += 1
    for query, scope in searches:
        try:
            found = search_cards(query, scope)
        except JOB_FETCH_ERRORS as exc:
            pause_jobs_if_rate_limited(exc, ctx, f"la búsqueda '{query}' ({scope.label})")
            break
        cards.update((c.job_id, c) for c in found if not ctx.store.is_seen(c.key))
        polite_pause()
    return list(cards.values())


def process_job_card(card: JobCard, ctx: LoopContext) -> int:
    """Evalúa un aviso: con email va a la cola de borradores; sin email, a la lista manual."""
    description = fetch_description(card)
    ctx.store.mark_seen(card.key)
    verdict, posting = evaluate_job(card.title, f"{card.title}\n{card.company}\n{card.location}\n{description}")
    audit.info("%s empleo %s | %s | %s", "APTO" if posting else "desc", verdict.reason, card.title, card.company)
    if posting is None:
        return 0
    if posting.emails:
        return _enqueue_posting(posting, card.url, ctx)
    cv_path = select_cv(ctx.settings.mail.cv_dir, posting.track, posting.language)
    result = ctx.applier(card.url, str(cv_path))
    ctx.store.record_manual_job((datetime.now().isoformat(timespec="seconds"), card.title, card.company,
                                 card.location, card.url, result.status, "; ".join(result.missing)))
    log.info("EMPLEO → %s | %s | %s | %s", card.title, card.company, result.status, card.url)
    return 1


def _evaluate_job_cards(cards: list[JobCard], ctx: LoopContext) -> int:
    """Descarta por título sin pedir nada; lee hasta MAX_DETAILS_PER_CYCLE descripciones."""
    found = details = 0
    for card in cards:
        if not is_profile_title(card.title):
            audit.info("desc empleo título fuera del perfil | %s | %s", card.title, card.company)
            ctx.store.mark_seen(card.key)
            continue
        if details == MAX_DETAILS_PER_CYCLE:
            break  # el resto queda sin marcar como visto: se lee en la próxima vuelta
        details += 1
        try:
            found += process_job_card(card, ctx)
        except JOB_FETCH_ERRORS as exc:
            pause_jobs_if_rate_limited(exc, ctx, card.url)
            break
        detail_pause()
    return found


def harvest_job_listings(ctx: LoopContext) -> int:
    """Sección Empleos de LinkedIn (HTTP, sin Chrome). Devuelve las postulaciones nuevas."""
    if time.time() < ctx.jobs_paused_until:
        return 0
    found = _evaluate_job_cards(new_job_cards(ctx), ctx)
    ctx.store.save()
    return found


def new_recruiters(driver: webdriver.Chrome, ctx: LoopContext) -> list[RecruiterCard]:
    """Recruiters IT de las búsquedas de esta vuelta que todavía no se visitaron."""
    budget = min(MAX_PROFILES_PER_CYCLE, MAX_PROFILES_PER_DAY - ctx.store.visits_on(date.today()))
    if budget <= 0:
        return []
    queries = queries_for_cycle(ctx.recruiter_queries, ctx.recruiter_cycle, RECRUITER_QUERIES_PER_CYCLE)
    ctx.recruiter_cycle += 1
    cards: dict[str, RecruiterCard] = {}
    for query in queries:
        cards.update(_unseen_recruiters(driver, query, ctx, budget - len(cards)))
    return list(cards.values())[:budget]


def _unseen_recruiters(driver: webdriver.Chrome, query: str, ctx: LoopContext, budget: int) -> dict[str, RecruiterCard]:
    """Hasta `budget` recruiters sin visitar de `query`. Avanza de página (guardada en el estado) cuando
    la actual queda toda visitada; al final de los resultados vuelve a la primera."""
    unseen: dict[str, RecruiterCard] = {}
    for _ in range(SEARCH_PAGES_PER_CYCLE):
        page = ctx.store.search_pages.get(query, 1)
        cards = safe_search(driver, query, page)
        unseen.update((c.slug, c) for c in cards if not ctx.store.is_seen(c.key))
        if len(unseen) > budget:
            break
        ctx.store.search_pages[query] = page + 1 if cards and page < MAX_SEARCH_PAGE else 1
        if len(unseen) == budget or ctx.store.search_pages[query] == 1:
            break
    return unseen


def _first_vacancy(posts: list[FeedPost], ctx: LoopContext) -> tuple[FeedPost, JobPosting] | None:
    return next(((post, vacancy) for post in posts if (vacancy := evaluate_vacancy(post.text, ctx.keywords))),
                None)


def _record_linkedin_lead(card: RecruiterCard, found: tuple[FeedPost, JobPosting], ctx: LoopContext) -> None:
    """Vacante acorde sin email del recruiter: queda para escribirle por LinkedIn o usar su link."""
    post, vacancy = found
    links = " ".join(dict.fromkeys(URL_PATTERN.findall(post.text)))
    ctx.store.record_lead((date.today().isoformat(), card.name, card.profile_url, vacancy.role_title, post.url,
                           links, linkedin_message(card.first_name, vacancy)))
    log.info("LINKEDIN → %s | %s | %s", card.name, vacancy.role_title, card.profile_url)


def _follow_if_allowed(driver: webdriver.Chrome, card: RecruiterCard, ctx: LoopContext) -> None:
    today = date.today().isoformat()
    if not ctx.allow_follow or ctx.follows.get(today, 0) >= MAX_FOLLOWS_PER_DAY:
        return
    if follow(driver, card):
        ctx.follows[today] = ctx.follows.get(today, 0) + 1
        log.info("  Siguiendo a %s.", card.name)


def process_recruiter(driver: webdriver.Chrome, card: RecruiterCard, ctx: LoopContext) -> int:
    """Sus búsquedas recientes con email van como postulación; después se lo sigue y, si el perfil
    muestra email, queda un borrador "téngame en cuenta" (con la vacante acorde si publicó una)."""
    ctx.store.count_visit(date.today())
    posts = recent_posts(driver, card)
    queued = enqueue_new_posts(posts, ctx)
    found = _first_vacancy(posts, ctx)
    vacancy = found[1] if found else None
    open_profile(driver, card)
    _follow_if_allowed(driver, card, ctx)
    email = contact_email(driver)
    ctx.store.mark_seen(card.key)
    ctx.store.save()
    if email is None or ctx.store.is_known_recipient(email):
        if found and not queued:
            _record_linkedin_lead(card, found, ctx)
        return queued
    language = vacancy.language if vacancy else "es"
    first_name = card.first_name if card.owns_email(email) else ""
    app = compose_outreach(Outreach(email, first_name, language, vacancy), ctx.settings.mail.cv_dir)
    ctx.store.enqueue(QueuedApplication(app, card.profile_url))
    ctx.store.save()
    log.info("RECRUITER → %s | %s | %s | %s", card.name, email, app.subject,
             "con vacante" if vacancy else "sin vacante reciente")
    return queued + 1


def stop_if_checkpoint(driver: webdriver.Chrome, ctx: LoopContext) -> None:
    """LinkedIn pidió verificación de seguridad: se frena todo; la resuelve Adriel a mano."""
    if CHECKPOINT_PATH not in driver.current_url:
        return
    ctx.store.save()
    log.error("LinkedIn pidió verificación de seguridad (checkpoint); freno el loop.")
    raise SystemExit(2)


def harvest_recruiters(driver: webdriver.Chrome, ctx: LoopContext) -> int:
    """Visita hasta MAX_PROFILES_PER_CYCLE recruiters nuevos; devuelve los borradores encolados."""
    queued = 0
    for card in new_recruiters(driver, ctx):
        try:
            queued += process_recruiter(driver, card, ctx)
        except DEAD_SESSION_ERRORS:
            raise
        except WebDriverException as exc:
            log.warning("Recruiters: falló %s (%s).", card.profile_url, exc.msg)
            ctx.store.mark_seen(card.key)
        stop_if_checkpoint(driver, ctx)
        recruiter_pause()
    ctx.store.save()
    return queued


def run_cycle(driver: webdriver.Chrome, ctx: LoopContext) -> None:
    sender = ctx.make_sender(driver)
    ctx.applier = ctx.make_applier(driver)

    def drain() -> int:
        return drain_queue(ctx.store, ctx.settings.run, sender)

    sent = drain()  # lo que quedó de la vuelta anterior
    recruiters = harvest_recruiters(driver, ctx)
    # Empleos antes de las fuentes: con 45 fuentes la vuelta dura ~2 h y casi nunca llegaba al final.
    jobs = harvest_job_listings(ctx)
    sent += drain()
    read, queued, sent_from_sources = harvest_sources(driver, ctx, drain)
    sent += sent_from_sources
    ctx.found_last_cycle = queued + jobs + recruiters
    log.info("Vuelta: %d posts, %d nuevos en cola, %d de Empleos, %d de recruiters, %d borradores, %d pendientes, "
             "%d hoy.", read, queued, jobs, recruiters, sent, len(ctx.store.pending), ctx.store.sent_on(date.today()))


# Errores de un Chrome colgado o caído: el comando a chromedriver vence o se corta.
CHROME_ERRORS = (WebDriverException, urllib3.exceptions.HTTPError, OSError)
RETRY_AFTER_HANG_MINUTES = 1


def open_feed(settings: Settings) -> webdriver.Chrome:
    driver = create_driver(settings.chrome_profile_dir, settings.chrome_headless)
    if not wait_for_login(driver):
        driver.quit()
        raise SystemExit("No se inició sesión en LinkedIn a tiempo.")
    return driver


def ensure_gmail_session(driver: webdriver.Chrome, ctx: LoopContext) -> None:
    """Abre Gmail solo en la primera vuelta del proceso: la sesión queda en el perfil y, si vence,
    el borrador siguiente falla con AuthError y frena el loop igual."""
    if ctx.gmail_checked:
        return
    if not wait_for_gmail_login(driver):
        driver.quit()
        raise SystemExit("No se inició sesión en Gmail a tiempo (pestaña aparte del Chrome del loop).")
    ctx.gmail_checked = True


def kill_chrome(driver: webdriver.Chrome | None, profile_dir: Path) -> None:
    """Cierre forzado: chromedriver y todo Chrome que use el perfil del loop."""
    if driver is not None:
        driver.service.process.kill()
    subprocess.run(["pkill", "-f", "--", f"--user-data-dir={profile_dir}"], check=False)
    time.sleep(3)


def run_fresh_cycle(ctx: LoopContext, dry_run: bool) -> bool:
    """Una vuelta con un Chrome nuevo, que se cierra al final para liberar la memoria del feed.

    Devuelve False si Chrome se colgó, para reintentar enseguida en vez de esperar la pausa.
    """
    driver: webdriver.Chrome | None = None
    closed = False
    try:
        driver = open_feed(ctx.settings)
        if not dry_run:
            ensure_gmail_session(driver, ctx)
        run_cycle(driver, ctx)
        driver.quit()
        closed = True
    except CHROME_ERRORS as exc:
        ctx.store.progress[CURSOR_KEY] = ctx.current_source + 1
        log.error("Chrome dejó de responder (%s) en la fuente %d; lo cierro y retomo desde la siguiente en %d min.",
                  type(exc).__name__, ctx.current_source, RETRY_AFTER_HANG_MINUTES)
    finally:
        if not closed:
            kill_chrome(driver, ctx.settings.chrome_profile_dir)
    return closed


def run_loop(ctx: LoopContext, args: argparse.Namespace) -> None:
    while True:
        completed = run_fresh_cycle(ctx, args.dry_run)
        if args.once:
            return
        if not completed:
            time.sleep(RETRY_AFTER_HANG_MINUTES * 60)
            continue
        ctx.idle_cycles = 0 if ctx.found_last_cycle else ctx.idle_cycles + 1
        pause = next_pause_minutes(ctx.settings.run, ctx.idle_cycles)
        log.info("Pausa de %.0f min antes del próximo F5 (%d vueltas seguidas sin novedades).", pause, ctx.idle_cycles)
        time.sleep(pause * 60)


def next_pause_minutes(run: RunSettings, idle_cycles: int) -> float:
    """Pausa base al azar, duplicada por cada vuelta seguida sin novedades, con tope MAX_PAUSE_MINUTES."""
    base = random.uniform(run.pause_minutes_min, run.pause_minutes_max)
    return min(MAX_PAUSE_MINUTES, base * 2 ** min(idle_cycles, 6))


def _log_only(_driver: webdriver.Chrome) -> Sender:
    return lambda app: log.info("[dry-run] %s | %s\n%s", app.to, app.subject, app.body)


def build_sender_factory(settings: Settings, dry_run: bool) -> SenderFactory:
    errors = validate_mail_settings(settings.mail)
    if errors:
        raise SystemExit("Configuración incompleta:\n  " + "\n  ".join(errors))
    return _log_only if dry_run else GmailDraftWriter


def load_store(settings: Settings, dry_run: bool) -> Store:
    store = Store.load(settings.state_dir / "dry_run" if dry_run else settings.state_dir)
    if PREVIOUS_CONTACTS_FILE.exists():
        lines = PREVIOUS_CONTACTS_FILE.read_text(encoding="utf-8").splitlines()
        store.import_previous_contacts([line.strip() for line in lines if "@" in line])
    return store


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LinkedIn Job Finder v3")
    parser.add_argument("--once", action="store_true", help="una sola vuelta")
    parser.add_argument("--dry-run", action="store_true", help="arma los mails sin enviarlos")
    return parser.parse_args()


def main() -> None:
    # kill/systemd mandan SIGTERM: como Ctrl+C, para que los finally cierren Chrome y guarden el estado.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    args = parse_args()
    settings = load_settings()
    setup_logging(settings)
    factory = build_sender_factory(settings, args.dry_run)
    ctx = LoopContext(settings, load_store(settings, args.dry_run), factory)
    ctx.make_applier = _no_easy_apply if args.dry_run else easy_apply_factory(ctx)
    ctx.allow_follow = not args.dry_run
    log.info("Job Finder v3 | dry-run=%s | cupo diario %d | %d canales | %d en cola",
             args.dry_run, settings.run.daily_send_limit, len(ctx.channels), len(ctx.store.pending))
    try:
        run_loop(ctx, args)
    except AuthError as exc:
        log.critical("%s. Loop detenido.", exc)
    except KeyboardInterrupt:
        log.info("Detenido por el usuario.")
    finally:
        ctx.store.save()


if __name__ == "__main__":
    main()
