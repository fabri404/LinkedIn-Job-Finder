"""store.py - Estado persistente del loop: posts vistos, cola de envío, emails contactados."""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from composer import Application

STATE_FILE = "state.json"
SENT_CSV = "enviados.csv"
SENT_CSV_HEADER = ("fecha", "email", "puesto", "asunto", "cv", "post_url")
PREVIOUS_CONTACT = "previo"
JOBS_CSV = "empleos_linkedin.csv"
# Emails a descartar a mano (uno por línea): se sacan de la cola sin frenar el loop.
VETO_FILE = "descartar.txt"
EASY_APPLY_SENT = "enviada"
JOBS_CSV_HEADER = ("fecha", "puesto", "empresa", "ubicacion", "url", "solicitud_sencilla", "faltan")
# Vacantes de recruiters sin email: Adriel les escribe por LinkedIn o completa el link que dejaron.
LEADS_CSV = "contactar_linkedin.csv"
LEADS_CSV_HEADER = ("fecha", "recruiter", "perfil", "puesto", "post", "links", "mensaje")
# A un mismo email se le puede mandar otra vacante (otro puesto) pasados estos días.
RECONTACT_AFTER = timedelta(days=14)
# Posts y avisos vistos se olvidan a los 60 días: nada tan viejo vuelve a aparecer en las búsquedas
# (son de la última semana) y el estado deja de crecer sin límite.
SEEN_RETENTION = timedelta(days=60)
# Contadores de ritmo ("pages:2026-10-30", "pages:2026-10-30T14"): con una semana alcanza.
COUNTER_RETENTION = timedelta(days=8)
DAY_IN_KEY = re.compile(r"\d{4}-\d{2}-\d{2}")
LEVEL_WORDS = re.compile(r"\b(junior|jr|semi ?senior|ssr|senior|sr|trainee|a|o|de|del|la|el)\b")


def normalize_role(role: str) -> str:
    """"Desarrollador/a Python Jr." y "desarrollador python" son el mismo puesto."""
    text = unicodedata.normalize("NFKD", role.lower()).encode("ascii", "ignore").decode()
    text = LEVEL_WORDS.sub(" ", re.sub(r"[^a-z0-9#+ ]", " ", text))
    return " ".join(text.split())


def _recent_counters(raw: dict[str, int]) -> dict[str, int]:
    """Descarta los contadores con fecha de hace más de COUNTER_RETENTION; los que no tienen fecha quedan."""
    cutoff = (date.today() - COUNTER_RETENTION).isoformat()
    return {key: value for key, value in raw.items()
            if not (day := DAY_IN_KEY.search(key)) or day.group(0) >= cutoff}


def _recent_seen(raw: list[str] | dict[str, str]) -> dict[str, str]:
    """Vistos de los últimos SEEN_RETENTION días. El formato viejo (lista sin fechas) cuenta como de hoy."""
    today = date.today()
    if isinstance(raw, list):
        return dict.fromkeys(raw, today.isoformat())
    cutoff = (today - SEEN_RETENTION).isoformat()
    return {key: day for key, day in raw.items() if day >= cutoff}


@dataclass(frozen=True)
class QueuedApplication:
    app: Application
    post_url: str
    score: int = 0  # relevance.relevance_score: la cola sale de mayor a menor

    def to_dict(self) -> dict[str, str | int]:
        data: dict[str, str | int] = asdict(self.app)
        data["cv_path"] = str(self.app.cv_path)
        data["post_url"] = self.post_url
        data["score"] = self.score
        return data

    @classmethod
    def from_dict(cls, data: dict) -> QueuedApplication:
        app = Application(data["to"], data["subject"], data["body"],
                          Path(data["cv_path"]), data["role"])
        return cls(app, data["post_url"], int(data.get("score", 0)))


