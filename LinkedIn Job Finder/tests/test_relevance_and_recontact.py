from datetime import date, timedelta
from pathlib import Path

from classifier import evaluate_post
from composer import Application
from relevance import relevance_score
from store import SENT_CSV, QueuedApplication, Store, normalize_role

TAIL = " Remoto Argentina. Requisitos: Git. Enviar CV a rrhh@empresa.com"


def _posting(body: str):
    return evaluate_post(body + TAIL, [])[1]


def _queued(to: str, score: int) -> QueuedApplication:
    return QueuedApplication(Application(to, "asunto", "cuerpo", Path("cv.pdf"), "Dev"), "url", score)


def test_relevance_score_python_junior_ranks_above_java():
    # Act
    python = relevance_score(_posting("Buscamos Desarrollador Python Jr con FastAPI."))
    java = relevance_score(_posting("Buscamos Desarrollador Java Jr con Spring."))

    # Assert
    assert python > java


def test_store_enqueue_orders_by_score_keeping_arrival_order_on_ties(tmp_path):
    # Arrange
    store = Store(tmp_path)

    # Act
    for to, score in [("a@x.com", 1), ("b@x.com", 5), ("c@x.com", 1), ("d@x.com", 5)]:
        store.enqueue(_queued(to, score))

    # Assert
    assert [item.app.to for item in store.pending] == ["b@x.com", "d@x.com", "a@x.com", "c@x.com"]


def test_queued_application_round_trips_score(tmp_path):
    # Arrange
    store = Store(tmp_path)
    store.enqueue(_queued("a@x.com", 7))

    # Act
    store.save()

    # Assert
    assert Store.load(tmp_path).pending[0].score == 7


def _store_contacted(tmp_path, days_ago: int, role: str) -> Store:
    store = Store(tmp_path)
    store.contacted["r@x.com"] = (date.today() - timedelta(days=days_ago)).isoformat()
    (tmp_path / SENT_CSV).write_text(f"fecha,email,puesto,asunto,cv,post_url\n2026-01-01,r@x.com,{role},s,cv,u\n",
                                     encoding="utf-8")
    return store


def test_is_known_recipient_recent_contact_blocks_any_role(tmp_path):
    store = _store_contacted(tmp_path, days_ago=3, role="Desarrollador Python")
    assert store.is_known_recipient("r@x.com", "QA Tester")


def test_is_known_recipient_old_contact_allows_a_different_role(tmp_path):
    store = _store_contacted(tmp_path, days_ago=30, role="Desarrollador Python")
    assert not store.is_known_recipient("r@x.com", "QA Tester Jr")


def test_is_known_recipient_old_contact_blocks_the_same_role(tmp_path):
    store = _store_contacted(tmp_path, days_ago=30, role="Desarrollador/a Python Jr.")
    assert store.is_known_recipient("R@x.com", "desarrollador python")


def test_is_known_recipient_previous_or_discarded_contact_is_always_blocked(tmp_path):
    store = Store(tmp_path)
    store.contacted["p@x.com"] = "previo"
    assert store.is_known_recipient("p@x.com", "QA")


def test_normalize_role_ignores_level_accents_and_gender_marks():
    assert normalize_role("Desarrollador/a Python Jr.") == normalize_role("desarrollador python")
