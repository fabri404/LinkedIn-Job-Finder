import time
from types import SimpleNamespace
from urllib.error import HTTPError

import main
from jobs import MAX_DETAILS_PER_CYCLE, JobCard
from store import Store


def _ctx(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(store=Store.load(tmp_path), jobs_paused_until=0.0)


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

    # Assert
    assert ctx.jobs_paused_until > time.time()
    assert not ctx.store.is_seen("job:1")


def test_sources_from_cursor_starts_after_hung_source_and_wraps():
    assert main.sources_from_cursor(5, 3) == [3, 4, 0, 1, 2]


def test_sources_from_cursor_past_end_wraps_to_start():
    assert main.sources_from_cursor(3, 3) == [0, 1, 2]
