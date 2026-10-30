from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

import main
from classifier import evaluate_job
from easy_apply import SUBMITTED, ApplyResult
from jobs import MAX_DETAILS_PER_CYCLE, JobCard
from pacing import JOBS, Pacer, PaceSettings
from store import Store

DAY = datetime(2026, 11, 2, 15, 0)


def _ctx(tmp_path, now: datetime = DAY, applied: list[str] | None = None) -> SimpleNamespace:
    store = Store.load(tmp_path)
    log = applied if applied is not None else []
    return SimpleNamespace(store=store, pacer=Pacer(store, PaceSettings(), lambda: now),
                           settings=SimpleNamespace(mail=SimpleNamespace(cv_dir=Path("/tmp/cv"))),
                           applier=lambda url, _cv: log.append(url) or ApplyResult(SUBMITTED))


def _card(job_id: str, title: str = "Desarrollador Python") -> JobCard:
    return JobCard(job_id, title, "Acme", "Argentina")


def test_evaluate_job_cards_reads_at_most_max_details(tmp_path, monkeypatch):
    # Arrange
    ctx = _ctx(tmp_path)
    read: list[str] = []
    monkeypatch.setattr(main, "process_job_card", lambda card, _ctx: read.append(card.job_id) or 0)
    monkeypatch.setattr(main, "detail_pause", lambda: None)
    cards = [_card(str(i)) for i in range(MAX_DETAILS_PER_CYCLE + 3)]

    # Act
    main._evaluate_job_cards(cards, ctx)

    # Assert
    assert len(read) == MAX_DETAILS_PER_CYCLE


def test_evaluate_job_cards_off_profile_title_is_seen_without_request(tmp_path, monkeypatch):
    # Arrange
    ctx = _ctx(tmp_path)
    monkeypatch.setattr(main, "process_job_card", lambda *_: (_ for _ in ()).throw(AssertionError))

    # Act
    main._evaluate_job_cards([_card("1", "Data Scientist")], ctx)

    # Assert
    assert ctx.store.is_seen("job:1")


def test_evaluate_job_cards_on_429_pauses_jobs_section(tmp_path, monkeypatch):
    # Arrange
    ctx = _ctx(tmp_path)

    def rate_limited(card, _ctx):
        raise HTTPError(card.url, 429, "Too Many Requests", None, None)

    monkeypatch.setattr(main, "process_job_card", rate_limited)

    # Act
    main._evaluate_job_cards([_card("1"), _card("2")], ctx)

    # Assert: la pausa queda en el estado y sobrevive a un reinicio
    assert ctx.pacer.cooling(JOBS)
    ctx.store.save()
    assert Pacer(Store.load(tmp_path), PaceSettings(), lambda: DAY).cooling(JOBS)
    assert not ctx.store.is_seen("job:1")


def test_sources_from_cursor_starts_after_hung_source_and_wraps():
    assert main.sources_from_cursor(5, 3) == [3, 4, 0, 1, 2]


def test_sources_from_cursor_past_end_wraps_to_start():
    assert main.sources_from_cursor(3, 3) == [0, 1, 2]


def _posting(title: str, body: str):
    verdict, posting = evaluate_job(title, f"{title}\nAcme\nCórdoba, Argentina\n{body}")
    assert verdict.accepted, verdict.reason
    return posting


def test_apply_or_list_relevant_job_is_applied_and_spaces_the_next_one(tmp_path):
    # Arrange
    applied: list[str] = []
    ctx = _ctx(tmp_path, applied=applied)
    card = JobCard("1", "Desarrollador Python Junior", "Acme", "Córdoba, Argentina")

    # Act
    main._apply_or_list(card, _posting(card.title, "Python, FastAPI y SQL. Híbrido."), ctx)

    # Assert
    assert applied == [card.url]
    assert not ctx.pacer.may_easy_apply(1)  # intervalo de 10–20 min hasta la próxima


def test_apply_or_list_off_stack_title_goes_to_manual_list_without_applying(tmp_path):
    # Arrange
    applied: list[str] = []
    ctx = _ctx(tmp_path, applied=applied)
    card = JobCard("2", "Desarrollador .NET Junior", "Acme", "Córdoba, Argentina")

    # Act
    main._apply_or_list(card, _posting(card.title, "C# y SQL Server. Híbrido."), ctx)

    # Assert
    assert applied == []
    assert "revisar a mano" in (tmp_path / "empleos_linkedin.csv").read_text(encoding="utf-8")


def test_apply_or_list_same_role_and_company_is_applied_once(tmp_path):
    # Arrange
    applied: list[str] = []
    ctx = _ctx(tmp_path, applied=applied)
    posting = _posting("Desarrollador Python Junior", "Python y FastAPI. Híbrido.")

    # Act: el mismo aviso republicado con otro id
    main._apply_or_list(JobCard("3", "Desarrollador Python Junior", "Acme", "Córdoba"), posting, ctx)
    main._apply_or_list(JobCard("4", "Desarrollador Python Jr.", "ACME", "Córdoba"), posting, ctx)

    # Assert
    assert len(applied) == 1


def test_evaluate_job_cards_at_night_reads_nothing(tmp_path, monkeypatch):
    # Arrange
    ctx = _ctx(tmp_path, now=datetime(2026, 11, 2, 3, 0))
    monkeypatch.setattr(main, "process_job_card", lambda *_: (_ for _ in ()).throw(AssertionError))

    # Act
    found = main._evaluate_job_cards([_card("1")], ctx)

    # Assert
    assert found == 0
    assert not ctx.store.is_seen("job:1")
