"""classifier.py - Decide si un post del feed es una búsqueda laboral a la que postular.

Combina el puntaje por patrones de la v2 (¿es una oferta real?) con los filtros del
perfil (rol, nivel, ubicación) y extrae lo necesario para postular: emails, idioma,
puesto y asunto pedido por el post.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

JOB_SCORE_THRESHOLD = 3
# Sin alguno de estos grupos no es una oferta aunque sume puntos: "remote" + un email alcanzaba
# para que un spam de drones en un grupo de Python generara borradores.
HIRING_SIGNAL_LABELS = frozenset({
    "frase de contratación", "sección de requisitos", "pide postulación", "lista de posiciones", "convocatoria",
})

# (peso, etiqueta, frases). Suma el peso una sola vez por grupo.
POSITIVE_GROUPS: tuple[tuple[int, str, tuple[str, ...]], ...] = (
    (3, "frase de contratación", (
        "estamos buscando", "estamos en la búsqueda", "nos encontramos en búsqueda",
        "nos encontramos buscando", "necesitamos incorporar", "necesitamos sumar", "busca incorporar",
        "busca desarrollador", "busca programador", "busca analista", "busca tester", "busca un/a",
        "buscamos", "sumate a", "unite a", "se busca", "se requiere",
        "incorporar a nuestro equipo", "sumarse a nuestro equipo", "sumarse al equipo",
        "seguimos creciendo", "we are looking for", "we're looking for",
        "we are hiring", "we're hiring", "were hiring", "looking to hire", "join our team",
        "buscando talento", "estamos contratando", "en la búsqueda de",
    )),
    (3, "sección de requisitos", (
        "requisitos", "requirements", "perfil buscado", "perfil ideal",
        "qué buscamos", "que buscamos", "must have", "nice to have",
        "conocimientos en", "experiencia en", "experiencia con",
    )),
    (3, "pide postulación", (
        "enviá tu cv", "envia tu cv", "envía tu cv", "enviar cv", "enviar tu cv",
        "envianos tu cv", "envíanos tu cv", "enviános tu cv", "postulate",
        "postúlate", "postularse", "postularte", "apply now", "apply here",
        "send your cv", "send your resume", "escribinos a", "contactanos a",
        "mandá tu cv", "manda tu cv", "mandanos tu cv", "mandame tu cv", "enviame tu cv", "envíame tu cv",
        "aplica aquí", "aplicá acá",
    )),
    (3, "lista de posiciones", (
        "posiciones abiertas", "vacantes disponibles", "búsquedas abiertas",
        "búsquedas activas", "roles abiertos", "open positions",
    )),
    (2, "convocatoria", (
        "convocatoria", "búsqueda laboral", "busqueda laboral",
        "oportunidad laboral", "vacante", "#hiring",
    )),
    (2, "modalidad de trabajo", (
        "híbrid", "hibrid", "remoto", "remote", "presencial",
        "lunes a viernes", "full time", "part time", "jornada",
    )),
    (2, "describe tareas", (
        "responsabilidades", "tareas", "funciones", "tu rol", "your role",
        "what you'll do", "responsibilities", "qué vas a hacer",
    )),
    (1, "menciona beneficios", (
        "beneficios", "ofrecemos", "we offer", "sueldo", "salario",
        "remuneración", "prepaga", "plan de carrera",
    )),
)

NEGATIVE_GROUPS: tuple[tuple[int, str, tuple[str, ...]], ...] = (
    (8, "persona buscando empleo", (
        "me encuentro en búsqueda", "estoy en búsqueda", "busco empleo",
        "busco trabajo", "en búsqueda de nuevas oportunidades",
        "#opentowork", "open to work", "estoy buscando trabajo",
    )),
    (4, "contenido de engagement", (
        "seguime", "compartilo", "guardá este post", "guarda este post",
        "save this post", "follow me", "tips para", "consejos para",
    )),
    (4, "publicidad", ("promocionado", "promoted")),
    (8, "busca reclutadores, no devs", (
        "reclutadores/as", "reclutador/a freelance", "reclutadores freelance", "recruiters freelance",
        "freelance recruiters", "conectar con reclutadores", "buscamos reclutador", "buscamos recruiter",
    )),
)

# Roles del perfil: dev, backend, full stack, Python, QA, IA, DevOps y soporte técnico.
DEV_ROLE_PATTERN = re.compile(
    r"desarrollador|desarrolladora|developer|programador|programadora|back[- ]?end|"
    r"full[- ]?stack|front[- ]?end|python|django|fastapi|node\.?js|\bqa\b|tester|testing|"
    r"quality assurance|automatizaci[oó]n de pruebas|ingenier[oa] de software|"
    r"software (?:engineer|developer)|ai engineer|ingenier[oa] de ia|machine learning|"
    r"devops|\bsre\b|soporte t[eé]cnico|data engineer|product support|technical support|"
    r"application support|it support|soporte de aplicaciones|mesa de ayuda|help ?desk",
    re.IGNORECASE,
)
NON_DEV_ROLE_PATTERN = re.compile(
    r"abogad|dise[ñn]ador|contador|contable|log[ií]stica|transporte|vendedor|ventas|"
    r"comercial|administrativ|recepcionista|marketing|community manager|analista funcional|"
    r"business analyst|data analyst|analista de datos|recursos humanos|enfermer|chofer|"
    r"telemarketing|call center|atenci[oó]n al cliente|supervisor|despacho|dep[oó]sito|"
    r"almac[eé]n|operari[oa]|repositor|cajer[oa]|mantenimiento|producci[oó]n|compras|"
    r"tesorer[oa]|cobranzas|liquidaci[oó]n de sueldos|t[eé]cnic[oa] electr|mec[aá]nic|"
    r"\brisk\b|riesgo|fraude|\bfraud\b|prevenci[oó]n|docente|profesor|instructor|tutor|capacitador|"
    r"suscriptor|underwriter|seguros|t[eé]cnico de ingenier",
    re.IGNORECASE,
)

SENIOR_PATTERN = re.compile(
    r"\b(senior|sr\.?|líder técnico|tech lead|team lead|lead (?:developer|engineer|dev|backend|qa)|"
    r"principal (?:engineer|developer))\b"
)
# "sumarte a un equipo de devs senior": describe a los compañeros, no el puesto.
SENIOR_TEAM_CONTEXT = re.compile(
    r"((equipo|team) (de|of)|junto a|rodeado de|acompañad[oa] (de|por)|mentor[eí]a de|aprender de|learn from)"
    r"[^.\n]{0,20}$"
)
JUNIOR_PATTERN = re.compile(r"\b(junior|jr\.?|trainee|pasant[eí]a?|entry level|sin experiencia)\b")
# Solo para títulos de avisos: en el texto de un post "staff" suele ser "el equipo".
ABOVE_LEVEL_TITLE_PATTERN = re.compile(
    r"\b(staff|architect|arquitect[oa]|manager|head|director|gerente|iii|iv|v)\b", re.IGNORECASE
)
LOWER_LEVEL_PATTERN = re.compile(
    r"\b(semi ?senior|ssr|junior|jr\.?|trainee|pasant[eí]a?|entry level|sin experiencia)\b"
)
# "5 años", "+4 años", "3-5 años", "2 a 5 años", "8–12 Years", "5+ years": cuenta el mínimo del rango.
YEARS_PATTERN = re.compile(
    r"(?:más de |more than |over |at least |al menos |minimum |mínimo |\+ ?)?"
    r"(\d{1,2}) ?(?:(?:[-–]|a|y|to|and) ?\d{1,2} ?)?(\+)? ?(?:años|years|yrs)"
)
# Nadie pide 16+ años de experiencia: son edades ("mayor de 18") o la antigüedad de la empresa.
MAX_EXPERIENCE_YEARS = 15
YEARS_NOT_EXPERIENCE_BEFORE = re.compile(
    r"(edad|age|aged|mayor de|menor de|empresa con|compañía con|company with|trayectoria de)[^.\n]{0,15}$"
)
YEARS_NOT_EXPERIENCE_AFTER = re.compile(
    r"^[^.\n]{0,4}(de edad|en el mercado|de trayectoria|de historia|de carrera|de antigüedad|in business|"
    r"of history|old)"
)

# Encabezado del post ("5 meses •", "2 años Seguir", "3mo •"): los grupos muestran búsquedas de hace meses.
# Lo que sigue a la antigüedad en el encabezado; "Unirse" aparece en posts de grupos en la búsqueda.
POST_AGE_SUFFIX = r"\s*(?:•|seguir|conectar|unirse|follow|connect|join)"
POST_AGE_PATTERN = re.compile(
    r"\b\d+\s*(?:mes|meses|month|months|mo|año|años|year|years|yr)\b" + POST_AGE_SUFFIX,
    re.IGNORECASE,
)
POST_HEADER_CHARS = 500
# Primera línea que LinkedIn agrega según quién interactuó ("X recomienda esto", "A Y le gusta esto"):
# cambia según el contexto y movía la ventana de la clave, duplicando el mismo post.
CONTEXT_LINE = re.compile(
    r"^[^\n]{0,120}\b(recomienda|le gusta|les gusta|le encanta|le hace gracia|apoya|comentó|ha comentado|"
    r"compartió|ha compartido|celebra|publicación sugerida|promocionado|likes this|loves this|commented on|"
    r"reposted|suggested|promoted)\b[^\n]*\n", re.I)
FEED_POST_TITLES = ("publicación en el feed", "feed post")
# Fin del encabezado del post (autor, titular, "8 h •", "1 sem Seguir"): lo que sigue es el cuerpo.
HEADER_AGE_LINE = re.compile(
    r"^\s*\d+\s*(?:min|h|d|día|días|sem|semana|semanas|w|mes|meses|mo|año|años|yr)\b[^\n]{0,40}$",
    re.IGNORECASE | re.MULTILINE,
)

FOREIGN_PLACES = (
    "méxico", "mexico", "cdmx", "chile", "santiago de chile", "perú", "peru", "lima",
    "colombia", "bogotá", "medellín", "uruguay", "montevideo", "paraguay", "asunción",
    "venezuela", "bolivia", "ecuador", "costa rica", "guatemala", "panamá",
    "españa", "madrid", "brasil", "são paulo",
    "india", "bangalore", "bengaluru", "hyderabad", "pune", "chennai", "noida", "gurgaon",
    "mumbai", "delhi", "pakistan", "united states", "estados unidos", "canada",
    "canadá", "uk", "united kingdom", "reino unido", "london", "guayaquil", "quito", "carcelén",
    "querétaro", "queretaro", "guadalajara", "monterrey", "región metropolitana", "valparaíso",
    "arequipa", "barranquilla", "cali", "caracas", "san josé", "santo domingo", "cusco", "trujillo",
    "el salvador", "san salvador", "honduras", "tegucigalpa", "nicaragua", "managua",
    "república dominicana", "puerto rico", "cuba",
    "nuevo león", "nuevo leon", "santa catarina", "jalisco", "puebla", "edomex", "estado de méxico",
    "tijuana", "saltillo", "coahuila", "chihuahua", "aguascalientes", "san luis potosí", "yucatán",
    "ciudad de guatemala", "zapopan",
    "indonesia", "jakarta", "tangerang", "surabaya", "bandung", "surat", "vadodara", "ahmedabad",
    "gujarat", "kolkata", "las condes", "pudahuel", "medellin",
    # Jerga de avisos de India e Indonesia: nunca aparece en búsquedas de Argentina.
    "immediate joiner", "early joiner", "notice period", "wfo",
)
# Dominio de país del email del reclutador: sin mención de Argentina, la búsqueda es de ese país.
FOREIGN_EMAIL_TLDS = (".mx", ".cl", ".pe", ".ec", ".co", ".uy", ".py", ".bo", ".ve", ".es", ".br", ".in", ".pk",
                      ".id", ".cr", ".gt", ".hn", ".sv", ".pa", ".do", ".ni", ".cu", ".pr")
# Títulos que dicen "desarrollador" o "developer" pero no son el perfil (negocios, SAP, BI).
OFF_PROFILE_TITLE_PATTERN = re.compile(
    r"negocios|business develop|\bsap\b|abap|wricef|salesforce|power ?bi|\bcnc\b|\bplc\b|costos|pricing|"
    r"\bbpm\b|docente|convocatoria docente",
    re.IGNORECASE,
)
# Palabra completa: con substring, "lima" aparecía en "buen clima laboral" y "usa" en "causa".
FOREIGN_PLACE_PATTERN = re.compile(r"\b(" + "|".join(map(re.escape, FOREIGN_PLACES)) + r")\b")
# EE.UU. solo en mayúsculas: en minúsculas "usa" es un verbo.
US_PATTERN = re.compile(r"\bUSA\b|\bEE\.? ?UU\.?")
US_PLACES = frozenset({"united states", "estados unidos", "usa"})
ARGENTINA_OR_REMOTE = ("argentina", "latam", "latinoamérica", "córdoba", "cordoba")
REMOTE_TERMS = ("remoto", "remote", "home office", "100% remoto")
ONSITE_TERMS = ("presencial", "híbrid", "hibrid", "on-site", "onsite")
CORDOBA_TERMS = ("córdoba", "cordoba")
ARGENTINA_TERMS = ("argentina", "córdoba", "cordoba", "buenos aires", "caba", "rosario", "#arg")
# Bandera emoji (par de "regional indicators"). 🇺🇸/🇬🇧/🇪🇺 suelen marcar el nivel de inglés, no el país.
FLAG_PATTERN = re.compile("[\U0001F1E6-\U0001F1FF]{2}")
NEUTRAL_FLAGS = frozenset({"🇦🇷", "🇺🇸", "🇬🇧", "🇪🇺"})

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9\-]+(?:\.[a-zA-Z0-9\-]+)*\.[a-zA-Z]{2,}")
BLACKLIST_DOMAINS = (
    "example.com", "linkedin.com", "facebook.com", "google.com", "sentry.io",
    "instagram.com", "twitter.com",
)
OWN_EMAILS = ("fabri404lopez@gmail.com",)
# Casillas de avisos que no reciben CVs (adaptaciones, privacidad, avisos legales).
NOT_RECRUITER_MAILBOX = re.compile(
    r"^(accessibility|accommodations?|accesibilidad|privacy|privacidad|no-?reply|do-?not-?reply|eeo|legal|dpo|"
    r"compliance|datos\.personales|data\.protection|gdpr|abuse|security|cursos?|capacitaci[oó]n|training|"
    r"ventas|sales|marketing|prensa|press|facturaci[oó]n|billing|referidos|referrals?)(?:[._-][^@]*)?@",
    re.IGNORECASE,
)

SPANISH_MARKERS = (
    "buscamos", "equipo", "empresa", "requisitos", "experiencia", "desarrollador",
    "enviá", "envía", "remoto", "presencial", "trabajo", "puesto", "vacante",
)
ENGLISH_MARKERS = (
    "hiring", "looking for", "requirements", "experience", "developer",
    "engineer", "apply", "remote", "position", "role", "team",
)

ROLE_PATTERN = re.compile(
    r"(?:buscamos|estamos buscando|en búsqueda de|busca|hiring|we're hiring|"
    r"we are hiring|looking for|vacante|puesto|nueva oportunidad)[:!|\s]+(?:a |an |un/a |una |un |una/o |"
    r"el/la )?([^\n.!¿?#📍📩🔎✅]{4,70})",
    re.IGNORECASE,
)
ROLE_LINE_PATTERN = re.compile(
    r"^(desarrollador|desarrolladora|developer|programador|programadora|ingenier|engineer|qa\b|tester|"
    r"analista (qa|tester|de testing)|back|front|full|python|java|\.net|react|node|devops|soporte)",
    re.IGNORECASE,
)
SUBJECT_QUOTED = re.compile(r"asunto[^\"“'«\n]{0,40}[\"“'«]([^\"”'»\n]{3,80})[\"”'»]", re.IGNORECASE)
QUOTED_OPTION = re.compile(r"[\"“'«]([^\"”'»]{3,80})[\"”'»]")
SUBJECT_INLINE = re.compile(r"(?:asunto|subject)\s*:\s*([^\n]{3,80})", re.IGNORECASE)
SUBJECT_GENERIC_HINT = re.compile(
    r"\b(indicar|indica|indique|colocar|coloca|poner|pon[eé]|referencia|la búsqueda|"
    r"el puesto|al cargo|que postulan|que te interes)", re.IGNORECASE
)
QA_PATTERN = re.compile(r"\b(qa|tester|testing|quality assurance|automation tester)\b")


@dataclass(frozen=True)
class JobScore:
    score: int
    reasons: tuple[str, ...]
    hiring_signal: bool = True

    @property
    def is_job(self) -> bool:
        return self.hiring_signal and self.score >= JOB_SCORE_THRESHOLD


@dataclass(frozen=True)
class Verdict:
    accepted: bool
    reason: str


@dataclass(frozen=True)
class JobPosting:
    text: str
    emails: tuple[str, ...]
    language: str
    role_title: str
    track: str
    subject_hint: str | None
    asks_role_in_subject: bool


def _score_groups(text_lower: str, groups, sign: int) -> list[tuple[int, str, str]]:
    """(peso, etiqueta, motivo) de cada grupo con alguna frase en el texto."""
    hits = []
    for weight, label, phrases in groups:
        phrase = next((p for p in phrases if p in text_lower), None)
        if phrase:
            hits.append((sign * weight, label, f"{sign * weight:+d} {label}: '{phrase}'"))
    return hits


def split_post(text: str) -> tuple[str, str]:
    """(encabezado, cuerpo). El encabezado es autor, titular y antigüedad: "Senior IT Recruiter",
    "10 años en RRHH" o el nombre del grupo ("Búsqueda laboral Argentina") no describen el puesto."""
    head = text[:POST_HEADER_CHARS]
    match = POST_AGE_ANY.search(head) or HEADER_AGE_LINE.search(head)
    if not match:
        return "", text
    return text[:match.end()], text[match.end():]


def post_author(text: str) -> str:
    """Nombre de quien publicó: primera línea del encabezado que no es el título oculto ni el contexto."""
    header = split_post(text)[0]
    for line in CONTEXT_LINE.sub("", header.strip(), count=1).splitlines():
        line = line.split("•")[0].strip()
        if line and line.lower() not in FEED_POST_TITLES and not CONTEXT_LINE.match(line + "\n"):
            return line[:80]
    return ""


def score_job_posting(text: str) -> JobScore:
    """Puntaje de la v2: positivo si parece una oferta real, negativo si es contenido.
    Los positivos se buscan solo en el cuerpo; los negativos ("Promocionado", "#OpenToWork"), en todo."""
    text_lower = text.lower()
    hits = _score_groups(split_post(text_lower)[1], POSITIVE_GROUPS, 1)
    hiring_signal = any(label in HIRING_SIGNAL_LABELS for _, label, _ in hits)
    hits += _score_groups(text_lower, NEGATIVE_GROUPS, -1)
    if extract_emails(text):
        hits.append((2, "email", "+2 email de contacto"))
    return JobScore(sum(w for w, _, _ in hits), tuple(r for _, _, r in hits), hiring_signal)


def extract_emails(text: str) -> tuple[str, ...]:
    found = []
    for raw in EMAIL_PATTERN.findall(text):
        email = raw.lower().strip().rstrip(".")
        domain = email.split("@")[1]
        if domain in BLACKLIST_DOMAINS or email in OWN_EMAILS or email in found or NOT_RECRUITER_MAILBOX.match(email):
            continue
        found.append(email)
    return tuple(found)


def detect_language(text: str) -> str:
    text_lower = text.lower()
    es_score = sum(1 for word in SPANISH_MARKERS if word in text_lower)
    en_score = sum(1 for word in ENGLISH_MARKERS if word in text_lower)
    return "en" if en_score > es_score else "es"


def is_dev_title(title: str) -> bool:
    return bool(DEV_ROLE_PATTERN.search(title))


def matches_keywords(text: str, keywords: list[str]) -> bool:
    """Filtro 1 (amplio): al menos una keyword de keywords.txt. Sin keywords, pasa todo."""
    text_lower = text.lower()
    return not keywords or any(keyword in text_lower for keyword in keywords)


def is_dev_role(text: str, role_title: str) -> bool:
    """El puesto extraído manda; si no hay puesto claro, se mira el texto con la lista estricta."""
    if role_title and OFF_PROFILE_TITLE_PATTERN.search(role_title):
        return False
    if role_title and is_dev_title(role_title):
        return True
    if role_title and NON_DEV_ROLE_PATTERN.search(role_title):
        return False
    return is_dev_title(text)


def check_seniority(text: str) -> Verdict:
    """Sobre el cuerpo del post: descarta si pide 5+ años (o 4+) o el puesto es Senior/Lead."""
    text_lower = text.lower()
    has_junior = bool(JUNIOR_PATTERN.search(text_lower))
    for match in YEARS_PATTERN.finditer(text_lower):
        if _asks_experience_years(text_lower, match, has_junior):
            return Verdict(False, f"pide {match.group(0).strip()}")
    if _mentions_senior_role(text_lower) and not LOWER_LEVEL_PATTERN.search(text_lower):
        return Verdict(False, "nivel Senior/Lead")
    return Verdict(True, "nivel ok")


def _asks_experience_years(text_lower: str, match: re.Match[str], has_junior: bool) -> bool:
    years = int(match.group(1))
    has_plus = bool(match.group(2)) or match.group(0).startswith(("más de", "more than", "over", "+"))
    if years > MAX_EXPERIENCE_YEARS or not (years >= 5 or (years == 4 and has_plus)):
        return False
    before = text_lower[max(0, match.start() - 40):match.start()]
    after = text_lower[match.end():match.end() + 30]
    if YEARS_NOT_EXPERIENCE_BEFORE.search(before) or YEARS_NOT_EXPERIENCE_AFTER.search(after):
        return False
    # Post con varias búsquedas ("Python Jr" y "Java Sr con 8 años"): los años de otro puesto no
    # descartan al junior.
    return not (has_junior and not JUNIOR_PATTERN.search(_line_at(text_lower, match.start())))


def _line_at(text: str, index: int) -> str:
    start = text.rfind("\n", 0, index) + 1
    end = text.find("\n", index)
    return text[start:end if end != -1 else len(text)]


def _mentions_senior_role(text_lower: str) -> bool:
    return any(not SENIOR_TEAM_CONTEXT.search(text_lower[max(0, m.start() - 40):m.start()])
               for m in SENIOR_PATTERN.finditer(text_lower))


def check_location(text: str) -> Verdict:
    text_lower = text.lower()
    foreign_match = FOREIGN_PLACE_PATTERN.search(text_lower)
    foreign = foreign_match.group(1) if foreign_match else ("usa" if US_PATTERN.search(text) else None)
    local = any(p in text_lower for p in ARGENTINA_OR_REMOTE)
    remote = any(p in text_lower for p in REMOTE_TERMS)
    onsite = any(p in text_lower for p in ONSITE_TERMS)
    in_cordoba = any(p in text_lower for p in CORDOBA_TERMS)
    flag = _foreign_flag_without_argentina(text, text_lower)
    if flag:
        return Verdict(False, f"bandera de otro país ({flag})")
    others = _foreign_places_without_argentina(text_lower)
    if others:
        return Verdict(False, f"solo para otros países ({', '.join(others)})")
    if foreign and not local and not _remote_from_abroad(foreign, text_lower):
        return Verdict(False, f"ubicación fuera de Argentina ({foreign})")
    if onsite and not remote and not in_cordoba and _mentions_other_city(text_lower):
        return Verdict(False, "presencial fuera de Córdoba")
    return Verdict(True, "ubicación ok")


def _remote_from_abroad(foreign: str, text_lower: str) -> bool:
    """Remoto para LATAM, o remoto para un cliente de EE.UU. en un post en castellano: se contrata
    desde Argentina (pago en USD)."""
    if not any(p in text_lower for p in REMOTE_TERMS):
        return False
    if "latam" in text_lower:
        return True
    onsite = any(p in text_lower for p in ONSITE_TERMS)
    return foreign in US_PLACES and not onsite and detect_language(text_lower) == "es"


def _foreign_places_without_argentina(text_lower: str) -> list[str]:
    """"LATAM" no alcanza si el post enumera otros países (o una sede en Bogotá y Madrid)
    y nunca nombra Argentina: es una búsqueda para residentes de esos lugares."""
    places = sorted(set(FOREIGN_PLACE_PATTERN.findall(text_lower)))
    if len(places) < 2 or any(p in text_lower for p in ARGENTINA_TERMS):
        return []
    return places


def _foreign_flag_without_argentina(text: str, text_lower: str) -> str | None:
    """Un 🇬🇹 o 🇨🇴 en el aviso, sin 🇦🇷 ni mención de Argentina, es una búsqueda de ese país."""
    flags = set(FLAG_PATTERN.findall(text))
    if "🇦🇷" in flags or any(p in text_lower for p in ARGENTINA_TERMS):
        return None
    return next(iter(sorted(flags - NEUTRAL_FLAGS)), None)


def _mentions_other_city(text_lower: str) -> bool:
    cities = ("caba", "buenos aires", "rosario", "mendoza", "tucumán", "mar del plata",
              "la plata", "santa fe", "neuquén", "bahía blanca", "gba", "amba")
    return any(city in text_lower for city in cities) or bool(FOREIGN_PLACE_PATTERN.search(text_lower))


def extract_role_title(text: str) -> str:
    """Puesto tras "buscamos…"; si eso no es un rol dev, la primera línea corta con un título dev
    ("📍 Desarrollador React Native Semi Senior")."""
    match = ROLE_PATTERN.search(text)
    title = re.sub(r"\s+", " ", match.group(1)).strip(" -–:,¡!")[:70] if match else ""
    if title and is_dev_title(title):
        return title
    return _role_line(text) or title


def _role_line(text: str) -> str:
    for line in text.splitlines():
        line = re.sub(r"^[^\wÁÉÍÓÚÑáéíóúñ]+", "", line).strip(" -–:,¡!")
        if 6 <= len(line) <= 80 and ROLE_LINE_PATTERN.search(line) and is_dev_title(line):
            return line
    return ""


def extract_subject_hint(text: str) -> tuple[str | None, bool]:
    """Asunto que pide el post: (texto exacto, True) o (None, True) si pide algo genérico
    como "indicar la búsqueda" (se arma con el puesto). (None, False) si no pide nada."""
    quoted = SUBJECT_QUOTED.search(text)
    if quoted:
        return quoted.group(1).strip(), True
    inline = SUBJECT_INLINE.search(text)
    if inline and not SUBJECT_GENERIC_HINT.search(inline.group(1)):
        # 'Asunto: • "Desarrollador PHP" o • "Mobile"': si hay opciones entre comillas, va la primera.
        option = QUOTED_OPTION.search(inline.group(1))
        subject = option.group(1) if option else inline.group(1)
        return subject.strip(" .\"'•-–"), True
    asks_subject = bool(re.search(r"\basunto\b|\bsubject\b", text, re.IGNORECASE))
    return None, asks_subject


def detect_track(text: str, role_title: str, subject_hint: str | None) -> str:
    """QA si el puesto o el asunto pedido es de QA; sin ninguno de los dos, mira el texto."""
    source = f"{subject_hint or ''} {role_title}".strip() or text
    return "qa" if QA_PATTERN.search(source.lower()) else "backend"


def normalize_text(text: str) -> str:
    """NFKC: las letras "negritas" de LinkedIn (𝗦𝗿, 𝗵𝗶́𝗯𝗿𝗶𝗱𝗮) pasan a texto común para los filtros;
    el apóstrofo curvo ("We’re hiring") pasa a recto."""
    return unicodedata.normalize("NFKC", text).replace("’", "'")


def check_vacancy(text: str, keywords: list[str]) -> Verdict:
    """Todo el filtro salvo el email: oferta real → reciente → rol dev → nivel → ubicación.
    Rol, nivel y ubicación miran solo el cuerpo: el titular del autor no es el puesto."""
    score = score_job_posting(text)
    if not score.is_job:
        return Verdict(False, f"no es oferta (score {score.score})")
    age = POST_AGE_PATTERN.search(text[:POST_HEADER_CHARS])
    if age:
        return Verdict(False, f"publicado hace {age.group(0).strip(' •')}")
    body = split_post(text)[1]
    if not matches_keywords(body, keywords):
        return Verdict(False, "sin keywords")
    if not is_dev_role(body, extract_role_title(body)):
        return Verdict(False, "rol fuera del perfil")
    for check in (check_seniority, check_location):
        verdict = check(body)
        if not verdict.accepted:
            return verdict
    return Verdict(True, f"apto (score {score.score})")


def evaluate_vacancy(text: str, keywords: list[str]) -> JobPosting | None:
    """Vacante acorde aunque no traiga email (para escribirle al recruiter que la publicó)."""
    text = normalize_text(text)
    if not check_vacancy(text, keywords).accepted:
        return None
    return _build_posting(text, extract_emails(text))


POST_AGE_UNITS = (("min", 0), ("h", 0), ("d", 1), ("día", 1), ("días", 1), ("sem", 7), ("semana", 7),
                  ("semanas", 7), ("w", 7), ("mes", 30), ("meses", 30), ("mo", 30), ("año", 365),
                  ("años", 365), ("yr", 365))
POST_AGE_ANY = re.compile(
    r"\b(\d+)\s*(min|h|d|día|días|sem|semana|semanas|w|mes|meses|mo|año|años|yr)\b" + POST_AGE_SUFFIX,
    re.IGNORECASE,
)


def post_age_days(text: str) -> int | None:
    """Días desde la publicación según el encabezado ("3 h •", "5 días •", "2 sem Seguir"); None si no figura."""
    match = POST_AGE_ANY.search(normalize_text(text)[:POST_HEADER_CHARS])
    if not match:
        return None
    unit = dict(POST_AGE_UNITS)[match.group(2).lower()]
    return int(match.group(1)) * unit


def evaluate_post(text: str, keywords: list[str]) -> tuple[Verdict, JobPosting | None]:
    """Filtro completo: oferta real → rol dev → nivel → ubicación → email.
    El posting viene con el veredicto aceptado, o rechazado solo por "sin email"."""
    text = normalize_text(text)
    verdict = check_vacancy(text, keywords)
    if not verdict.accepted:
        return verdict, None
    emails = extract_emails(text)
    if not emails:
        # Vacante acorde sin email: se devuelve igual para dejarla en la lista de contacto por LinkedIn.
        return Verdict(False, "sin email"), _build_posting(text, ())
    if _foreign_recruiter(emails, text):
        return Verdict(False, f"email de otro país ({emails[0]})"), None
    return verdict, _build_posting(text, emails)


def _foreign_recruiter(emails: tuple[str, ...], text: str) -> bool:
    text_lower = text.lower()
    if any(term in text_lower for term in ARGENTINA_TERMS):
        return False
    return all(email.endswith(FOREIGN_EMAIL_TLDS) for email in emails)


# Títulos junior de IT que no dicen "desarrollador": "Trainee IT", "Pasante de Sistemas", "Soporte IT".
IT_ENTRY_TITLE_PATTERN = re.compile(
    r"analista de (sistemas|soporte)|soporte (it|ti|de sistemas)|test automation|automation (engineer|tester)|"
    r"ingenier[oa] de datos|((trainee|pasant[eí]a?|j[oó]venes profesionales)\b.*\b(it|ti|sistemas|tecnolog[ií]a|"
    r"software|desarrollo|programaci[oó]n|datos|qa|testing))|\b(it|sistemas)\b.*\b(trainee|pasant[eí]a?)",
    re.IGNORECASE,
)


def is_profile_title(title: str) -> bool:
    """Prefiltro de avisos de la sección Empleos: puesto dev y nivel que no sea Senior/Lead."""
    if not (is_dev_title(title) or IT_ENTRY_TITLE_PATTERN.search(title)) or NON_DEV_ROLE_PATTERN.search(title):
        return False
    if ABOVE_LEVEL_TITLE_PATTERN.search(title) or OFF_PROFILE_TITLE_PATTERN.search(title):
        return False
    return check_seniority(title).accepted


def evaluate_job(title: str, text: str) -> tuple[Verdict, JobPosting | None]:
    """Aviso de la sección Empleos: el puesto viene dado y el email es opcional
    (sin email se postula desde LinkedIn)."""
    title, text = normalize_text(title), normalize_text(text)
    if not is_profile_title(title):
        return Verdict(False, "rol o nivel fuera del perfil"), None
    for check in (check_seniority, check_location):
        verdict = check(text)
        if not verdict.accepted:
            return verdict, None
    emails = extract_emails(text)
    reason = "apto con email" if emails else "apto sin email"
    return Verdict(True, reason), _build_posting(text, emails, title)


def _build_posting(text: str, emails: tuple[str, ...], role_title: str = "") -> JobPosting:
    body = split_post(text)[1]
    role_title = role_title or extract_role_title(body)
    subject_hint, asks_subject = extract_subject_hint(text)
    return JobPosting(
        text=text,
        emails=emails,
        language=detect_language(body),
        role_title=role_title,
        track=detect_track(text, role_title, subject_hint),
        subject_hint=subject_hint,
        asks_role_in_subject=asks_subject and subject_hint is None,
    )
