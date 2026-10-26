from datetime import date

import pytest

import easy_apply
from classifier import is_profile_title
from easy_apply import CLOSE_LABEL, EASY_APPLY_TEXT, READY, SUBMITTED, ApplyResult, EasyApplyFiller
from store import JOBS_CSV, Store


def test_easy_apply_text_matches_only_the_button_label():
    assert EASY_APPLY_TEXT.match("Solicitud sencilla")
    assert EASY_APPLY_TEXT.match("Continuar")
    assert not EASY_APPLY_TEXT.match("Senior Full Stack Engineer\nAcme\nArgentina · Solicitud sencilla")


def test_close_label_ignores_dismiss_job_buttons():
    assert CLOSE_LABEL.match("Descartar")
    assert not CLOSE_LABEL.match("Descartar empleo «Software Engineer»")



def _filler(monkeypatch, walk: ApplyResult, may_submit: bool) -> tuple[EasyApplyFiller, list[str]]:
    calls: list[str] = []
    filler = EasyApplyFiller(None, lambda: may_submit)
    monkeypatch.setattr(easy_apply, "open_url", lambda _d, _u: None)
    monkeypatch.setattr(easy_apply.time, "sleep", lambda _s: None)
    monkeypatch.setattr(filler, "_start_button", lambda: object())
    monkeypatch.setattr(filler, "driver", type("D", (), {"execute_script": lambda *_a: None})())
    monkeypatch.setattr(filler, "_wait_for_root", lambda: object())
    monkeypatch.setattr(filler, "_walk_pages", lambda: walk)
    monkeypatch.setattr(filler, "_submit", lambda: calls.append("submit") or ApplyResult(SUBMITTED))
    monkeypatch.setattr(filler, "_close_and_save", lambda: calls.append("save") or True)
    return filler, calls


def test_easy_apply_complete_form_with_quota_left_is_submitted(monkeypatch):
    filler, calls = _filler(monkeypatch, ApplyResult(READY), may_submit=True)
    assert filler("https://www.linkedin.com/jobs/view/1/", "cv.pdf").status == SUBMITTED
    assert calls == ["submit"]


def test_easy_apply_complete_form_without_quota_is_only_saved(monkeypatch):
    filler, calls = _filler(monkeypatch, ApplyResult(READY), may_submit=False)
    assert filler("https://www.linkedin.com/jobs/view/1/", "cv.pdf").status == READY
    assert calls == ["save"]


def test_easy_apply_incomplete_form_is_saved_even_with_quota(monkeypatch):
    filler, calls = _filler(monkeypatch, ApplyResult("guardada incompleta", ("Gender",)), may_submit=True)
    result = filler("https://www.linkedin.com/jobs/view/1/", "cv.pdf")
    assert result.missing == ("Gender",)
    assert calls == ["save"]


def test_store_easy_applies_on_counts_only_sent_rows_of_that_day(tmp_path):
    # Arrange
    (tmp_path / JOBS_CSV).write_text(
        "fecha,puesto,empresa,ubicacion,url,solicitud_sencilla,faltan\n"
        "2026-10-25T10:00:00,Dev,A,AR,u1,enviada,\n"
        "2026-10-25T11:00:00,Dev,B,AR,u2,guardada incompleta,Gender\n"
        "2026-10-24T11:00:00,Dev,C,AR,u3,enviada,\n", encoding="utf-8")

    # Act / Assert
    assert Store(tmp_path).easy_applies_on(date(2026, 10, 25)) == 1


@pytest.mark.parametrize("title", ["Trainee IT", "Pasante de Sistemas", "Analista de Soporte Jr", "Soporte IT",
                                   "Test Automation Engineer", "Programa Jóvenes Profesionales IT"])
def test_is_profile_title_junior_it_titles_are_accepted(title):
    assert is_profile_title(title)


@pytest.mark.parametrize("title", ["Trainee de Finanzas", "Pasante Administrativo", "Senior Data Engineer"])
def test_is_profile_title_non_it_or_senior_titles_are_rejected(title):
    assert not is_profile_title(title)
