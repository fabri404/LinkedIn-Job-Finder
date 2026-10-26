"""answers.py - Respuestas para formularios de Solicitud sencilla, solo con datos verificados.

Cada regla mira la etiqueta de la pregunta. Lo que no tiene regla queda sin responder y el
formulario se guarda para que Adriel lo complete a mano: nunca se inventa un dato.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HEADLINE = "Backend Developer | Python · FastAPI · PostgreSQL | Testing & QA"
CITY = "Córdoba, Córdoba, Argentina"
LINKEDIN_URL = "https://www.linkedin.com/in/adriel-lopez"
GITHUB_URL = "https://github.com/fabri404"
# Años de experiencia con su stack (SE-AR Manager y cursos): una pregunta "¿al menos N años?" con
# N mayor se contesta que no.
STACK_YEARS = 1
COVER_LETTER = (
    "Hola, me postulo a esta búsqueda. Creé y desarrollo SE-AR Manager, un SaaS multi-tenant en "
    "Python/FastAPI, PostgreSQL y Flutter que usan negocios reales, con más de 2.300 tests y CI/CD. "
    "Inglés C1. Disponibilidad inmediata. Saludos, Adriel López."
)
YES = ("sí", "si", "yes")
NO = ("no",)
# Preguntas demográficas voluntarias (EEO): siempre "prefiero no decir", la opción que existe para eso.
DECLINE = ("decline to self-identify", "i don't wish to answer", "i do not want to answer", "prefer not to say",
           "prefiero no decir", "prefiero no responder", "no deseo responder", "decline", "prefer not")
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
    _rule(r"github", GITHUB_URL),
    _rule(r"linkedin", LINKEDIN_URL),
    _rule(r"portfolio|portafolio|website|sitio web|p[aá]gina web|personal site", GITHUB_URL),
    _rule(r"(live|living|based|located|resid|viv[ií]s|vives|vive).*argentin|argentin.*(resid|based)", YES),
    _rule(r"cover letter|carta de presentaci", COVER_LETTER),
    _rule(r"location \(city\)|\bciudad\b|\bcity\b", CITY),
    _rule(r"(authori[sz]ed|autorizad|derecho).*(work|trabajar).*argentin|legally.*argentin", YES),
    _rule(r"sponsor|patrocin|visa", NO),
    _rule(r"remot|home office", YES),
    _rule(r"(h[ií]brid|presencial|on-?site|oficina).*c[oó]rdoba|c[oó]rdoba.*(h[ií]brid|presencial|oficina)", YES),
    # Máximo nivel educativo *completado*: secundario (la Tecnicatura en la UTN está en curso hasta 2027).
    _rule(r"(highest|m[aá]ximo|mayor) (level of )?(education|nivel (de estudios|educativo))",
          ("high school", "secundari", "secondary", "bachiller")),
    # Preferencia: fuera de Córdoba solo remoto, así que no se muda.
    _rule(r"relocat|reubic|mudarte|mudanza|trasladarte", ("not open", "no estoy", "no")),
    # No es veterano (de EE.UU. ni de otro país): es un dato cierto, no hace falta declinar.
    _rule(r"\bveteran", ("i am not a protected veteran", "not a protected veteran", "no", *DECLINE)),
    _rule(r"\b(race|ethnicity|etnia|raza|gender|g[eé]nero|sexo|disabilit\w*|discapacidad|"
          r"sexual orientation|orientaci[oó]n sexual|pronouns|pronombres)\b", DECLINE),
    _rule(r"(communicat|comunicar|fluent|fluid).*(english|ingl[eé]s)|(english|ingl[eé]s).*(communicat|comunicar|fluent)",
          YES),
    _rule(r"(english|ingl[eé]s).*(level|nivel|proficien|dominio)|(level|nivel).*(english|ingl[eé]s)",
          ("c1", "advanced", "avanzado", "profesional", "professional", "fluent", *YES)),
    # Pretensión ya usada en sus postulaciones (USD 900/mes); en pesos no se responde.
    _rule(r"^(?!.*(\bars\b|pesos|reviewed|aligned|revisaste|de acuerdo)).*"
          r"(salary|salario|pretensi|pretendid|sueldo|expected .*income|remuneraci|compensation)", "900"),
    _rule(r"start date|fecha de inicio|cu[aá]ndo (pod|pued)|notice period|preaviso|timing to start|"
          r"when (can|could) you start|start a new position|incorporaci[oó]n|"
          r"disponibilidad (para (empezar|comenzar|incorporarte)|de inicio)", ("Inmediata", "inmediat", "immediate", "asap", "lo antes posible")),
)
YEARS_QUESTION = re.compile(r"\b(years?|años?)\b.*(experien)|(experien).*\b(years?|años?)\b", re.IGNORECASE)
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
    r"available|disponib|comfortable to work|home office setup|stable internet|conexi[oó]n (a internet )?estable|"
    r"conexi[oó]n a internet",
    re.IGNORECASE,
)


MIN_YEARS = re.compile(r"(\d+)\s*\+?\s*(años?|years?|yrs?)\b", re.IGNORECASE)


# "¿Estás autorizado a trabajar en la ubicación del empleo?": sí solo si el aviso es en Argentina.
JOB_LOCATION_AUTHORIZATION = re.compile(
    r"authori[sz]ed to work in the job'?s location|autorizad[oa] (para|a) trabajar en (la|esta) ubicaci[oó]n",
    re.IGNORECASE)


def answer_with_job_location(label: str, job_in_argentina: bool) -> str | tuple[str, ...] | None:
    """answer_for, más las preguntas que dependen de dónde es el aviso."""
    if JOB_LOCATION_AUTHORIZATION.search(label):
        return YES if job_in_argentina else None
    return answer_for(label)


def answer_for(label: str) -> str | tuple[str, ...] | None:
    """Respuesta para la pregunta `label`; None si no hay un dato verificado para darla."""
    if YEARS_QUESTION.search(label):
        return _years_answer(label)
    rule = next((rule.answer for rule in RULES if rule.pattern.search(label)), None)
    if rule is not None:
        return rule
    if EXPERIENCE_QUESTION.search(label):
        known = (CORE_STACK.search(label) or PRODUCTION_WORK.search(label)) and not OTHER_STACK.search(label)
        return YES if known else None
    return YES if WILLINGNESS.search(label) else None


def _years_answer(label: str) -> tuple[str, ...] | None:
    """"1" para un campo numérico; para Sí/No ("¿al menos 3 años con Python?"), sí solo si llega."""
    if not CORE_STACK.search(label) or OTHER_STACK.search(label):
        return None
    asked = MIN_YEARS.search(label)
    meets = asked is None or int(asked.group(1)) <= STACK_YEARS
    return (str(STACK_YEARS), *(YES if meets else NO))


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
