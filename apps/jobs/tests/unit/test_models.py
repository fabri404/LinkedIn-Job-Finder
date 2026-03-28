"""
Unit tests for jobs/models.py — no DB required for pure model logic.
"""
import pytest
from datetime import timedelta
from django.utils import timezone

from apps.jobs.models import SearchSession, Job


pytestmark = pytest.mark.unit


# ─── SearchSession ────────────────────────────────────────────────────────────

class TestSearchSessionDurationSeconds:
    """SearchSession.duration_seconds property."""

    def test_returns_none_when_not_finished(self):
        session = SearchSession(
            scroll_duration=60,
            started_at=timezone.now(),
            finished_at=None,
        )
        assert session.duration_seconds is None

    def test_returns_integer_when_finished(self):
        now = timezone.now()
        session = SearchSession(
            scroll_duration=60,
            started_at=now,
            finished_at=now + timedelta(seconds=90),
        )
        assert session.duration_seconds == 90

    def test_returns_zero_for_same_start_and_finish(self):
        now = timezone.now()
        session = SearchSession(
            scroll_duration=10,
            started_at=now,
            finished_at=now,
        )
        assert session.duration_seconds == 0


class TestSearchSessionStr:
    """SearchSession.__str__ format."""

    def test_str_contains_status(self):
        session = SearchSession(
            pk=1,
            scroll_duration=30,
            status=SearchSession.Status.COMPLETED,
            started_at=timezone.now(),
        )
        assert "completed" in str(session).lower()

    def test_str_contains_pk(self):
        session = SearchSession(
            pk=42,
            scroll_duration=30,
            status=SearchSession.Status.PENDING,
            started_at=timezone.now(),
        )
        assert "42" in str(session)


class TestSearchSessionStatusChoices:
    """SearchSession.Status choices exist and are correct."""

    def test_all_status_choices_present(self):
        statuses = [c[0] for c in SearchSession.Status.choices]
        assert "pending" in statuses
        assert "running" in statuses
        assert "completed" in statuses
        assert "failed" in statuses


# ─── Job ──────────────────────────────────────────────────────────────────────

class TestJobStr:
    """Job.__str__ format."""

    def test_verified_job_str(self):
        job = Job(pk=5, score=8, is_verified=True)
        result = str(job)
        assert "verified" in result
        assert "8" in result

    def test_unverified_job_str(self):
        job = Job(pk=3, score=1, is_verified=False)
        result = str(job)
        assert "unverified" in result
        assert "1" in result


class TestJobEmailsExtractedDefault:
    """emails_extracted should default to an empty list."""

    def test_default_is_empty_list(self):
        job = Job(score=0)
        assert job.emails_extracted == []
        assert isinstance(job.emails_extracted, list)
