from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from collector.telegram_channels import (
    _fetch_channel_jobs,
    _source_ok,
    extract_apply_url,
    extract_company,
    extract_title,
    is_candidate_post,
    job_from_message,
    looks_like_vacancy,
    should_keep_message,
)
from storage.source_health import classify_degraded
from parser.normalize import is_ios_job


VACANCY_IOS = """
#ios #swift #вакансія
Senior iOS Engineer
SmartTek Solutions шукає Senior iOS Engineer
Swift, UIKit, 5+ years
За деталями пишіть - @recruiter
""".strip()

CANDIDATE_IOS = """
#ios #candidates
Senior iOS Developer looking for new opportunities
Location: Kyiv
English: B2
CV: https://drive.google.com/file/d/xyz
""".strip()

BACKEND_VACANCY = """
#python #вакансія
Senior Backend Engineer
Python, TypeScript
""".strip()

STUDIOS_SEO = """
⚓️Admiral Studios шукає SEO Specialist
#вакансія #seo
""".strip()

QA_CRYPTO = """
🚀 We’re Hiring: Manual QA Engineer (Crypto Casino | AI-Native Team)
#вакансія #qa
""".strip()

GREETING = """
Всім хай 🙋🏻‍♀️
""".strip()

PARTNERSHIP = """
We propose partnership on the development of White-Label, Outsourcing & Outstaffing projects.
""".strip()

REMOTEJOBSS_IOS = """
💼 JOB OPPORTUNITY
🚀 Senior iOS Engineer
🏢 Company: Acme Labs
━━━━━━━━━━━━━━━
✅ Tags
#mobile#engineering#remote
━━━━━━━━━━━━━━━
Ready to Apply?
👇 Apply using the button below
""".strip()

ITFREELANCERS_IOS = """
‼️‼️🆕 We're looking for a Senior Swift / iOS Engineer for a remote product team.
Tech: Swift, UIKit, SwiftUI
#ITJobs#iOS#Swift
Send your resume to jobs@example.com
‼️‼️
""".strip()

ITFREELANCERS_QA = """
‼️‼️🆕 QA Engineer / Software Tester (Freelance / Remote)
We're looking for a detail-oriented QA Engineer.
#ITJobs#QA
‼️‼️
""".strip()

MOBILE_JOBS_IOS = """
#вакансия
Senior iOS Developer
Город: Москва
Формат работы: удаленка
Занятость: полная
Зарплатная вилка: от 300000 до 400000
Описание вакансии: Swift, UIKit, SwiftUI, 5+ years
Название компании: Acme Mobile
Контакты: @hr_acme
""".strip()

MOBILE_JOBS_ANDROID = """
#вакансия
Senior Android Developer
Город: Санкт-Петербург
Формат работы: офис
Занятость: полная
Зарплатная вилка: от 250000 до 350000
Описание вакансии: Kotlin, Jetpack Compose
Название компании: Droid Corp
Контакты: hr@droid.example
""".strip()

MOBILE_JOBS_RESUME = """
#ищу
iOS Developer
Формат работы: удаленка
Занятость: полная
Ожидания по зарплате: от 250000
Обо мне: Swift, SwiftUI, https://github.com/example
""".strip()

MOBILE_JOBS_RESUME_HASH = """
#резюме
Senior iOS Developer
Формат работы: удаленка
Swift, UIKit, SwiftUI
""".strip()

TOPIC_ONLY_IOS = """
#ios #swift
Senior iOS Developer
Kyiv, remote
""".strip()

ISHCHUT_VACANCY = """
#ищут Senior iOS Developer
#вакансия
Swift, UIKit, 4+ years
Название компании: Beta Apps
""".strip()

COMPOUND_SEEKING = """
#ищуработу
Senior iOS Developer
Swift, UIKit
#вакансия
""".strip()

COMPOUND_SEEKING_UNDERSCORE = """
#ищу_работу
iOS Developer
Swift, SwiftUI
""".strip()

CONCAT_RESUME = """
#mobile#resume
Senior iOS Developer
Swift, UIKit
""".strip()

VACANCY_WITH_SALARY_EXPECTATION = """
#вакансия
Senior iOS Developer
Ожидания по зарплате: от 300000 до 400000
Swift, UIKit
Название компании: Acme Mobile
""".strip()

HIRIFY_IOS = """
Senior IOS Developer (AI) в Prequel

Удаленно (global) | Фулл-тайм | senior | Мобильная разработка

Навыки: ai, ios, swift, swiftui, uikit, code review, storekit, mcp

По подписке: (AI) Senior iOS Engineer Remote
""".strip()


def test_is_ios_job_rejects_studios_substring() -> None:
    assert not is_ios_job(STUDIOS_SEO)
    assert not is_ios_job("Mind Studios Designer")


def test_extract_title_skips_hashtag_only_line() -> None:
    assert extract_title(VACANCY_IOS) == "Senior iOS Engineer"


def test_extract_company_from_hiring_line() -> None:
    assert extract_company(VACANCY_IOS) == "SmartTek Solutions"


