"""easy_apply.py - Completa la Solicitud sencilla de LinkedIn y la GUARDA sin enviarla.

Avanza página por página respondiendo solo lo que answers.py sabe con certeza. Se detiene
ante la primera pregunta obligatoria sin respuesta o al llegar a "Enviar solicitud", y en
ambos casos cierra el formulario eligiendo "Guardar": la solicitud queda en LinkedIn →
Mis empleos → En curso, para que Adriel la revise y la envíe desde el celular.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import Select

from answers import answer_for, pick_option
from feed import open_url

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

ROOT_JS = r"""
const h = [...document.querySelectorAll('h1,h2,h3')].find(t => /^(Aplicar a|Apply to|Solicitar en)/i.test((t.innerText||'').trim()));
if (!h) return null;
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
PROGRESS_JS = "return (arguments[0].innerText.match(/\\d+\\/\\d+ p[aá]ginas|\\d+ ?%/) || [''])[0];"


@dataclass(frozen=True)
class ApplyResult:
    status: str
    missing: tuple[str, ...] = ()


class EasyApplyFiller:
    """Completa y guarda una Solicitud sencilla. Nunca toca "Enviar solicitud"."""

    def __init__(self, driver: webdriver.Chrome) -> None:
        self.driver = driver
        self.cv_name = ""

    def __call__(self, job_url: str, cv_name: str) -> ApplyResult:
        self.cv_name = cv_name
        open_url(self.driver, job_url)
        time.sleep(6)
        start = self._start_button()
        if isinstance(start, ApplyResult):
            return start
        self.driver.execute_script("arguments[0].click()", start)
        time.sleep(4)
        if self._root() is None:
            return ApplyResult("formulario no encontrado")
        result = self._walk_pages()
        saved = self._close_and_save()
        return result if saved else ApplyResult("no se pudo guardar", result.missing)

    def _start_button(self) -> WebElement | ApplyResult:
        # "Solicitud sencilla" es un botón; "Continuar" (solicitud ya guardada) es un enlace.
        buttons = self.driver.find_elements(By.CSS_SELECTOR, "button, a")
        easy = next((b for b in buttons if EASY_APPLY_TEXT.match((b.text or "").strip())), None)
        if easy is not None:
            return easy
        # Las tarjetas de "empleos similares" también dicen "Postulado": solo cuenta la página sin botón.
        page_text = self.driver.find_element(By.TAG_NAME, "main").text[:1500]
        return ApplyResult("ya postulado" if APPLIED_TEXT.search(page_text) else "sin solicitud sencilla")

    def _root(self) -> WebElement | None:
        return self.driver.execute_script(ROOT_JS)

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
                return ApplyResult("guardada lista para enviar")
            if not self._advance(root, button):
                return ApplyResult("guardada incompleta", ("LinkedIn marcó un error en la página",))
        return ApplyResult("guardada incompleta", ("demasiadas páginas",))

    def _fill_page(self, root: WebElement) -> list[str]:
        missing = [label for el in root.find_elements(By.CSS_SELECTOR, FIELD_SELECTOR)
                   if (label := self._fill_field(el))]
        missing += self._fill_radio_groups(root)
        return missing

    def _fill_field(self, el: WebElement) -> str | None:
        """Completa un campo vacío. Devuelve su etiqueta si es obligatorio y no hay respuesta."""
        label = self.driver.execute_script(LABEL_JS, el)
        if not el.is_displayed() or self._has_value(el):
            return None
        answer = answer_for(label)
        if answer is None:
            return label if self._is_required(el, label) else None
        if el.tag_name == "select":
            return self._choose(el, label, answer)
        el.send_keys(answer if isinstance(answer, str) else answer[0])
        self._accept_typeahead(el)
        return None

    def _has_value(self, el: WebElement) -> bool:
        if el.tag_name == "select":
            return Select(el).first_selected_option.get_attribute("value") not in ("", "Select an option")
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
        """Los campos de ciudad muestran sugerencias: se elige la primera."""
        time.sleep(1.5)
        options = self.driver.find_elements(By.CSS_SELECTOR, "[role=option]")
        if options:
            self.driver.execute_script("arguments[0].click()", options[0])
        else:
            el.send_keys(Keys.TAB)

    def _fill_radio_groups(self, root: WebElement) -> list[str]:
        missing = []
        for group in self.driver.execute_script(RADIO_GROUPS_JS, root):
            if group["checked"]:
                continue
            index = self._radio_choice(group)
            if index is None:
                missing.append(group["legend"] or group["name"])
                continue
            radios = root.find_elements(By.CSS_SELECTOR, f'input[type=radio][name="{group["name"]}"]')
            self.driver.execute_script("arguments[0].click()", radios[index])
        return missing

    def _radio_choice(self, group: dict) -> int | None:
        if any(o.lower().endswith(".pdf") for o in group["options"]):
            return pick_option(group["options"], self.cv_name)
        answer = answer_for(group["legend"])
        return None if answer is None else pick_option(group["options"], answer)

    @staticmethod
    def _primary_button(root: WebElement) -> WebElement | None:
        buttons = [b for b in root.find_elements(By.TAG_NAME, "button") if b.text.strip()]
        return next((b for b in buttons if SUBMIT_TEXT.match(b.text.strip()) or NEXT_TEXT.match(b.text.strip())), None)

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


def safe_apply(filler: EasyApplyFiller, job_url: str, cv_name: str) -> ApplyResult:
    try:
        return filler(job_url, cv_name)
    except WebDriverException as exc:
        log.warning("Solicitud sencilla: falló %s (%s).", job_url, exc.msg)
        return ApplyResult("error")
