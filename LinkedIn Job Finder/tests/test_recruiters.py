from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from classifier import evaluate_vacancy, post_age_days
from composer import Outreach, compose_outreach
from recruiters import RecruiterCard, is_it_recruiter, parse_people
from store import Store

CV_DIR = Path("/tmp/cv")
VACANCY_POST = (
    "Rocio • 2º Talent Partner 5 días • Conectar Buscamos Desarrollador Python para equipo remoto. "
    "Requisitos: 2 años de experiencia. Remoto Argentina. Postulate por LinkedIn."
)


@pytest.mark.parametrize(("header", "days"), [
    ("Ana • IT Recruiter 3 h • Buscamos", 0),
    ("Ana • IT Recruiter 5 días • Buscamos", 5),
    ("Ana • IT Recruiter 2 sem Conectar Buscamos", 14),
    ("Ana • IT Recruiter 1 mes • Buscamos", 30),
])
def test_post_age_days_reads_header(header, days):
    assert post_age_days(header) == days


def test_post_age_days_without_header_returns_none():
    assert post_age_days("Buscamos desarrollador Python con 2 años de experiencia") is None


def test_parse_people_keeps_it_recruiters_and_skips_mutual_links():
    rows = [
        ["rocio", "Rocio Gonzalez • 2º Talent Partner | IT Recruiter 🚀"],
        ["emilia", "Emilia Conti"],
        ["vendedor", "Juan Pérez • 3er Ejecutivo de ventas"],
        ["rocio", "Rocio Gonzalez • 2º Talent Partner | IT Recruiter 🚀"],
    ]

    cards = parse_people(rows)

    assert [(c.slug, c.name) for c in cards] == [("rocio", "Rocio Gonzalez")]


def test_is_it_recruiter_requires_recruiting_and_it():
    assert is_it_recruiter("Talent Acquisition | IT Recruiter | LATAM")
    assert not is_it_recruiter("Recruiter generalista | Retail")
    assert not is_it_recruiter("Senior Python Developer")


def test_compose_outreach_without_vacancy_is_generic_and_never_junior():
    app = compose_outreach(Outreach("ana@rh.com", "Ana", "es", None), CV_DIR)

    assert app.to == "ana@rh.com"
    assert app.body.startswith("Hola Ana,")
    assert "Desarrollador Backend Python o QA" in app.subject
    assert "junior" not in (app.subject + app.body).lower()
    assert app.cv_path.name == "CV_Adriel_Lopez_Backend_ES.pdf"


def test_compose_outreach_with_vacancy_mentions_the_role():
    vacancy = evaluate_vacancy(VACANCY_POST, [])

    app = compose_outreach(Outreach("rocio@rock.com", "Rocio", "es", vacancy), CV_DIR)

    assert vacancy is not None
    assert "vi que publicaste la búsqueda de Desarrollador Python" in app.body


