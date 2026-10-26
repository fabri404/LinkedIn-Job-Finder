from pathlib import Path

from classifier import evaluate_post
from composer import clean_role, compose
from tests.test_classifier import ADN, EMBITALENT, KEYWORDS

CV_DIR = Path("/tmp/cv")


def test_compose_generic_subject_never_says_junior():
    _, posting = evaluate_post(EMBITALENT, KEYWORDS)
    app = compose(posting, posting.emails[0], CV_DIR)
    assert "junior" not in app.subject.lower()
    assert "junior" not in app.body.lower()
    assert app.subject.startswith("Postulación: ")
    assert app.cv_path.name == "CV_Adriel_Lopez_Backend_ES.pdf"


def test_compose_generic_subject_request_uses_role_and_name():
    _, posting = evaluate_post(ADN, KEYWORDS)
    app = compose(posting, posting.emails[0], CV_DIR)
    assert app.subject.endswith("- Adriel López")


def test_clean_role_non_dev_phrase_falls_back_to_default_role():
    from composer import clean_role
    assert clean_role("hashtag", "backend", "es") == "Desarrollador Backend Python"
    assert clean_role("Enviá tu CV junto con tu remuneración", "backend", "es") == "Desarrollador Backend Python"


def test_clean_role_cuts_at_first_clause():
    from composer import clean_role
    role = clean_role("Desarrollador/a Fullstack , con buena base técnica, iniciativa", "backend", "es")
    assert role == "Desarrollador/a Fullstack"


def test_clean_role_drops_unclosed_parenthesis_after_cut():
    from composer import clean_role
    assert clean_role("QA (Kubernetes, Docker)", "qa", "es") == "QA Automation"


def test_clean_role_strips_leading_verb_and_article():
    from composer import clean_role
    assert clean_role("incorporar un/a Desarrollador/a Full stack", "backend", "es") == "Desarrollador/a Full stack"


def test_clean_role_strips_senior_and_dangling_connectors():
    from composer import clean_role
    assert clean_role("Fullstack Developer o Senior", "backend", "es") == "Fullstack Developer"
    assert clean_role("QA Automation / Sr", "qa", "es") == "QA Automation"


def test_clean_role_strips_busqueda_activa_prefix():
    from composer import clean_role
    assert clean_role("activa de QA Engineer (QE) bilingüe", "qa", "es") == "QA Engineer (QE) bilingüe"


def test_clean_role_keeps_product_support_role():
    assert clean_role("Product Support Specialist", "backend", "en") == "Product Support Specialist"


def test_clean_role_removes_city_and_dangling_slash():
    role = clean_role("Desarrollador/a Backend Ssr / Sr (Focus en Ciberseguridad) en Córdoba", "backend", "es")

    assert role == "Desarrollador/a Backend (Focus en Ciberseguridad)"


def test_clean_role_strips_un_a_and_cargo_prefixes():
    assert clean_role("un(a) Desarrollador(a) de Software", "backend", "es") == "Desarrollador(a) de Software"
    assert clean_role("Cargo: Desarrollador de Sistemas", "backend", "es") == "Desarrollador de Sistemas"


def test_clean_role_strips_client_prefix_and_country():
    role = clean_role("para un cliente un/a QA Automation Engineer de Argentina", "qa", "es")

    assert role == "QA Automation Engineer"


def test_clean_role_strips_trailing_emojis():
    assert clean_role("Desarrollador de Aplicaciones y Sistemas 🌐 📲", "backend", "es") == (
        "Desarrollador de Aplicaciones y Sistemas")


def test_clean_role_cuts_at_hashtags():
    assert clean_role("Java Developer #Java #SpringBoot #Hiring", "backend", "en") == "Java Developer"


def test_clean_role_removes_links():
    assert clean_role("Full-Stack Developer (TypeScript+React) https://lnkd.in/eqTDPhQm", "backend", "en") == (
        "Full-Stack Developer (TypeScript+React)")


def test_clean_role_strips_modality_suffix():
    assert clean_role("Desarrollador Java Ssr/Sr - 100% remoto", "backend", "es") == "Desarrollador Java"
