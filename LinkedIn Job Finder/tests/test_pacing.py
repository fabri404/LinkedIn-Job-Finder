from datetime import datetime, timedelta

import pytest

from pacing import (
    CONTENT_SEARCH,
    DAY_CONTENT_SEARCHES,
    EASY_APPLY_PER_HOUR,
    EMPTY_SEARCHES_LIMIT,
    NIGHT_CONTENT_SEARCHES,
    NIGHT_HOURLY_PAGES,
    WARMUP_EASY_APPLY_LIMIT,
    Pacer,
    PaceSettings,
)
from store import Store

DAY = datetime(2026, 11, 2, 15, 10)
NIGHT = datetime(2026, 11, 2, 3, 10)
FEED = "https://www.linkedin.com/feed/"


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _pacer(tmp_path, now: datetime = DAY) -> tuple[Pacer, Clock]:
    clock = Clock(now)
    return Pacer(Store.load(tmp_path), PaceSettings(), clock), clock


def _reloaded(pacer: Pacer, clock: Clock) -> Pacer:
    pacer.store.save()
    return Pacer(Store.load(pacer.store.state_dir), PaceSettings(), clock)


def test_count_page_ignores_non_linkedin_urls(tmp_path):
    # Arrange
    pacer, _ = _pacer(tmp_path)

    # Act
    pacer.count_page("https://mail.google.com/mail/?view=cm&body=linkedin.com/in/adriel-lopez")
    pacer.count_page("about:blank")
    pacer.count_page(FEED)

    # Assert
    assert pacer.pages_left() == PaceSettings().hourly_pages - 1


def test_pages_left_respects_hourly_cap_by_day(tmp_path):
    # Arrange
    pacer, _ = _pacer(tmp_path)

    # Act
    for _ in range(PaceSettings().hourly_pages):
        pacer.count_page(FEED)

    # Assert
    assert not pacer.has_page_budget()


def test_pages_left_respects_daily_cap_across_hours(tmp_path):
    # Arrange
    pacer, clock = _pacer(tmp_path, DAY.replace(hour=8))
    for hour in range(8, 13):
        clock.now = DAY.replace(hour=hour)
        for _ in range(24):
            pacer.count_page(FEED)

    # Act
    clock.now = DAY.replace(hour=14)

    # Assert: 120 en el día aunque la hora 14 esté sin usar
    assert not pacer.has_page_budget()


def test_pages_left_at_night_uses_small_hourly_cap(tmp_path):
    # Arrange
    pacer, _ = _pacer(tmp_path, NIGHT)

    # Act
    for _ in range(NIGHT_HOURLY_PAGES):
        pacer.count_page(FEED)

    # Assert
    assert not pacer.has_page_budget()


def test_cycle_plan_is_smaller_at_night(tmp_path):
    day_plan = _pacer(tmp_path)[0].cycle_plan(3)
    night_plan = _pacer(tmp_path, NIGHT)[0].cycle_plan(3)

    assert (day_plan.content_searches, night_plan.content_searches) == (DAY_CONTENT_SEARCHES, NIGHT_CONTENT_SEARCHES)
    assert night_plan.pages == 0 and day_plan.rotation == 3


def test_record_search_result_after_limit_empties_starts_cooldown_that_survives_restart(tmp_path):
    # Arrange
    pacer, clock = _pacer(tmp_path)

    # Act
    results = [pacer.record_search_result(0) for _ in range(EMPTY_SEARCHES_LIMIT)]
    reloaded = _reloaded(pacer, clock)

    # Assert
    assert results[:-1] == [None] * (EMPTY_SEARCHES_LIMIT - 1)
    assert results[-1] == DAY + timedelta(hours=12)
    assert reloaded.cooling(CONTENT_SEARCH)
    assert reloaded.cycle_plan(0).content_searches == 0


def test_record_search_result_with_posts_resets_the_streak(tmp_path):
    # Arrange
    pacer, _ = _pacer(tmp_path)
    for _ in range(EMPTY_SEARCHES_LIMIT - 1):
        pacer.record_search_result(0)

    # Act
    pacer.record_search_result(3)

    # Assert
    assert pacer.record_search_result(0) is None


