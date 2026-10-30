from datetime import datetime
from types import SimpleNamespace

import pytest

import main
from classifier import post_age_days
from pacing import FOLLOWS_PER_DAY, Pacer, PaceSettings
from recruiters import RecruiterCard, is_it_recruiter, parse_people
from store import Store

DAY = datetime(2026, 11, 2, 15, 0)
NIGHT = datetime(2026, 11, 2, 3, 0)


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


def _ctx(tmp_path, now: datetime = DAY) -> SimpleNamespace:
    store = Store.load(tmp_path)
    return SimpleNamespace(store=store, pacer=Pacer(store, PaceSettings(), lambda: now), allow_follow=True,
                           recruiter_queries=["IT recruiter Córdoba", "tech recruiter"])


def _cards(count: int) -> list[RecruiterCard]:
    return [RecruiterCard(f"r{n}", f"Rec {n}", "IT Recruiter") for n in range(count)]


def _patch(monkeypatch, cards: list[RecruiterCard], searches: list[str], followed: list[str]) -> None:
    monkeypatch.setattr(main, "safe_search", lambda _d, query, _page: searches.append(query) or list(cards))
    monkeypatch.setattr(main, "follow", lambda _d, card: followed.append(card.slug) or True)
    monkeypatch.setattr(main, "follow_pause", lambda: None)


def test_harvest_recruiters_follows_up_to_daily_cap_from_search_results(tmp_path, monkeypatch):
    # Arrange
    ctx, searches, followed = _ctx(tmp_path), [], []
    _patch(monkeypatch, _cards(6), searches, followed)

    # Act
    main.harvest_recruiters(None, ctx)

    # Assert
    assert searches == ["IT recruiter Córdoba"]
    assert len(followed) == FOLLOWS_PER_DAY


def test_harvest_recruiters_searches_people_once_per_day_even_after_restart(tmp_path, monkeypatch):
    # Arrange
    searches, followed = [], []
    _patch(monkeypatch, _cards(1), searches, followed)
    main.harvest_recruiters(None, _ctx(tmp_path))

    # Act: estado recargado de disco, como tras reiniciar el loop
    main.harvest_recruiters(None, _ctx(tmp_path))

    # Assert
    assert len(searches) == 1


def test_harvest_recruiters_at_night_does_nothing(tmp_path, monkeypatch):
    # Arrange
    searches, followed = [], []
    _patch(monkeypatch, _cards(3), searches, followed)

    # Act
    main.harvest_recruiters(None, _ctx(tmp_path, NIGHT))

    # Assert
    assert searches == [] and followed == []


def test_harvest_recruiters_during_warmup_does_nothing(tmp_path, monkeypatch):
    # Arrange
    ctx, searches, followed = _ctx(tmp_path), [], []
    ctx.pacer.mark_restricted()
    _patch(monkeypatch, _cards(3), searches, followed)

    # Act
    main.harvest_recruiters(None, ctx)

    # Assert
    assert searches == []


def test_harvest_recruiters_with_all_seen_advances_page_for_next_day(tmp_path, monkeypatch):
    # Arrange
    ctx, searches, followed = _ctx(tmp_path), [], []
    cards = _cards(2)
    for card in cards:
        ctx.store.mark_seen(card.key)
    _patch(monkeypatch, cards, searches, followed)

    # Act
    main.harvest_recruiters(None, ctx)

    # Assert
    assert followed == []
    assert ctx.store.search_pages["IT recruiter Córdoba"] == 2
