"""
Integration tests for the Search Sessions API endpoints.

Endpoints covered:
  GET  /api/searches/
  GET  /api/searches/{id}/
  POST /api/searches/start/
"""
import pytest
from django.urls import reverse

from apps.jobs.models import SearchSession
from apps.jobs.tests.factories import SearchSessionFactory, JobFactory


pytestmark = [pytest.mark.django_db, pytest.mark.integration]


# ─── GET /api/searches/ ───────────────────────────────────────────────────────

class TestSearchSessionListView:
    def test_returns_200(self, api_client):
        response = api_client.get("/api/searches/")
        assert response.status_code == 200

    def test_empty_when_no_sessions(self, api_client):
        response = api_client.get("/api/searches/")
        assert response.data["count"] == 0
        assert response.data["results"] == []

    def test_lists_all_sessions(self, api_client):
        SearchSessionFactory.create_batch(3)
        response = api_client.get("/api/searches/")
        assert response.data["count"] == 3

    def test_response_contains_expected_fields(self, api_client):
        SearchSessionFactory()
        response = api_client.get("/api/searches/")
        item = response.data["results"][0]
        expected_fields = {
            "id", "started_at", "finished_at", "scroll_duration",
            "search_mode", "search_keywords",
            "status", "total_found", "total_verified", "duration_seconds",
        }
        assert expected_fields.issubset(set(item.keys()))

    def test_ordered_by_started_at_descending(self, api_client):
        s1 = SearchSessionFactory(status=SearchSession.Status.COMPLETED)
        s2 = SearchSessionFactory(status=SearchSession.Status.PENDING)
        response = api_client.get("/api/searches/")
        ids = [item["id"] for item in response.data["results"]]
        # Most recent first — s2 was created after s1
        assert ids.index(s2.id) < ids.index(s1.id)

    def test_pagination_page_size(self, api_client):
        SearchSessionFactory.create_batch(25)
        response = api_client.get("/api/searches/")
        # Default PAGE_SIZE is 20
        assert len(response.data["results"]) <= 20
        assert response.data["count"] == 25


# ─── GET /api/searches/{id}/ ──────────────────────────────────────────────────

class TestSearchSessionDetailView:
    def test_returns_200_for_existing_session(self, api_client):
        session = SearchSessionFactory()
        response = api_client.get(f"/api/searches/{session.pk}/")
        assert response.status_code == 200

    def test_returns_404_for_missing_session(self, api_client):
        response = api_client.get("/api/searches/99999/")
        assert response.status_code == 404

    def test_detail_includes_jobs(self, api_client):
        session = SearchSessionFactory()
        JobFactory.create_batch(3, session=session)
        response = api_client.get(f"/api/searches/{session.pk}/")
        assert "jobs" in response.data
        assert len(response.data["jobs"]) == 3

    def test_detail_jobs_have_expected_fields(self, api_client):
        session = SearchSessionFactory()
        JobFactory(session=session)
        response = api_client.get(f"/api/searches/{session.pk}/")
        job_item = response.data["jobs"][0]
        assert "id" in job_item
        assert "url" in job_item
        assert "score" in job_item
        assert "is_verified" in job_item


# ─── POST /api/searches/start/ ────────────────────────────────────────────────

class TestStartSearchView:
    def test_returns_202_with_valid_payload(self, api_client, mocker):
        # Mock the background scraper thread so it does not actually run
        mocker.patch("threading.Thread.start")
        response = api_client.post(
            "/api/searches/start/",
            {"scroll_duration": 30},
            format="json",
        )
        assert response.status_code == 202

    def test_creates_search_session_in_db(self, api_client, mocker):
        mocker.patch("threading.Thread.start")
        api_client.post(
            "/api/searches/start/",
            {"scroll_duration": 60},
            format="json",
        )
        assert SearchSession.objects.count() == 1

    def test_session_created_with_pending_status(self, api_client, mocker):
        mocker.patch("threading.Thread.start")
        api_client.post(
            "/api/searches/start/",
            {"scroll_duration": 60},
            format="json",
        )
        session = SearchSession.objects.first()
        assert session.status == SearchSession.Status.PENDING

    def test_session_created_with_correct_scroll_duration(self, api_client, mocker):
        mocker.patch("threading.Thread.start")
        api_client.post(
            "/api/searches/start/",
            {"scroll_duration": 90},
            format="json",
        )
        session = SearchSession.objects.first()
        assert session.scroll_duration == 90

    def test_returns_202_when_body_empty_uses_defaults(self, api_client, mocker):
        # scroll_duration and search_mode both have defaults now
        mocker.patch("threading.Thread.start")
        response = api_client.post("/api/searches/start/", {}, format="json")
        assert response.status_code == 202

    def test_returns_400_when_scroll_duration_too_low(self, api_client):
        response = api_client.post(
            "/api/searches/start/",
            {"scroll_duration": 2},
            format="json",
        )
        assert response.status_code == 400

    def test_returns_400_when_scroll_duration_too_high(self, api_client):
        response = api_client.post(
            "/api/searches/start/",
            {"scroll_duration": 9999},
            format="json",
        )
        assert response.status_code == 400

    def test_response_contains_session_data(self, api_client, mocker):
        mocker.patch("threading.Thread.start")
        response = api_client.post(
            "/api/searches/start/",
            {"scroll_duration": 45},
            format="json",
        )
        data = response.data
        assert "id" in data
        assert data["scroll_duration"] == 45
        assert data["status"] == "pending"

    def test_returns_409_when_session_already_running(self, api_client, mocker):
        """Only one scraper session may run at a time."""
        mocker.patch("threading.Thread.start")
        SearchSessionFactory(status=SearchSession.Status.RUNNING)
        response = api_client.post(
            "/api/searches/start/",
            {"scroll_duration": 60},
            format="json",
        )
        assert response.status_code == 409

    def test_session_defaults_to_jobs_mode(self, api_client, mocker):
        mocker.patch("threading.Thread.start")
        api_client.post(
            "/api/searches/start/",
            {"scroll_duration": 60},
            format="json",
        )
        session = SearchSession.objects.first()
        assert session.search_mode == "jobs"

    def test_session_can_be_created_with_feed_mode(self, api_client, mocker):
        mocker.patch("threading.Thread.start")
        api_client.post(
            "/api/searches/start/",
            {"scroll_duration": 60, "search_mode": "feed"},
            format="json",
        )
        session = SearchSession.objects.first()
        assert session.search_mode == "feed"

    def test_response_includes_search_mode_field(self, api_client, mocker):
        mocker.patch("threading.Thread.start")
        response = api_client.post(
            "/api/searches/start/",
            {"search_mode": "jobs"},
            format="json",
        )
        assert "search_mode" in response.data
        assert response.data["search_mode"] == "jobs"
