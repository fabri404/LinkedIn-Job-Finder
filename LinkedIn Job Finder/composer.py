"""composer.py - Arma asunto, cuerpo y CV de cada postulación (plantilla genérica §3)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from classifier import JobPosting, is_dev_title

CANDIDATE_NAME = "Adriel López"
SIGNATURE = (
    "Adriel Fabricio López\n"
    "fabri404lopez@gmail.com · +54 9 351 714-1146 · "
    "linkedin.com/in/adriel-lopez · github.com/fabri404"
)
SUBJECT_TAIL = {
    "es": "(Python/FastAPI · SaaS en producción)",
    "en": "(Python/FastAPI · SaaS in production)",
}
DEFAULT_ROLE = {
    ("backend", "es"): "Desarrollador Backend Python",
    ("backend", "en"): "Backend Python Developer",
    ("qa", "es"): "QA Automation",
    ("qa", "en"): "QA Automation Engineer",
}
# El posicionamiento nunca dice "junior" ni "trainee", aunque el aviso lo diga.
LEVEL_WORDS = re.compile(
    r"\b(junior|jr\.?|trainee|traineer|entry[- ]level|semi ?senior|ssr|senior|sr\.?)\b", re.I
)

BULLETS = {
    ("backend", "es"): (
        "• Implementé auth con JWT/MFA, roles y permisos, webhooks de pago firmados "
        "e integración con WhatsApp Cloud API.\n"
        "• Mantengo más de 2.300 tests automatizados y CI/CD con GitHub Actions hacia Fly.io y Vercel."
    ),
    ("qa", "es"): (
        "• Escribí tests de autorización y aislamiento multi-tenant, flujos e2e y pruebas de carga con k6.\n"
        "• Tengo formación en QA manual (CoderHouse): diseño de casos y reporte de bugs."
    ),
    ("backend", "en"): (
        "• I implemented JWT/MFA auth, roles and permissions, signed payment webhooks "
        "and WhatsApp Cloud API integration.\n"
        "• I maintain 2,300+ automated tests and CI/CD with GitHub Actions to Fly.io and Vercel."
    ),
    ("qa", "en"): (
        "• I wrote authorization and multi-tenant isolation tests, e2e flows and k6 load tests.\n"
        "• I have manual QA training (CoderHouse): test case design and bug reporting."
    ),
}

BODY_ES = """Hola,

Me postulo a la búsqueda de {role} publicada en LinkedIn.

En pocas palabras:
• Creé y desarrollo SE-AR Manager, un SaaS multi-tenant en Python/FastAPI, PostgreSQL y Flutter que usan negocios reales (searmanager.com.ar).
{bullets}
• Estudio la Tecnicatura en Programación (UTN) y tengo inglés C1. Estoy en Córdoba, Argentina, con disponibilidad para trabajo remoto.

Adjunto mi CV. Puedo mostrar el código del producto en una entrevista técnica.

Muchas gracias,
{signature}"""

BODY_EN = """Hi,

I'm applying for the {role} position posted on LinkedIn.

• I founded and develop SE-AR Manager, a multi-tenant SaaS in Python/FastAPI, PostgreSQL and Flutter used by real businesses (searmanager.com.ar).
{bullets}
• I'm studying Programming at UTN (Argentina), my English level is C1, and I'm based in Córdoba, available for remote work.

My CV is attached; I'm happy to walk through the code in a technical interview.

Best regards,
{signature}"""


@dataclass(frozen=True)
class Application:
    to: str
    subject: str
    body: str
    cv_path: Path
    role: str


URL_PATTERN = re.compile(r"https?://\S+|lnkd\.in/\S+")
ROLE_CUT = re.compile(r",| con | para | que | with | to |#", re.IGNORECASE)
# Modalidad pegada al puesto: "Desarrollador Java Ssr/Sr - 100% remoto".
MODALITY_SUFFIX = re.compile(
    r"\s*[-–|(]?\s*(?:100\s*%\s*)?(?:remoto|remote|h[ií]brido|hybrid|presencial|home office)\b.*$", re.IGNORECASE
)
LEADING_FILLER = re.compile(
    r"^(?:(?:activa|activo|incorporar|sumar|contratar|desarrollar:?|cargo:|puesto:|para un cliente|"
    r"para nuestro cliente|de|un/a|un\(a\)|una/o|"
    r"una|un|a|el/la|la|el|an)\s+)+",
    re.IGNORECASE
)


def clean_role(role_title: str, track: str, language: str) -> str:
    """Puesto para asunto y cuerpo: sin nivel, cortado en la primera cláusula, y el
    puesto por defecto si lo extraído no parece un rol de desarrollo ("hashtag", frases)."""
    role = ROLE_CUT.split(LEVEL_WORDS.sub("", URL_PATTERN.sub("", role_title)))[0]
    if role.count("(") > role.count(")"):
        role = role[: role.rindex("(")]
    role = MODALITY_SUFFIX.sub("", role)
    role = re.sub(r"\s*/\s*\(", " (", role)
    role = re.sub(r"\s+(?:en|de|desde)\s+(c[oó]rdoba|caba|buenos aires|rosario|argentina)\b.*$", "", role,
                  flags=re.IGNORECASE)
    role = re.sub(r"[^\w)\]]+$", "", role)  # emojis y símbolos al final ("Sistemas 🌐 📲")
    role = re.sub(r"\s{2,}", " ", role).strip(" -–:,/!¡")
    role = re.sub(r"(?:\s+(?:o|or|y|and)|\s*[/|-])+$", "", role)
    role = LEADING_FILLER.sub("", role)
    if len(role) < 4 or not is_dev_title(role):
        return DEFAULT_ROLE[(track, language)]
    return role


def build_subject(posting: JobPosting, role: str) -> str:
    if posting.subject_hint:
        return posting.subject_hint
    if posting.asks_role_in_subject:
        return f"{role} - {CANDIDATE_NAME}"
    prefix = "Postulación" if posting.language == "es" else "Application"
    return f"{prefix}: {role}, {CANDIDATE_NAME} {SUBJECT_TAIL[posting.language]}"


def build_body(posting: JobPosting, role: str) -> str:
    template = BODY_ES if posting.language == "es" else BODY_EN
    bullets = BULLETS[(posting.track, posting.language)]
    return template.format(role=role, bullets=bullets, signature=SIGNATURE)


def select_cv(cv_dir: Path, track: str, language: str) -> Path:
    kind = "QA" if track == "qa" else "Backend"
    return cv_dir / f"CV_Adriel_Lopez_{kind}_{language.upper()}.pdf"


def compose(posting: JobPosting, to: str, cv_dir: Path) -> Application:
    role = clean_role(posting.role_title, posting.track, posting.language)
    return Application(
        to=to,
        subject=build_subject(posting, role),
        body=build_body(posting, role),
        cv_path=select_cv(cv_dir, posting.track, posting.language),
        role=role,
    )


LINKEDIN_MESSAGE = ("Hola {name}, vi tu búsqueda de {role}. Soy desarrollador backend Python (FastAPI, PostgreSQL) "
                    "en Córdoba y desarrollo un SaaS propio en producción. Me gustaría postularme: "
                    "¿te puedo enviar mi CV? ¡Gracias!")


def linkedin_message(first_name: str, vacancy: JobPosting) -> str:
    """Mensaje corto para que Adriel lo pegue en LinkedIn cuando el recruiter no deja email."""
    role = clean_role(vacancy.role_title, vacancy.track, "es")
    return re.sub(r"\s+,", ",", LINKEDIN_MESSAGE.format(name=first_name, role=role))
