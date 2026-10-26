"""feed.py - Lee el feed de LinkedIn con Selenium usando un perfil de Chrome persistente.

No escribe contraseñas: la primera vez se inicia sesión a mano en la ventana que abre
el script y la sesión queda guardada en el perfil.
"""

from __future__ import annotations

import hashlib
import logging
import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from selenium import webdriver
from selenium.common.exceptions import (
    InvalidSessionIdException,
    NoSuchWindowException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions.wheel_input import ScrollOrigin
from selenium.webdriver.common.by import By

if TYPE_CHECKING:
    from sources import Source

log = logging.getLogger(__name__)

FEED_URL = "https://www.linkedin.com/feed/"
LOGGED_IN_PREFIX = "https://www.linkedin.com/feed"
PAGE_LOAD_TIMEOUT_S = 60
STALL_SECONDS = 45
MAX_RELOADS_PER_PAGE = 3
WHEEL_TICKS = 4
WHEEL_DELTA_PX = 300
HEADLESS_WINDOW_SIZE = "1366,900"

# UI 2026: clases ofuscadas, cada post es un [role=listitem] con un h2 oculto
# "Publicación en el feed". Se mantiene el selector de la UI vieja como respaldo.
# innerText ya trae el post completo aunque se vea cortado en "… más" (medido: abrirlo no suma
# texto y duplica el alto del DOM), así que no se expande. Cada nodo se lee hasta que su texto
# deja de cambiar y después se saltea: el costo por pasada ya no crece con lo scrolleado.
COLLECT_JS = """
const titles = new Set(['Publicación en el feed', 'Feed post']);
const items = [];
document.querySelectorAll('h2').forEach(h => {
  if (!titles.has((h.innerText || '').trim())) return;
  items.push(h.closest('[role="listitem"]') || h.parentElement.parentElement);
});
if (!items.length) document.querySelectorAll('div.feed-shared-update-v2').forEach(c => items.push(c));
const out = [];
for (const c of items) {
  if (c.dataset.jfDone) continue;
  const text = (c.innerText || '').trim();
  if (text.length <= 40) continue;
  if (c.dataset.jfLen === String(text.length)) { c.dataset.jfDone = '1'; continue; }
  c.dataset.jfLen = String(text.length);
  const urn = c.getAttribute('data-urn') || '';
  const link = [...c.querySelectorAll('a[href]')].map(a => a.href)
    .find(u => /\\/feed\\/update\\/|\\/posts\\//.test(u))
    || (urn ? `https://www.linkedin.com/feed/update/${urn}/` : '');
  out.push([text, link.split('?')[0]]);
}
return out;
"""

# El feed 2026 scrollea dentro de main#workspace; las páginas de empresa, en el documento.
SCROLL_STATE_JS = """
const w = document.querySelector('#workspace');
const el = (w && w.scrollHeight > w.clientHeight + 10) ? w : document.scrollingElement;
return [el.scrollHeight, document.visibilityState];
"""


@dataclass(frozen=True)
class FeedPost:
    key: str
    text: str
    url: str


# Primera línea que LinkedIn agrega según quién interactuó ("X recomienda esto", "A Y le gusta esto"):
# cambia según el contexto y movía la ventana de la clave, duplicando el mismo post.
CONTEXT_LINE = re.compile(
    r"^[^\n]{0,120}\b(recomienda|le gusta|les gusta|le encanta|le hace gracia|apoya|comentó|ha comentado|"
    r"compartió|ha compartido|celebra|publicación sugerida|promocionado|likes this|loves this|commented on|"
    r"reposted|suggested|promoted)\b[^\n]*\n", re.I)


def post_key(text: str) -> str:
    """Clave estable: ignora números (seguidores, horas, reacciones) y la línea de contexto."""
    body = CONTEXT_LINE.sub("", text.strip(), count=1)
    body = re.sub(r"\d+", "", body.lower())
    body = re.sub(r"\s+", " ", body)
    return hashlib.sha1(body[60:460].encode("utf-8")).hexdigest()[:16]


def create_driver(profile_dir: Path, headless: bool) -> webdriver.Chrome:
    """Chrome con el perfil del loop.

    Headless por defecto: con ventana, si se minimizaba o quedaba tapada Chrome dejaba de
    dibujar y el scroll con la rueda se colgaba esperando el cuadro siguiente. Para iniciar
    sesión por primera vez hace falta la ventana (CHROME_HEADLESS=0 en .env).
    """
    profile_dir.mkdir(parents=True, exist_ok=True)
    options = Options()
    options.add_argument(f"--user-data-dir={profile_dir}")
    if headless:
        options.add_argument("--headless=new")
        options.add_argument(f"--window-size={HEADLESS_WINDOW_SIZE}")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    # Que Chrome no congele el render si la ventana queda tapada o en segundo plano:
    # sin render, LinkedIn no dispara la carga de más posts.
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--disable-background-timer-throttling")
    # Sin autoplay de videos, que pesan en memoria. Las imágenes no se pueden apagar:
    # sin ellas las páginas de empresa nunca terminan de cargar los posts.
    options.add_argument("--autoplay-policy=user-gesture-required")
    options.add_argument("--mute-audio")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.page_load_strategy = "eager"
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT_S)
    if headless:
        hide_headless_user_agent(driver)
    return driver