def test_record_search_result_repeated_block_doubles_cooldown(tmp_path):
    # Arrange
    pacer, clock = _pacer(tmp_path)
    for _ in range(EMPTY_SEARCHES_LIMIT):
        pacer.record_search_result(0)
    clock.now = DAY + timedelta(hours=13)

    # Act
    for _ in range(EMPTY_SEARCHES_LIMIT - 1):
        pacer.record_search_result(0)
    until = pacer.record_search_result(0)

    # Assert
    assert until == clock.now + timedelta(hours=24)


def test_may_easy_apply_never_at_night(tmp_path):
    assert not _pacer(tmp_path, NIGHT)[0].may_easy_apply(0)


def test_may_easy_apply_waits_gap_and_hourly_cap(tmp_path):
    # Arrange
    pacer, clock = _pacer(tmp_path, DAY.replace(minute=0))

    # Act / Assert
    assert pacer.may_easy_apply(0)
    pacer.record_easy_apply()
    assert not pacer.may_easy_apply(1)
    for step in range(1, EASY_APPLY_PER_HOUR):
        clock.now = DAY.replace(minute=20 * step)
        assert pacer.may_easy_apply(step)
        pacer.record_easy_apply()
    clock.now = DAY.replace(minute=59)
    assert not pacer.may_easy_apply(EASY_APPLY_PER_HOUR)


def test_may_easy_apply_respects_daily_limit(tmp_path):
    assert not _pacer(tmp_path)[0].may_easy_apply(PaceSettings().easy_apply_daily_limit)


def test_warmup_halves_budget_lowers_easy_apply_and_blocks_follows(tmp_path):
    # Arrange
    pacer, clock = _pacer(tmp_path)

    # Act
    pacer.mark_restricted()
    reloaded = _reloaded(pacer, clock)

    # Assert
    assert reloaded.in_warmup()
    assert reloaded.pages_left() == PaceSettings().hourly_pages // 2
    assert reloaded.easy_apply_limit() == WARMUP_EASY_APPLY_LIMIT
    assert not reloaded.may_follow()


def test_warmup_ends_after_a_week(tmp_path):
    # Arrange
    pacer, clock = _pacer(tmp_path)
    pacer.mark_restricted()

    # Act
    clock.now = DAY + timedelta(days=7, minutes=1)

    # Assert
    assert not pacer.in_warmup()


def test_follows_capped_per_day_and_reset_next_day(tmp_path):
    # Arrange
    pacer, clock = _pacer(tmp_path)
    while pacer.may_follow():
        pacer.record_follow()

    # Act
    clock.now = DAY + timedelta(days=1)

    # Assert
    assert pacer.may_follow()


def test_next_pause_at_night_is_two_to_three_hours(tmp_path):
    pause = _pacer(tmp_path, NIGHT)[0].next_pause_minutes(0)

    assert 120 <= pause <= 180


@pytest.mark.parametrize("idle", [0, 1, 5])
def test_next_pause_by_day_stays_in_human_range(tmp_path, idle):
    pacer, _ = _pacer(tmp_path)

    pause = pacer.next_pause_minutes(idle)

    assert 25 <= pause <= 90


def test_next_pause_takes_a_long_break_every_few_cycles(tmp_path):
    # Arrange
    pacer, _ = _pacer(tmp_path)

    # Act
    pauses = [pacer.next_pause_minutes(0) for _ in range(4)]

    # Assert
    assert any(p >= 90 for p in pauses)


def test_next_pause_without_hourly_budget_waits_for_next_hour(tmp_path):
    # Arrange
    pacer, _ = _pacer(tmp_path, DAY.replace(minute=5))
    for _ in range(PaceSettings().hourly_pages):
        pacer.count_page(FEED)

    # Act
    pause = pacer.next_pause_minutes(0)

    # Assert
    assert pause >= 55