def test_is_candidate_post_detects_seeking() -> None:
    assert is_candidate_post(CANDIDATE_IOS) is True
    assert is_candidate_post(VACANCY_IOS) is False
    assert is_candidate_post(MOBILE_JOBS_RESUME) is True
    assert is_candidate_post(MOBILE_JOBS_RESUME_HASH) is True
    assert is_candidate_post(ISHCHUT_VACANCY) is False
    assert is_candidate_post(COMPOUND_SEEKING) is True
    assert is_candidate_post(COMPOUND_SEEKING_UNDERSCORE) is True
    assert is_candidate_post(CONCAT_RESUME) is True
    assert is_candidate_post(VACANCY_WITH_SALARY_EXPECTATION) is False


def test_looks_like_vacancy() -> None:
    assert looks_like_vacancy(VACANCY_IOS) is True
    assert looks_like_vacancy(GREETING) is False
    assert looks_like_vacancy(TOPIC_ONLY_IOS) is False
    assert looks_like_vacancy(ITFREELANCERS_IOS) is True


def test_should_keep_only_ios_hiring_posts() -> None:
    assert should_keep_message(VACANCY_IOS) is True
    assert should_keep_message(CANDIDATE_IOS) is False
    assert should_keep_message(BACKEND_VACANCY) is False
    assert should_keep_message(STUDIOS_SEO) is False
    assert should_keep_message(QA_CRYPTO) is False
    assert should_keep_message(GREETING) is False
    assert should_keep_message(PARTNERSHIP) is False
    assert should_keep_message(REMOTEJOBSS_IOS) is True
    assert should_keep_message(ITFREELANCERS_IOS) is True
    assert should_keep_message(ITFREELANCERS_QA) is False
    assert should_keep_message(MOBILE_JOBS_IOS) is True
    assert should_keep_message(MOBILE_JOBS_ANDROID) is False
    assert should_keep_message(MOBILE_JOBS_RESUME) is False
    assert should_keep_message(MOBILE_JOBS_RESUME_HASH) is False
    assert should_keep_message(TOPIC_ONLY_IOS) is False
    assert should_keep_message(ISHCHUT_VACANCY) is True
    assert should_keep_message(COMPOUND_SEEKING) is False
    assert should_keep_message(COMPOUND_SEEKING_UNDERSCORE) is False
    assert should_keep_message(CONCAT_RESUME) is False
    assert should_keep_message(VACANCY_WITH_SALARY_EXPECTATION) is True


def test_remotejobss_parses_role_and_company() -> None:
    job = job_from_message("remotejobss", 99, REMOTEJOBSS_IOS)
    assert job is not None
    assert job["title"] == "Senior iOS Engineer"
    assert job["company"] == "Acme Labs"
    assert "Ready to Apply" in job["description"]


def test_itfreelancers_keeps_english_ios_hiring() -> None:
    job = job_from_message("itfreelancers", 50, ITFREELANCERS_IOS)
    assert job is not None
    assert "Swift" in job["title"] or "iOS" in job["title"]
    assert job_from_message("itfreelancers", 51, ITFREELANCERS_QA) is None


def test_mobile_jobs_parses_ios_vacancy_and_drops_resume() -> None:
    job = job_from_message("mobile_jobs", 10, MOBILE_JOBS_IOS)
    assert job is not None
    assert job["title"] == "Senior iOS Developer"
    assert job["company"] == "Acme Mobile"
    assert job["url"] == "https://t.me/mobile_jobs/10"
    assert job_from_message("mobile_jobs", 11, MOBILE_JOBS_ANDROID) is None
    assert job_from_message("mobile_jobs", 12, MOBILE_JOBS_RESUME) is None


def test_job_from_message_builds_telegram_url_and_date() -> None:
    published = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)
    job = job_from_message("itrecruit_ua", 12345, VACANCY_IOS, published_at=published)
    assert job is not None
    assert job["title"] == "Senior iOS Engineer"
    assert job["company"] == "SmartTek Solutions"
    assert job["url"] == "https://t.me/itrecruit_ua/12345"
    assert job["source"] == "telegram"
    assert job["source_job_id"] == "itrecruit_ua:12345"
    assert job["published_at"] == published.isoformat()
    assert "UIKit" in job["description"]


def test_extract_apply_url_skips_telegram_hosts() -> None:
    assert extract_apply_url("Apply: https://djinni.co/jobs/123-ios/") == "https://djinni.co/jobs/123-ios/"
    assert extract_apply_url("See https://t.me/itrecruit_ua/99") is None
    assert (
        extract_apply_url("https://t.me/foo/1 and https://jobs.lever.co/acme/abc")
        == "https://jobs.lever.co/acme/abc"
    )


def test_job_from_message_prefers_apply_url() -> None:
    text = """
#ios #вакансія
Senior iOS Engineer
Acme Labs шукає Senior iOS Engineer
Apply: https://djinni.co/jobs/999-senior-ios/
""".strip()
    job = job_from_message("itrecruit_ua", 77, text)
    assert job is not None
    assert job["url"] == "https://djinni.co/jobs/999-senior-ios/"
    assert job["source_job_id"] == "itrecruit_ua:77"


