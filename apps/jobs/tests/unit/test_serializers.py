"""
Unit tests for jobs/serializers.py.
"""
import pytest
from django.utils import timezone

from apps.jobs.models import Job, SearchSession
from apps.jobs.serializers import (
    JobSerializer,
    JobDetailSerializer,
    SearchSessionSerializer,
    StartSearchSerializer,
)


pytestmark = pytest.mark.unit


# ─── JobSerializer ───────────────────────────────────────────────────────────

class TestJobSerializer:
    def _make_job(self, emails=None):
        """Build an unsaved Job instance (no DB)."""
        session = SearchSession(
            pk=1,
            scroll_duration=30,
            status=SearchSession.Status.COMPLETED,
            started_at=timezone.now(),
            total_found=5,
            total_verified=2,
        )
        return Job(
            pk=10,
            session=session,
            url="https://www.linkedin.com/feed/update/urn:li:activity:123",
            text_preview="Looking for a Django developer.",
            score=7,
            is_verified=True,
            found_at=timezone.now(),
            emails_extracted=emails or [],
        )

    def test_emails_count_zero_when_empty(self):
        job = self._make_job(emails=[])
        data = JobSerializer(job).data
        assert data["emails_count"] == 0

    def test_emails_count_matches_list_length(self):
        job = self._make_job(emails=["recruiter@acme.com", "hr@corp.io"])
        data = JobSerializer(job).data
        assert data["emails_count"] == 2

    def test_all_expected_fields_present(self):
        job = self._make_job()
        data = JobSerializer(job).data
        expected = {
            "id", "url", "text_preview", "score", "is_verified",
            "found_at", "emails_extracted", "emails_count", "session",
        }
        assert expected.issubset(set(data.keys()))


class TestJobDetailSerializer:
    def test_score_reasons_empty_by_default(self):
        session = SearchSession(
            pk=1,
            scroll_duration=30,
            status=SearchSession.Status.COMPLETED,
            started_at=timezone.now(),
        )
        job = Job(
            pk=1,
            session=session,
            url="https://www.linkedin.com/feed/update/urn:li:activity:1",
            score=5,
            found_at=timezone.now(),
            emails_extracted=[],
        )
        data = JobDetailSerializer(job).data
        assert data["score_reasons"] == []

    def test_score_reasons_from_context(self):
        session = SearchSession(
            pk=1,
            scroll_duration=30,
            status=SearchSession.Status.COMPLETED,
            started_at=timezone.now(),
        )
        job = Job(
            pk=1,
            session=session,
            url="https://www.linkedin.com/feed/update/urn:li:activity:1",
            score=5,
            found_at=timezone.now(),
            emails_extracted=[],
        )
        reasons = ["+3 hiring phrase: 'we are hiring'", "+2 contact email"]
        data = JobDetailSerializer(job, context={"score_reasons": reasons}).data
        assert data["score_reasons"] == reasons


# ─── SearchSessionSerializer ──────────────────────────────────────────────────

class TestSearchSessionSerializer:
    def _make_session(self):
        return SearchSession(
            pk=1,
            scroll_duration=60,
            status=SearchSession.Status.COMPLETED,
            started_at=timezone.now(),
            total_found=10,
            total_verified=4,
        )

    def test_all_expected_fields_present(self):
        session = self._make_session()
        data = SearchSessionSerializer(session).data
        expected = {
            "id", "started_at", "finished_at", "scroll_duration",
            "status", "total_found", "total_verified", "duration_seconds",
        }
        assert expected.issubset(set(data.keys()))

    def test_duration_seconds_none_when_not_finished(self):
        session = self._make_session()
        session.finished_at = None
        data = SearchSessionSerializer(session).data
        assert data["duration_seconds"] is None


# ─── StartSearchSerializer ────────────────────────────────────────────────────

class TestStartSearchSerializer:
    def test_valid_scroll_duration(self):
        s = StartSearchSerializer(data={"scroll_duration": 60})
        assert s.is_valid(), s.errors

    def test_scroll_duration_too_low(self):
        s = StartSearchSerializer(data={"scroll_duration": 4})
        assert not s.is_valid()
        assert "scroll_duration" in s.errors

    def test_scroll_duration_too_high(self):
        s = StartSearchSerializer(data={"scroll_duration": 601})
        assert not s.is_valid()
        assert "scroll_duration" in s.errors

    def test_scroll_duration_boundary_min(self):
        s = StartSearchSerializer(data={"scroll_duration": 5})
        assert s.is_valid(), s.errors

    def test_scroll_duration_boundary_max(self):
        s = StartSearchSerializer(data={"scroll_duration": 600})
        assert s.is_valid(), s.errors
