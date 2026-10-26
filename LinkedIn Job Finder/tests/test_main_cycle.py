from types import SimpleNamespace

import main


def _ctx(channels: list[str]) -> SimpleNamespace:
    run = SimpleNamespace(scroll_minutes=4, channel_scroll_minutes=1)
    return SimpleNamespace(settings=SimpleNamespace(run=run), channels=channels, source_cursor=0, current_source=0)


def test_harvest_sources_drains_right_after_each_source_with_new_posts(monkeypatch):
    # Arrange
    queued_by_url = {main.FEED_URL: 0, "canal-a": 2, "canal-b": 0, "canal-c": 1}
    monkeypatch.setattr(main, "safe_harvest", lambda _d, url, _m: [url])
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
    assert drained_after == [1, 3]
