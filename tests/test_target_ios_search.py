import pytest

from parser.normalize import is_inbox_candidate, vacancy_labels
from tests.conftest import make_vacancy


IOS_TARGET_TITLES = (
    "Senior iOS Engineer",
    "Senior iOS Developer",
    "Senior Software Engineer — iOS",
    "Senior iOS SDK Engineer",
)


@pytest.mark.parametrize("title", IOS_TARGET_TITLES + (
    "Sr. iOS Developer", "iOS Senior Software Engineer", "Senior Swift Engineer",
))
def test_senior_ios_title_variants_are_admitted(title):
    assert is_inbox_candidate(make_vacancy(title=title))


@pytest.mark.parametrize("title", (
    "Lead iOS Engineer", "iOS Tech Lead", "Staff iOS Engineer",
    "Principal iOS Engineer", "Middle iOS Developer", "iOS Developer",
    "iOS Engineer", "Swift Developer",
))
def test_non_junior_ios_levels_are_admitted(title):
    assert is_inbox_candidate(make_vacancy(title=title))


@pytest.mark.parametrize("title", (
    "Junior iOS Engineer", "Jr. iOS Developer", "Trainee iOS Developer",
    "iOS Developer Intern", "iOS Developer (Internship)",
))
def test_junior_ios_titles_are_collected_with_a_junior_label(title):
    vacancy = make_vacancy(title=title)
    assert is_inbox_candidate(vacancy)
    assert vacancy_labels(vacancy)["junior"] is True


@pytest.mark.parametrize("title", (
    "Senior DevOps Engineer", "Senior DevOps & AI Automation Engineer",
    "Senior SRE Engineer", "AI Product Engineer", "Senior Backend Engineer",
    "Senior iOS QA Engineer", "Senior React Native Engineer",
))
def test_other_roles_are_not_admitted_even_with_ai_evidence(title):
    assert not is_inbox_candidate(make_vacancy(
        title=title,
        description="Build AI products using LLM APIs, agent orchestration and RAG services.",
    ))


