"""
apps/mailer/services.py

MailerService — sends CV emails via Gmail SMTP and records an EmailLog entry.

Consolidates the original mailer.py logic into a Django service class.
"""
from __future__ import annotations

import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from apps.jobs.models import Job
    from apps.mailer.models import EmailLog


# ─── Email templates ─────────────────────────────────────────────────────────

SUBJECT_ES = "Postulación para el puesto — Desarrollador de Software"
SUBJECT_EN = "Job Application — Software Developer"

BODY_ES = """\
Hola,

Me comunico con usted porque encontré su publicación en LinkedIn y me gustaría postularme para el puesto mencionado.

Soy desarrollador de software con experiencia en Python, Django y desarrollo backend. Adjunto mi CV para su consideración.

Quedo a disposición ante cualquier consulta.

Saludos cordiales,
"""

BODY_EN = """\
Hello,

I'm reaching out because I found your job posting on LinkedIn and would like to apply for the mentioned position.

I'm a software developer with experience in Python, Django, and backend development. Please find my CV attached for your consideration.

I'm available for any questions you may have.

Best regards,
"""


class MailerService:
    """Handles CV email composition, sending, and logging."""

    @staticmethod
    def send_cv(job: "Job", to_email: str, language: str = "es") -> "EmailLog":
        """
        Compose and send a CV email to *to_email*.

        Creates and returns an EmailLog record regardless of success/failure.
        """
        from apps.mailer.models import EmailLog

        subject = SUBJECT_ES if language == "es" else SUBJECT_EN
        body = BODY_ES if language == "es" else BODY_EN

        log = EmailLog(
            job=job,
            to_email=to_email,
            language=language,
            subject=subject,
            body=body,
        )

        try:
            MailerService._send(
                to_email=to_email,
                subject=subject,
                body=body,
            )
            log.success = True
        except Exception as exc:  # noqa: BLE001
            log.success = False
            log.error_message = str(exc)

        log.save()
        return log

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _send(to_email: str, subject: str, body: str) -> None:
        """Low-level send via Gmail SMTP with optional CV attachment."""
        gmail_user: str = settings.GMAIL_USER
        gmail_password: str = settings.GMAIL_APP_PASSWORD
        cv_path: str = settings.CV_PATH

        msg = MIMEMultipart()
        msg["From"] = gmail_user
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        # Attach CV if the file exists
        cv_file = Path(cv_path)
        if cv_file.is_file():
            with cv_file.open("rb") as fh:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(fh.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{cv_file.name}"',
            )
            msg.attach(part)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_password)
            server.sendmail(gmail_user, to_email, msg.as_string())
