from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any



_TRACKING_QUERY_KEYS = {
    "ref",
    "source",
    "gh_src",
    "sent",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "utm_reader",
}

_HOST_ALIASES = {
    "people.andersenlab.com": "people-andersenlab.com",
}


def canonicalize_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""

    split = urlsplit(raw)
    scheme = (split.scheme or "https").lower()
    host = (split.hostname or "").lower()
    host = _HOST_ALIASES.get(host, host)
    netloc = host
    if split.port and ((scheme == "http" and split.port != 80) or (scheme == "https" and split.port != 443)):
        netloc = f"{host}:{split.port}"

    path = split.path or "/"
    if path != "/":
        path = path.rstrip("/")

    query_items: list[tuple[str, str]] = []
    for key, value in parse_qsl(split.query, keep_blank_values=True):
        lowered_key = key.lower()
        if lowered_key.startswith("utm_"):
            continue
        if lowered_key in _TRACKING_QUERY_KEYS:
            continue
        query_items.append((key, value))

    query_items.sort(key=lambda kv: (kv[0], kv[1]))
    query = urlencode(query_items, doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def compute_identity_key(
    *,
    company: str,
    canonical_url: str,
    source: str,
    source_job_id: str | None,
) -> tuple[str, str]:
    normalized_company = canonical_company(company)
    normalized_source = normalize_token(source)
    if source_job_id:
        raw = f"provider|{normalized_company}|{normalized_source}|{source_job_id.strip()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest(), "source_job_id"
    if canonical_url:
        raw = f"url|{normalized_company}|{canonical_url}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest(), "canonical_url"
    raw = f"fallback|{normalized_company}|{normalize_token(canonical_url)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest(), "fallback"


@dataclass
class Vacancy:
    company: str
    title: str
    url: str
    source: str
    location: str | None = None
    remote: str | None = None
    published_at: datetime | None = None
    description: str | None = None
    canonical_url: str = ""
    source_job_id: str | None = None
    identity_key: str = ""
    identity_strategy: str = ""
    advertised_locations: tuple[str, ...] = ()
    russian_company: bool = False
    hash: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self.canonical_url = self.canonical_url or canonicalize_url(self.url)
        if not self.identity_key:
            self.identity_key, self.identity_strategy = compute_identity_key(
                company=self.company,
                canonical_url=self.canonical_url,
                source=self.source,
                source_job_id=self.source_job_id,
            )
        self.hash = self.identity_key or compute_hash(self.company, self.title, self.location)


def normalize_title(title: str) -> str:
    without_ref = re.sub(r"\s*\(#\d+\)\s*$", "", title.strip())
    return re.sub(r"\s+", " ", without_ref).lower()


def role_key(company: str, title: str) -> tuple[str, str]:
    return canonical_company(company), normalize_title(title)


_TITLE_QUALIFIER = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_TITLE_SENIORITY = re.compile(r"(?<![a-z0-9])(?:senior|sr\.?|staff|principal|middle|mid)(?![a-z0-9])")


def role_family_key(company: str, title: str) -> tuple[str, str]:
    """Matches re-posts of one iOS role at a company: seniority, Developer vs
    Engineer, and a team qualifier ("(AI)", "(Ethena Pay)") are ignored.
    Lead stays in the key: a lead opening is a distinct step up that must be
    reported even after applying to a senior role at the same company.
    Only titles naming iOS outside the qualifier are broadened; in "Software
    Engineer (iOS)" the qualifier is the role itself and stays in the key."""
    normalized = normalize_title(title)
    base = _TITLE_QUALIFIER.sub(" ", normalized)
    if not _IOS_ANCHOR.search(base):
        return role_key(company, title)
    base = _TITLE_SENIORITY.sub(" ", base)
    base = re.sub(r"(?<![a-z0-9])developer(?![a-z0-9])", "engineer", base)
    return canonical_company(company), re.sub(r"[\s,/|–-]+", " ", base).strip()


def compute_hash(company: str, title: str, location: str | None) -> str:
    raw = "|".join(
        [
            canonical_company(company),
            normalize_title(title),
            normalize_token(location or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_token(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


_COMPANY_ALIASES = {
    "n ix": "n-ix",
    "n i x": "n-ix",
    "nix": "n-ix",
    "n-ix": "n-ix",
    "chisw": "chi software",
    "chi software": "chi software",
    "globallogic": "globallogic",
    "global logic": "globallogic",
    "softserve": "softserve",
    "soft serve": "softserve",
    "sigma": "sigma software",
    "sigma software": "sigma software",
    "onix": "onix systems",
    "onix systems": "onix systems",
    "zone 3000": "zone3000",
    "zone3000": "zone3000",
    "eleks": "eleks",
    "grid dynamics": "grid dynamics",
    "griddynamics": "grid dynamics",
}


def canonical_company(value: str) -> str:
    token = normalize_token(value)
    collapsed = token.replace("-", " ")
    return _COMPANY_ALIASES.get(token) or _COMPANY_ALIASES.get(collapsed) or token


_IOS_ANCHOR = re.compile(
    r"(?i)(?<![a-z0-9])("
    r"ios|swift|swiftui|uikit|"
    r"objective[\s\-]?c|objc|obj[\s\-]?c|"
    r"xcode|iphone|ipad|tvos|watchos|visionos|"
    r"macos|mac\s*os|os\s*x|appkit|"
    r"cocoa(?:pods|touch)?"
    r")(?![a-z0-9])"
)

_NON_IOS_ROLE_TITLE = re.compile(
    r"(?i)(?<![a-z0-9])(qa|sdet|tpm|"
    r"quality\s+assurance|"
    r"test(?:ing)?\s+(?:automation|engineer|developer)|"
    r"automation\s+(?:qa|engineer|tester)|"
    r"manual\s+qa|"
    r"mobile\s+automation"
    r")(?![a-z0-9])"
)

_BODY_ROLE = re.compile(
    r"(?i)(?<![a-z0-9а-яіїєґ])("
    r"mobile|native|"
    r"software\s+(?:engineer|developer)|"
    r"client[\s\-]?side"
    r")(?![a-z0-9а-яіїєґ])"
)

_JUNIOR_TITLE = re.compile(
    r"(?i)(?<![a-z0-9а-яіїєґ])("
    r"junior|jr\.?|intern|internship|trainee|стажер|інтерн|джуніор|"
    r"без\s+(?:досвіду|опыта)|no\s+experience|entry[\s\-]?level"
    r")(?![a-z0-9а-яіїєґ])"
)

_SENIORISH_TITLE = re.compile(
    r"(?i)(?<![a-z0-9а-яіїєґ])("
    r"senior|sr\.?|lead|staff|principal|head|architect"
    r")(?![a-z0-9а-яіїєґ])"
)

_APPLE_CORE = re.compile(
    r"(?i)(?<![a-z0-9])("
    r"ios|swift|swiftui|uikit|"
    r"objective[\s\-]?c|objc|obj[\s\-]?c|"
    r"appkit|cocoa(?:pods|touch)?"
    r")(?![a-z0-9])"
)

_CROSS_PLATFORM_TITLE = re.compile(
    r"(?i)(?:"
    r"\bios\s*(?:/|&|and)\s*android\b|"
    r"\bandroid\s*(?:/|&|and)\s*ios\b|"
    r"\bios\s+(?:developer|engineer)\s+with\s+android\b|"
    r"\breact\s+native\s+(?:developer|engineer)\b|"
    r"\b(?:kmm|kotlin\s+multiplatform)\s+(?:developer|engineer)\b|"
    r"\bflutter\s+(?:developer|engineer)\b"
    r")"
)


def is_ios_job(title: str, description: str | None = None) -> bool:
    title_text = title or ""
    if _NON_IOS_ROLE_TITLE.search(title_text):
        return False
    if _IOS_ANCHOR.search(title_text):
        return True
    if description and _APPLE_CORE.search(description) and _BODY_ROLE.search(title_text):
        return True
    return False


def is_target_level(title: str) -> bool:
    text = title or ""
    if _JUNIOR_TITLE.search(text) and not _SENIORISH_TITLE.search(text):
        return False
    return True


_UKRAINE = re.compile(
    r"\b(?:ukraine|ukrainian|kyiv|kiev|lviv|kharkiv|kharkov|dnipro|dnepr|"
    r"odesa|odessa|vinnytsia|vinnitsa|ivano-frankivsk|uzhhorod|chernivtsi|"
    r"cherkasy|poltava|zaporizhzhia|ternopil|rivne|lutsk|mykolaiv|"
    r"україн\w*|украин\w*|київ|киев|львів|львов|харків|харьков|дніпро|днепр|"
    r"одеса|одесса|вінниця|винница|івано-франківськ|ивано-франковск|ужгород|"
    r"чернівці|черновцы|черкаси|черкассы|полтава|запоріжжя|запорожье|"
    r"тернопіль|тернополь|рівне|ровно|луцьк|луцк|миколаїв|николаев)\b",
    re.I,
)
_KYIV = re.compile(r"\b(?:kyiv|kiev|київ|киев)\b", re.I)
_REMOTE_LOCATION = re.compile(r"\b(?:remote|remotely|work from home|worldwide|global|anywhere|віддалено|віддалений|дистанційно)\b", re.I)
_NATIVE_IOS_TITLE = re.compile(r"\b(?:ios|swift|swiftui|uikit|iphone|ipad|objective[ -]?c|objc|cocoatouch)\b", re.I)


def is_primary_ios_role(title: str) -> bool:
    return bool(_NATIVE_IOS_TITLE.search(title or "")) and is_ios_job(title) and not _CROSS_PLATFORM_TITLE.search(title or "")


def is_work_mode_eligible(location: str | None, remote: str | None = None) -> bool:
    """Admission gate: the role must be workable from Kyiv, which means remote
    work or a Kyiv office. Geography does not reject a remote role, because an
    EU-, EMEA- or EET-scoped opening is a target; a foreign remote scope is
    reported through location_attention instead of being dropped."""
    value = (location or "").strip()
    mode = (remote or "").strip().lower()
    if not value:
        return True
    if _KYIV.search(value):
        return True
    if mode in {"onsite", "on-site", "office", "hybrid"} or re.search(r"\b(?:on[- ]?site|office|hybrid|not remote|no remote)\b", value, re.I):
        return False
    return mode == "remote" or bool(_REMOTE_LOCATION.search(value))


def is_location_eligible(location: str | None, remote: str | None = None) -> bool:
    """Work from Ukraine or a Kyiv office, with no foreign country restriction.
    Narrower than the admission gate: it marks the roles that need no location
    check before applying, and ranks duplicate variants of one role."""
    value = (location or "").strip()
    if not is_work_mode_eligible(value, remote):
        return False
    if not value or _KYIV.search(value) or _UKRAINE.search(value):
        return True
    # A remote label does not override a concrete country restriction.
    scope = _REMOTE_LOCATION.sub("", value)
    scope = re.sub(r"\b(?:work|working|from|home|fully|only|in|or)\b", "", scope, flags=re.I)
    return not scope.strip(" ,;/()–-|")


# A posting that requires local work authorization, citizenship or a clearance
# cannot be taken from Kyiv, however remote it is advertised. This is a
# requirement of the role, not its geography, so it rejects the vacancy instead
# of only flagging the location.
_WORK_AUTHORIZATION_REQUIRED = re.compile(
    r"(?i)"
    r"\b(?:authoriz|authoris)\w*\s+to\s+work\b"
    r"|\beligib\w*\s+to\s+work\b"
    r"|\bright\s+to\s+work\b"
    r"|\b(?:valid|existing|current)\s+work\s+(?:permit|visa|authoriz\w+)\b"
    r"|\bwork\s+(?:permit|visa|authoriz\w+)\b[^.]{0,40}\b(?:required|mandatory)\b"
    r"|\bcitizenship\b[^.]{0,40}\b(?:required|mandatory)\b"
    r"|\bmust\s+be\s+(?:an?\s+)?(?:[a-z.]+\s+)?citizens?\b"
    r"|\bcitizens?\s+(?:only|or\s+permanent\s+residents?)\b"
    r"|\bpermanent\s+resident\w*\b[^.]{0,30}\b(?:required|only)\b"
    r"|\bsecurity\s+clearance\b"
)
# The same words appear when the company offers to solve it, which is a
# positive signal: "we provide visa support", "relocation package included".
_WORK_AUTHORIZATION_SUPPORT = re.compile(
    r"(?i)"
    r"\bsponsorship\s+(?:is\s+)?(?:available|provided|offered)\b"
    r"|\b(?:visa|work\s+permit|relocation)\b[^.]{0,60}"
    r"\b(?:sponsor\w*|support|assistance|assist\w*|provided|available|covered|help\w*|package)\b"
    r"|\bwe\s+(?:sponsor|provide|offer|cover|help|assist)\w*\b[^.]{0,60}"
    r"\b(?:visa|work\s+permit|relocation|citizenship)\b"
)


def work_authorization_blockers(description: str = "") -> tuple[str, ...]:
    """Requirements that cannot be satisfied from Kyiv. A sentence is ignored
    when it offers help with the permit instead of demanding one, and when it
    names Ukraine, because "right to work in Ukraine" is already satisfied."""
    blockers = []
    for sentence in re.split(r"(?<=[.!?])\s+|[\n;]", required_text(description)):
        if not _WORK_AUTHORIZATION_REQUIRED.search(sentence):
            continue
        if _WORK_AUTHORIZATION_SUPPORT.search(sentence) or _UKRAINE.search(sentence):
            continue
        if re.search(r"(?i)\bsecurity\s+clearance\b", sentence):
            blockers.append("security clearance required")
        elif re.search(r"(?i)\bcitizens?(?:hip)?\b", sentence):
            blockers.append("citizenship or permanent residency required")
        else:
            blockers.append("local work authorization required")
    return tuple(dict.fromkeys(blockers))


def location_attention(location: str | None, remote: str | None = None) -> bool:
    """The role may be workable, but its geography is unknown or names a scope
    outside Ukraine, so eligibility needs a manual check. A role that is plainly
    not workable -- an office abroad -- needs no check: that is already certain,
    and flagging it too would make the flag say nothing."""
    if not is_work_mode_eligible(location, remote):
        return False
    if not (location or "").strip():
        return True
    return not is_location_eligible(location, remote)


RUSSIAN_COMPANY_MARK = "🇷🇺"


def vacancy_title_marks(vacancy: Vacancy) -> str:
    """Digest title with attention prefixes; the Russian-company mark leads so it
    is never lost behind the other marks."""
    title = vacancy.title.strip()
    if not is_target_level(vacancy.title):
        title = f"🌱 {title}"
    if location_attention(vacancy.location, vacancy.remote):
        title = f"⚠️ {title}"
    if not is_work_mode_eligible(vacancy.location, vacancy.remote):
        title = f"🏢 {title}"
    if work_authorization_blockers(vacancy.description or ""):
        title = f"🛂 {title}"
    if vacancy.russian_company:
        title = f"{RUSSIAN_COMPANY_MARK} {title}"
    return title


def is_inbox_candidate(vacancy: Vacancy) -> bool:
    """Topic gate only: a native iOS role. The collector gathers and hands over;
    level, work mode and work authorization label a vacancy (vacancy_labels)
    and never drop it."""
    return is_primary_ios_role(vacancy.title)


_LEVELS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Highest first: "Senior Staff Engineer" is a staff role.
    ("principal", re.compile(r"(?i)(?<![a-z])principal(?![a-z])")),
    ("staff", re.compile(r"(?i)(?<![a-z])staff(?![a-z])")),
    # Head and architect titles have no tier of their own; they sit with lead.
    ("lead", re.compile(r"(?i)(?<![a-z])(?:lead|head|architect)(?![a-z])")),
    ("senior", re.compile(r"(?i)(?<![a-z])(?:senior|sr\.?)(?![a-z])")),
    ("middle", re.compile(r"(?i)(?<![a-z])(?:middle|mid)(?![a-z])")),
)


def title_level(title: str) -> str:
    text = title or ""
    for level, pattern in _LEVELS:
        if pattern.search(text):
            return level
    return "junior" if _JUNIOR_TITLE.search(text) else "unknown"


def posting_language(text: str) -> str:
    """Cheap script-based guess; good enough to route a reader, not a detector."""
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return "unknown"
    cyrillic = [char for char in letters if "\u0400" <= char <= "\u04ff"]
    if len(cyrillic) < len(letters) * 0.3:
        return "en"
    lowered = "".join(cyrillic).lower()
    ukrainian = sum(lowered.count(char) for char in "\u0456\u0457\u0454\u0491")
    russian = sum(lowered.count(char) for char in "\u044b\u044d\u044a\u0451")
    return "uk" if ukrainian >= russian else "ru"


def vacancy_labels(vacancy: Vacancy) -> dict[str, Any]:
    """Signals for the downstream decision. They are facts about the posting;
    the collector attaches them and does not act on them."""
    return {
        "junior": not is_target_level(vacancy.title),
        "level": title_level(vacancy.title),
        "work_mode": (vacancy.remote or "unknown").strip().lower() or "unknown",
        "workable_from_kyiv": is_work_mode_eligible(vacancy.location, vacancy.remote),
        "location_needs_check": location_attention(vacancy.location, vacancy.remote),
        "work_authorization": list(work_authorization_blockers(vacancy.description or "")),
    }


def infer_remote(title: str, location: str | None, description: str | None) -> str:
    text = f"{title} {location or ''} {description or ''}".lower()
    if re.search(
        r"\b(?:not (?:a )?remote|no remote (?:work|option)|"
        r"remote (?:work )?is not (?:available|offered|supported)|"
        r"cannot (?:work|be done) remotely)\b",
        text,
    ):
        return "onsite"
    if re.search(r"\bhybrid\b", text):
        return "hybrid"
    if re.search(r"\bon[- ]?site\b", text):
        return "onsite"
    if _REMOTE_LOCATION.search(text):
        return "remote"
    if re.search(r"\boffice\b", text):
        return "onsite"
    return "unknown"


def normalize_raw(raw: dict[str, Any]) -> Vacancy | None:
    title = str(raw.get("title", "")).strip()
    company = str(raw.get("company", "")).strip()
    url = str(raw.get("url", "")).strip()
    if not title or not company or not url:
        return None

    description = raw.get("description")
    if description is not None:
        description = str(description).strip() or None

    if not is_ios_job(title, description):
        return None

    location = raw.get("location")
    location = str(location).strip() if location else None
    remote = raw.get("remote")
    if not remote or str(remote).strip().lower() == "unknown":
        remote = infer_remote(title, location, description)

    published_at = None
    if raw.get("published_at"):
        try:
            published_at = datetime.fromisoformat(str(raw["published_at"]).replace("Z", "+00:00"))
        except ValueError:
            published_at = None

    source_job_id: str | None = None
    raw_source_job_id = raw.get("source_job_id") or raw.get("job_id") or raw.get("id")
    if raw_source_job_id is not None:
        source_job_id = str(raw_source_job_id).strip() or None

    return Vacancy(
        company=company,
        title=title,
        url=url,
        source=str(raw.get("source", "company")),
        location=location,
        remote=str(remote),
        published_at=published_at,
        description=description,
        source_job_id=source_job_id,
        russian_company=bool(raw.get("russian_company")),
    )


def normalize_many(raw_jobs: list[dict[str, Any]]) -> list[Vacancy]:
    vacancies: list[Vacancy] = []
    for raw in raw_jobs:
        vacancy = normalize_raw(raw)
        if vacancy:
            vacancies.append(vacancy)
    return vacancies


def is_target_job(title: str, description: str | None = None) -> bool:
    """Shared early collector gate."""
    return is_ios_job(title, description)


def required_text(description: str) -> str:
    """Keep requirement sections and exclude explicitly optional bullets."""
    from bs4 import BeautifulSoup

    document = BeautifulSoup(description or "", "html.parser")
    for node in document.find_all(["p", "li", "div", "h1", "h2", "h3", "h4", "br"]):
        node.insert_after("\n")
    text = document.get_text(" ")
    required = []
    optional_section = False
    required_section = False
    for line in re.split(r"[\n;]|(?<=[.!?])\s+", text):
        line = line.strip()
        if re.search(r"^(?:nice.to.have|preferred(?: qualifications)?|bonus|desirable)\b", line, re.I):
            optional_section = True
            continue
        if re.search(r"^(?:requirements|qualifications|personal profile|required skills)\b", line, re.I):
            optional_section = False
            required_section = True
        if re.search(r"^(?:responsibilities|about us|what we offer|benefits)\b", line, re.I):
            optional_section = False
            required_section = False
        if optional_section:
            continue
        # Optional wording belongs to its clause, not every requirement in a bullet.
        for clause in re.split(r",|\bbut\b|\band(?=\s+\w+\s+(?:is\s+)?(?:preferred|optional))", line, flags=re.I):
            if re.search(r"\b(?:not required|optional|preferred|also acceptable|other languages|nice.to.have|no need)\b", clause, re.I):
                continue
            required.append(("required: " if required_section else "") + clause.strip())
    return "\n".join(required)