def hide_headless_user_agent(driver: webdriver.Chrome) -> None:
    """El modo headless se anuncia como "HeadlessChrome": se usa el mismo UA sin esa marca."""
    user_agent = driver.execute_script("return navigator.userAgent")
    driver.execute_cdp_cmd("Network.setUserAgentOverride",
                           {"userAgent": user_agent.replace("HeadlessChrome", "Chrome")})


def open_url(driver: webdriver.Chrome, url: str) -> None:
    """driver.get tolerante: si la página tarda más del límite, sigue con lo que cargó."""
    try:
        driver.get(url)
    except TimeoutException:
        log.warning("%s tardó más de %ds en cargar; sigo igual.", url, PAGE_LOAD_TIMEOUT_S)


def wait_for_login(driver: webdriver.Chrome, timeout_s: int = 900) -> bool:
    """Espera la sesión de LinkedIn. False si vence el plazo sin sesión.

    Si Chrome se cae mientras tanto (por ejemplo, al volver de una suspensión), el error se
    propaga: es pasajero y el loop reintenta con un Chrome nuevo en vez de terminar.
    """
    open_url(driver, FEED_URL)
    deadline = time.time() + timeout_s
    if not driver.current_url.startswith(LOGGED_IN_PREFIX):
        log.warning("Iniciá sesión en LinkedIn en la ventana de Chrome (una sola vez; "
                    "si no ves la ventana, poné CHROME_HEADLESS=0 en .env).")
    while not driver.current_url.startswith(LOGGED_IN_PREFIX):
        if time.time() > deadline:
            return False
        time.sleep(5)
    return True


def _collect(driver: webdriver.Chrome, posts: dict[str, FeedPost], is_seen: Callable[[str], bool]) -> int:
    """Suma a `posts` lo que hay en pantalla; devuelve cuántos posts aparecieron que no se habían visto."""
    fresh = 0
    for text, url in driver.execute_script(COLLECT_JS) or []:
        key = post_key(text)
        current = posts.get(key)
        if current is None and not is_seen(key):
            fresh += 1
        if current is None or len(text) > len(current.text):
            posts[key] = FeedPost(key, text, url)
    return fresh


def _wheel_scroll(driver: webdriver.Chrome) -> None:
    """Rueda real del mouse (eventos de input, como una persona) sobre el contenedor del feed.

    Todos los movimientos van en una sola cadena: un único pedido a chromedriver por paso.
    """
    targets = driver.find_elements(By.CSS_SELECTOR, "#workspace")
    origin = ScrollOrigin.from_element(targets[0]) if targets else ScrollOrigin.from_viewport(200, 200)
    chain = ActionChains(driver)
    for _ in range(WHEEL_TICKS):
        chain.scroll_from_origin(origin, 0, WHEEL_DELTA_PX).pause(random.uniform(0.15, 0.4))
    chain.perform()


