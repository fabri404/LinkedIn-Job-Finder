#!/usr/bin/env python3
"""main.py - LinkedIn Job Finder v3.

Loop 24/7: feed, canales y Empleos → filtro → borrador en Gmail con el CV adjunto o Solicitud
sencilla. Los borradores los revisa y envía el usuario. El ritmo (cuánto navega y cuánto descansa,
de día y de noche) lo decide pacing.Pacer.

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
from datetime import date, datetime, timedelta
from pathlib import Path

import urllib3

from selenium import webdriver
from selenium.common.exceptions import WebDriverException

from classifier import (
    JobPosting,
    evaluate_job,
    evaluate_post,
    is_dev_title,
    is_profile_title,
    post_author,
)
from composer import URL_PATTERN, Application, compose, linkedin_message, select_cv
from config import (
    BASE_DIR,
    RunSettings,
    Settings,
    load_channels,
    load_keywords,
    load_settings,
    validate_mail_settings,
)
from easy_apply import SUBMITTED, ApplyResult, EasyApplyFiller, safe_apply
from feed import PAGE_LISTENERS, AccountBlocked, FeedPost, create_driver, safe_harvest, wait_for_login
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
from pacing import CONTENT_SEARCH, EMPTY_SEARCHES_LIMIT, JOBS, Pacer
from recruiters import MAX_SEARCH_PAGE, RecruiterCard, follow, follow_pause, safe_search
from relevance import fit_for_draft, fit_for_easy_apply
from sources import plan_sources
from store import VETO_FILE, QueuedApplication, Store, normalize_role

log = logging.getLogger("job_finder")
# Una línea por post evaluado: va a data/audit.log para que job_finder.log (el que lee el
# dashboard) quede corto y legible.
audit = logging.getLogger("job_finder.audit")
LOG_MAX_BYTES = 2_000_000
LOG_BACKUPS = 3
PREVIOUS_CONTACTS_FILE = BASE_DIR / "contactados_previos.txt"
CURSOR_KEY = "source_cursor"
ROTATION_KEY = "source_rotation"
RECRUITER_QUERY_KEY = "recruiter_query"
JOB_CYCLE_KEY = "job_cycle"

Sender = Callable[[Application], None]
SenderFactory = Callable[[webdriver.Chrome], Sender]
Applier = Callable[[str, str], ApplyResult]
ApplierFactory = Callable[[webdriver.Chrome | None], Applier]


def _no_easy_apply(_driver: webdriver.Chrome | None) -> Applier:
    return lambda _url, _cv: ApplyResult("dry-run: sin solicitud sencilla")


def easy_apply_factory(ctx: LoopContext) -> ApplierFactory:
    """Solicitud sencilla que se envía sola mientras no se llegue al cupo del día (menor en calentamiento)."""

    def may_submit() -> bool:
        return ctx.store.easy_applies_on(date.today()) < ctx.pacer.easy_apply_limit()

    def factory(driver: webdriver.Chrome | None) -> Applier:
        filler = EasyApplyFiller(driver, may_submit)
        return lambda url, cv_path: safe_apply(filler, url, cv_path)

    return factory


class LoopContext:
    def __init__(self, settings: Settings, store: Store, make_sender: SenderFactory) -> None:
        self.settings = settings
        self.store = store
        self.pacer = Pacer(store, settings.pace)
        self.make_sender = make_sender
        self.make_applier: ApplierFactory = _no_easy_apply
        self.applier: Applier = _no_easy_apply(None)
        self.keywords = load_keywords(settings.keywords_file)
        self.channels = load_channels(settings.channels_file)
        self.job_queries = load_channels(settings.job_queries_file)
        self.current_source = 0
        self.recruiter_queries = load_channels(settings.recruiter_queries_file)
        self.allow_follow = True
        self.gmail_checked = False
        self.found_last_cycle = 0
        self.idle_cycles = 0
        self.failed_cycles = 0


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
    fits, score = fit_for_draft(posting)
    if not fits:
        reason = f"relevancia {score}" if is_profile_title(posting.role_title) else "sin puesto claro"
        _record_for_review(posting, post_url, ctx, reason)
        return 0
    queued = 0
    for email in posting.emails:
        if ctx.store.is_known_recipient(email, posting.role_title):
            log.info("  ya contactado: %s", email)
            continue
        app = compose(posting, email, ctx.settings.mail.cv_dir)
        ctx.store.enqueue(QueuedApplication(app, post_url, score))
        log.info("  en cola (relevancia %d): %s | %s", score, email, posting.role_title)
        queued += 1
    return queued


def _record_for_review(posting: JobPosting, post_url: str, ctx: LoopContext, reason: str) -> None:
    """Oferta con email que no llega al mínimo para borrador: queda en contactar_linkedin.csv para mirarla
    a mano, una vez por email y puesto."""
    key = f"review:{','.join(posting.emails)}:{normalize_role(posting.role_title)}"
    if ctx.store.is_seen(key):
        return
    ctx.store.mark_seen(key)
    ctx.store.record_lead((date.today().isoformat(), "", "", posting.role_title or "?", post_url,
                           " ".join(posting.emails), f"revisar: {reason}"))
    log.info("  a revisar (%s): %s | %s", reason, " ".join(posting.emails), posting.role_title or "?")


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
    sources = plan_sources(ctx.channels, ctx.settings.run, ctx.pacer.cycle_plan(progress.get(ROTATION_KEY, 0)))
    read = queued = sent = 0
    for index in sources_from_cursor(len(sources), progress.get(CURSOR_KEY, 0)):
        if not ctx.pacer.has_page_budget():
            log.info("Presupuesto de páginas agotado por ahora; sigo desde acá en la próxima vuelta.")
            return read, queued, sent
        ctx.current_source = index
        if sources[index].is_content_search and ctx.pacer.cooling(CONTENT_SEARCH):
            continue
        posts = safe_harvest(driver, sources[index], ctx.store.is_seen)
        if sources[index].is_content_search:
            _watch_search_block(len(posts), ctx)
        read += len(posts)
        progress[CURSOR_KEY] = index + 1
        new = enqueue_new_posts(posts, ctx)
        queued += new
        if new:
            sent += drain()
    progress[CURSOR_KEY] = 0
    progress[ROTATION_KEY] = progress.get(ROTATION_KEY, 0) + 1
    return read, queued, sent


def _watch_search_block(posts: int, ctx: LoopContext) -> None:
    """Varias búsquedas seguidas sin un solo post: LinkedIn las está bloqueando; se dejan de pedir un rato."""
    until = ctx.pacer.record_search_result(posts)
    if until:
        log.warning("Búsquedas de publicaciones vacías %d veces seguidas: LinkedIn las limita. "
                    "Las retomo el %s.", EMPTY_SEARCHES_LIMIT, until.strftime("%d/%m %H:%M"))


def sources_from_cursor(count: int, cursor: int) -> list[int]:
    """Índices de las fuentes empezando por `cursor`: tras un cuelgue se retoma desde la
    fuente siguiente, para que una página que siempre cuelga Chrome no frene a las demás."""
    start = cursor % count if count else 0
    return list(range(start, count)) + list(range(start))


def pause_jobs_if_rate_limited(exc: Exception, ctx: LoopContext, what: str) -> None:
    """Un 429 de LinkedIn pausa la sección Empleos una hora; otro error solo corta esta vuelta."""
    if is_rate_limited(exc):
        resume = ctx.pacer.start_cooldown(JOBS, timedelta(seconds=COOLDOWN_AFTER_429_S)).strftime("%H:%M")
        log.warning("Empleos: LinkedIn limitó los pedidos (%s); retomo a las %s.", what, resume)
        return
    log.warning("Empleos: falló %s (%s); sigo en la próxima vuelta.", what, exc)


def new_job_cards(ctx: LoopContext) -> list[JobCard]:
    """Avisos de la sección Empleos que todavía no se evaluaron, sin repetir entre búsquedas."""
    cards: dict[str, JobCard] = {}
    cycle = ctx.store.progress.get(JOB_CYCLE_KEY, 0)
    searches = searches_for_cycle(ctx.job_queries, cycle)
    ctx.store.progress[JOB_CYCLE_KEY] = cycle + 1
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
    return _apply_or_list(card, posting, ctx)


def _apply_or_list(card: JobCard, posting: JobPosting, ctx: LoopContext) -> int:
    """Solicitud sencilla si encaja y no se postuló ya al mismo puesto en la misma empresa (los avisos se
    republican con otro id); si no encaja, queda en la lista para revisar a mano."""
    role_key = f"jobrole:{normalize_role(card.company)}:{normalize_role(card.title)}"
    if ctx.store.is_seen(role_key):
        audit.info("desc empleo ya postulado (mismo puesto y empresa) | %s | %s", card.title, card.company)
        return 0
    fits, score = fit_for_easy_apply(posting)
    if fits:
        cv_path = select_cv(ctx.settings.mail.cv_dir, posting.track, posting.language)
        result = ctx.applier(card.url, str(cv_path))
        ctx.store.mark_seen(role_key)
        if result.status == SUBMITTED:
            ctx.pacer.record_easy_apply()
    else:
        result = ApplyResult(f"relevancia {score}: revisar a mano")
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
        # Sin turno para una Solicitud sencilla (cupo, hora o intervalo), el resto se lee en otra vuelta.
        if details == MAX_DETAILS_PER_CYCLE or not ctx.pacer.may_easy_apply(ctx.store.easy_applies_on(date.today())):
            break
        details += 1
        try:
            found += process_job_card(card, ctx)
        except JOB_FETCH_ERRORS as exc:
            pause_jobs_if_rate_limited(exc, ctx, card.url)
            break
        detail_pause()
    return found


def harvest_job_listings(ctx: LoopContext) -> int:
    """Sección Empleos de LinkedIn (búsqueda por HTTP; la Solicitud sencilla abre el aviso en Chrome).
    Solo con turno para una Solicitud sencilla (de día, bajo los cupos) y fuera del enfriamiento por 429.
    Devuelve las postulaciones nuevas."""
    if ctx.pacer.cooling(JOBS) or not ctx.pacer.may_easy_apply(ctx.store.easy_applies_on(date.today())):
        return 0
    found = _evaluate_job_cards(new_job_cards(ctx), ctx)
    ctx.store.save()
    return found


def harvest_recruiters(driver: webdriver.Chrome, ctx: LoopContext) -> None:
    """Una búsqueda de personas por día y "Seguir" a unos pocos recruiters IT desde los resultados.
    No abre perfiles: eso fue lo que LinkedIn marcó como acceso masivo a datos de perfiles."""
    if not (ctx.allow_follow and ctx.recruiter_queries and ctx.pacer.may_search_people()):
        return
    index = ctx.store.progress.get(RECRUITER_QUERY_KEY, 0)
    query = queries_for_cycle(ctx.recruiter_queries, index, 1)[0]
    ctx.store.progress[RECRUITER_QUERY_KEY] = index + 1
    page = ctx.store.search_pages.get(query, 1)
    ctx.pacer.record_people_search()
    unseen = [card for card in safe_search(driver, query, page) if not ctx.store.is_seen(card.key)]
    if not unseen:
        ctx.store.search_pages[query] = page + 1 if page < MAX_SEARCH_PAGE else 1
    for card in unseen:
        if not ctx.pacer.may_follow():
            break
        _follow(driver, card, ctx)
    ctx.store.save()


def _follow(driver: webdriver.Chrome, card: RecruiterCard, ctx: LoopContext) -> None:
    ctx.store.mark_seen(card.key)
    if not follow(driver, card):
        return
    ctx.pacer.record_follow()
    ctx.store.save()
    log.info("  Siguiendo a %s (%s).", card.name, card.headline[:60])
    follow_pause()


def run_cycle(driver: webdriver.Chrome, ctx: LoopContext) -> None:
    sender = ctx.make_sender(driver)
    ctx.applier = ctx.make_applier(driver)

    def drain() -> int:
        return drain_queue(ctx.store, ctx.settings.run, sender)

    sent = drain()  # lo que quedó de la vuelta anterior
    harvest_recruiters(driver, ctx)
    jobs = harvest_job_listings(ctx)
    sent += drain()
    read, queued, sent_from_sources = harvest_sources(driver, ctx, drain)
    sent += sent_from_sources
    ctx.found_last_cycle = queued + jobs
    log.info("Vuelta%s: %d posts, %d nuevos en cola, %d de Empleos, %d borradores, %d pendientes, %d hoy; "
             "%d páginas de LinkedIn quedan en esta hora.", " nocturna" if ctx.pacer.is_night() else "", read,
             queued, jobs, sent, len(ctx.store.pending), ctx.store.sent_on(date.today()), max(0, ctx.pacer.pages_left()))


# Errores de un Chrome colgado o caído: el comando a chromedriver vence o se corta.
CHROME_ERRORS = (WebDriverException, urllib3.exceptions.HTTPError, OSError)
# Errores de programación o de un HTML inesperado en una vuelta: se registran con el traceback y el
# loop sigue en vez de morir en segundo plano sin que nadie lo note. AuthError y SystemExit (Gmail
# sin sesión, checkpoint de LinkedIn) sí lo frenan, a propósito.
UNEXPECTED_ERRORS = (AttributeError, LookupError, TypeError, ValueError, RuntimeError, ArithmeticError)
MAX_RETRY_MINUTES = 60
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
        log.error("Chrome dejó de responder (%s) en la fuente %d; lo cierro y retomo desde la siguiente.",
                  type(exc).__name__, ctx.current_source)
    except UNEXPECTED_ERRORS:
        ctx.store.progress[CURSOR_KEY] = ctx.current_source + 1
        log.exception("Error inesperado en la fuente %d; sigo con la siguiente.", ctx.current_source)
    finally:
        ctx.store.save()
        if not closed:
            kill_chrome(driver, ctx.settings.chrome_profile_dir)
    return closed


def run_loop(ctx: LoopContext, args: argparse.Namespace) -> None:
    while True:
        if not (args.once or ctx.pacer.has_page_budget()):
            _rest(ctx, "sin presupuesto de páginas de LinkedIn por ahora")  # ni siquiera abre Chrome
            continue
        completed = run_fresh_cycle(ctx, args.dry_run)
        if args.once:
            return
        if not completed:
            ctx.failed_cycles += 1
            wait = retry_minutes(ctx.failed_cycles)
            log.info("Reintento en %d min (%d vueltas seguidas con error).", wait, ctx.failed_cycles)
            time.sleep(wait * 60)
            continue
        ctx.failed_cycles = 0
        ctx.idle_cycles = 0 if ctx.found_last_cycle else ctx.idle_cycles + 1
        _rest(ctx, f"{ctx.idle_cycles} vueltas seguidas sin novedades")


def _rest(ctx: LoopContext, why: str) -> None:
    pause = ctx.pacer.next_pause_minutes(ctx.idle_cycles)
    ctx.store.save()
    log.info("Pausa de %.0f min antes de la próxima vuelta (%s).", pause, why)
    time.sleep(pause * 60)


def retry_minutes(failed_cycles: int) -> int:
    """1, 2, 4… minutos tras cada vuelta fallida seguida: un error que se repite no relanza Chrome cada minuto."""
    return min(MAX_RETRY_MINUTES, RETRY_AFTER_HANG_MINUTES * 2 ** min(failed_cycles - 1, 6))


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
    PAGE_LISTENERS.append(ctx.pacer.count_page)
    ctx.make_applier = _no_easy_apply if args.dry_run else easy_apply_factory(ctx)
    ctx.allow_follow = not args.dry_run
    log.info("Job Finder v3 | dry-run=%s | cupo diario %d | %d canales | %d en cola | calentamiento=%s",
             args.dry_run, settings.run.daily_send_limit, len(ctx.channels), len(ctx.store.pending),
             ctx.pacer.in_warmup())
    try:
        run_loop(ctx, args)
    except AuthError as exc:
        log.critical("%s. Loop detenido.", exc)
    except AccountBlocked as exc:
        ctx.pacer.mark_restricted()
        log.critical("LinkedIn pidió verificación o cerró la sesión (%s); freno el loop. Resolvelo a mano con "
                     "\"Con ventana (login)\"; al volver corre una semana a mitad de ritmo.", exc)
    except KeyboardInterrupt:
        log.info("Detenido por el usuario.")
    finally:
        ctx.store.save()


if __name__ == "__main__":
    main()
