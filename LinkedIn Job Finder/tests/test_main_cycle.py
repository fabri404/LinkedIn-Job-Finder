from datetime import datetime
from types import SimpleNamespace

import main
from pacing import CyclePlan, Pacer, PaceSettings
from sources import Source
from store import Store


class _OpenPacer:
    """Sin topes: los tests de recorrido no dependen del presupuesto."""

    def cycle_plan(self, rotation: int) -> CyclePlan:
        return CyclePlan(rotation, content_searches=6, pages=3)

    def has_page_budget(self) -> bool:
        return True

    def cooling(self, _name: str) -> bool:
        return False

    def record_search_result(self, _posts: int) -> None:
        return None


def _ctx(channels: list[str], progress: dict[str, int] | None = None, pacer=None) -> SimpleNamespace:
    run = SimpleNamespace(scroll_minutes=4, channel_scroll_minutes=1)
    store = SimpleNamespace(progress=progress if progress is not None else {}, is_seen=lambda _key: False)
    return SimpleNamespace(settings=SimpleNamespace(run=run), channels=channels, store=store, current_source=0,
                           pacer=pacer or _OpenPacer())


def _fake_harvest(monkeypatch, visited: list[str]) -> None:
    def harvest(_driver, source: Source, _is_seen):
        visited.append(source.url)
        return [source.url]

    monkeypatch.setattr(main, "safe_harvest", harvest)


def test_harvest_sources_drains_right_after_each_source_with_new_posts(monkeypatch):
    # Arrange
    visited: list[str] = []
    _fake_harvest(monkeypatch, visited)
    queued_by_url = {"https://www.linkedin.com/feed/": 0,
                     "canal-a": 2, "canal-b": 0, "canal-c": 1}
    monkeypatch.setattr(main, "enqueue_new_posts", lambda posts, _ctx: queued_by_url[posts[0]])
    drained_after: list[int] = []
    ctx = _ctx(["canal-a", "canal-b", "canal-c"])

    def drain() -> int:
        drained_after.append(ctx.current_source)
        return 1

    # Act
    read, queued, sent = main.harvest_sources(None, ctx, drain)

    # Assert
    assert (read, queued, sent) == (4, 3, 2)
    assert drained_after == [0, 2]


def test_harvest_sources_runs_content_searches_before_pages_and_feed(monkeypatch):
    # Arrange
    visited: list[str] = []
    _fake_harvest(monkeypatch, visited)
    monkeypatch.setattr(main, "enqueue_new_posts", lambda _posts, _ctx: 0)
    search = "https://www.linkedin.com/search/results/content/?keywords=cv"
    ctx = _ctx(["https://www.linkedin.com/groups/1/", search])

    # Act
    main.harvest_sources(None, ctx, lambda: 0)

    # Assert
    assert visited[0] == search
    assert visited[-1] == "https://www.linkedin.com/feed/"


def test_harvest_sources_resumes_from_persisted_cursor_and_advances_rotation(monkeypatch):
    # Arrange
    visited: list[str] = []
    _fake_harvest(monkeypatch, visited)
    monkeypatch.setattr(main, "enqueue_new_posts", lambda _posts, _ctx: 0)
    progress = {main.CURSOR_KEY: 1, main.ROTATION_KEY: 4}
    ctx = _ctx(["canal-a", "canal-b"], progress)

    # Act
    main.harvest_sources(None, ctx, lambda: 0)

    # Assert
    assert visited == ["canal-b", "https://www.linkedin.com/feed/", "canal-a"]
    assert progress == {main.CURSOR_KEY: 0, main.ROTATION_KEY: 5}


def _real_pacer(tmp_path) -> Pacer:
    return Pacer(Store(tmp_path), PaceSettings(), lambda: datetime(2026, 11, 2, 15, 0))


def test_harvest_sources_without_page_budget_stops_and_keeps_cursor(monkeypatch, tmp_path):
    # Arrange
    visited: list[str] = []
    _fake_harvest(monkeypatch, visited)
    monkeypatch.setattr(main, "enqueue_new_posts", lambda _posts, _ctx: 0)
    pacer = _real_pacer(tmp_path)
    for _ in range(PaceSettings().hourly_pages):
        pacer.count_page("https://www.linkedin.com/feed/")
    progress = {main.CURSOR_KEY: 1}
    ctx = _ctx(["canal-a", "canal-b"], progress, pacer)

    # Act
    main.harvest_sources(None, ctx, lambda: 0)

    # Assert
    assert visited == []
    assert progress[main.CURSOR_KEY] == 1


def test_harvest_sources_empty_content_searches_start_a_cooldown(monkeypatch, tmp_path):
    # Arrange
    visited: list[str] = []
    monkeypatch.setattr(main, "safe_harvest", lambda _d, source, _s: visited.append(source.url) or [])
    monkeypatch.setattr(main, "enqueue_new_posts", lambda _posts, _ctx: 0)
    searches = [f"https://www.linkedin.com/search/results/content/?keywords=q{n}" for n in range(6)]
    pacer = _real_pacer(tmp_path)
    ctx = _ctx(searches, pacer=pacer)

    # Act
    main.harvest_sources(None, ctx, lambda: 0)

    # Assert: tras la quinta vacía no se pide la sexta, pero el feed sí
    assert visited == searches[:5] + ["https://www.linkedin.com/feed/"]
    assert pacer.cooling(main.CONTENT_SEARCH)
