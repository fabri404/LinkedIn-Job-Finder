from pathlib import Path
from urllib.parse import parse_qs, urlparse

from composer import Application
from mailer import compose_url


def test_compose_url_round_trips_subject_and_body_with_accents():
    # Arrange
    body = "Hola,\n\nMe postulo a la búsqueda de Dev Python · SaaS.\n• Viñeta"
    app = Application("rrhh@acme.com", "Postulación: Dev & QA, Adriel López", body,
                      Path("/tmp/cv.pdf"), "Dev")

    # Act
    params = parse_qs(urlparse(compose_url(app)).query)

    # Assert
    assert params["view"] == ["cm"]
    assert params["to"] == ["rrhh@acme.com"]
    assert params["su"] == ["Postulación: Dev & QA, Adriel López"]
    assert params["body"] == [body]
