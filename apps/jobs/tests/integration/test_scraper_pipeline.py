"""
Integration tests for the ScraperService pipeline.

All Selenium calls are mocked — no real browser is launched.
Tests verify the logic: keyword → URL → collect → deduplicate → score → save.
"""
import pytest
from unittest.mock import MagicMock, patch

from apps.jobs.models import SearchSession, Job
from apps.jobs.services import ScraperService
from apps.jobs.tests.factories import SearchSessionFactory
from apps.keywords.tests.factories import KeywordFactory


pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def make_scraper(session=None, **session_kwargs):
    """Helper: create a ScraperService instance with a real DB session."""
    if session is None:
        session = SearchSessionFactory(status=SearchSession.Status.PENDING, **session_kwargs)
    return ScraperService(session.pk), session


def mock_driver_ctx(scraper, cards=None, login_ok=True):
    """Return a context manager that patches Selenium and Display on scraper."""
    mock_driver = MagicMock()
    mock_display = MagicMock()

    def create_driver():
        scraper._display = mock_display
        return mock_driver

    return (
        patch.object(scraper, "_create_driver", side_effect=create_driver),
        patch.object(scraper, "_login", return_value=login_ok),
        patch.object(scraper, "_collect_job_cards", return_value=cards or []),
        patch.object(scraper, "_scroll_job_results"),
        mock_driver,
    )


# ─── Session lifecycle ────────────────────────────────────────────────────────

class TestScraperSessionLifecycle:
    def test_sets_session_status_to_running_during_run(self):
        """Session should be RUNNING while the scraper is active."""
        KeywordFactory(word="python")
        scraper, session = make_scraper()
        status_during = []

        def check_status(driver):
            session.refresh_from_db()
            status_during.append(session.status)
            return []

        p_driver = patch.object(scraper, "_create_driver", return_value=MagicMock())
        p_login = patch.object(scraper, "_login", return_value=True)
        p_scroll = patch.object(scraper, "_scroll_job_results")
        p_collect = patch.object(scraper, "_collect_job_cards", side_effect=check_status)

        with p_driver, p_login, p_scroll, p_collect:
            scraper.run()

        assert SearchSession.Status.RUNNING in status_during

    def test_sets_session_completed_on_success(self):
        KeywordFactory(word="python")
        scraper, session = make_scraper()

        p_driver, p_login, p_collect, p_scroll, _ = mock_driver_ctx(scraper)
        with p_driver, p_login, p_collect, p_scroll:
            scraper.run()

        session.refresh_from_db()
        assert session.status == SearchSession.Status.COMPLETED

    def test_sets_session_failed_on_exception(self):
        KeywordFactory(word="python")
        scraper, session = make_scraper()

        p_driver = patch.object(scraper, "_create_driver", return_value=MagicMock())
        p_login = patch.object(scraper, "_login", side_effect=Exception("boom"))

        with p_driver, p_login, pytest.raises(Exception, match="boom"):
            scraper.run()

        session.refresh_from_db()
        assert session.status == SearchSession.Status.FAILED

    def test_sets_finished_at_on_completion(self):
        KeywordFactory(word="python")
        scraper, session = make_scraper()

        p_driver, p_login, p_collect, p_scroll, _ = mock_driver_ctx(scraper)
        with p_driver, p_login, p_collect, p_scroll:
            scraper.run()

        session.refresh_from_db()
        assert session.finished_at is not None

    def test_raises_runtime_error_when_login_fails(self):
        KeywordFactory(word="python")
        scraper, session = make_scraper()

        p_driver, p_login, p_collect, p_scroll, _ = mock_driver_ctx(scraper, login_ok=False)
        with p_driver, p_login, p_collect, p_scroll:
            with pytest.raises(RuntimeError, match="login failed"):
                scraper.run()


# ─── Keyword tracking ────────────────────────────────────────────────────────