@dataclass
class Store:
    state_dir: Path
    seen: dict[str, str] = field(default_factory=dict)  # clave → fecha en que se vio
    contacted: dict[str, str] = field(default_factory=dict)
    pending: list[QueuedApplication] = field(default_factory=list)
    search_pages: dict[str, int] = field(default_factory=dict)
    # Fuente por la que sigue la vuelta y vuelta de rotación: sobreviven a un reinicio.
    progress: dict[str, int] = field(default_factory=dict)
    # Ritmo (pacing.py): páginas por día y hora, follows, Solicitudes sencillas por hora…
    counters: dict[str, int] = field(default_factory=dict)
    # Momentos (epoch) que deben sobrevivir a un reinicio: fin de enfriamientos, última restricción.
    marks: dict[str, float] = field(default_factory=dict)
    _saved: str = field(default="", repr=False, compare=False)

    @classmethod
    def load(cls, state_dir: Path) -> Store:
        state_dir.mkdir(parents=True, exist_ok=True)
        path = state_dir / STATE_FILE
        if not path.exists():
            return cls(state_dir)
        data = json.loads(path.read_text(encoding="utf-8"))
        pending = [QueuedApplication.from_dict(item) for item in data.get("pending", [])]
        return cls(state_dir, _recent_seen(data.get("seen", {})), dict(data.get("contacted", {})), pending,
                   dict(data.get("search_pages", {})), dict(data.get("progress", {})),
                   _recent_counters(data.get("counters", {})), dict(data.get("marks", {})))

    def save(self) -> None:
        """Escribe state.json solo si algo cambió desde el último guardado (se llama tras cada fuente)."""
        data = {
            "seen": self.seen,
            "contacted": self.contacted,
            "pending": [item.to_dict() for item in self.pending],
            "search_pages": self.search_pages,
            "progress": self.progress,
            "counters": self.counters,
            "marks": self.marks,
        }
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if payload == self._saved:
            return
        tmp = self.state_dir / f"{STATE_FILE}.tmp"
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self.state_dir / STATE_FILE)
        self._saved = payload

    def is_seen(self, key: str) -> bool:
        return key in self.seen

    def mark_seen(self, key: str) -> None:
        self.seen.setdefault(key, date.today().isoformat())

    def import_previous_contacts(self, emails: list[str]) -> None:
        for email in emails:
            self.contacted.setdefault(email.lower(), PREVIOUS_CONTACT)

    def is_known_recipient(self, email: str, role: str = "") -> bool:
        """True si ya está en la cola, si se le escribió hace menos de RECONTACT_AFTER, si ya se le
        mandó este mismo puesto o si fue un contacto previo/descartado (sin fecha)."""
        email = email.lower()
        if any(item.app.to == email for item in self.pending):
            return True
        if email not in self.contacted:
            return False
        try:
            last = date.fromisoformat(self.contacted[email])
        except ValueError:
            return True
        if date.today() - last < RECONTACT_AFTER:
            return True
        return not role or normalize_role(role) in self._sent_roles().get(email, set())

    def _sent_roles(self) -> dict[str, set[str]]:
        """Puestos ya enviados por email, según enviados.csv."""
        path = self.state_dir / SENT_CSV
        roles: dict[str, set[str]] = {}
        if not path.exists():
            return roles
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                roles.setdefault(row["email"].lower(), set()).add(normalize_role(row["puesto"]))
        return roles

    def is_vetoed(self, email: str) -> bool:
        path = self.state_dir / VETO_FILE
        if not path.exists():
            return False
        lines = path.read_text(encoding="utf-8").splitlines()
        return email.lower() in {line.strip().lower() for line in lines if line.strip()}

    def counter(self, key: str) -> int:
        return self.counters.get(key, 0)

    def count(self, key: str) -> int:
        """Suma uno al contador `key` y devuelve el valor nuevo."""
        self.counters[key] = self.counter(key) + 1
        return self.counters[key]

    def record_lead(self, row: tuple[str, ...]) -> None:
        self._append_csv(LEADS_CSV, LEADS_CSV_HEADER, row)

    def enqueue(self, item: QueuedApplication) -> None:
        """Inserta detrás de los de igual o mayor puntaje: la cola sale por relevancia."""
        index = next((i for i, queued in enumerate(self.pending) if queued.score < item.score), len(self.pending))
        self.pending.insert(index, item)

    def sent_on(self, day: date) -> int:
        return sum(1 for sent in self.contacted.values() if sent == day.isoformat())

    def complete_first(self, when: datetime) -> QueuedApplication:
        """Saca el primero de la cola, lo marca como contactado y lo registra en el CSV."""
        item = self.pending.pop(0)
        self.contacted[item.app.to] = when.date().isoformat()
        self.save()
        self._append_csv(SENT_CSV, SENT_CSV_HEADER,
                         (when.isoformat(timespec="seconds"), item.app.to, item.app.role,
                          item.app.subject, item.app.cv_path.name, item.post_url))
        return item

    def easy_applies_on(self, day: date) -> int:
        """Solicitudes sencillas enviadas ese día, según empleos_linkedin.csv."""
        path = self.state_dir / JOBS_CSV
        if not path.exists():
            return 0
        with path.open(newline="", encoding="utf-8") as fh:
            return sum(1 for row in csv.DictReader(fh)
                       if row["fecha"].startswith(day.isoformat()) and row["solicitud_sencilla"] == EASY_APPLY_SENT)

    def record_manual_job(self, row: tuple[str, ...]) -> None:
        """Aviso apto sin email: queda en la lista para postular desde LinkedIn."""
        self._append_csv(JOBS_CSV, JOBS_CSV_HEADER, row)

    def discard_first(self, reason: str) -> QueuedApplication:
        """Descarte a mano: el email no vuelve a recibir borradores."""
        item = self.pending.pop(0)
        self.contacted[item.app.to] = f"descartado: {reason}"
        self.save()
        return item

    def drop_first(self) -> QueuedApplication:
        """Saca el primero sin marcarlo como contactado: un fallo al armar el borrador (CV, adjunto)
        no debe impedir postular a ese email con otra vacante."""
        item = self.pending.pop(0)
        self.save()
        return item

    def _append_csv(self, name: str, header: tuple[str, ...], row: tuple[str, ...]) -> None:
        path = self.state_dir / name
        is_new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            if is_new:
                writer.writerow(header)
            writer.writerow(row)
