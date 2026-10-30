import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

import dashboard_data
import loop_control
import main
from pacing import Pacer, PaceSettings
from store import STATE_FILE, Store


def test_store_load_migrates_old_seen_list_and_prunes_old_dates(tmp_path):
    # Arrange
    old = (date.today() - timedelta(days=90)).isoformat()
    recent = (date.today() - timedelta(days=5)).isoformat()
    (tmp_path / STATE_FILE).write_text(json.dumps({"seen": {"viejo": old, "nuevo": recent}}), encoding="utf-8")
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / STATE_FILE).write_text(json.dumps({"seen": ["a", "b"]}), encoding="utf-8")

    # Act
    store = Store.load(tmp_path)
    migrated = Store.load(legacy)

    # Assert
    assert store.seen == {"nuevo": recent}
    assert migrated.seen == {"a": date.today().isoformat(), "b": date.today().isoformat()}


def test_store_save_skips_writing_when_nothing_changed(tmp_path):
    # Arrange
    store = Store(tmp_path)
    store.mark_seen("k")
    store.save()
    path = tmp_path / STATE_FILE
    first = path.stat().st_mtime_ns
    path.write_text("tocado a mano", encoding="utf-8")

    # Act
    store.save()

    # Assert
    assert path.read_text(encoding="utf-8") == "tocado a mano"
    assert first > 0


def test_loop_command_runs_loop_with_low_cpu_and_io_priority():
    command = loop_control.loop_command(loop_control.LoopMode.CONTINUOUS)
    assert command[command.index("nice"):command.index("nice") + 6] == loop_control.LOW_PRIORITY
    assert command[-1] == "main.py"


def test_dashboard_cached_reloads_only_when_file_changes(tmp_path):
    # Arrange
    path = tmp_path / "x.txt"
    path.write_text("a", encoding="utf-8")
    loads: list[int] = []

    def load() -> str:
        loads.append(1)
        return path.read_text(encoding="utf-8")

    # Act
    first = dashboard_data._cached(path, load)
    second = dashboard_data._cached(path, load)
    path.write_text("bb", encoding="utf-8")
    third = dashboard_data._cached(path, load)

    # Assert
    assert (first, second, third) == ("a", "a", "bb")
    assert len(loads) == 2


def test_retry_minutes_backs_off_after_consecutive_failures():
    assert [main.retry_minutes(n) for n in (1, 2, 3, 4)] == [1, 2, 4, 8]
    assert main.retry_minutes(20) == main.MAX_RETRY_MINUTES


def test_run_fresh_cycle_unexpected_error_is_logged_and_skips_the_source(monkeypatch, tmp_path):
    # Arrange
    store = Store(tmp_path)
    ctx = SimpleNamespace(settings=SimpleNamespace(chrome_profile_dir=tmp_path), store=store, current_source=4)
    monkeypatch.setattr(main, "open_feed", lambda _s: object())
    monkeypatch.setattr(main, "run_cycle", lambda _d, _c: {}["falta"])
    monkeypatch.setattr(main, "kill_chrome", lambda _d, _p: None)

    # Act
    completed = main.run_fresh_cycle(ctx, dry_run=True)

    # Assert
    assert completed is False
    assert store.progress[main.CURSOR_KEY] == 5


def test_run_loop_without_page_budget_rests_without_opening_chrome(monkeypatch, tmp_path):
    # Arrange
    store = Store(tmp_path)
    pacer = Pacer(store, PaceSettings(), lambda: datetime(2026, 11, 2, 15, 0))
    for _ in range(PaceSettings().hourly_pages):
        pacer.count_page("https://www.linkedin.com/feed/")
    ctx = SimpleNamespace(store=store, pacer=pacer, idle_cycles=0)
    monkeypatch.setattr(main, "run_fresh_cycle", lambda *_: (_ for _ in ()).throw(AssertionError("abrió Chrome")))

    def stop(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(main.time, "sleep", stop)

    # Act / Assert
    with pytest.raises(KeyboardInterrupt):
        main.run_loop(ctx, SimpleNamespace(once=False, dry_run=True))
