"""easy_apply.py - Completa la Solicitud sencilla de LinkedIn y la envía si quedó completa.

Avanza página por página respondiendo solo lo que answers.py sabe con certeza. Si llega a
"Enviar solicitud" sin preguntas pendientes y `may_submit()` lo permite (cupo diario), la envía.
Si queda una pregunta obligatoria sin respuesta, cierra el formulario eligiendo "Guardar": la
solicitud queda en LinkedIn → Mis empleos → En curso, para que Adriel la complete a mano.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException, WebDriverException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import Select

from answers import CITY, answer_with_job_location, pick_option
from feed import open_url
from store import EASY_APPLY_SENT

log = logging.getLogger(__name__)

MAX_PAGES = 10
FIELD_SELECTOR = "input:not([type=hidden]):not([type=file]):not([type=radio]):not([type=checkbox]), select, textarea"
# Texto exacto del botón: las tarjetas de "empleos similares" también dicen "Solicitud sencilla".
EASY_APPLY_TEXT = re.compile(r"^(solicitud sencilla|easy apply|continuar|continue|continuar solicitud)$", re.IGNORECASE)
APPLIED_TEXT = re.compile(r"postulado|solicitud enviada|applied|application submitted", re.IGNORECASE)
NEXT_TEXT = re.compile(r"^(siguiente|next|revisar|review|continuar|continue)$", re.IGNORECASE)
SUBMIT_TEXT = re.compile(r"^(enviar solicitud|submit application|enviar|submit)$", re.IGNORECASE)
# Solo la X del formulario: "Descartar empleo «…»" de la lista de recomendados oculta avisos.
CLOSE_LABEL = re.compile(r"^(descartar|dismiss|cerrar|close)$", re.IGNORECASE)
SAVE_TEXT = re.compile(r"^(guardar|save)$", re.IGNORECASE)
SUBMITTED_TEXT = re.compile(
    r"se envi[oó] tu solicitud|tu solicitud se envi[oó]|your application was sent|application submitted|"
    r"solicitud enviada", re.IGNORECASE)
PLACEHOLDER_OPTION = re.compile(r"^(select an option|selecciona(r)?( una)? opci[oó]n|seleccionar)$", re.IGNORECASE)
CONSENT_LABEL = re.compile(
    r"acepto|accept|agree|consent|consiento|t[eé]rminos|terms|privacidad|privacy|pol[ií]tica|declaro|certif",
    re.IGNORECASE)
CV_LABEL = re.compile(r"curr[ií]cul|resume|\bcv\b", re.IGNORECASE)
# Entrada del perfil incompleta (p. ej. una educación sin fechas) que LinkedIn abre para editar y no
# deja avanzar: se quita de esta solicitud; no se inventan los datos que faltan.
REMOVE_ENTRY_TEXT = re.compile(r"^(eliminar|remove|delete) (educaci[oó]n|experiencia|education|experience|posici[oó]n)",
                               re.IGNORECASE)
CONFIRM_REMOVE_TEXT = re.compile(r"^(eliminar|remove|delete|s[ií], eliminar)$", re.IGNORECASE)
READY = "guardada lista para enviar"
SUBMITTED = EASY_APPLY_SENT
START_WAIT_S = 12
# Elegir una opción puede redibujar la página y dejar viejos los campos ya leídos: se relee y se sigue.
FILL_ATTEMPTS = 3
FORM_WAIT_S = 8
OPEN_ATTEMPTS = 2

# El formulario 2026 es un <dialog> con el título "Aplicar a…": si existe se usa ese contenedor
# (subir a ciegas llegaba a la página entera cuando el contenido todavía no había cargado).
ROOT_JS = r"""
const h = [...document.querySelectorAll('h1,h2,h3')].find(t => /^(Aplicar a|Apply to|Solicitar en)/i.test((t.innerText||'').trim())
                                                          && t.getClientRects().length > 0);
if (!h) return null;
const box = h.closest('dialog, [role=dialog], [aria-modal=true], .artdeco-modal');
if (box) return box;
let el = h;
for (let i = 0; i < 8 && el.parentElement; i++) {
  el = el.parentElement;
  if (el.querySelector('button') && el.querySelectorAll('input,select,textarea').length) break;
}
return el;
"""
LABEL_JS = r"""
const e = arguments[0];
const root = e.closest('form') || document;
return (root.querySelector(`label[for="${e.id}"]`)?.innerText || e.getAttribute('aria-label') ||
        e.closest('fieldset')?.querySelector('legend')?.innerText || e.placeholder || '').trim();
