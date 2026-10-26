"""mailer.py - Deja cada postulación como borrador en Gmail, con el CV adjunto.

Usa la sesión de Gmail del mismo perfil de Chrome del loop: no guarda contraseñas.
El envío final lo hace el usuario desde la carpeta Borradores.
"""

from __future__ import annotations

import logging
import time
from urllib.parse import quote, urlencode

from selenium import webdriver
from selenium.common.exceptions import UnexpectedAlertPresentException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from composer import Application
from feed import hide_headless_user_agent, open_url

log = logging.getLogger(__name__)

GMAIL_INBOX_URL = "https://mail.google.com/mail/u/0/#inbox"
GMAIL_COMPOSE_URL = "https://mail.google.com/mail/u/0/"
FILE_INPUT = "input[type=file][name=Filedata]"
UPLOAD_PROGRESS = "[role=progressbar]"
LOAD_TIMEOUT_S = 30
UPLOAD_TIMEOUT_S = 90
SAVE_TIMEOUT_S = 30
AUTOSAVE_WAIT_S = 4
# Gmail guarda solo el borrador y lo indica con "Guardado" ("Saved" con la UI en inglés).
SAVED_JS = """
return [...document.querySelectorAll('span, div')].some(e =>
  e.children.length === 0 && ['Guardado', 'Saved'].includes((e.innerText || '').trim()));
"""


class MailError(Exception):
    """Fallo al crear el borrador. `permanent` indica que reintentar no sirve."""

    def __init__(self, message: str, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


class AuthError(MailError):
    """No hay sesión de Gmail en el perfil de Chrome: hay que frenar."""


def compose_url(app: Application) -> str:
    params = {"view": "cm", "fs": "1", "to": app.to, "su": app.subject, "body": app.body}
    return f"{GMAIL_COMPOSE_URL}?{urlencode(params, quote_via=quote)}"


GMAIL_PREFIX = "https://mail.google.com/mail"
GOOGLE_LOGIN_PREFIX = "https://accounts.google.com"


def is_gmail_logged_in(driver: webdriver.Chrome) -> bool:
    return driver.current_url.startswith(GMAIL_PREFIX)


def _landed_url(driver: webdriver.Chrome) -> str:
    """Espera a que la navegación llegue a Gmail o al login de Google; devuelve la URL final."""
    try:
        WebDriverWait(driver, LOAD_TIMEOUT_S).until(
            lambda d: d.current_url.startswith((GMAIL_PREFIX, GOOGLE_LOGIN_PREFIX)))
    except WebDriverException:
        pass  # sigue con la URL que haya: el llamador decide si es error pasajero
    return driver.current_url


def wait_for_gmail_login(driver: webdriver.Chrome, timeout_s: int = 900) -> bool:
    """Abre Gmail en una pestaña aparte y espera a que el usuario inicie sesión (una sola vez)."""
    main_tab = driver.current_window_handle
    driver.switch_to.new_window("tab")
    try:
        hide_headless_user_agent(driver)
        open_url(driver, GMAIL_INBOX_URL)
        deadline = time.time() + timeout_s
        if not is_gmail_logged_in(driver):
            log.warning("Iniciá sesión en Gmail en la pestaña que abrió el loop (una sola vez).")
        while not is_gmail_logged_in(driver):
            if time.time() > deadline:
                return False
            time.sleep(5)
        return True
    finally:
        driver.close()
        driver.switch_to.window(main_tab)


class GmailDraftWriter:
    """Sender que crea un borrador por postulación en una pestaña temporal.

    Gmail guarda el borrador apenas se abre la redacción: un fallo después de abrirla es
    permanente (no se reintenta) para no duplicar borradores.
    """

    def __init__(self, driver: webdriver.Chrome) -> None:
        self.driver = driver

    def __call__(self, app: Application) -> None:
        if not app.cv_path.is_file():
            raise MailError(f"CV no encontrado: {app.cv_path}", permanent=True)
        main_tab = self.driver.current_window_handle
        self.driver.switch_to.new_window("tab")
        try:
            hide_headless_user_agent(self.driver)
            self._open_compose(app)
            self._attach_and_save(app)
        finally:
            self._close_tab(main_tab)

    def _open_compose(self, app: Application) -> None:
        try:
            open_url(self.driver, compose_url(app))
            url = _landed_url(self.driver)
            if url.startswith(GOOGLE_LOGIN_PREFIX):
                raise AuthError("No hay sesión de Gmail en el Chrome del loop")
            if not url.startswith(GMAIL_PREFIX):
                raise MailError(f"Gmail no cargó a tiempo para {app.to}")
            WebDriverWait(self.driver, LOAD_TIMEOUT_S).until(
                lambda d: d.find_elements(By.CSS_SELECTOR, FILE_INPUT))
        except WebDriverException as exc:
            raise MailError(f"Gmail no abrió la redacción para {app.to}: {exc.msg}") from exc

    def _attach_and_save(self, app: Application) -> None:
        try:
            self.driver.find_element(By.CSS_SELECTOR, FILE_INPUT).send_keys(str(app.cv_path))
            WebDriverWait(self.driver, UPLOAD_TIMEOUT_S).until(lambda d: self._upload_done(app))
            time.sleep(AUTOSAVE_WAIT_S)
            WebDriverWait(self.driver, SAVE_TIMEOUT_S).until(lambda d: d.execute_script(SAVED_JS))
        except WebDriverException as exc:
            raise MailError(f"borrador para {app.to} quizá incompleto (revisalo en Gmail): {exc.msg}",
                            permanent=True) from exc

    def _upload_done(self, app: Application) -> bool:
        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        uploading = self.driver.find_elements(By.CSS_SELECTOR, UPLOAD_PROGRESS)
        return app.cv_path.name in body_text and not uploading

    def _close_tab(self, main_tab: str) -> None:
        try:
            self.driver.close()
        except UnexpectedAlertPresentException:
            self.driver.switch_to.alert.accept()
        finally:
            self.driver.switch_to.window(main_tab)
