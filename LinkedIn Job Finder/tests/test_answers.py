from answers import CITY, HEADLINE, answer_for, pick_option


def test_answer_for_headline_returns_profile_headline():
    assert answer_for("Headline") == HEADLINE


def test_answer_for_city_typeahead_returns_cordoba():
    assert answer_for("Location (city)*") == CITY


def test_answer_for_years_with_core_stack_returns_one():
    assert answer_for("¿Cuántos años de experiencia tienes con Python?") == "1"


def test_answer_for_years_with_unknown_tech_returns_none():
    assert answer_for("How many years of experience do you have with Salesforce?") is None


def test_answer_for_birth_date_returns_none():
    assert answer_for("Birth date *") is None


def test_answer_for_salary_without_currency_returns_usd_900():
    assert answer_for("¿Cuál es tu pretensión salarial?") == "900"


def test_answer_for_sponsorship_returns_no():
    assert answer_for("Will you now or in the future require visa sponsorship?") == ("no",)


def test_pick_option_prefers_exact_match():
    assert pick_option(["Seleccionar", "Sí", "No"], ("sí", "yes")) == 1


def test_pick_option_falls_back_to_partial_match():
    assert pick_option(["Básico", "Intermedio", "Avanzado (C1)"], ("c1", "advanced")) == 2


def test_answer_for_software_development_years_returns_one():
    assert answer_for("How many years of professional software development experience do you have?") == "1"


def test_answer_for_usd_income_returns_900():
    assert answer_for("Please state your expected monthly net income in USD.") == "900"


def test_answer_for_salary_in_pesos_returns_none():
    assert answer_for("¿Cuál es tu pretensión salarial en pesos argentinos?") is None


def test_answer_for_sql_experience_question_returns_yes():
    assert answer_for("Do you have experience with relational or non-relational databases and SQL?*") == ("sí", "si", "yes")


def test_answer_for_aws_question_with_api_gateway_returns_none():
    assert answer_for("Do you have experience working with AWS services such as EC2, S3, Lambda, or API Gateway?*") is None


def test_answer_for_java_professional_experience_returns_none():
    assert answer_for("Do you have professional experience with Java?*") is None


def test_answer_for_background_check_returns_yes():
    assert answer_for("Are you willing to undergo a background check?*") == ("sí", "si", "yes")


def test_answer_for_reviewed_conditions_with_compensation_returns_yes():
    label = ("Have you reviewed the job requirements, work arrangement (shift schedule, contract type, and "
             "compensation), and job description, and are these aligned with your expectations?*")

    assert answer_for(label) == ("sí", "si", "yes")
