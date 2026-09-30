from __future__ import annotations

from parser.deduplicate import deduplicate
from parser.normalize import normalize_title, role_key
from tests.conftest import make_vacancy


def test_normalize_title_strips_reference_suffix() -> None:
    assert normalize_title("Lead iOS Engineer (#5458)") == "lead ios engineer"
    assert normalize_title("Senior iOS Developer") == "senior ios developer"


def test_role_key_ignores_reference_suffix() -> None:
    assert role_key("N-iX", "Lead iOS Engineer (#5458)") == role_key("N-iX", "Lead iOS Engineer")


def test_deduplicate_removes_same_identity_vacancies() -> None:
    first = make_vacancy(url="https://example.com/job/1")
    duplicate = make_vacancy(url="https://example.com/job/1/?utm_source=telegram&utm_medium=bot")
    other = make_vacancy(title="Staff iOS Engineer", url="https://example.com/job/3")

    unique, removed = deduplicate([first, duplicate, other])

    assert removed == 1
    assert len(unique) == 2
    assert unique[0] is first
    assert unique[1] is other


def test_deduplicate_keeps_russian_company_mark_from_the_dropped_copy() -> None:
    api_copy = make_vacancy(source="hirify.me", source_job_id="hirify:7", description=None, russian_company=True)
    telegram_copy = make_vacancy(source="hirify.me", source_job_id="hirify:7", url="https://example.com/job/1?x=1")

    unique, removed = deduplicate([api_copy, telegram_copy])

    assert removed == 1
    assert unique[0].russian_company


def test_deduplicate_keeps_same_role_with_distinct_identities() -> None:
    swift = make_vacancy(
        company="N-iX",
        title="Lead iOS Engineer (#5458)",
        url="https://careers.n-ix.com/jobs/4494044101-ios-leader/",
        source="company",
        location="Ukraine",
        description="SwiftUI, UIKit, and leadership experience required",
    )
    greenhouse = make_vacancy(
        company="N-iX",
        title="Lead iOS Engineer",
        url="https://careers.n-ix.com/jobs/4912838101?gh_jid=4912838101",
        source="company",
        source_job_id="4912838101",
        description="Greenhouse description",
    )

    unique, removed = deduplicate([swift, greenhouse])

    assert removed == 1
    assert len(unique) == 1
    assert set(unique[0].advertised_locations) == {"Ukraine", "Kyiv"}


def test_deduplicate_keeps_unique_vacancies() -> None:
    vacancies = [
        make_vacancy(title="Senior iOS Developer", url="https://example.com/job/1"),
        make_vacancy(title="Lead iOS Engineer", url="https://example.com/job/2"),
        make_vacancy(title="Principal iOS Engineer", url="https://example.com/job/3"),
    ]

    unique, removed = deduplicate(vacancies)

    assert removed == 0
    assert unique == vacancies


def test_deduplicate_handles_empty_list() -> None:
    unique, removed = deduplicate([])

    assert unique == []
    assert removed == 0


def test_multi_geo_keeps_eligible_url_and_its_requirements() -> None:
    foreign = make_vacancy(url="https://example.com/mexico", location="Mexico", remote="onsite", description="Long description " * 100)
    local = make_vacancy(url="https://example.com/kyiv", location="Kyiv", remote="hybrid")
    unique, removed = deduplicate([foreign, local])
    assert removed == 1
    assert unique[0].url == local.url
    assert unique[0].location == "Kyiv"
    assert unique[0].remote == "hybrid"
    assert unique[0].description == local.description
    assert unique[0].advertised_locations == ("Kyiv", "Mexico")


def test_role_selection_is_independent_of_collection_order() -> None:
    a = make_vacancy(url="https://example.com/a")
    b = make_vacancy(url="https://example.com/b")
    assert deduplicate([a, b])[0][0].url == deduplicate([b, a])[0][0].url


def test_same_title_without_known_company_is_not_one_role() -> None:
    first = make_vacancy(company="", url="https://t.me/mobile_jobs/1", source="telegram")
    second = make_vacancy(company="", url="https://t.me/itrecruit_ua/2", source="telegram")

    unique, removed = deduplicate([first, second])

    assert removed == 0
    assert {vacancy.url for vacancy in unique} == {first.url, second.url}
