"""
detector.py - Detecta si un post es relevante y determina el idioma.
"""

import re

# Palabras comunes para detectar idioma
SPANISH_MARKERS = [
    "busco", "buscamos", "incorporar", "sumate", "equipo", "empresa",
    "oportunidad", "laboral", "puesto", "vacante", "requisitos",
    "experiencia", "conocimientos", "desarrollador", "programador",
    "enviar", "postularse", "interesados", "contacto", "trabajo",
    "remoto", "presencial", "híbrido", "sueldo", "salario",
]

ENGLISH_MARKERS = [
    "hiring", "looking for", "position", "role", "team", "company",
    "opportunity", "requirements", "experience", "developer", "engineer",
    "apply", "remote", "onsite", "hybrid", "salary", "job", "opening",
    "candidate", "we are", "join us", "send your",
]

# Patrones de email
EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

# Emails a ignorar (no son de reclutadores)
BLACKLIST_DOMAINS = [
    "example.com", "test.com", "linkedin.com", "facebook.com",
    "twitter.com", "instagram.com", "google.com", "sentry.io",
]


def extract_emails(text: str) -> list[str]:
    """Extrae emails válidos de un texto, filtrando dominios no deseados."""
    raw_emails = EMAIL_PATTERN.findall(text)
    valid = []
    for email in raw_emails:
        email = email.lower().strip().rstrip(".")
        domain = email.split("@")[1] if "@" in email else ""
        if domain and domain not in BLACKLIST_DOMAINS:
            valid.append(email)
    return list(set(valid))


def is_relevant_post(text: str, keywords: list[str], min_matches: int = 2) -> bool:
    """
    Determina si un post es relevante según las keywords.
    Requiere al menos `min_matches` coincidencias para reducir falsos positivos.
    """
    text_lower = text.lower()
    matches = sum(1 for kw in keywords if kw in text_lower)
    return matches >= min_matches


def detect_language(text: str) -> str:
    """
    Detecta si el post está en español o inglés.
    Retorna 'es' o 'en'.
    """
    text_lower = text.lower()
    es_score = sum(1 for word in SPANISH_MARKERS if word in text_lower)
    en_score = sum(1 for word in ENGLISH_MARKERS if word in text_lower)

    # Default a español si hay empate (contexto Argentina)
    return "en" if en_score > es_score else "es"


def analyze_post(text: str, keywords: list[str], min_matches: int = 2) -> dict | None:
    """
    Analiza un post completo. Retorna un dict con info si es relevante
    y contiene al menos un email, o None si no aplica.
    """
    if not is_relevant_post(text, keywords, min_matches):
        return None

    emails = extract_emails(text)
    if not emails:
        return None

    language = detect_language(text)

    return {
        "emails": emails,
        "language": language,
        "preview": text[:200].replace("\n", " "),
    }