class TestScraperKeywordTracking:
    def test_records_search_keywords_on_session(self):
        KeywordFactory(word="python")
        KeywordFactory(word="django")
        scraper, session = make_scraper()

        p_driver, p_login, p_collect, p_scroll, _ = mock_driver_ctx(scraper)
        with p_driver, p_login, p_collect, p_scroll:
            scraper.run()

        session.refresh_from_db()
        assert "python" in session.search_keywords
        assert "django" in session.search_keywords

    def test_only_active_keywords_are_searched(self):
        KeywordFactory(word="active_kw", is_active=True)
        KeywordFactory(word="inactive_kw", is_active=False)
        scraper, session = make_scraper()

        p_driver, p_login, p_collect, p_scroll, _ = mock_driver_ctx(scraper)
        with p_driver, p_login, p_collect, p_scroll:
            scraper.run()

        session.refresh_from_db()
        assert "active_kw" in session.search_keywords
        assert "inactive_kw" not in session.search_keywords


# ─── Job collection and saving ───────────────────────────────────────────────

class TestScraperJobPersistence:
    def test_saves_collected_jobs_to_db(self):
        KeywordFactory(word="python")
        scraper, session = make_scraper()

        cards = [{
            "url": "https://www.linkedin.com/jobs/view/123/",
            "title": "Python Developer",
            "company": "TechCorp",
            "location": "Remote",
            "text": "We are hiring a Python developer with Django experience.",
        }]

        p_driver, p_login, p_collect, p_scroll, _ = mock_driver_ctx(scraper, cards=cards)
        with p_driver, p_login, p_collect, p_scroll:
            scraper.run()

        assert Job.objects.count() == 1
        job = Job.objects.first()
        assert job.title == "Python Developer"
        assert job.company == "TechCorp"
        assert job.location == "Remote"

    def test_saves_search_keyword_on_job(self):
        KeywordFactory(word="react")
        scraper, session = make_scraper()

        cards = [{
            "url": "https://www.linkedin.com/jobs/view/456/",
            "title": "React Developer",
            "company": "StartupXYZ",
            "location": "Remote",
            "text": "React developer wanted for frontend team.",
        }]

        p_driver, p_login, p_collect, p_scroll, _ = mock_driver_ctx(scraper, cards=cards)
        with p_driver, p_login, p_collect, p_scroll:
            scraper.run()

        job = Job.objects.first()
        assert job.search_keyword == "react"

    def test_deduplicates_same_url_across_keywords(self):
        KeywordFactory(word="python")
        KeywordFactory(word="django")
        scraper, session = make_scraper()

        same_card = {
            "url": "https://www.linkedin.com/jobs/view/789/",
            "title": "Python Django Dev",
            "company": "Acme",
            "location": "Remote",
            "text": "Python Django developer wanted.",
        }

        p_driver, p_login, p_collect, p_scroll, _ = mock_driver_ctx(
            scraper, cards=[same_card]
        )
        with p_driver, p_login, p_collect, p_scroll:
            scraper.run()

        assert Job.objects.count() == 1

    def test_skips_previously_seen_urls(self):
        """Jobs already in DB from a previous run should not be duplicated."""
        KeywordFactory(word="python")
        scraper, session = make_scraper()

        # Pre-existing job in DB
        from apps.jobs.tests.factories import JobFactory
        existing = JobFactory(
            url="https://www.linkedin.com/jobs/view/999/",
            session=session,
        )

        cards = [{
            "url": existing.url,
            "title": "Old Job",
            "company": "OldCorp",
            "location": "Remote",
            "text": "Some old job posting.",
        }]

        p_driver, p_login, p_collect, p_scroll, _ = mock_driver_ctx(scraper, cards=cards)
        with p_driver, p_login, p_collect, p_scroll:
            scraper.run()

        assert Job.objects.count() == 1  # No duplicates

    def test_updates_total_found_on_session(self):
        KeywordFactory(word="python")
        scraper, session = make_scraper()

        cards = [
            {
                "url": f"https://www.linkedin.com/jobs/view/{i}/",
                "title": f"Job {i}",
                "company": "Corp",
                "location": "Remote",
                "text": "Job description here.",
            }
            for i in range(1, 4)
        ]

        p_driver, p_login, p_collect, p_scroll, _ = mock_driver_ctx(scraper, cards=cards)
        with p_driver, p_login, p_collect, p_scroll:
            scraper.run()

        session.refresh_from_db()
        assert session.total_found == 3
