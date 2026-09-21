from __future__ import annotations

from storage.seen import mark_seen
from parser.normalize import role_family_key
from scripts import run_pipeline
from tests.conftest import make_vacancy




def test_role_family_ignores_seniority_developer_engineer_and_team_qualifier() -> None:
    assert role_family_key("Nimbusly", "Senior IOS Developer (AI)") == role_family_key("Nimbusly", "iOS Developer")
    assert role_family_key("Quartzo", "Senior Staff iOS Engineer (Wallet)") == role_family_key(
        "Quartzo", "Senior Staff iOS Engineer (Lending)"
    )


def test_role_family_keeps_distinct_roles_apart() -> None:
    assert role_family_key("Nimbusly", "iOS Developer") != role_family_key("Other Co", "iOS Developer")
    assert role_family_key("Nimbusly", "iOS Developer") != role_family_key("Nimbusly", "iOS Team Lead")
    assert role_family_key("Nimbusly", "Lead iOS Developer") != role_family_key("Nimbusly", "Senior iOS Developer")
    assert role_family_key("Nimbusly", "Lead iOS Developer (Payments)") == role_family_key("Nimbusly", "Lead iOS Engineer")
    # Without iOS in the base title the qualifier names the role and must be kept.
    assert role_family_key("Nimbusly", "Software Engineer (iOS)") != role_family_key(
        "Nimbusly", "Software Engineer (AI)"
    )


def test_hirify_mirror_of_seen_ats_posting_is_not_new() -> None:
    seen: dict = {}
    mark_seen(seen, make_vacancy(
        company="Nimbusly", title="iOS Developer", url="https://nimbusly.example-ats.io/vacancy/ios-developer-2",
    ))
    mirror = make_vacancy(
        company="Nimbusly", title="Senior IOS Developer (AI)", url="https://hirify.me/jobs/100001-senior-ios-developer-ai",
    )
    assert run_pipeline.select_fresh([mirror], seen, seen_gate=True) == []


def test_repost_under_new_hirify_id_is_not_new() -> None:
    seen: dict = {}
    mark_seen(seen, make_vacancy(
        company="Quartzo", title="Senior Staff iOS Engineer (Lending)", url="https://hirify.me/jobs/200001-senior-staff-ios-engineer-lending",
    ))
    repost = make_vacancy(
        company="Quartzo", title="Senior Staff iOS Engineer (Wallet)", url="https://hirify.me/jobs/200002-senior-staff-ios-engineer-wallet",
    )
    other_company = make_vacancy(company="Other Co", url="https://hirify.me/jobs/200003-senior-ios-developer")
    assert run_pipeline.select_fresh([repost, other_company], seen, seen_gate=True) == [other_company]


def test_unknown_company_post_is_fresh_despite_a_seen_title() -> None:
    seen = {"https://t.me/mobile_jobs/1": {"company": "", "title": "Senior iOS Developer"}}
    first = make_vacancy(company="", url="https://t.me/mobile_jobs/2", source="telegram")
    second = make_vacancy(company="", url="https://t.me/itrecruit_ua/3", source="telegram")

    assert run_pipeline.select_fresh([first, second], seen, seen_gate=True) == [first, second]