def _ctx(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(store=Store.load(tmp_path), keywords=[], allow_follow=True, follows={},
                           settings=SimpleNamespace(mail=SimpleNamespace(cv_dir=CV_DIR)))


def _patch_profile(monkeypatch, email, posts=()):
    monkeypatch.setattr(main, "recent_posts", lambda _d, _c: list(posts))
    monkeypatch.setattr(main, "open_profile", lambda _d, _c: None)
    monkeypatch.setattr(main, "follow", lambda _d, _c: True)
    monkeypatch.setattr(main, "contact_email", lambda _d: email)


def test_process_recruiter_with_email_enqueues_outreach_and_follows(tmp_path, monkeypatch):
    # Arrange
    ctx = _ctx(tmp_path)
    _patch_profile(monkeypatch, "ana@rh.com")
    card = RecruiterCard("ana", "Ana Gómez", "IT Recruiter")

    # Act
    queued = main.process_recruiter(None, card, ctx)

    # Assert
    assert queued == 1
    assert ctx.store.pending[0].app.to == "ana@rh.com"
    assert ctx.store.pending[0].post_url == "https://www.linkedin.com/in/ana/"
    assert ctx.store.is_seen("recruiter:ana")
    assert sum(ctx.follows.values()) == 1


def test_process_recruiter_already_contacted_is_skipped(tmp_path, monkeypatch):
    # Arrange
    ctx = _ctx(tmp_path)
    ctx.store.import_previous_contacts(["ana@rh.com"])
    _patch_profile(monkeypatch, "ana@rh.com")

    # Act
    queued = main.process_recruiter(None, RecruiterCard("ana", "Ana", "IT Recruiter"), ctx)

    # Assert
    assert queued == 0
    assert not ctx.store.pending


def test_process_recruiter_without_email_only_marks_seen(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    _patch_profile(monkeypatch, None)

    assert main.process_recruiter(None, RecruiterCard("ana", "Ana", "IT Recruiter"), ctx) == 0
    assert ctx.store.is_seen("recruiter:ana")


def test_owns_email_matches_name_or_surname_only():
    card = RecruiterCard("tomas", "Tomas Ignacio Carballo", "IT Recruiter")

    assert card.owns_email("tcarballo@acme.com")
    assert not card.owns_email("slescanoseleccion@gmail.com")
    assert RecruiterCard("m", "María Toledo", "IT Recruiter").owns_email("maria.toledo@x.com")


def test_compose_outreach_without_first_name_greets_generically():
    app = compose_outreach(Outreach("cv@consultora.com", "", "es", None), CV_DIR)

    assert app.body.startswith("Hola,\n")


def test_process_recruiter_with_vacancy_and_no_email_records_linkedin_lead(tmp_path, monkeypatch):
    # Arrange
    ctx = _ctx(tmp_path)
    post = main.FeedPost("k1", VACANCY_POST + " Formulario: https://forms.gle/abc123", "https://www.linkedin.com/feed/update/1")
    _patch_profile(monkeypatch, None, [post])

    # Act
    queued = main.process_recruiter(None, RecruiterCard("rocio", "Rocio Gonzalez", "IT Recruiter"), ctx)

    # Assert
    rows = (tmp_path / "contactar_linkedin.csv").read_text(encoding="utf-8")
    assert queued == 0
    assert "https://forms.gle/abc123" in rows
    assert "Hola Rocio, vi tu búsqueda de Desarrollador Python" in rows
    assert ctx.store.visits_on(main.date.today()) == 1


def test_new_recruiters_with_daily_budget_spent_skips_search(tmp_path, monkeypatch):
    # Arrange
    ctx = _ctx(tmp_path)
    ctx.recruiter_queries, ctx.recruiter_cycle = ["IT recruiter"], 0
    ctx.store.profile_visits[main.date.today().isoformat()] = main.MAX_PROFILES_PER_DAY
    monkeypatch.setattr(main, "safe_search", lambda _d, _q, _p: pytest.fail("no debería buscar"))

    # Act / Assert
    assert main.new_recruiters(None, ctx) == []


def test_stop_if_checkpoint_exits_the_loop(tmp_path):
    ctx = _ctx(tmp_path)
    driver = SimpleNamespace(current_url="https://www.linkedin.com/checkpoint/challenge/abc")

    with pytest.raises(SystemExit):
        main.stop_if_checkpoint(driver, ctx)


def test_new_recruiters_skips_pages_already_visited(tmp_path, monkeypatch):
    # Arrange
    ctx = _ctx(tmp_path)
    monkeypatch.setattr(main, "MAX_PROFILES_PER_CYCLE", 3)
    ctx.recruiter_queries, ctx.recruiter_cycle = ["IT recruiter"], 0
    ctx.store.mark_seen("recruiter:vista")
    pages = {1: [RecruiterCard("vista", "Ana Vista", "IT Recruiter")],
             2: [RecruiterCard("nueva", "Eva Nueva", "IT Recruiter")]}
    monkeypatch.setattr(main, "safe_search", lambda _d, _q, page: pages.get(page, []))

    # Act
    cards = main.new_recruiters(None, ctx)

    # Assert
    assert [c.slug for c in cards] == ["nueva"]
    assert ctx.store.search_pages["IT recruiter"] == 1  # página 3 vacía: fin de resultados


def test_new_recruiters_fills_budget_across_pages(tmp_path, monkeypatch):
    # Arrange
    ctx = _ctx(tmp_path)
    monkeypatch.setattr(main, "MAX_PROFILES_PER_CYCLE", 3)
    ctx.recruiter_queries, ctx.recruiter_cycle = ["IT recruiter"], 0
    pages = {1: [RecruiterCard("a", "Ana A", "IT Recruiter")],
             2: [RecruiterCard("b", "Bea B", "IT Recruiter"), RecruiterCard("c", "Cris C", "IT Recruiter")]}
    monkeypatch.setattr(main, "safe_search", lambda _d, _q, page: pages.get(page, []))

    # Act
    cards = main.new_recruiters(None, ctx)

    # Assert
    assert [c.slug for c in cards] == ["a", "b", "c"]
    assert ctx.store.search_pages["IT recruiter"] == 3
