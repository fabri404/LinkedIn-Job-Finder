"""Ofertas reales (data/audit.log, 25–28/10/2026) que llegaban como borradores sin encajar con el perfil,
y las que tienen que seguir pasando."""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from classifier import check_location, evaluate_post, is_dev_role
from feed import AccountBlocked, open_url
from pacing import Pacer, PaceSettings
from relevance import fit_for_draft
from store import Store

INDUSTRIAL_POSTS = [
    "We are HIRING - Electrical & I&C Engineer Company: TG Group - Oil & Gas Services. Key Responsibilities: "
    "Conduct QC inspections to ensure all electrical and I&C installations meet quality standards.",
    "Urgent Hiring: QA/QC Technician (Metering). Inspect and test meters for QA/QC. Ensure compliance with "
    "quality control standards. Send your CV at hr@edgewaterqatar.com",
    "We are looking for a Civil Engineer to join our solar project. Coordinate with subcontractors and "
    "engineering, QA/QC and HSE teams.",
    "WE'RE HIRING | DAMAC Construction Group Positions: Production Coordinator, Site Supervisor, "
    "QA/QC Engineer & Bus Driver. Send your updated CV to hr@damacgroup.com",
]


@pytest.mark.parametrize("text", INDUSTRIAL_POSTS)
def test_is_dev_role_industrial_qa_is_rejected(text):
    assert not is_dev_role(text, "")


@pytest.mark.parametrize("text", [
    "Buscamos QA Tester manual para apps web. Testing de APIs con Postman y Jira.",
    "Buscamos QA Automation Jr con Selenium y Python.",
])
def test_is_dev_role_software_qa_is_accepted(text):
    assert is_dev_role(text, "")


@pytest.mark.parametrize("text", [
    "Pioneer is Hiring! Junior Geophysicist – Airborne Geophysical Surveys Full-time | Canada",
    "Talents - Qatar. Urgent Hiring: QA/QC Technician. Job Location: Qatar.",
    "We are HIRING, a food processing industry in Sidoarjo. Send your CV to annisa.f@reqruitasia.com",
    "Hiring Python developer. Location: Abu Dhabi, UAE. Contract 12 months.",
])
def test_check_location_foreign_onsite_without_modality_is_rejected(text):
    assert not check_location(text).accepted


def test_evaluate_post_senior_title_is_rejected_even_if_body_mentions_junior():
    text = ("Marc Ellis 12 h Seguir Marc Ellis is #HIRING Job Title: Senior Full Stack Engineer – (Typescript, "
            "Python) Remote. You will mentor junior engineers and lead technical reviews. Requirements: Python. "
            "Send your CV to jobs@marcellis.com")

    verdict, _ = evaluate_post(text, [])

    assert not verdict.accepted
    assert "Senior" in verdict.reason


@pytest.mark.parametrize("text", [
    "Ana • IT Recruiter 3 h • Buscamos Desarrollador Python Junior en Córdoba, modalidad híbrida. "
    "Requisitos: Python y SQL. Enviá tu CV a rrhh@acme.com.ar",
    "Ana • IT Recruiter 3 h • Estamos buscando QA Tester manual, 100% remoto desde Argentina. Requisitos: "
    "testing de apps web y Jira. Enviá tu CV a seleccion@qa.com",
    "Ana • IT Recruiter 3 h • Buscamos Trainee de Sistemas para soporte técnico. Requisitos: estudiante de "
    "sistemas. Postulate enviando tu CV a rrhh@empresa.com",
])
def test_evaluate_post_profile_offers_still_pass(text):
    verdict, posting = evaluate_post(text, [])

    assert verdict.accepted, verdict.reason
    assert fit_for_draft(posting)[0]


def _ctx(tmp_path) -> SimpleNamespace:
    store = Store(tmp_path)
    return SimpleNamespace(store=store, pacer=Pacer(store, PaceSettings(), lambda: datetime(2026, 11, 2, 15)),
                           settings=SimpleNamespace(mail=SimpleNamespace(cv_dir=Path("/tmp/cv"))))


def test_enqueue_posting_low_relevance_goes_to_review_list_not_draft(tmp_path):
    # Arrange
    text = ("Ana • Recruiter 3 h • We're hiring a Ruby on Rails developer. Requirements: Rails. "
            "Send your CV to jobs@acme.com")
    _, posting = evaluate_post(text, [])
    ctx = _ctx(tmp_path)

    # Act
    queued = main._enqueue_posting(posting, "https://www.linkedin.com/feed/update/1", ctx)

    # Assert
    assert queued == 0 and not ctx.store.pending
    assert "revisar: relevancia" in (tmp_path / "contactar_linkedin.csv").read_text(encoding="utf-8")


def test_enqueue_posting_without_role_title_is_not_drafted_with_generic_title(tmp_path):
    # Arrange
    _, posting = evaluate_post("Ana • Recruiter 3 h • Buscamos desarrollador Python en Córdoba, híbrido. "
                               "Requisitos: Python. Enviá tu CV a rrhh@acme.com", [])
    posting = main.JobPosting(posting.text, posting.emails, posting.language, "", posting.track,
                              posting.subject_hint, posting.asks_role_in_subject)
    ctx = _ctx(tmp_path)

    # Act
    queued = main._enqueue_posting(posting, "https://www.linkedin.com/feed/update/2", ctx)

    # Assert
    assert queued == 0
    assert "sin puesto claro" in (tmp_path / "contactar_linkedin.csv").read_text(encoding="utf-8")


@pytest.mark.parametrize("landing", [
    "https://www.linkedin.com/checkpoint/challenge/abc",
    "https://www.linkedin.com/authwall?trk=x",
    "https://www.linkedin.com/login?session_redirect=x",
])
def test_open_url_redirected_to_checkpoint_or_login_raises_account_blocked(landing):
    driver = SimpleNamespace(get=lambda _url: None, current_url=landing)

    with pytest.raises(AccountBlocked):
        open_url(driver, "https://www.linkedin.com/feed/")


def test_open_url_gmail_page_is_never_treated_as_blocked():
    driver = SimpleNamespace(get=lambda _url: None, current_url="https://accounts.google.com/v3/signin/login")

    open_url(driver, "https://mail.google.com/mail/u/0/#inbox")
