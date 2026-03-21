"""
mailer.py - Envío de emails con CV adjunto vía Gmail SMTP.
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from pathlib import Path

from config import GMAIL_USER, GMAIL_APP_PASSWORD, CV_PATH, TEMPLATE_ES, TEMPLATE_EN


SUBJECTS = {
    "es": "Desarrollador Backend Junior - Adriel Fabricio López",
    "en": "Junior Backend Developer - Adriel Fabricio López",
}


def load_template(language: str) -> str:
    """Carga la plantilla de email según el idioma."""
    template_path = TEMPLATE_ES if language == "es" else TEMPLATE_EN
    if not template_path.exists():
        raise FileNotFoundError(f"No se encontró la plantilla: {template_path}")

    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Saltar la primera línea (es el asunto dentro del archivo)
    lines = content.split("\n")
    body_start = next(
        (i for i, line in enumerate(lines) if line.strip() == ""),
        1,
    )
    return "\n".join(lines[body_start:]).strip()


def build_message(to_email: str, language: str) -> MIMEMultipart:
    """Construye el mensaje MIME con cuerpo + CV adjunto."""
    msg = MIMEMultipart()
    msg["From"] = GMAIL_USER
    msg["To"] = to_email
    msg["Subject"] = SUBJECTS.get(language, SUBJECTS["es"])

    # Cuerpo del email
    body = load_template(language)
    msg.attach(MIMEText(body, "plain", "utf-8"))

    # Adjuntar CV
    cv_path = Path(CV_PATH)
    if cv_path.exists():
        with open(cv_path, "rb") as f:
            attachment = MIMEApplication(f.read(), _subtype="pdf")
            attachment.add_header(
                "Content-Disposition",
                "attachment",
                filename="CV_Adriel_Fabricio_Lopez.pdf",
            )
            msg.attach(attachment)
    else:
        print(f"  [WARN] CV no encontrado en {CV_PATH}, se enviará sin adjunto.")

    return msg


def send_email(to_email: str, language: str) -> bool:
    """
    Envía un email a un destinatario con el CV adjunto.
    Retorna True si se envió correctamente, False en caso de error.
    """
    try:
        msg = build_message(to_email, language)

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.send_message(msg)

        print(f"  [OK] Email enviado a: {to_email} ({language.upper()})")
        return True

    except smtplib.SMTPAuthenticationError:
        print(
            "  [ERROR] Falló la autenticación de Gmail.\n"
            "  Verificá que GMAIL_APP_PASSWORD sea una contraseña de aplicación válida.\n"
            "  Generala en: https://myaccount.google.com/apppasswords"
        )
        return False

    except smtplib.SMTPRecipientsRefused:
        print(f"  [ERROR] Destinatario rechazado: {to_email}")
        return False

    except Exception as e:
        print(f"  [ERROR] No se pudo enviar a {to_email}: {e}")
        return False
