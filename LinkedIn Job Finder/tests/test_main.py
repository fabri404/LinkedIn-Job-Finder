from datetime import date
from pathlib import Path

import pytest

from composer import Application
from config import RunSettings
from mailer import AuthError, MailError
from main import drain_queue
from store import QueuedApplication, Store

RUN = RunSettings(scroll_minutes=1, channel_scroll_minutes=1, pause_minutes_min=1, pause_minutes_max=1,
                  daily_send_limit=2, send_delay_min_s=0, send_delay_max_s=0)


def _store_with(tmp_path: Path, *emails: str) -> Store:
    store = Store.load(tmp_path)
    for email in emails:
        app = Application(email, "Asunto", "Cuerpo", Path("/tmp/cv.pdf"), "Dev")
        store.enqueue(QueuedApplication(app, ""))
    return store


def test_drain_queue_with_daily_limit_keeps_rest_pending(tmp_path):
    # Arrange
    store = _store_with(tmp_path, "a@x.com", "b@x.com", "c@x.com")
    sent_to: list[str] = []

    # Act
    sent = drain_queue(store, RUN, lambda app: sent_to.append(app.to))

    # Assert
    assert sent == 2
    assert sent_to == ["a@x.com", "b@x.com"]
    assert [item.app.to for item in store.pending] == ["c@x.com"]
    assert store.sent_on(date.today()) == 2


def test_drain_queue_permanent_error_drops_without_marking_contacted(tmp_path):
    store = _store_with(tmp_path, "bad@x.com", "ok@x.com")

    def sender(app: Application) -> None:
        if app.to == "bad@x.com":
            raise MailError("rechazado", permanent=True)

    sent = drain_queue(store, RUN, sender)

    assert sent == 1
    assert store.pending == []
    assert "bad@x.com" not in store.contacted


def test_drain_queue_transient_error_stops_and_keeps_item(tmp_path):
    store = _store_with(tmp_path, "a@x.com")

    def sender(app: Application) -> None:
        raise MailError("timeout")

    assert drain_queue(store, RUN, sender) == 0
    assert len(store.pending) == 1


def test_drain_queue_auth_error_propagates(tmp_path):
    store = _store_with(tmp_path, "a@x.com")

    def sender(app: Application) -> None:
        raise AuthError("credenciales")

    with pytest.raises(AuthError):
        drain_queue(store, RUN, sender)
    assert len(store.pending) == 1


def test_drain_queue_skips_vetoed_email(tmp_path):
    # Arrange
    store = _store_with(tmp_path, "malo@x.com", "ok@x.com")
    (tmp_path / "descartar.txt").write_text("MALO@x.com\n", encoding="utf-8")
    sent_to: list[str] = []

    # Act
    drain_queue(store, RUN, lambda app: sent_to.append(app.to))

    # Assert
    assert sent_to == ["ok@x.com"]
    assert store.contacted["malo@x.com"] == "descartado: descartado a mano"