@dataclass
class _ScrollProgress:
    height: int = 0
    last_growth: float = field(default_factory=time.time)
    reloads: int = 0

    def update(self, height: int) -> bool:
        """Registra la altura; True si el feed está trabado hace más de STALL_SECONDS."""
        if height > self.height:
            self.height, self.last_growth = height, time.time()
        return time.time() - self.last_growth > STALL_SECONDS


def _recover_stall(driver: webdriver.Chrome, source: Source, progress: _ScrollProgress, visibility: str) -> bool:
    """F5 para traer otra tanda. False si ya se agotaron las recargas o si es una búsqueda:
    ahí una traba es el final de los resultados y recargar solo repite los primeros."""
    if visibility != "visible":
        log.warning("La ventana del loop está minimizada u oculta: LinkedIn no carga posts así.")
    if source.is_content_search:
        log.info("%s: fin de los resultados.", source.url)
        return False
    if progress.reloads >= MAX_RELOADS_PER_PAGE:
        log.warning("%s no carga más posts después de %d recargas; sigo con la próxima.", source.url, progress.reloads)
        return False
    progress.reloads += 1
    log.info("%s trabado; F5 (%d/%d).", source.url, progress.reloads, MAX_RELOADS_PER_PAGE)
    open_url(driver, source.url)
    time.sleep(4)
    progress.height, progress.last_growth = 0, time.time()
    return True


def _scroll_until_idle(driver: webdriver.Chrome, source: Source, is_seen: Callable[[str], bool]) -> dict[str, FeedPost]:
    """Scrollea hasta `source.minutes`, o antes si `source.idle_limit` lecturas seguidas no traen nada nuevo."""
    posts: dict[str, FeedPost] = {}
    deadline = time.time() + source.minutes * 60
    progress = _ScrollProgress()
    idle = 0
    while time.time() < deadline:
        idle = 0 if _collect(driver, posts, is_seen) else idle + 1
        if idle >= source.idle_limit:
            log.info("%s: %d lecturas seguidas sin posts nuevos; sigo con la próxima.", source.url, idle)
            break
        _wheel_scroll(driver)
        height, visibility = driver.execute_script(SCROLL_STATE_JS)
        if progress.update(height) and not _recover_stall(driver, source, progress, visibility):
            break
        time.sleep(random.uniform(1.5, 2.8))
    return posts


def harvest_page(driver: webdriver.Chrome, source: Source, is_seen: Callable[[str], bool]) -> list[FeedPost]:
    """Carga la fuente (feed, grupo, empresa o búsqueda) y acumula cada post hasta agotarla."""
    open_url(driver, source.url)
    time.sleep(4)
    posts = _scroll_until_idle(driver, source, is_seen)
    _collect(driver, posts, is_seen)
    if posts:
        log.info("%s: %d posts leídos.", source.url, len(posts))
    else:
        log.warning("%s: 0 posts leídos (¿la página no cargó o cambió el HTML de LinkedIn?).", source.url)
    open_url(driver, "about:blank")  # suelta el DOM del feed: cientos de posts pesan varios GB
    return list(posts.values())


def safe_harvest(driver: webdriver.Chrome, source: Source, is_seen: Callable[[str], bool]) -> list[FeedPost]:
    """Un error de una página se saltea; una sesión muerta (Chrome cerrado tras una suspensión
    de la notebook) se propaga para que el loop abra un Chrome nuevo en vez de seguir fallando."""
    try:
        return harvest_page(driver, source, is_seen)
    except (InvalidSessionIdException, NoSuchWindowException):
        raise
    except WebDriverException as exc:
        log.error("Error leyendo %s (%s): %s", source.url, type(exc).__name__, exc.msg)
        return []
