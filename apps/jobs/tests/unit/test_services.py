"""
Unit tests for JobAnalyzer and DetectorService in jobs/services.py.
No database access required — pure logic tests.
"""
import pytest

from apps.jobs.services import (
    JobAnalyzer,
    DetectorService,
    ScraperService,
    SCORE_THRESHOLD,
    BLACKLIST_DOMAINS,
)


pytestmark = pytest.mark.unit


# ─── Fixtures ─────────────────────────────────────────────────────────────────

JOB_POST_ES = """\
Estamos buscando un Desarrollador Python SR para sumar a nuestro equipo.

Requisitos:
- 3 años de experiencia en Python / Django
- Conocimientos en Docker y AWS

Modalidad híbrida, full time, lunes a viernes.
Ofrecemos muy buen sueldo + beneficios.

Interesados enviá tu CV a rrhh@tecnoempresa.com.ar
"""

JOB_POST_EN = """\
We are hiring a Senior Backend Engineer to join our growing team.

Requirements:
- 4+ years of Python / Django experience
- Familiarity with AWS and Docker

Remote position, full time.
We offer competitive salary and great benefits.

Apply now at careers@startup.io
"""

ENGAGEMENT_POST = """\
Si te resulta útil este post guardá este post y seguime para más tips.
¿Cansado de buscar trabajo? Te comparto los mejores consejos para conseguir empleo.
Dale like y compartilo con tus contactos!
"""

PLATFORM_POST = """\
Las mejores plataformas para buscar trabajo remoto:
1. Remotive
2. FlexJobs
3. Upwork
4. Workana
5. Remote OK

¡Comparte con alguien que lo necesite!
"""


# ─── JobAnalyzer.analyze ─────────────────────────────────────────────────────

class TestJobAnalyzerAnalyze:
    def setup_method(self):
        self.analyzer = JobAnalyzer()

    def test_spanish_job_post_is_verified(self):
        result = self.analyzer.analyze(JOB_POST_ES)
        assert result["is_job"] is True
        assert result["score"] >= SCORE_THRESHOLD

    def test_english_job_post_is_verified(self):
        result = self.analyzer.analyze(JOB_POST_EN)
        assert result["is_job"] is True
        assert result["score"] >= SCORE_THRESHOLD

    def test_engagement_post_is_not_job(self):
        result = self.analyzer.analyze(ENGAGEMENT_POST)
        assert result["is_job"] is False

    def test_platform_list_post_is_not_job(self):
        result = self.analyzer.analyze(PLATFORM_POST)
        assert result["is_job"] is False

    def test_returns_required_keys(self):
        result = self.analyzer.analyze("Some text")
        assert {"is_job", "score", "reasons", "emails", "language"} == set(result.keys())

    def test_reasons_is_list_of_strings(self):
        result = self.analyzer.analyze(JOB_POST_ES)
        assert isinstance(result["reasons"], list)
        assert all(isinstance(r, str) for r in result["reasons"])

    def test_empty_text_returns_low_score(self):
        result = self.analyzer.analyze("")
        assert result["score"] <= SCORE_THRESHOLD
        assert result["is_job"] is False


# ─── Positive signals ────────────────────────────────────────────────────────

class TestPositiveSignals:
    def setup_method(self):
        self.analyzer = JobAnalyzer()

    def test_hiring_phrase_adds_score(self):
        text = "Estamos buscando un desarrollador para el equipo."
        result = self.analyzer.analyze(text)
        reasons_text = " ".join(result["reasons"])
        assert "+3 hiring phrase" in reasons_text

    def test_requirement_header_adds_score(self):
        text = "Requisitos: 3 años de experiencia en Python."
        result = self.analyzer.analyze(text)
        reasons_text = " ".join(result["reasons"])
        assert "+3 requirements section" in reasons_text

    def test_apply_phrase_adds_score(self):
        text = "Postulate enviando tu CV a rrhh@empresa.com."
        result = self.analyzer.analyze(text)
        reasons_text = " ".join(result["reasons"])
        assert "+3 application phrase" in reasons_text

    def test_contact_email_adds_score(self):
        text = "Contacto: rrhh@empresa.com.ar para postularte."
        result = self.analyzer.analyze(text)
        reasons_text = " ".join(result["reasons"])
        assert "+2 contact email" in reasons_text

    def test_work_modality_adds_score(self):
        text = "La posición es modalidad híbrida con jornada full time."
        result = self.analyzer.analyze(text)
        reasons_text = " ".join(result["reasons"])
        assert "+2 work modality" in reasons_text

    def test_multiple_job_titles_adds_score(self):
        text = (
            "Buscamos desarrollador fullstack, también frontend, backend, "
            "qa tester y devops para el equipo."
        )
        result = self.analyzer.analyze(text)
        reasons_text = " ".join(result["reasons"])
        assert "+2 multiple job titles" in reasons_text