def test_job_from_message_drops_junk() -> None:
    assert job_from_message("itrecruit_ua", 1, CANDIDATE_IOS) is None
    assert job_from_message("itrecruit_ua", 2, STUDIOS_SEO) is None
    assert job_from_message("itrecruit_ua", 3, QA_CRYPTO) is None
    assert job_from_message("itrecruit_ua", 4, GREETING) is None


def test_hirify_message_uses_job_url_and_subscription_format() -> None:
    job = job_from_message(
        "hirifyme_bot",
        501,
        HIRIFY_IOS,
        apply_urls=["https://hirify.me/jobs/123456-senior-ios-developer-ai"],
    )
    assert job is not None
    assert job["title"] == "Senior IOS Developer (AI)"
    assert job["company"] == "Prequel"
    assert job["url"] == "https://hirify.me/jobs/123456-senior-ios-developer-ai"
    assert job["source"] == "hirify.me"
    assert job["source_job_id"] == "hirify:123456"


class _FakeMessage:
    def __init__(self, message_id: int, text: str) -> None:
        self.id = message_id
        self.message = text
        self.raw_text = text
        self.date = datetime(2026, 8, 27, 9, 11, tzinfo=timezone.utc)
        self.entities = []
        self.buttons = []


class _FakeClient:
    def __init__(self, messages: list[_FakeMessage]) -> None:
        self.messages = messages
        self.calls: list[dict[str, int]] = []

    async def get_messages(self, channel: str, **kwargs: int) -> list[_FakeMessage]:
        self.calls.append(kwargs)
        return self.messages

    async def iter_messages(self, channel: str, **kwargs: int):
        self.calls.append(kwargs)
        for message in self.messages:
            yield message


def test_hirify_first_collection_only_initializes_checkpoint() -> None:
    client = _FakeClient([_FakeMessage(501, HIRIFY_IOS)])
    jobs, checkpoint, scanned = asyncio.run(_fetch_channel_jobs(client, "hirifyme_bot"))
    assert jobs == []
    assert checkpoint == 501
    assert scanned == 1
    assert client.calls == [{"limit": 1}]


def test_hirify_reads_only_messages_after_checkpoint() -> None:
    message = _FakeMessage(502, HIRIFY_IOS)
    message.entities = [type("Entity", (), {"url": "https://hirify.me/jobs/123456-role"})()]
    client = _FakeClient([message])
    jobs, checkpoint, _ = asyncio.run(
        _fetch_channel_jobs(client, "hirifyme_bot", after_message_id=501)
    )
    assert client.calls == [{"min_id": 501, "reverse": True}]
    assert len(jobs) == 1
    assert checkpoint == 502


def test_hirify_does_not_advance_past_vacancy_without_job_url() -> None:
    client = _FakeClient([_FakeMessage(502, HIRIFY_IOS)])

    with pytest.raises(ValueError, match="no parseable hirify.me job URL"):
        asyncio.run(
            _fetch_channel_jobs(client, "hirifyme_bot", after_message_id=501)
        )


def test_hirify_reads_every_message_after_checkpoint_without_batch_loss() -> None:
    messages = []
    for message_id in range(502, 603):
        message = _FakeMessage(message_id, HIRIFY_IOS)
        message.entities = [
            type(
                "Entity",
                (),
                {"url": f"https://hirify.me/jobs/{message_id}-ios-role"},
            )()
        ]
        messages.append(message)
    client = _FakeClient(messages)

    jobs, checkpoint, scanned = asyncio.run(
        _fetch_channel_jobs(client, "hirifyme_bot", after_message_id=501)
    )

    assert len(jobs) == 101
    assert checkpoint == 602
    assert scanned == 101


def test_channel_reports_scanned_messages_so_health_stays_healthy() -> None:
    client = _FakeClient([_FakeMessage(900, "Hello"), _FakeMessage(901, "World")])
    jobs, _, scanned = asyncio.run(_fetch_channel_jobs(client, "itrecruit_ua"))
    result = _source_ok("itrecruit_ua", jobs, 0.0, scanned=scanned, checkpoint=901)
    baseline = {"telegram:itrecruit_ua": {"best_scanned": 0, "empty_runs": 77}}

    assert jobs == []
    assert result.items_scanned == 2
    assert classify_degraded([result], baseline) == []
    assert result.status == "healthy"


def test_hirify_without_new_messages_is_healthy() -> None:
    client = _FakeClient([])
    jobs, checkpoint, scanned = asyncio.run(
        _fetch_channel_jobs(client, "hirifyme_bot", after_message_id=501)
    )
    result = _source_ok("hirifyme_bot", jobs, 0.0, scanned=scanned, checkpoint=checkpoint)
    baseline = {"telegram:hirifyme_bot": {"best_scanned": 3, "empty_runs": 5}}

    assert checkpoint == 501
    assert classify_degraded([result], baseline) == []
