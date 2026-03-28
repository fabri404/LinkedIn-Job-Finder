"""
Integration tests for the Keywords API endpoints.

Endpoints covered:
  GET    /api/keywords/
  POST   /api/keywords/
  DELETE /api/keywords/{id}/
"""
import pytest

from apps.keywords.models import Keyword
from apps.keywords.tests.factories import KeywordFactory


pytestmark = [pytest.mark.django_db, pytest.mark.integration]


# ─── GET /api/keywords/ ───────────────────────────────────────────────────────

class TestKeywordListView:
    def test_returns_200(self, api_client):
        response = api_client.get("/api/keywords/")
        assert response.status_code == 200

    def test_empty_when_no_keywords(self, api_client):
        response = api_client.get("/api/keywords/")
        assert response.data["count"] == 0

    def test_lists_all_keywords(self, api_client):
        KeywordFactory.create_batch(4)
        response = api_client.get("/api/keywords/")
        assert response.data["count"] == 4

    def test_response_contains_expected_fields(self, api_client):
        KeywordFactory(word="python")
        response = api_client.get("/api/keywords/")
        item = response.data["results"][0]
        assert "id" in item
        assert "word" in item
        assert "is_active" in item
        assert "created_at" in item

    def test_filter_by_is_active_true(self, api_client):
        KeywordFactory.create_batch(3, is_active=True)
        KeywordFactory.create_batch(2, is_active=False)
        response = api_client.get("/api/keywords/?is_active=true")
        assert response.data["count"] == 3
        for item in response.data["results"]:
            assert item["is_active"] is True

    def test_filter_by_is_active_false(self, api_client):
        KeywordFactory.create_batch(3, is_active=True)
        KeywordFactory.create_batch(2, is_active=False)
        response = api_client.get("/api/keywords/?is_active=false")
        assert response.data["count"] == 2


# ─── POST /api/keywords/ ─────────────────────────────────────────────────────

class TestKeywordCreateView:
    def test_creates_keyword_and_returns_201(self, api_client):
        response = api_client.post(
            "/api/keywords/",
            {"word": "Django"},
            format="json",
        )
        assert response.status_code == 201

    def test_keyword_is_saved_to_db(self, api_client):
        api_client.post("/api/keywords/", {"word": "Django"}, format="json")
        assert Keyword.objects.filter(word="django").exists()

    def test_keyword_is_normalised_to_lowercase(self, api_client):
        api_client.post("/api/keywords/", {"word": "PYTHON"}, format="json")
        kw = Keyword.objects.get(word="python")
        assert kw.word == "python"

    def test_keyword_is_stripped_of_whitespace(self, api_client):
        api_client.post("/api/keywords/", {"word": "  react  "}, format="json")
        kw = Keyword.objects.get(word="react")
        assert kw.word == "react"

    def test_returns_400_for_blank_word(self, api_client):
        response = api_client.post("/api/keywords/", {"word": ""}, format="json")
        assert response.status_code == 400

    def test_returns_400_for_duplicate_word(self, api_client):
        KeywordFactory(word="django")
        response = api_client.post("/api/keywords/", {"word": "django"}, format="json")
        assert response.status_code == 400

    def test_returns_400_for_only_spaces(self, api_client):
        response = api_client.post("/api/keywords/", {"word": "   "}, format="json")
        assert response.status_code == 400

    def test_default_is_active_is_true(self, api_client):
        api_client.post("/api/keywords/", {"word": "flask"}, format="json")
        kw = Keyword.objects.get(word="flask")
        assert kw.is_active is True

    def test_can_create_inactive_keyword(self, api_client):
        response = api_client.post(
            "/api/keywords/",
            {"word": "cobol", "is_active": False},
            format="json",
        )
        assert response.status_code == 201
        assert Keyword.objects.get(word="cobol").is_active is False


# ─── DELETE /api/keywords/{id}/ ──────────────────────────────────────────────

class TestKeywordDestroyView:
    def test_deletes_keyword_and_returns_204(self, api_client):
        keyword = KeywordFactory(word="todelete")
        response = api_client.delete(f"/api/keywords/{keyword.pk}/")
        assert response.status_code == 204

    def test_keyword_removed_from_db(self, api_client):
        keyword = KeywordFactory(word="todelete")
        api_client.delete(f"/api/keywords/{keyword.pk}/")
        assert not Keyword.objects.filter(pk=keyword.pk).exists()

    def test_returns_404_for_missing_keyword(self, api_client):
        response = api_client.delete("/api/keywords/99999/")
        assert response.status_code == 404
