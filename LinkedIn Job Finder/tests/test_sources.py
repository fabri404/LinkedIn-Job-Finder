from types import SimpleNamespace

from feed import FEED_URL, post_key
from pacing import CyclePlan
from sources import FEED_SEGMENT_MINUTES, PAGE_IDLE_LIMIT, SEARCH_IDLE_LIMIT, plan_sources

RUN = SimpleNamespace(scroll_minutes=8, channel_scroll_minutes=2)
SEARCH = "https://www.linkedin.com/search/results/content/?keywords=%22enviar%20cv%22"


def test_plan_sources_with_many_pages_rotates_a_window_per_cycle():
    # Arrange
    pages = [f"https://www.linkedin.com/groups/{n}/" for n in range(6)]

    # Act
    first = plan_sources(pages + [SEARCH], RUN, CyclePlan(0, content_searches=6, pages=3))
    second = plan_sources(pages + [SEARCH], RUN, CyclePlan(1, content_searches=6, pages=3))

    # Assert
    assert first[0].url == SEARCH and first[0].idle_limit == SEARCH_IDLE_LIMIT
    rotating = [s.url for s in first if "/groups/" in s.url]
    assert len(rotating) == 3
    assert rotating != [s.url for s in second if "/groups/" in s.url]


def test_plan_sources_takes_only_a_rotating_window_of_content_searches():
    # Arrange
    searches = [f"{SEARCH}{n}" for n in range(41)]

    # Act
    sources = plan_sources(searches, RUN, CyclePlan(1, content_searches=6, pages=3))

    # Assert
    assert [s.url for s in sources[:-1]] == searches[6:12]


def test_plan_sources_ends_with_a_single_feed_segment():
    # Act
    sources = plan_sources([], RUN, CyclePlan(0, content_searches=6, pages=3))

    # Assert
    assert [s.url for s in sources] == [FEED_URL]
    assert sources[0].minutes == FEED_SEGMENT_MINUTES and sources[0].idle_limit == PAGE_IDLE_LIMIT


def test_plan_sources_without_searches_nor_pages_reads_only_the_feed():
    sources = plan_sources([SEARCH, "https://www.linkedin.com/groups/1/"], RUN, CyclePlan(0, 0, 0))

    assert [s.url for s in sources] == [FEED_URL]


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
    driver = _FakeDriver([[[text, "https://www.linkedin.com/feed/update/1/", "https://www.linkedin.com/in/ana/"]]])
    source = Source(SEARCH, minutes=5, idle_limit=SEARCH_IDLE_LIMIT)

    # Act
    posts = feed._scroll_until_idle(driver, source, lambda _key: False)

    # Assert
    assert len(posts) == 1
    assert driver.collects == 1 + SEARCH_IDLE_LIMIT