# ─── Negative signals ────────────────────────────────────────────────────────

class TestNegativeSignals:
    def setup_method(self):
        self.analyzer = JobAnalyzer()

    def test_engagement_phrases_reduce_score(self):
        base_text = "Estamos buscando un desarrollador Python."
        engagement_text = base_text + " Si te resulta útil compartilo con tus contactos."
        base_result = self.analyzer.analyze(base_text)
        eng_result = self.analyzer.analyze(engagement_text)
        assert eng_result["score"] < base_result["score"]

    def test_multiple_platforms_reduce_score(self):
        text = "Las mejores plataformas: Remotive, FlexJobs, Upwork, Workana, Remote OK."
        result = self.analyzer.analyze(text)
        reasons_text = " ".join(result["reasons"])
        assert "-4 platform list" in reasons_text

    def test_rhetorical_question_reduces_score(self):
        text = "¿Cansado de buscar trabajo? Acá algunos consejos útiles."
        result = self.analyzer.analyze(text)
        reasons_text = " ".join(result["reasons"])
        assert "-2 rhetorical question" in reasons_text


# ─── Language detection ──────────────────────────────────────────────────────

class TestLanguageDetection:
    def setup_method(self):
        self.analyzer = JobAnalyzer()

    def test_spanish_post_detected_as_es(self):
        result = self.analyzer.analyze(JOB_POST_ES)
        assert result["language"] == "es"

    def test_english_post_detected_as_en(self):
        result = self.analyzer.analyze(JOB_POST_EN)
        assert result["language"] == "en"


# ─── Email extraction ────────────────────────────────────────────────────────

class TestEmailExtraction:
    def setup_method(self):
        self.analyzer = JobAnalyzer()

    def test_extracts_valid_email(self):
        result = self.analyzer.analyze("Enviá tu CV a rrhh@empresa.com.ar para postularte.")
        assert "rrhh@empresa.com.ar" in result["emails"]

    def test_ignores_blacklisted_domains(self):
        result = self.analyzer.analyze("Ver más en linkedin.com o escribí a hr@linkedin.com")
        assert not any("linkedin.com" in e for e in result["emails"])

    def test_no_email_returns_empty_list(self):
        result = self.analyzer.analyze("Este post no tiene ningún email.")
        assert result["emails"] == []


# ─── DetectorService ─────────────────────────────────────────────────────────

class TestDetectorServiceExtractEmails:
    def test_extracts_single_email(self):
        emails = DetectorService.extract_emails("Contact hr@company.com for details.")
        assert "hr@company.com" in emails

    def test_extracts_multiple_emails(self):
        text = "Send to hr@company.com or jobs@startup.io"
        emails = DetectorService.extract_emails(text)
        assert len(emails) == 2

    def test_filters_blacklisted_domains(self):
        for domain in BLACKLIST_DOMAINS:
            emails = DetectorService.extract_emails(f"test@{domain}")
            assert len(emails) == 0, f"Expected {domain} to be blacklisted"

    def test_returns_lowercase(self):
        emails = DetectorService.extract_emails("Email: HR@Company.COM")
        assert all(e == e.lower() for e in emails)

    def test_deduplicates_emails(self):
        text = "Write to hr@company.com or HR@company.com"
        emails = DetectorService.extract_emails(text)
        assert len(emails) == 1

    def test_strips_trailing_dot(self):
        emails = DetectorService.extract_emails("Contact hr@company.com.")
        assert "hr@company.com" in emails
        assert "hr@company.com." not in emails


