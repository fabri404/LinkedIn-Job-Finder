"""Ofertas válidas que el clasificador descartaba (falsos negativos vistos en data/job_finder.log)."""

import pytest

from classifier import check_location, check_seniority, evaluate_post, extract_emails, post_author, split_post

KEYWORDS = [line.strip().lower() for line in open("keywords.txt", encoding="utf-8") if line.strip()]
FOOTER = " Modalidad remoto Argentina. Requisitos: Git. Enviar CV a rrhh@empresa.com.ar"


def _post(body: str, headline: str = "IT Recruiter") -> str:
    return f"Publicación en el feed\nLara Gómez • 2º\n{headline}\n3 h •\nSeguir\n{body}"


@pytest.mark.parametrize("body", [
    "Buscamos Software Engineer jr para nuestro equipo.",
    "Estamos buscando Ingeniero de Software trainee.",
    "Buscamos Analista de Soporte Técnico jr.",
    "Buscamos Help Desk N1 para mesa de ayuda.",
])
def test_evaluate_post_dev_roles_outside_old_keywords_are_accepted(body):
    # Act
    verdict, posting = evaluate_post(_post(body + FOOTER), KEYWORDS)

    # Assert
    assert verdict.accepted, verdict.reason
    assert posting is not None and posting.emails == ("rrhh@empresa.com.ar",)


def test_evaluate_post_senior_recruiter_headline_does_not_reject_junior_role():
    # Arrange
    text = _post("Buscamos Desarrollador Python con FastAPI." + FOOTER, headline="Senior IT Recruiter | 10 años")

    # Act
    verdict, _ = evaluate_post(text, KEYWORDS)

    # Assert
    assert verdict.accepted, verdict.reason


@pytest.mark.parametrize("body", [
    "Tu tarea principal será desarrollar APIs en Python.",
    "Vas a sumarte a un equipo de devs senior que te va a acompañar.",
    "You will help to lead our API migration in Python.",
])
def test_check_seniority_non_level_uses_of_senior_words_are_ok(body):
    assert check_seniority(body).accepted


@pytest.mark.parametrize("body", [
    "Requisitos: mayor de 18 años, Python básico.",
    "Empresa con más de 20 años en el mercado busca dev Python jr.",
    "Estudiante avanzado (3er año de 5 años de carrera).",
    "Edad: entre 20 y 35 años.",
])
def test_check_seniority_years_that_are_not_experience_are_ignored(body):
    assert check_seniority(body).accepted


def test_check_seniority_range_with_a_counts_minimum_years():
    assert check_seniority("Experiencia: 2 a 5 años en Python.").accepted
    assert not check_seniority("Experiencia: 5 a 8 años en Python.").accepted


def test_check_seniority_multi_role_post_keeps_junior_role():
    # Arrange
    body = "Posiciones abiertas:\nPython Developer Jr - remoto\nJava Developer Sr con 8 años de experiencia"

    # Act / Assert
    assert check_seniority(body).accepted


def test_check_seniority_real_senior_role_is_still_rejected():
    assert not check_seniority("Buscamos Desarrollador Senior Python con 6 años de experiencia.").accepted
    assert not check_seniority("Buscamos Tech Lead Python.").accepted


def test_check_location_verb_usa_is_not_a_country():
    assert check_location("El equipo usa FastAPI y Docker. 100% remoto.").accepted


def test_check_location_remote_spanish_post_for_us_client_is_ok():
    assert check_location("Trabajo remoto, pago en USD, cliente en Estados Unidos. Buscamos dev Python.").accepted


def test_check_location_onsite_in_usa_is_rejected():
    assert not check_location("Presencial en Miami, USA. Buscamos dev Python.").accepted


def test_evaluate_post_curly_apostrophe_hiring_is_an_offer():
    # Arrange
    text = _post("We’re hiring! Python Developer, remote LATAM. Send your CV to jobs@acme.io")

    # Act
    verdict, _ = evaluate_post(text, KEYWORDS)

    # Assert
    assert verdict.accepted, verdict.reason


@pytest.mark.parametrize("email", ["dportillo@empresa.com", "pressler@empresa.com", "salesjobs@empresa.com"])
def test_extract_emails_personal_addresses_with_mailbox_prefix_are_kept(email):
    assert extract_emails(f"Enviar CV a {email}") == (email,)


def test_extract_emails_real_non_recruiter_mailboxes_are_dropped():
    assert extract_emails("privacy@acme.com dpo@acme.com sales.team@acme.com") == ()


def test_evaluate_post_without_email_returns_posting_for_linkedin_lead():
    # Act
    verdict, posting = evaluate_post(_post("Buscamos Desarrollador Python jr. Remoto Argentina. Requisitos: Git."),
                                     KEYWORDS)

    # Assert
    assert verdict.reason == "sin email" and not verdict.accepted
    assert posting is not None and posting.emails == ()


def test_split_post_and_post_author_skip_context_and_hidden_title():
    # Arrange
    text = "Publicación en el feed\nJuan recomienda esto\nMaría Pérez • 2º\nRecruiter\n3 h •\nBuscamos dev"

    # Act
    header, body = split_post(text)

    # Assert
    assert body.strip() == "Buscamos dev"
    assert post_author(text) == "María Pérez"
