"""Preferencia de Adriel: Córdoba presencial/híbrido/remoto; fuera de Córdoba solo 100% remoto."""

import pytest

from classifier import _build_posting, check_location, is_preferred_remote_country, work_modality
from relevance import relevance_score


@pytest.mark.parametrize("text", [
    "Modalidad presencial en Córdoba Capital.",
    "Híbrido: 3 días en oficina de Córdoba.",
    "Remoto, equipo con base en Córdoba.",
])
def test_check_location_any_modality_in_cordoba_is_accepted(text):
    assert check_location(text).accepted


@pytest.mark.parametrize("text", [
    "Modalidad híbrida, oficinas en CABA.",
    "Presencial en Buenos Aires, zona Palermo.",
    "Remoto con presencialidad 1 vez por semana en oficina de Rosario.",
    "Híbrido en Santiago de Chile.",
    "Presencial en Madrid, España.",
])
def test_check_location_hybrid_or_onsite_outside_cordoba_is_rejected(text):
    assert not check_location(text).accepted


@pytest.mark.parametrize("text", [
    "100% remoto, empresa de CABA.",
    "Full remote para empresa de Bogotá, Colombia.",
    "Remoto desde cualquier país de LATAM, cliente en España.",
    "Trabajo remoto, empresa chilena con sede en Santiago de Chile.",
    "Posición remota para empresa de México (CDMX), pago en USD. Remoto.",
])
def test_check_location_full_remote_anywhere_is_accepted(text):
    assert check_location(text).accepted


def test_check_location_remote_only_for_foreign_residents_is_rejected():
    assert not check_location("Remoto, solo para residentes en México.").accepted


def test_check_location_remote_for_residents_of_argentina_is_accepted():
    assert check_location("Remoto para residentes en Argentina o Chile.").accepted


@pytest.mark.parametrize("text", [
    "Buscamos dev Python para nuestra sede de CABA.",
    "Buscamos desarrollador full stack 🇬🇹",
    "Buscamos dev Python. Enviá tu CV a rrhh@empresa.com",
])
def test_check_location_without_modality_nor_foreign_place_is_accepted_just_in_case(text):
    assert check_location(text).accepted


@pytest.mark.parametrize("text", [
    "Empresa de Bogotá, Colombia, busca dev Python.",
    "Junior Geophysicist. Full-time | Canada",
    "QA/QC Technician (Metering). Job Location: Qatar. Send your CV at hr@edgewaterqatar.com",
    "Buscamos dev Python. Enviá tu CV a rrhh@empresa.com.mx",
])
def test_check_location_without_modality_in_another_country_is_rejected(text):
    assert not check_location(text).accepted


def test_work_modality_no_presencial_is_remote():
    assert work_modality("modalidad remota, no presencial") == "remote"


def test_is_preferred_remote_country_only_for_remote_in_listed_countries():
    assert is_preferred_remote_country("100% remoto para empresa de chile")
    assert not is_preferred_remote_country("presencial en chile")
    assert not is_preferred_remote_country("100% remoto para empresa de brasil")


def _score(body: str) -> int:
    return relevance_score(_build_posting(f"Buscamos Desarrollador Python Jr. {body} Enviar CV a a@b.com", ("a@b.com",)))


def test_relevance_prefers_cordoba_onsite_and_preferred_remote_countries():
    plain_remote = _score("100% remoto.")
    assert _score("Híbrido en Córdoba.") > plain_remote
    assert _score("100% remoto, empresa de Colombia.") > plain_remote


def test_searches_for_cycle_covers_argentina_remote_cordoba_and_one_preferred_country():
    # Arrange
    from jobs import FOREIGN_SCOPES, LOCAL_SCOPES, searches_for_cycle

    # Act
    first = searches_for_cycle(["python", "qa", "backend"], 0)
    second = searches_for_cycle(["python", "qa", "backend"], 1)

    # Assert
    assert [scope for _, scope in first[:2]] == list(LOCAL_SCOPES)
    assert first[-1][1] == FOREIGN_SCOPES[0] and second[-1][1] == FOREIGN_SCOPES[1]
    assert len(first) == 5


def test_search_params_remote_scope_filters_remote_and_cordoba_does_not():
    from jobs import LOCAL_SCOPES, search_params

    cordoba, remote = (search_params("python", scope, 0) for scope in LOCAL_SCOPES)

    assert remote["f_WT"] == "2" and "location" not in remote
    assert "f_WT" not in cordoba and cordoba["location"] == "Córdoba, Argentina"
    assert remote["f_AL"] == "true" and "f_AL" not in cordoba and cordoba["f_TPR"] == "r604800"


def test_lab_testing_role_is_not_a_qa_role():
    from classifier import is_dev_role

    text = "Incorpora Analista SSR de Microbiología. Testing de muestras en laboratorio."
    assert not is_dev_role(text, "Analista SSR de Microbiología")


def test_relevance_goes_from_cordoba_outwards():
    cordoba = _score("Remoto, equipo en Córdoba.")
    argentina = _score("Remoto, empresa de Buenos Aires.")
    preferred = _score("100% remoto, empresa de Chile.")
    elsewhere = _score("100% remoto, empresa de Alemania.")
    assert cordoba > argentina > preferred > elsewhere


def test_relevance_prefers_entry_levels_over_unstated_and_engineer_titles():
    from classifier import _build_posting

    def score(role: str) -> int:
        return relevance_score(_build_posting(f"Buscamos {role}. 100% remoto. Enviar CV a a@b.com", ("a@b.com",)))

    assert score("Desarrollador Python Trainee") > score("Desarrollador Python Semi Senior") > score("Desarrollador Python")
    assert score("Desarrollador Python") > score("Software Engineer Python")
