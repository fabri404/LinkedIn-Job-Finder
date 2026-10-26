from easy_apply import CLOSE_LABEL, EASY_APPLY_TEXT


def test_easy_apply_text_matches_only_the_button_label():
    assert EASY_APPLY_TEXT.match("Solicitud sencilla")
    assert EASY_APPLY_TEXT.match("Continuar")
    assert not EASY_APPLY_TEXT.match("Senior Full Stack Engineer\nAcme\nArgentina · Solicitud sencilla")


def test_close_label_ignores_dismiss_job_buttons():
    assert CLOSE_LABEL.match("Descartar")
    assert not CLOSE_LABEL.match("Descartar empleo «Software Engineer»")
