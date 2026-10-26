"""relevance.py - Cuánto encaja una vacante con el perfil de Adriel (Python/FastAPI, QA, junior).

No descarta nada: ordena la cola para que los borradores más acordes salgan primero cuando el cupo
diario no alcanza para todos.
"""

from __future__ import annotations

import re

from classifier import CORDOBA_TERMS, JobPosting, is_preferred_remote_country, split_post, work_modality

# (peso, patrón). Cada patrón suma una vez en el cuerpo y otra en el puesto: el puesto pesa doble.
RELEVANCE_RULES: tuple[tuple[int, re.Pattern[str]], ...] = (
    (3, re.compile(r"\b(python|fastapi|django|flask)\b")),
    (2, re.compile(r"\b(qa|tester|testing|automation|automatizaci[oó]n|selenium|playwright|pytest)\b")),
    (1, re.compile(r"\b(sql|postgres(ql)?|docker|api rest|apis?|back[- ]?end)\b")),
    (2, re.compile(r"\b(junior|jr\.?|trainee|pasant[eí]a?|sin experiencia|entry level)\b")),
    (1, re.compile(r"\b(remoto|remote|home office)\b")),
    (1, re.compile(r"\bc[oó]rdoba\b")),
    # Lookarounds en vez de \b: ".net" y "c#" empiezan o terminan con un símbolo.
    (-3, re.compile(r"(?<!\w)(java|asp\.net|\.net|c#|php|kotlin|sap|abap|salesforce|cobol|cnc)(?![\w#])")),
    (-1, re.compile(r"\b(swift|ios|android|flutter|angular|unity)\b")),
)


def relevance_score(posting: JobPosting) -> int:
    """Suma de reglas sobre el cuerpo del post y sobre el puesto extraído, más la ubicación preferida."""
    body = split_post(posting.text)[1].lower()
    title = posting.role_title.lower()
    rules = sum(weight * (bool(rule.search(body)) + bool(rule.search(title))) for weight, rule in RELEVANCE_RULES)
    return rules + location_bonus(body)


def location_bonus(body: str) -> int:
    """Preferencias de Adriel: presencial/híbrido en Córdoba, o remoto en Chile, Paraguay, Colombia,
    España o México."""
    in_cordoba = any(term in body for term in CORDOBA_TERMS)
    if in_cordoba and work_modality(body) in ("hybrid", "onsite"):
        return 3
    return 2 if is_preferred_remote_country(body) else 0
