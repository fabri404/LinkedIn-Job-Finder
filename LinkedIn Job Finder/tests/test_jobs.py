from classifier import evaluate_job, is_profile_title
from jobs import html_to_text, parse_cards, parse_description, queries_for_cycle

CARD_HTML = """
<ul><li>
  <div class="base-card job-search-card" data-entity-urn="urn:li:jobPosting:4478860511">
    <h3 class="base-search-card__title">
        Desarrollador Backend Python
    </h3>
    <h4 class="base-search-card__subtitle"><a href="#"> Acme &amp; Co </a></h4>
    <span class="job-search-card__location"> Córdoba, Argentina </span>
  </div>
</li></ul>
"""
DETAIL_HTML = """
<div class="show-more-less-html__markup relative">
  <p>Buscamos dev <strong>Python</strong>.</p><ul><li>2 años de experiencia</li><li>Remoto</li></ul>
</div>
"""


def test_parse_cards_with_guest_list_html_returns_card_fields():
    # Act
    cards = parse_cards(CARD_HTML)

    # Assert
    assert len(cards) == 1
    assert cards[0].job_id == "4478860511"
    assert cards[0].title == "Desarrollador Backend Python"
    assert cards[0].company == "Acme & Co"
    assert cards[0].location == "Córdoba, Argentina"
    assert cards[0].url == "https://www.linkedin.com/jobs/view/4478860511/"


def test_parse_description_with_lists_keeps_one_line_per_item():
    # Act
    text = parse_description(DETAIL_HTML)

    # Assert
    assert text.splitlines() == ["Buscamos dev Python .", "2 años de experiencia", "Remoto"]


def test_html_to_text_with_entities_unescapes_them():
    assert html_to_text("<p>QA &amp; Testing</p>") == "QA & Testing"


def test_is_profile_title_with_senior_title_returns_false():
    assert not is_profile_title("Senior Python Developer")


def test_is_profile_title_with_non_dev_title_returns_false():
    assert not is_profile_title("Data Scientist")


def test_evaluate_job_without_email_returns_posting_for_manual_apply():
    # Arrange
    text = "Desarrollador Python\nAcme\nArgentina\nBuscamos dev con 2 años. Remoto."

    # Act
    verdict, posting = evaluate_job("Desarrollador Python", text)

    # Assert
    assert verdict.accepted
    assert posting is not None
    assert posting.emails == ()
    assert posting.role_title == "Desarrollador Python"


def test_evaluate_job_with_email_in_description_returns_email():
    # Arrange
    text = "QA Tester\nAcme\nArgentina\nEnviá tu CV a talento@acme.com.ar. Remoto."

    # Act
    _, posting = evaluate_job("QA Tester", text)

    # Assert
    assert posting is not None
    assert posting.emails == ("talento@acme.com.ar",)
    assert posting.track == "qa"


def test_evaluate_job_asking_five_years_is_rejected():
    # Act
    verdict, posting = evaluate_job("Backend Developer", "Backend Developer\n5+ years of experience")

    # Assert
    assert not verdict.accepted
    assert posting is None


def test_is_profile_title_with_staff_title_returns_false():
    assert not is_profile_title("Staff Software Engineer - Argentina")


def test_queries_for_cycle_rotates_through_all_queries():
    # Arrange
    queries = ["a", "b", "c", "d", "e"]

    # Act
    windows = [queries_for_cycle(queries, cycle) for cycle in range(2)]

    # Assert
    assert windows == [["a", "b", "c"], ["d", "e", "a"]]


def test_is_profile_title_with_level_three_returns_false():
    assert not is_profile_title("Software Engineer III")
