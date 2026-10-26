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
from dataclasses import dataclass, field
from pathlib import Path

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
COLLECT_JS = """
const out = [];
const titles = new Set(['Publicación en el feed', 'Feed post']);
document.querySelectorAll('h2').forEach(h => {
  if (!titles.has((h.innerText || '').trim())) return;
  const c = h.closest('[role="listitem"]') || h.parentElement.parentElement;
  out.push(c);
});
if (!out.length) document.querySelectorAll('div.feed-shared-update-v2').forEach(c => out.push(c));
return out.map(c => {
  const urn = c.getAttribute('data-urn') || '';
  const link = [...c.querySelectorAll('a[href]')].map(a => a.href)
    .find(u => /\\/feed\\/update\\/|\\/posts\\//.test(u))
    || (urn ? `https://www.linkedin.com/feed/update/${urn}/` : '');
  return [(c.innerText || '').trim(), link.split('?')[0]];
}).filter(p => p[0].length > 40);
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


def post_key(text: str) -> str:
    """Clave estable: ignora números (seguidores, horas, reacciones) y la línea de contexto."""
    body = re.sub(r"\d+", "", text.lower())
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


def _collect(driver: webdriver.Chrome, posts: dict[str, FeedPost]) -> None:
    for text, url in driver.execute_script(COLLECT_JS) or []:
        key = post_key(text)
        current = posts.get(key)
        if current is None or len(text) > len(current.text):
            posts[key] = FeedPost(key, text, url)


def _wheel_scroll(driver: webdriver.Chrome) -> None:
    """Rueda real del mouse (eventos de input, como una persona) sobre el contenedor del feed."""
    targets = driver.find_elements(By.CSS_SELECTOR, "#workspace")
    origin = ScrollOrigin.from_element(targets[0]) if targets else ScrollOrigin.from_viewport(200, 200)
    for _ in range(WHEEL_TICKS):
        ActionChains(driver).scroll_from_origin(origin, 0, WHEEL_DELTA_PX).perform()
        time.sleep(random.uniform(0.15, 0.4))


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


def _recover_stall(driver: webdriver.Chrome, url: str, progress: _ScrollProgress, visibility: str) -> bool:
    """F5 para traer otra tanda. False si ya se agotaron las recargas."""
    if visibility != "visible":
        log.warning("La ventana del loop está minimizada u oculta: LinkedIn no carga posts así.")
    if progress.reloads >= MAX_RELOADS_PER_PAGE:
        log.warning("%s no carga más posts después de %d recargas; sigo con la próxima.", url, progress.reloads)
        return False
    progress.reloads += 1
    log.info("%s trabado; F5 (%d/%d).", url, progress.reloads, MAX_RELOADS_PER_PAGE)
    open_url(driver, url)
    time.sleep(4)
    progress.height, progress.last_growth = 0, time.time()
    return True


def harvest_page(driver: webdriver.Chrome, url: str, minutes: float) -> list[FeedPost]:
    """Carga `url` (feed o posts de una página) y scrollea `minutes` acumulando cada post."""
    open_url(driver, url)
    time.sleep(4)
    posts: dict[str, FeedPost] = {}
    deadline = time.time() + minutes * 60
    progress = _ScrollProgress()
    while time.time() < deadline:
        _collect(driver, posts)
        _wheel_scroll(driver)
        height, visibility = driver.execute_script(SCROLL_STATE_JS)
        if progress.update(height) and not _recover_stall(driver, url, progress, visibility):
            break
        time.sleep(random.uniform(1.5, 2.8))
    _collect(driver, posts)
    log.info("%s: %d posts leídos.", url, len(posts))
    open_url(driver, "about:blank")  # suelta el DOM del feed: cientos de posts pesan varios GB
    return list(posts.values())


def safe_harvest(driver: webdriver.Chrome, url: str, minutes: float) -> list[FeedPost]:
    """Un error de una página se saltea; una sesión muerta (Chrome cerrado tras una suspensión
    de la notebook) se propaga para que el loop abra un Chrome nuevo en vez de seguir fallando."""
    try:
        return harvest_page(driver, url, minutes)
    except (InvalidSessionIdException, NoSuchWindowException):
        raise
    except WebDriverException as exc:
        log.error("Error leyendo %s: %s", url, exc.msg)
        return []
