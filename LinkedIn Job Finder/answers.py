"""answers.py - Respuestas para formularios de Solicitud sencilla, solo con datos verificados.

Cada regla mira la etiqueta de la pregunta. Lo que no tiene regla queda sin responder y el
formulario se guarda para que Adriel lo complete a mano: nunca se inventa un dato.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HEADLINE = "Backend Developer | Python · FastAPI · PostgreSQL | Testing & QA"
CITY = "Córdoba, Córdoba, Argentina"
COVER_LETTER = (
    "Hola, me postulo a esta búsqueda. Creé y desarrollo SE-AR Manager, un SaaS multi-tenant en "
    "Python/FastAPI, PostgreSQL y Flutter que usan negocios reales, con más de 2.300 tests y CI/CD. "
    "Inglés C1. Disponibilidad inmediata. Saludos, Adriel López."
)
YES = ("sí", "si", "yes")
NO = ("no",)
# Años con la tecnología: el stack de SE-AR Manager y los cursos (1 año); lo demás no se responde.
CORE_STACK = re.compile(
    r"python|fastapi|sql|postgres|git\b|docker|api|rest|backend|back-end|testing|qa|pytest|linux|flutter|"
    r"software|programaci|desarrollo|development",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Rule:
    pattern: re.Pattern[str]
    answer: str | tuple[str, ...]


def _rule(pattern: str, answer: str | tuple[str, ...]) -> Rule:
    return Rule(re.compile(pattern, re.IGNORECASE), answer)


RULES: tuple[Rule, ...] = (
    _rule(r"headline|titular", HEADLINE),
    _rule(r"cover letter|carta de presentaci", COVER_LETTER),
    _rule(r"location \(city\)|ciudad|city", CITY),
    _rule(r"(authori[sz]ed|autorizad|derecho).*(work|trabajar).*argentin|legally.*argentin", YES),
    _rule(r"sponsor|patrocin|visa", NO),
    _rule(r"remot|home office", YES),
    _rule(r"(h[ií]brid|presencial|on-?site|oficina).*c[oó]rdoba|c[oó]rdoba.*(h[ií]brid|presencial|oficina)", YES),
    _rule(r"(english|ingl[eé]s).*(level|nivel|proficien|dominio)|(level|nivel).*(english|ingl[eé]s)",
          ("c1", "advanced", "avanzado", "profesional", "professional", "fluent")),
    # Pretensión ya usada en sus postulaciones (USD 900/mes); en pesos no se responde.
    _rule(r"^(?!.*(\bars\b|pesos|reviewed|aligned|revisaste|de acuerdo)).*"
          r"(salary|salario|pretensi|expected .*income|remuneraci|compensation)", "900"),
    _rule(r"start date|fecha de inicio|cu[aá]ndo (pod|pued)|notice period|preaviso|"
          r"disponibilidad (para (empezar|comenzar|incorporarte)|de inicio)", "Inmediata"),
)
YEARS_QUESTION = re.compile(r"(years|años).*(experien)|(experien).*(years|años)", re.IGNORECASE)
EXPERIENCE_QUESTION = re.compile(r"experien|hands-on|have you (used|worked)|ten[eé]s conocimiento|conocimientos? (de|en)",
                                 re.IGNORECASE)
# Tecnologías que no están en su perfil: esas preguntas las contesta Adriel ("API Gateway" de AWS no es su API).
OTHER_STACK = re.compile(
    r"\baws\b|azure|gcp|\bjava\b|javascript|typescript|react|vue|angular|node|\.net|c#|php|ruby|\bgo\b|golang|"
    r"kotlin|swift|salesforce|\bsap\b|kubernetes|terraform|spark|scala|rust",
    re.IGNORECASE,
)
PRODUCTION_WORK = re.compile(r"debug|troubleshoot|producci[oó]n|production|database|bases? de datos", re.IGNORECASE)
WILLINGNESS = re.compile(
    r"willing|dispuest[oa]|background check|antecedentes|reviewed .*requirements|aligned with your expectations|"
    r"available|disponib|comfortable to work|home office setup|stable internet|conexi[oó]n estable",
    re.IGNORECASE,
)


def answer_for(label: str) -> str | tuple[str, ...] | None:
    """Respuesta para la pregunta `label`; None si no hay un dato verificado para darla."""
    if YEARS_QUESTION.search(label):
        return "1" if CORE_STACK.search(label) and not OTHER_STACK.search(label) else None
    rule = next((rule.answer for rule in RULES if rule.pattern.search(label)), None)
    if rule is not None:
        return rule
    if EXPERIENCE_QUESTION.search(label):
        known = (CORE_STACK.search(label) or PRODUCTION_WORK.search(label)) and not OTHER_STACK.search(label)
        return YES if known else None
    return YES if WILLINGNESS.search(label) else None


def pick_option(options: list[str], answer: str | tuple[str, ...]) -> int | None:
    """Índice de la opción que corresponde a la respuesta (exacta primero, después parcial)."""
    wanted = (answer,) if isinstance(answer, str) else answer
    lowered = [o.strip().lower() for o in options]
    for word in wanted:
        if word.lower() in lowered:
            return lowered.index(word.lower())
    for word in wanted:
        hit = next((i for i, o in enumerate(lowered) if word.lower() in o), None)
        if hit is not None:
            return hit
    return None
