"""relevance.py - Cuánto encaja una vacante con el perfil de Adriel (Python/FastAPI, QA, junior).

Ordena la cola (los más acordes salen primero) y además filtra: debajo de MIN_DRAFT_RELEVANCE no se
arma borrador y debajo de MIN_EASY_APPLY_RELEVANCE no se envía la Solicitud sencilla; quedan en la
lista para revisar a mano. Medido 25–28/10: 42 % de la cola tenía relevancia ≤ 2. Prioridades: nivel trainee/junior/semi senior (o sin aclarar) y
ubicación de adentro hacia afuera: Córdoba → resto de Argentina → Chile, Paraguay, Colombia, España,
México → el resto.
"""

from __future__ import annotations

import re

from classifier import (
    CORDOBA_TERMS,
    JobPosting,
    is_preferred_remote_country,
    is_profile_title,
    split_post,
    work_modality,
)

# (peso, patrón). Cada patrón suma una vez en el cuerpo y otra en el puesto: el puesto pesa doble.
RELEVANCE_RULES: tuple[tuple[int, re.Pattern[str]], ...] = (
    (3, re.compile(r"\b(python|fastapi|django|flask)\b")),
    (2, re.compile(r"\b(qa|tester|testing|automation|automatizaci[oó]n|selenium|playwright|pytest)\b")),
    (1, re.compile(r"\b(sql|postgres(ql)?|docker|api rest|apis?|back[- ]?end)\b")),
    (3, re.compile(r"\b(junior|jr\.?|trainee|pasant[eí]a?|sin experiencia|entry level|primer empleo)\b")),
    (2, re.compile(r"\b(semi ?senior|ssr\.?|semisenior|mid[- ]level)\b")),
    # Lookarounds en vez de \b: ".net" y "c#" empiezan o terminan con un símbolo.
    (-3, re.compile(r"(?<!\w)(java|asp\.net|\.net|c#|php|kotlin|sap|abap|salesforce|cobol|cnc|oracle forms|"
                    r"sql server dba|dynamics 365|odoo)(?![\w#])")),
    (-1, re.compile(r"\b(swift|ios|android|flutter|angular|unity)\b")),
)
MIN_DRAFT_RELEVANCE = 2
MIN_EASY_APPLY_RELEVANCE = 3
# Stack que Adriel no usa: en el puesto mismo descarta aunque el resto sume ("Desarrollador .NET Jr").
OFF_STACK_TITLE = re.compile(
    r"(?<!\w)(java|\.net|c#|php|kotlin|android|ios|swift|oracle|sap|abap|salesforce|cobol|dynamics|odoo)(?![\w#])")
# "Engineer"/"Ingeniero" sin nivel de entrada suele ser un puesto mid/senior: un poco más abajo.
ENGINEER_TITLE = re.compile(r"\b(engineer|ingenier[oa])\b")
ENTRY_LEVEL = re.compile(r"\b(junior|jr\.?|trainee|pasant|semi ?senior|ssr|entry level|i)\b")
ARGENTINA_PLACES = ("argentina", "buenos aires", "caba", "rosario", "mendoza", "santa fe", "tucumán", "#arg")


def relevance_score(posting: JobPosting) -> int:
    """Suma de reglas sobre el cuerpo del post y sobre el puesto extraído, más la ubicación preferida."""
    body = split_post(posting.text)[1].lower()
    title = posting.role_title.lower()
    rules = sum(weight * (bool(rule.search(body)) + bool(rule.search(title))) for weight, rule in RELEVANCE_RULES)
    engineer = -2 if ENGINEER_TITLE.search(title) and not ENTRY_LEVEL.search(title) else 0
    return rules + engineer + location_bonus(body)


def location_bonus(body: str) -> int:
    """De adentro hacia afuera: Córdoba (más si es presencial/híbrido) → Argentina → países preferidos."""
    if any(term in body for term in CORDOBA_TERMS):
        return 6 if work_modality(body) in ("hybrid", "onsite") else 5
    if any(place in body for place in ARGENTINA_PLACES):
        return 3
    return 2 if is_preferred_remote_country(body) else 0


def is_off_stack_title(title: str) -> bool:
    return bool(OFF_STACK_TITLE.search(title.lower()))


def fit_for_draft(posting: JobPosting) -> tuple[bool, int]:
    """(¿se arma el borrador?, relevancia). Hace falta un puesto IT legible ("Alert" o "un/a" no lo son),
    sin stack ajeno y relevancia mínima."""
    score = relevance_score(posting)
    title = posting.role_title
    ok = is_profile_title(title) and not is_off_stack_title(title) and score >= MIN_DRAFT_RELEVANCE
    return ok, score


def fit_for_easy_apply(posting: JobPosting) -> tuple[bool, int]:
    """(¿se envía la Solicitud sencilla?, relevancia)."""
    score = relevance_score(posting)
    return not is_off_stack_title(posting.role_title) and score >= MIN_EASY_APPLY_RELEVANCE, score
