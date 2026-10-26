from types import SimpleNamespace

from feed import FEED_URL, post_key
from sources import PAGES_PER_CYCLE, PAGE_IDLE_LIMIT, SEARCH_IDLE_LIMIT, plan_sources

RUN = SimpleNamespace(scroll_minutes=8, channel_scroll_minutes=2)
SEARCH = "https://www.linkedin.com/search/results/content/?keywords=%22enviar%20cv%22"


def test_plan_sources_with_many_pages_rotates_a_window_per_cycle():
    # Arrange
    pages = [f"https://www.linkedin.com/groups/{n}/" for n in range(PAGES_PER_CYCLE + 3)]

    # Act
    first = plan_sources(pages + [SEARCH], RUN, 0)
    second = plan_sources(pages + [SEARCH], RUN, 1)

    # Assert
    assert first[0].url == SEARCH and first[0].idle_limit == SEARCH_IDLE_LIMIT
    rotating = [s.url for s in first if "/groups/" in s.url]
    assert len(rotating) == PAGES_PER_CYCLE
    assert rotating != [s.url for s in second if "/groups/" in s.url]


def test_plan_sources_ends_with_feed_split_in_segments():
    # Act
    sources = plan_sources([], RUN, 0)

    # Assert
    assert [s.url for s in sources] == [FEED_URL, FEED_URL]
    assert all(s.minutes == 4 and s.idle_limit == PAGE_IDLE_LIMIT for s in sources)


def test_post_key_ignores_social_context_line():
    # Arrange
    body = "María Pérez • Tech Recruiter\n" + "Buscamos dev Python jr, enviar cv a rrhh@empresa.com. " * 4

    # Act / Assert
    assert post_key("Juan Gómez recomienda esto\n" + body) == post_key(body)
    assert post_key("A Ana le gusta esto\n" + body) == post_key(body)


class _FakeDriver:
    """Devuelve una tanda de posts por lectura y después nada, como una búsqueda agotada."""

    def __init__(self, batches: list[list[list[str]]]) -> None:
        self.batches = batches
        self.collects = 0

    def execute_script(self, script: str):
        if "jfDone" in script:
            self.collects += 1
            return self.batches.pop(0) if self.batches else []
        return [1000, "visible"]


def test_scroll_until_idle_stops_after_idle_limit_reads_without_new_posts(monkeypatch):
    # Arrange
    import feed
    from sources import Source

    monkeypatch.setattr(feed, "_wheel_scroll", lambda _driver: None)
    monkeypatch.setattr(feed.time, "sleep", lambda _s: None)
    text = "Buscamos desarrollador Python, enviar cv a rrhh@empresa.com " * 3
    driver = _FakeDriver([[[text, "https://www.linkedin.com/feed/update/1/"]]])
    source = Source(SEARCH, minutes=5, idle_limit=SEARCH_IDLE_LIMIT)

    # Act
    posts = feed._scroll_until_idle(driver, source, lambda _key: False)

    # Assert
    assert len(posts) == 1
    assert driver.collects == 1 + SEARCH_IDLE_LIMIT
