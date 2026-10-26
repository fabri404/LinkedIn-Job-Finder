from datetime import date, datetime
from pathlib import Path

from composer import Application
from store import QueuedApplication, Store


def _item(to: str = "rrhh@acme.com") -> QueuedApplication:
    app = Application(to, "Postulación: Dev", "Hola", Path("/tmp/cv.pdf"), "Dev")
    return QueuedApplication(app, "https://linkedin.com/posts/x")


def test_store_load_after_save_preserves_pending_and_seen(tmp_path):
    # Arrange
    store = Store.load(tmp_path)
    store.mark_seen("abc")
    store.enqueue(_item())

    # Act
    store.save()
    reloaded = Store.load(tmp_path)

    # Assert
    assert reloaded.is_seen("abc")
    assert reloaded.pending == [_item()]


def test_complete_first_counts_toward_daily_quota_and_writes_csv(tmp_path):
    store = Store.load(tmp_path)
    store.enqueue(_item())

    store.complete_first(datetime(2026, 10, 15, 10, 0))

    assert store.sent_on(date(2026, 10, 15)) == 1
    assert store.pending == []
    assert "rrhh@acme.com" in (tmp_path / "enviados.csv").read_text(encoding="utf-8")


def test_previous_contacts_are_known_but_not_counted_in_quota(tmp_path):
    store = Store.load(tmp_path)

    store.import_previous_contacts(["Sofia@BeRecruiting.com"])

    assert store.is_known_recipient("sofia@berecruiting.com")
    assert store.sent_on(date.today()) == 0


def test_queued_recipient_is_known_to_avoid_duplicates(tmp_path):
    store = Store.load(tmp_path)

    store.enqueue(_item("talento@acme.com"))

    assert store.is_known_recipient("talento@acme.com")
