
import pytest

from parser.normalize import (
    Vacancy,
    is_inbox_candidate,
    normalize_raw,
    vacancy_labels,
    work_authorization_blockers,
)


@pytest.mark.parametrize('description,location,mode,eligible', [
    ('This role is not remote.', 'Ukraine', 'onsite', False),
    ('Remote work is not available.', 'Ukraine', 'onsite', False),
    ('Hybrid role with remote days.', 'Lviv', 'hybrid', False),
    ('On-site work with remote collaboration.', 'Lviv', 'onsite', False),
    ('This role is not remote.', 'Kyiv', 'onsite', True),
    ('Fully remote; office visits are optional.', 'Ukraine', 'remote', True),
])
def test_normalized_work_mode_respects_office_constraints(description, location, mode, eligible):
    vacancy = normalize_raw(dict(company='Acme', title='Senior iOS Engineer',
                                 url='https://example.com/job', location=location,
                                 description=description, remote='unknown'))
    assert vacancy.remote == mode
    # Work mode labels the vacancy; it no longer removes it from the hand-over.
    assert is_inbox_candidate(vacancy)
    assert vacancy_labels(vacancy)["workable_from_kyiv"] is eligible


@pytest.mark.parametrize('description,blocked', [
    ('Requirements\nMust be authorized to work in the United States', True),
    ('Requirements\nUS citizenship is required', True),
    ('Requirements\nApplicants must be a US citizen', True),
    ('Requirements\nCitizens or permanent residents only', True),
    ('Requirements\nActive security clearance required', True),
    ('Requirements\nYou must have the right to work in the UK', True),
    ('Requirements\nValid work permit for Germany', True),
    ('Requirements\nWork authorization in Poland is mandatory', True),
    # Satisfiable from Kyiv, or offered by the company: not a blocker.
    ('Requirements\nYou must have the right to work in Ukraine', False),
    ('Requirements\nWe provide visa support and relocation assistance', False),
    ('Requirements\nVisa sponsorship is available for this role', False),
    ('Requirements\nWork permit assistance is provided', False),
    ('Requirements\n5 years of Swift experience, English B2', False),
    ('Requirements\nYou will work with US clients daily', False),
    ('Requirements\nSwift and SwiftUI\nNice to have\nUS citizenship', False),
])
def test_work_authorization_blockers(description, blocked):
    assert bool(work_authorization_blockers(description)) is blocked


def test_visa_requirement_labels_an_ios_role_without_dropping_it():
    vacancy = Vacancy(
        'Acme', 'Senior iOS Engineer', 'https://example.com/job/us', 'company',
        location='Remote, US', remote='remote',
        description='Requirements\nSwift and SwiftUI\nMust be authorized to work in the United States',
    )

    # The requirement is handed over as a label; the decision is made downstream.
    assert is_inbox_candidate(vacancy)
    assert vacancy_labels(vacancy)["work_authorization"] == ["local work authorization required"]
