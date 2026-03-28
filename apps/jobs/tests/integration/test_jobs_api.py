"""
Integration tests for the Jobs API endpoints.

Endpoints covered:
  GET  /api/jobs/
  GET  /api/jobs/{id}/
  POST /api/jobs/{id}/send-email/
"""
import pytest
from unittest.mock import MagicMock, patch

from apps.jobs.models import Job
from apps.jobs.tests.factories import JobFactory, SearchSessionFactory
from apps.mailer.models import EmailLog


pytestmark = [pytest.mark.django_db, pytest.mark.integration]


# ─── GET /api/jobs/ ───────────────────────────────────────────────────────────

class TestJobListView:
    def test_returns_200(self, api_client):
        response = api_client.get("/api/jobs/")
        assert response.status_code == 200

    def test_empty_when_no_jobs(self, api_client):
        response = api_client.get("/api/jobs/")
        assert response.data["count"] == 0

    def test_lists_all_jobs(self, api_client):
        JobFactory.create_batch(5)
        response = api_client.get("/api/jobs/")
        assert response.data["count"] == 5

    def test_response_contains_expected_fields(self, api_client):
        JobFactory()
        response = api_client.get("/api/jobs/")
        item = response.data["results"][0]
        expected_fields = {
            "id", "url", "title", "company", "location", "search_keyword",
            "text_preview", "score", "is_verified",
            "found_at", "emails_extracted", "emails_count", "session",
        }
        assert expected_fields.issubset(set(item.keys()))

    def test_response_includes_title_and_company(self, api_client):
        JobFactory(title="Backend Developer", company="Acme Corp", location="Remote")
        response = api_client.get("/api/jobs/")
        item = response.data["results"][0]
        assert item["title"] == "Backend Developer"
        assert item["company"] == "Acme Corp"
        assert item["location"] == "Remote"

    def test_filter_by_is_verified_true(self, api_client):
        JobFactory.create_batch(3, is_verified=True)
        JobFactory.create_batch(2, is_verified=False)
        response = api_client.get("/api/jobs/?is_verified=true")
        assert response.data["count"] == 3
        for item in response.data["results"]:
            assert item["is_verified"] is True

    def test_filter_by_is_verified_false(self, api_client):
        JobFactory.create_batch(3, is_verified=True)
        JobFactory.create_batch(2, is_verified=False)
        response = api_client.get("/api/jobs/?is_verified=false")
        assert response.data["count"] == 2

    def test_filter_by_session(self, api_client):
        session_a = SearchSessionFactory()
        session_b = SearchSessionFactory()
        JobFactory.create_batch(3, session=session_a)
        JobFactory.create_batch(2, session=session_b)
        response = api_client.get(f"/api/jobs/?session={session_a.pk}")
        assert response.data["count"] == 3

    def test_pagination(self, api_client):
        JobFactory.create_batch(25)
        response = api_client.get("/api/jobs/")
        assert len(response.data["results"]) <= 20
        assert response.data["count"] == 25


# ─── GET /api/jobs/{id}/ ──────────────────────────────────────────────────────

class TestJobDetailView:
    def test_returns_200_for_existing_job(self, api_client):
        job = JobFactory()
        response = api_client.get(f"/api/jobs/{job.pk}/")
        assert response.status_code == 200

    def test_returns_404_for_missing_job(self, api_client):
        response = api_client.get("/api/jobs/99999/")
        assert response.status_code == 404

    def test_detail_includes_score_reasons(self, api_client):
        job = JobFactory(
            text_preview=(
                "Estamos buscando un desarrollador Python SR. "
                "Requisitos: 3 años de experiencia. "
                "Enviá tu CV a hr@empresa.com. Modalidad híbrida."
            )
        )
        response = api_client.get(f"/api/jobs/{job.pk}/")
        assert "score_reasons" in response.data

    def test_score_reasons_is_list(self, api_client):
        job = JobFactory(text_preview="Estamos buscando desarrollador.")
        response = api_client.get(f"/api/jobs/{job.pk}/")
        assert isinstance(response.data["score_reasons"], list)

    def test_response_has_correct_url(self, api_client):
        job = JobFactory(
            url="https://www.linkedin.com/feed/update/urn:li:activity:999"
        )
        response = api_client.get(f"/api/jobs/{job.pk}/")
        assert response.data["url"] == job.url


# ─── POST /api/jobs/{id}/send-email/ ─────────────────────────────────────────

class TestSendEmailView:
    def test_returns_200_on_successful_send(self, api_client):
        job = JobFactory()
        mock_log = MagicMock(spec=EmailLog)
        mock_log.success = True

        with patch("apps.mailer.services.MailerService.send_cv", return_value=mock_log):
            response = api_client.post(
                f"/api/jobs/{job.pk}/send-email/",
                {"to_email": "recruiter@company.com", "language": "es"},
                format="json",
            )
        assert response.status_code == 200
        assert "recruiter@company.com" in response.data["detail"]

    def test_returns_502_on_failed_send(self, api_client):
        job = JobFactory()
        mock_log = MagicMock(spec=EmailLog)
        mock_log.success = False
        mock_log.error_message = "SMTP connection refused"

        with patch("apps.mailer.services.MailerService.send_cv", return_value=mock_log):
            response = api_client.post(
                f"/api/jobs/{job.pk}/send-email/",
                {"to_email": "recruiter@company.com", "language": "es"},
                format="json",
            )
        assert response.status_code == 502
        assert "error" in response.data

    def test_returns_404_for_missing_job(self, api_client):
        response = api_client.post(
            "/api/jobs/99999/send-email/",
            {"to_email": "recruiter@company.com", "language": "es"},
            format="json",
        )
        assert response.status_code == 404

    def test_returns_400_for_invalid_email(self, api_client):
        job = JobFactory()
        response = api_client.post(
            f"/api/jobs/{job.pk}/send-email/",
            {"to_email": "not-a-valid-email", "language": "es"},
            format="json",
        )
        assert response.status_code == 400

    def test_returns_400_when_to_email_missing(self, api_client):
        job = JobFactory()
        response = api_client.post(
            f"/api/jobs/{job.pk}/send-email/",
            {"language": "es"},
            format="json",
        )
        assert response.status_code == 400

    def test_sends_with_english_language(self, api_client):
        job = JobFactory()
        mock_log = MagicMock(spec=EmailLog)
        mock_log.success = True

        with patch("apps.mailer.services.MailerService.send_cv", return_value=mock_log) as mock_send:
            api_client.post(
                f"/api/jobs/{job.pk}/send-email/",
                {"to_email": "recruiter@company.com", "language": "en"},
                format="json",
            )
        mock_send.assert_called_once_with(
            job=job,
            to_email="recruiter@company.com",
            language="en",
        )
