import json
from datetime import date, timedelta
from types import SimpleNamespace

import dashboard_data
import loop_control
import main
from store import STATE_FILE, Store

RUN = SimpleNamespace(pause_minutes_min=10, pause_minutes_max=10)


def test_next_pause_minutes_doubles_per_idle_cycle_up_to_cap():
    assert main.next_pause_minutes(RUN, 0) == 10
    assert main.next_pause_minutes(RUN, 1) == 20
    assert main.next_pause_minutes(RUN, 2) == 40
    assert main.next_pause_minutes(RUN, 10) == main.MAX_PAUSE_MINUTES


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
