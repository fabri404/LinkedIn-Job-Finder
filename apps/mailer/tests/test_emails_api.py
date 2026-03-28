"""
Integration tests for the Email Logs API endpoints.

Endpoints covered:
  GET /api/emails/
  GET /api/emails/{id}/
"""
import pytest

from apps.mailer.models import EmailLog
from apps.mailer.tests.factories import EmailLogFactory
from apps.jobs.tests.factories import JobFactory


pytestmark = [pytest.mark.django_db, pytest.mark.integration]


# ─── GET /api/emails/ ────────────────────────────────────────────────────────

class TestEmailLogListView:
    def test_returns_200(self, api_client):
        response = api_client.get("/api/emails/")
        assert response.status_code == 200

    def test_empty_when_no_logs(self, api_client):
        response = api_client.get("/api/emails/")
        assert response.data["count"] == 0

    def test_lists_all_email_logs(self, api_client):
        EmailLogFactory.create_batch(4)
        response = api_client.get("/api/emails/")
        assert response.data["count"] == 4

    def test_response_contains_expected_fields(self, api_client):
        EmailLogFactory()
        response = api_client.get("/api/emails/")
        item = response.data["results"][0]
        expected_fields = {
            "id", "job", "to_email", "language",
            "subject", "success", "error_message", "sent_at",
        }
        assert expected_fields.issubset(set(item.keys()))

    def test_filter_by_success_true(self, api_client):
        EmailLogFactory.create_batch(3, success=True)
        EmailLogFactory.create_batch(2, success=False)
        response = api_client.get("/api/emails/?success=true")
        assert response.data["count"] == 3
        for item in response.data["results"]:
            assert item["success"] is True

    def test_filter_by_success_false(self, api_client):
        EmailLogFactory.create_batch(3, success=True)
        EmailLogFactory.create_batch(2, success=False, error_message="SMTP error")
        response = api_client.get("/api/emails/?success=false")
        assert response.data["count"] == 2
        for item in response.data["results"]:
            assert item["success"] is False

    def test_filter_by_job(self, api_client):
        job_a = JobFactory()
        job_b = JobFactory()
        EmailLogFactory.create_batch(3, job=job_a)
        EmailLogFactory.create_batch(2, job=job_b)
        response = api_client.get(f"/api/emails/?job={job_a.pk}")
        assert response.data["count"] == 3

    def test_pagination(self, api_client):
        EmailLogFactory.create_batch(25)
        response = api_client.get("/api/emails/")
        assert len(response.data["results"]) <= 20
        assert response.data["count"] == 25

    def test_ordered_by_sent_at_descending(self, api_client):
        log_a = EmailLogFactory(success=True)
        log_b = EmailLogFactory(success=False, error_message="timeout")
        response = api_client.get("/api/emails/")
        ids = [item["id"] for item in response.data["results"]]
        # Most recently created (log_b) should appear first
        assert ids.index(log_b.id) < ids.index(log_a.id)


# ─── GET /api/emails/{id}/ ───────────────────────────────────────────────────

class TestEmailLogDetailView:
    def test_returns_200_for_existing_log(self, api_client):
        log = EmailLogFactory()
        response = api_client.get(f"/api/emails/{log.pk}/")
        assert response.status_code == 200

    def test_returns_404_for_missing_log(self, api_client):
        response = api_client.get("/api/emails/99999/")
        assert response.status_code == 404

    def test_detail_contains_correct_to_email(self, api_client):
        log = EmailLogFactory(to_email="hr@targetcompany.com")
        response = api_client.get(f"/api/emails/{log.pk}/")
        assert response.data["to_email"] == "hr@targetcompany.com"

    def test_detail_contains_correct_language(self, api_client):
        log = EmailLogFactory(language=EmailLog.Language.ENGLISH)
        response = api_client.get(f"/api/emails/{log.pk}/")
        assert response.data["language"] == "en"

    def test_detail_contains_job_id(self, api_client):
        job = JobFactory()
        log = EmailLogFactory(job=job)
        response = api_client.get(f"/api/emails/{log.pk}/")
        assert response.data["job"] == job.pk

    def test_detail_success_field_matches_model(self, api_client):
        log_ok = EmailLogFactory(success=True)
        log_fail = EmailLogFactory(success=False, error_message="SMTP timeout")

        resp_ok = api_client.get(f"/api/emails/{log_ok.pk}/")
        resp_fail = api_client.get(f"/api/emails/{log_fail.pk}/")

        assert resp_ok.data["success"] is True
        assert resp_fail.data["success"] is False
        assert resp_fail.data["error_message"] == "SMTP timeout"
