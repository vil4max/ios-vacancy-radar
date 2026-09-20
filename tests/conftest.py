from __future__ import annotations

from parser.normalize import Vacancy


def make_vacancy(**overrides) -> Vacancy:
    defaults = {
        "company": "Acme",
        "title": "Senior iOS Developer",
        "url": "https://example.com/job/1",
        "source": "test",
        "location": "Kyiv",
        "remote": "remote",
        "description": "SwiftUI and UIKit experience required",
    }
    defaults.update(overrides)
    return Vacancy(**defaults)