"""
RADIO_GROUPS_JS = r"""
const root = arguments[0];
const groups = {};
// Texto de la opción: label[for] (a veces vacío) o el bloque que envuelve al radio ("<p>Yes</p>").
const optionLabel = r => {
  const own = (root.querySelector(`label[for="${r.id}"]`)?.innerText || r.closest('label')?.innerText || '').trim();
  if (own) return own;
  const box = (r.parentElement?.parentElement?.innerText || '').trim();
  return box || (r.getAttribute('aria-label') || r.value || '').trim();
};
// Título de la pregunta: legend, aria del radiogroup, o la primera línea del bloque que la contiene.
const groupLabel = r => {
  const legend = r.closest('fieldset')?.querySelector('legend')?.innerText;
  if (legend) return legend.trim();
  const rg = r.closest('[role=radiogroup]');
  const byId = rg?.getAttribute('aria-labelledby');
  if (byId) return (document.getElementById(byId)?.innerText || '').trim();
  if (rg?.getAttribute('aria-label')) return rg.getAttribute('aria-label').trim();
  let el = r.parentElement;
  for (let i = 0; i < 6 && el; i++, el = el.parentElement) {
    const radios = el.querySelectorAll(`input[type=radio][name="${r.name}"]`).length;
    const lines = (el.innerText || '').split('\n').map(t => t.trim()).filter(Boolean);
    if (radios > 1 && lines.length > radios) return lines[0];
  }
  return '';
};
root.querySelectorAll('input[type=radio]').forEach(r => {
  const g = groups[r.name] ||= {name: r.name, checked: false, options: [], legend: groupLabel(r)};
  g.options.push(optionLabel(r));
  g.checked = g.checked || r.checked;
});
return Object.values(groups);
"""
# Contenedor del formulario completo (encabezado con la X incluido): sube desde el título "Aplicar a…".
MODAL_JS = r"""
const h = [...document.querySelectorAll('h1,h2,h3')].find(t => /^(Aplicar a|Apply to|Solicitar en)/i.test((t.innerText||'').trim()));
if (!h) return null;
return h.closest('[role=dialog], [aria-modal=true], .artdeco-modal') || h.parentElement?.parentElement?.parentElement || null;
"""
START_JS = r"""
const re = new RegExp(arguments[0], 'i');
return [...document.querySelectorAll('button, a')].find(b => re.test((b.innerText || '').trim())) || null;
"""
# Encabezado del aviso (puesto, empresa, ubicación) en un solo pedido: LinkedIn redibuja <main> al cargar.
TOP_CARD_JS = "return ((document.querySelector('main') || document.body).innerText || '').slice(0, 800);"
# Checkbox sin etiqueta propia ("I consent" va en un elemento vecino): se usa el texto de su pregunta.
CHECKBOX_CONTEXT_JS = r"""
const e = arguments[0];
const box = e.closest('fieldset') || e.closest('[componentkey^="easyApplyFieldFocus"]') || e.parentElement?.parentElement;
return ((box && box.innerText) || '').trim().slice(0, 300);
"""
# Sugerencias del campo de ciudad: solo las de su propio listbox, no cualquier [role=option] de la página.
TYPEAHEAD_JS = r"""
const e = arguments[0];
const id = e.getAttribute('aria-controls') || e.getAttribute('aria-owns');
const box = id && document.getElementById(id);
const option = box && box.querySelector('[role=option]');
if (option) { option.click(); return true; }
return false;
"""
# Preguntas de opción única hechas con "tarjetas": un <fieldset> sin inputs, cada opción un <p>.
# Funcionan como radios (otro clic sobre la elegida la deja elegida) y solo responden a un clic real.
TILE_FIELDSETS_XPATH = ".//fieldset[not(.//input or .//select or .//textarea)]"
TILE_GROUPS_JS = r"""
return arguments[0].map(f => {
  const box = f.closest('[componentkey^="easyApplyFieldFocus"]') || f.parentElement;
  const legend = (f.querySelector('legend')?.innerText || box.querySelector('p')?.innerText || '').trim();
  return {legend, options: [...f.querySelectorAll('p')].map(p => (p.innerText || '').trim()).filter(Boolean)};
});
"""
PROGRESS_JS = "return (arguments[0].innerText.match(/\\d+\\/\\d+ p[aá]ginas|\\d+ ?%/) || [''])[0];"


@dataclass(frozen=True)
class ApplyResult:
    status: str
    missing: tuple[str, ...] = ()


def _never_submit() -> bool:
    return False


class EasyApplyFiller:
    """Completa una Solicitud sencilla; la envía solo si está completa y `may_submit()` lo permite."""

    def __init__(self, driver: webdriver.Chrome, may_submit: Callable[[], bool] = _never_submit) -> None:
        self.driver = driver
        self.may_submit = may_submit
        self.cv_path = Path()
        self.job_in_argentina = False

    def __call__(self, job_url: str, cv_path: str) -> ApplyResult:
        self.cv_path = Path(cv_path)
        open_url(self.driver, job_url)
        start = self._start_button()
        if isinstance(start, ApplyResult):
            return start
        if self._open_form() is None:
            return ApplyResult("formulario no encontrado")
        result = self._walk_pages()
        if result.status == READY and self.may_submit():
            return self._submit()
        saved = self._close_and_save()
        return result if saved else ApplyResult("no se pudo guardar", result.missing)

    def _start_button(self) -> WebElement | ApplyResult:
        # "Solicitud sencilla" es un botón; "Continuar" (solicitud ya guardada) es un enlace.
        # Se espera a que aparezca en vez de dormir un tiempo fijo: la página carga a ritmos muy distintos.
        deadline = time.time() + START_WAIT_S
        while time.time() < deadline:
            easy = self.driver.execute_script(START_JS, EASY_APPLY_TEXT.pattern)
            if easy is not None:
                top_card = self.driver.execute_script(TOP_CARD_JS).lower()
                self.job_in_argentina = "argentina" in top_card
                return easy
            time.sleep(1)
        # Las tarjetas de "empleos similares" también dicen "Postulado": solo cuenta la página sin botón.
        page_text = self.driver.find_element(By.TAG_NAME, "main").text[:1500]
        return ApplyResult("ya postulado" if APPLIED_TEXT.search(page_text) else "sin solicitud sencilla")

    def _root(self) -> WebElement | None:
        return self.driver.execute_script(ROOT_JS)

    def _open_form(self) -> WebElement | None:
        """El botón aparece antes de que la página termine de cargar: un clic temprano no abre nada y
        al hidratarse LinkedIn lo reemplaza. Se espera un poco, se lo vuelve a buscar y se hace clic;
        si el formulario no aparece, se reintenta una vez."""
        for _ in range(OPEN_ATTEMPTS):
            time.sleep(2)
            button = self.driver.execute_script(START_JS, EASY_APPLY_TEXT.pattern)
            if button is None:
                return None
            self.driver.execute_script("arguments[0].click()", button)
            if (root := self._wait_for_root()) is not None:
                return root
        return None

    def _wait_for_root(self) -> WebElement | None:
        """El formulario tarda en abrir entre 2 y 8 s según el aviso, y el título aparece antes que
        los campos: se espera a que tenga su botón Siguiente/Revisar/Enviar."""
        deadline = time.time() + FORM_WAIT_S
        while time.time() < deadline:
            root = self._root()
            if root is not None and self._primary_button(root) is not None:
                return root
            time.sleep(1)
        return None

    def _walk_pages(self) -> ApplyResult:
        for _ in range(MAX_PAGES):
            root = self._root()
            if root is None:
                return ApplyResult("formulario no encontrado")
            missing = self._fill_page(root)
            if missing:
                return ApplyResult("guardada incompleta", tuple(missing))
            button = self._primary_button(root)
            if button is None:
                return ApplyResult("guardada incompleta", ("sin botón Siguiente",))
            if SUBMIT_TEXT.match(button.text.strip()):
                return ApplyResult(READY)
            if not self._advance(root, button) and not self._retry_after_fixes():
                return ApplyResult("guardada incompleta", ("LinkedIn marcó un error en la página",))
        return ApplyResult("guardada incompleta", ("demasiadas páginas",))

    def _fill_page(self, root: WebElement) -> list[str]:
        for _ in range(FILL_ATTEMPTS - 1):
            try:
                return self._fill_page_once(root)
            except StaleElementReferenceException:
                time.sleep(1)
                root = self._root() or root
        return self._fill_page_once(root)

    def _fill_page_once(self, root: WebElement) -> list[str]:
        missing = [label for el in root.find_elements(By.CSS_SELECTOR, FIELD_SELECTOR)
                   if (label := self._fill_field(el))]
        missing += self._fill_radio_groups(root)
        missing += self._fill_checkboxes(root)
        return missing

    def _fill_field(self, el: WebElement) -> str | None:
        """Completa un campo vacío. Devuelve su etiqueta si es obligatorio y no hay respuesta."""
        label = self.driver.execute_script(LABEL_JS, el)
        if not el.is_displayed() or self._has_value(el):
            return None
        answer = answer_with_job_location(label, self.job_in_argentina)
        if answer is None:
            return label if self._is_required(el, label) else None
        if el.tag_name == "select":
            return self._choose(el, label, answer)
        el.send_keys(answer if isinstance(answer, str) else answer[0])
        if answer == CITY:
            self._accept_typeahead(el)
        return None

    def _has_value(self, el: WebElement) -> bool:
        if el.tag_name == "select":
            option = Select(el).first_selected_option
            value = option.get_attribute("value") or ""
            return value not in ("", "Select an option") and not PLACEHOLDER_OPTION.match(option.text.strip())
        return bool((el.get_attribute("value") or "").strip())

    @staticmethod
    def _is_required(el: WebElement, label: str) -> bool:
        return bool(el.get_attribute("required")) or el.get_attribute("aria-required") == "true" or label.endswith("*")

    def _choose(self, el: WebElement, label: str, answer: str | tuple[str, ...]) -> str | None:
        select = Select(el)
        index = pick_option([o.text for o in select.options], answer)
        if index is None:
            return label
        select.select_by_index(index)
        return None

    def _accept_typeahead(self, el: WebElement) -> None:
        """Los campos de ciudad muestran sugerencias: se elige la primera de su propia lista."""
        time.sleep(1.5)
        if not self.driver.execute_script(TYPEAHEAD_JS, el):
            el.send_keys(Keys.TAB)

    def _fill_checkboxes(self, root: WebElement) -> list[str]:
        """Marca los de términos/privacidad; otro obligatorio sin marcar queda como faltante."""
        missing = []
        for box in root.find_elements(By.CSS_SELECTOR, "input[type=checkbox]"):
            if box.is_selected():
                continue
            label = self.driver.execute_script(LABEL_JS, box) or self.driver.execute_script(CHECKBOX_CONTEXT_JS, box)
            if CONSENT_LABEL.search(label):
                self.driver.execute_script("arguments[0].click()", box)
            elif self._is_required(box, label):
                missing.append(label)
        return missing

    def _upload_cv(self, root: WebElement) -> bool:
        """El CV elegido no está entre los ya cargados: se sube al campo de currículum de la página."""
        inputs = [el for el in root.find_elements(By.CSS_SELECTOR, "input[type=file]")
                  if CV_LABEL.search(self.driver.execute_script(LABEL_JS, el) or "currículum")]
        if not inputs or not self.cv_path.is_file():
            return False
        inputs[0].send_keys(str(self.cv_path.resolve()))
        time.sleep(4)
        return True

    def _fill_radio_groups(self, root: WebElement) -> list[str]:
        missing = []
        for group in self.driver.execute_script(RADIO_GROUPS_JS, root):
            if group["checked"]:
                continue
            index = self._radio_choice(group)
            if index is None and self._is_cv_group(group) and self._upload_cv(root):
                continue  # LinkedIn deja seleccionado el CV recién subido
            if index is None:
                missing.append(group["legend"] or group["name"])
                continue
            radios = root.find_elements(By.CSS_SELECTOR, f'input[type=radio][name="{group["name"]}"]')
            self.driver.execute_script("arguments[0].click()", radios[index])
        return missing

    @staticmethod
    def _is_cv_group(group: dict) -> bool:
        return any(o.lower().endswith(".pdf") for o in group["options"])

    def _radio_choice(self, group: dict) -> int | None:
        if self._is_cv_group(group):
            return pick_option(group["options"], self.cv_path.name)
        answer = answer_with_job_location(group["legend"], self.job_in_argentina)
        return None if answer is None else pick_option(group["options"], answer)

    @staticmethod
    def _primary_button(root: WebElement) -> WebElement | None:
        buttons = [b for b in root.find_elements(By.TAG_NAME, "button") if b.text.strip()]
        return next((b for b in buttons if SUBMIT_TEXT.match(b.text.strip()) or NEXT_TEXT.match(b.text.strip())), None)

    def _retry_after_fixes(self) -> bool:
        """LinkedIn no dejó avanzar: responde las preguntas de tarjetas que marcó y, si no alcanza, quita
        una entrada incompleta del perfil; después vuelve a intentar."""
        root = self._root()
        if root is not None and self._answer_tile_groups(root):
            button = self._primary_button(root)
            if button is not None and self._advance(root, button):
                return True
        return self._retry_without_incomplete_entry()

    def _answer_tile_groups(self, root: WebElement) -> bool:
        fieldsets = root.find_elements(By.XPATH, TILE_FIELDSETS_XPATH)
        answered = False
        for fieldset, group in zip(fieldsets, self.driver.execute_script(TILE_GROUPS_JS, fieldsets)):
            answer = answer_with_job_location(group["legend"], self.job_in_argentina)
            index = None if answer is None else pick_option(group["options"], answer)
            if index is None:
                continue
            option = next((p for p in fieldset.find_elements(By.TAG_NAME, "p")
                           if p.text.strip() == group["options"][index]), None)
            if option is not None:
                ActionChains(self.driver).move_to_element(option).click().perform()
                answered = True
        time.sleep(1)
        return answered

    def _retry_without_incomplete_entry(self) -> bool:
        """Quita de la solicitud la entrada que quedó abierta con campos obligatorios vacíos y vuelve a avanzar."""
        root = self._root()
        if root is None:
            return False
        remove = next((b for b in root.find_elements(By.TAG_NAME, "button")
                       if REMOVE_ENTRY_TEXT.match(b.text.strip()) and b.is_displayed()), None)
        if remove is None:
            return False
        log.info("Solicitud sencilla: quito una entrada incompleta del perfil (%s).", remove.text.strip())
        self.driver.execute_script("arguments[0].click()", remove)
        time.sleep(2)
        confirm = next((b for b in self.driver.find_elements(By.TAG_NAME, "button")
                        if CONFIRM_REMOVE_TEXT.match((b.text or "").strip()) and b.is_displayed()), None)
        if confirm is not None:
            self.driver.execute_script("arguments[0].click()", confirm)
            time.sleep(2)
        root = self._root()
        button = self._primary_button(root) if root is not None else None
        return button is not None and self._advance(root, button)

    def _advance(self, root: WebElement, button: WebElement) -> bool:
        """Clic en Siguiente/Revisar. False si la página no cambió (LinkedIn marcó un error)."""
        before = self.driver.execute_script(PROGRESS_JS, root)
        heading = root.text[:200]
        self.driver.execute_script("arguments[0].click()", button)
        time.sleep(3)
        new_root = self._root()
        if new_root is None:
            return False
        return self.driver.execute_script(PROGRESS_JS, new_root) != before or new_root.text[:200] != heading

    def _submit(self) -> ApplyResult:
        """Clic en "Enviar solicitud" y confirma con el mensaje de LinkedIn. Si no se confirma y el
        formulario sigue abierto, se guarda como antes para revisarlo a mano."""
        root = self._root()
        button = self._primary_button(root) if root is not None else None
        if button is None or not SUBMIT_TEXT.match(button.text.strip()):
            return ApplyResult(READY) if self._close_and_save() else ApplyResult("no se pudo guardar")
        self.driver.execute_script("arguments[0].click()", button)
        time.sleep(5)
        page = self.driver.find_element(By.TAG_NAME, "body").text
        if SUBMITTED_TEXT.search(page):
            return ApplyResult(SUBMITTED)
        if self._root() is not None and self._close_and_save():
            return ApplyResult(READY, ("LinkedIn no confirmó el envío",))
        return ApplyResult("envío sin confirmar")

    def _close_and_save(self) -> bool:
        modal = self.driver.execute_script(MODAL_JS)
        if modal is None:
            return False
        close = next((b for b in modal.find_elements(By.TAG_NAME, "button")
                      if CLOSE_LABEL.match((b.get_attribute("aria-label") or "").strip()) and b.is_displayed()), None)
        if close is None:
            return False
        self.driver.execute_script("arguments[0].click()", close)
        time.sleep(2)
        save = next((b for b in self.driver.find_elements(By.TAG_NAME, "button")
                     if SAVE_TEXT.match((b.text or "").strip()) and b.is_displayed()), None)
        if save is None:
            return False
        self.driver.execute_script("arguments[0].click()", save)
        time.sleep(2)
        return True


def safe_apply(filler: EasyApplyFiller, job_url: str, cv_path: str) -> ApplyResult:
    try:
        return filler(job_url, cv_path)
    except WebDriverException as exc:
        log.warning("Solicitud sencilla: falló %s (%s).", job_url, exc.msg)
        return ApplyResult("error")
