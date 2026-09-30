from __future__ import annotations

from dataclasses import dataclass

from ..config import Registry
from ..models import Candidate, SourceTier
from ..utils import domain_matches, normalized_for_match, url_domain


DIRECT_INTERVIEW_DOMAINS = {
    "youtube.com",
    "youtu.be",
    "bilibili.com",
    "ted.com",
}

AUTHORITATIVE_MEDIA_DOMAINS = {
    "reuters.com",
    "bloomberg.com",
    "ft.com",
    "wsj.com",
    "technologyreview.com",
    "wired.com",
    "theverge.com",
    "36kr.com",
    "caixin.com",
    "yicai.com",
}

NON_OFFICIAL_PLATFORM_HOSTS = {
    "community.openai.com",
    "baike.baidu.com",
    "tieba.baidu.com",
    "zhidao.baidu.com",
    "wenku.baidu.com",
}

NON_OFFICIAL_URL_PREFIXES = (
    "https://cloud.baidu.com/article/",
)


@dataclass(slots=True)
class Verification:
    tier: SourceTier
    official: bool
    people: list[dict[str, str]]
    attribution_status: str
    reason: str


def verify_candidate(candidate: Candidate, title: str, text: str, registry: Registry) -> Verification:
    company = registry.companies[candidate.company]
    host = url_domain(candidate.url)
    platform_or_ugc = host in NON_OFFICIAL_PLATFORM_HOSTS or candidate.url.startswith(NON_OFFICIAL_URL_PREFIXES)
    is_official_domain = domain_matches(candidate.url, company.official_domains) and not platform_or_ugc
    official = bool(candidate.official_hint or is_official_domain)

    if platform_or_ugc:
        tier = SourceTier.D
        official = False
        reason = "公司域名下的社区、百科或用户内容平台，不视为企业第一方发言"
    elif official and candidate.source_type in {"official_personal", "official_code"}:
        tier = SourceTier.B
        reason = "已登记的研究者本人主页或官方代码组织；作为直接来源使用，但不等同于机构正式公告"
    elif official and candidate.source_type == "official_video":
        tier = SourceTier.B
        reason = "已配置的官方视频频道"
    elif official:
        tier = SourceTier.A
        reason = "命中厂商官方域名或已登记第一方来源"
    elif host in DIRECT_INTERVIEW_DOMAINS:
        tier = SourceTier.B
        reason = "公开视频/演讲平台，频道身份仍需人工复核"
    elif host in AUTHORITATIVE_MEDIA_DOMAINS:
        tier = SourceTier.C
        reason = "权威媒体来源，不是第一方页面"
    else:
        tier = candidate.tier_hint or SourceTier.D
        reason = "非白名单来源，仅作为发现线索"

    searchable = normalized_for_match(f"{title}\n{text}")
    matched_people: list[dict[str, str]] = []
    for person in registry.people_for(candidate.company):
        aliases = [alias for alias in person.aliases if len(normalized_for_match(alias)) >= 2]
        if any(normalized_for_match(alias) in searchable for alias in aliases):
            matched_people.append({"name": person.name, "role": person.role})

    if matched_people:
        attribution_status = "named_person_mention"
    elif official:
        attribution_status = "official_editorial"
    else:
        attribution_status = "unverified"
    return Verification(tier, official, matched_people, attribution_status, reason)


def source_is_usable(verification: Verification, include_leads: bool = False) -> bool:
    return verification.tier in {SourceTier.A, SourceTier.B, SourceTier.C} or include_leads
