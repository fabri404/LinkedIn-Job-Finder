"""config.py - Configuración del Job Finder, leída desde .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

DEFAULT_CV_DIR = Path.home() / "Documentos/ADRIEL/cv/2026-10_relanzamiento/02_cv"
DEFAULT_PROFILE_DIR = Path.home() / ".config/linkedin-job-finder/chrome-profile"


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _env_path(name: str, default: Path) -> Path:
    return Path(os.path.expanduser(os.getenv(name, str(default))))


@dataclass(frozen=True)
class RunSettings:
    scroll_minutes: int
    channel_scroll_minutes: int
    pause_minutes_min: int
    pause_minutes_max: int
    daily_send_limit: int
    send_delay_min_s: int
    send_delay_max_s: int
    # Solicitudes sencillas que se envían solas por día (0 = solo guardarlas, nunca enviar).
    easy_apply_daily_limit: int = 25


@dataclass(frozen=True)
class MailSettings:
    cv_dir: Path


@dataclass(frozen=True)
class Settings:
    run: RunSettings
    mail: MailSettings
    chrome_profile_dir: Path
    chrome_headless: bool
    state_dir: Path
    keywords_file: Path
    channels_file: Path
    job_queries_file: Path
    recruiter_queries_file: Path


def load_settings() -> Settings:
    run = RunSettings(
        scroll_minutes=_env_int("SCROLL_MINUTES", 8),
        channel_scroll_minutes=_env_int("CHANNEL_SCROLL_MINUTES", 2),
        pause_minutes_min=_env_int("PAUSE_MINUTES_MIN", 8),
        pause_minutes_max=_env_int("PAUSE_MINUTES_MAX", 15),
        daily_send_limit=_env_int("DAILY_SEND_LIMIT", 100),
        send_delay_min_s=_env_int("SEND_DELAY_MIN_S", 5),
        send_delay_max_s=_env_int("SEND_DELAY_MAX_S", 15),
        easy_apply_daily_limit=_env_int("EASY_APPLY_DAILY_LIMIT", 25),
    )
    mail = MailSettings(cv_dir=_env_path("CV_DIR", DEFAULT_CV_DIR))
    return Settings(
        run=run,
        mail=mail,
        chrome_profile_dir=_env_path("CHROME_PROFILE_DIR", DEFAULT_PROFILE_DIR),
        chrome_headless=_env_int("CHROME_HEADLESS", 1) == 1,
        state_dir=_env_path("STATE_DIR", BASE_DIR / "data"),
        keywords_file=BASE_DIR / "keywords.txt",
        channels_file=BASE_DIR / "channels.txt",
        job_queries_file=BASE_DIR / "job_queries.txt",
        recruiter_queries_file=BASE_DIR / "recruiter_queries.txt",
    )


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def load_keywords(path: Path) -> list[str]:
    return [line.lower() for line in _read_lines(path)]


def load_channels(path: Path) -> list[str]:
    """URLs de páginas que recopilan búsquedas (p. ej. /company/<x>/posts/?feedView=all)."""
    return _read_lines(path)


def validate_mail_settings(mail: MailSettings) -> list[str]:
    errors = []
    if not mail.cv_dir.is_dir():
        errors.append(f"CV_DIR no existe: {mail.cv_dir}")
    return errors