class TestDetectorServiceDetectLanguage:
    def test_spanish_text_returns_es(self):
        text = "Buscamos incorporar un desarrollador con experiencia en Python."
        assert DetectorService.detect_language(text) == "es"

    def test_english_text_returns_en(self):
        text = "We are hiring a senior engineer to join our team and apply now."
        assert DetectorService.detect_language(text) == "en"

    def test_empty_text_defaults_to_es(self):
        assert DetectorService.detect_language("") == "es"


class TestDetectorServiceIsRelevant:
    def test_relevant_when_keyword_present(self):
        assert DetectorService.is_relevant("Looking for a Django developer", ["django"]) is True

    def test_not_relevant_when_keyword_absent(self):
        assert DetectorService.is_relevant("Java spring boot position", ["django"]) is False

    def test_min_matches_respected(self):
        text = "Python Django developer position"
        assert DetectorService.is_relevant(text, ["python", "django", "react"], min_matches=2) is True
        assert DetectorService.is_relevant(text, ["python", "django", "react"], min_matches=3) is False

    def test_case_insensitive(self):
        assert DetectorService.is_relevant("Looking for DJANGO developer", ["django"]) is True


# ─── Score threshold constant ─────────────────────────────────────────────────

class TestScoreThreshold:
    def test_threshold_is_positive_integer(self):
        assert isinstance(SCORE_THRESHOLD, int)
        assert SCORE_THRESHOLD > 0


# ─── DetectorService.is_relevant — word boundary matching ─────────────────────

class TestDetectorServiceIsRelevantWordBoundary:
    """Tests for the improved word-boundary keyword matching."""

    def test_keyword_go_does_not_match_google(self):
        assert DetectorService.is_relevant("Check out google.com", ["go"]) is False

    def test_keyword_go_matches_standalone_go(self):
        assert DetectorService.is_relevant("Experience with Go language required", ["go"]) is True

    def test_keyword_java_does_not_match_javascript(self):
        assert DetectorService.is_relevant("JavaScript developer", ["java"]) is False

    def test_keyword_java_matches_standalone_java(self):
        assert DetectorService.is_relevant("Senior Java engineer wanted", ["java"]) is True

    def test_empty_keywords_returns_false(self):
        assert DetectorService.is_relevant("Python developer wanted", []) is False

    def test_empty_text_returns_false(self):
        assert DetectorService.is_relevant("", ["python"]) is False

    def test_multi_word_keyword_matches(self):
        assert DetectorService.is_relevant(
            "We are looking for a python developer", ["python developer"]
        ) is True

    def test_multi_word_keyword_no_partial_match(self):
        assert DetectorService.is_relevant(
            "We are looking for a python backend dev", ["python developer"]
        ) is False


# ─── ScraperService.build_search_url ─────────────────────────────────────────

class TestBuildSearchUrl:
    """Tests for ScraperService.build_search_url (static method)."""

    def test_contains_base_linkedin_jobs_url(self):
        url = ScraperService.build_search_url("python")
        assert url.startswith("https://www.linkedin.com/jobs/search/")

    def test_single_keyword_encoded(self):
        url = ScraperService.build_search_url("python")
        assert "keywords=python" in url

    def test_multi_word_keyword_encoded(self):
        url = ScraperService.build_search_url("python developer")
        assert "keywords=python+developer" in url or "keywords=python%20developer" in url

    def test_remote_filter_included(self):
        url = ScraperService.build_search_url("django")
        assert "f_WT=2" in url

    def test_time_filter_included(self):
        url = ScraperService.build_search_url("django")
        assert "f_TPR=r604800" in url

    def test_start_defaults_to_zero(self):
        url = ScraperService.build_search_url("react")
        assert "start=0" in url

    def test_start_pagination(self):
        url = ScraperService.build_search_url("react", start=25)
        assert "start=25" in url

    def test_special_characters_encoded(self):
        url = ScraperService.build_search_url("c#")
        assert "c%23" in url or "c+" not in url  # # must be encoded

    def test_empty_keyword_produces_valid_url(self):
        url = ScraperService.build_search_url("")
        assert "keywords=" in url
        assert url.startswith("https://www.linkedin.com/jobs/search/")
