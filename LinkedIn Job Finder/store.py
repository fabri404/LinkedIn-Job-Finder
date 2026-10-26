"""store.py - Estado persistente del loop: posts vistos, cola de envío, emails contactados."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

from composer import Application

STATE_FILE = "state.json"
SENT_CSV = "enviados.csv"
SENT_CSV_HEADER = ("fecha", "email", "puesto", "asunto", "cv", "post_url")
PREVIOUS_CONTACT = "previo"
JOBS_CSV = "empleos_linkedin.csv"
# Emails a descartar a mano (uno por línea): se sacan de la cola sin frenar el loop.
VETO_FILE = "descartar.txt"
JOBS_CSV_HEADER = ("fecha", "puesto", "empresa", "ubicacion", "url", "solicitud_sencilla", "faltan")
# Vacantes de recruiters sin email: Adriel les escribe por LinkedIn o completa el link que dejaron.
LEADS_CSV = "contactar_linkedin.csv"
LEADS_CSV_HEADER = ("fecha", "recruiter", "perfil", "puesto", "post", "links", "mensaje")


@dataclass(frozen=True)
class QueuedApplication:
    app: Application
    post_url: str

    def to_dict(self) -> dict[str, str]:
        data = asdict(self.app)
        data["cv_path"] = str(self.app.cv_path)
        data["post_url"] = self.post_url
        return data

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> QueuedApplication:
        app = Application(data["to"], data["subject"], data["body"],
                          Path(data["cv_path"]), data["role"])
        return cls(app, data["post_url"])


@dataclass
class Store:
    state_dir: Path
    seen: set[str] = field(default_factory=set)
    contacted: dict[str, str] = field(default_factory=dict)
    pending: list[QueuedApplication] = field(default_factory=list)
    profile_visits: dict[str, int] = field(default_factory=dict)
    search_pages: dict[str, int] = field(default_factory=dict)
    # Fuente por la que sigue la vuelta y vuelta de rotación: sobreviven a un reinicio.
    progress: dict[str, int] = field(default_factory=dict)

    @classmethod
    def load(cls, state_dir: Path) -> Store:
        state_dir.mkdir(parents=True, exist_ok=True)
        path = state_dir / STATE_FILE
        if not path.exists():
            return cls(state_dir)
        data = json.loads(path.read_text(encoding="utf-8"))
        pending = [QueuedApplication.from_dict(item) for item in data.get("pending", [])]
        return cls(state_dir, set(data.get("seen", [])), dict(data.get("contacted", {})), pending,
                   dict(data.get("profile_visits", {})), dict(data.get("search_pages", {})),
                   dict(data.get("progress", {})))

    def save(self) -> None:
        data = {
            "seen": sorted(self.seen),
            "contacted": self.contacted,
            "pending": [item.to_dict() for item in self.pending],
            "profile_visits": self.profile_visits,
            "search_pages": self.search_pages,
            "progress": self.progress,
        }
        tmp = self.state_dir / f"{STATE_FILE}.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.state_dir / STATE_FILE)

    def is_seen(self, key: str) -> bool:
        return key in self.seen

    def mark_seen(self, key: str) -> None:
        self.seen.add(key)

    def import_previous_contacts(self, emails: list[str]) -> None:
        for email in emails:
            self.contacted.setdefault(email.lower(), PREVIOUS_CONTACT)

    def is_known_recipient(self, email: str) -> bool:
        email = email.lower()
        return email in self.contacted or any(item.app.to == email for item in self.pending)

    def is_vetoed(self, email: str) -> bool:
        path = self.state_dir / VETO_FILE
        if not path.exists():
            return False
        lines = path.read_text(encoding="utf-8").splitlines()
        return email.lower() in {line.strip().lower() for line in lines if line.strip()}

    def visits_on(self, day: date) -> int:
        return self.profile_visits.get(day.isoformat(), 0)

    def count_visit(self, day: date) -> None:
        """Perfiles de recruiters abiertos por día: persiste para que reiniciar no reabra el cupo."""
        self.profile_visits[day.isoformat()] = self.visits_on(day) + 1

    def record_lead(self, row: tuple[str, ...]) -> None:
        self._append_csv(LEADS_CSV, LEADS_CSV_HEADER, row)

    def enqueue(self, item: QueuedApplication) -> None:
        self.pending.append(item)

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

    def record_manual_job(self, row: tuple[str, ...]) -> None:
        """Aviso apto sin email: queda en la lista para postular desde LinkedIn."""
        self._append_csv(JOBS_CSV, JOBS_CSV_HEADER, row)

    def discard_first(self, reason: str) -> QueuedApplication:
        item = self.pending.pop(0)
        self.contacted[item.app.to] = f"descartado: {reason}"
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
