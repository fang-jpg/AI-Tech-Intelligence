from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class SourceTier(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class EvidenceLevel(StrEnum):
    EXPLICIT = "Explicit"
    STRONG_INFERENCE = "Strong inference"
    SPECULATIVE = "Speculative"


@dataclass(slots=True)
class Company:
    id: str
    name: str
    country: str
    aliases: list[str]
    official_domains: list[str]
    query_topics: list[str]
    entity_type: str = "vendor"


@dataclass(slots=True)
class Person:
    company: str
    name: str
    role: str
    aliases: list[str]
    profile_url: str = ""


@dataclass(slots=True)
class Source:
    id: str
    company: str
    name: str
    type: str
    tier: SourceTier
    url: str
    include_patterns: list[str] = field(default_factory=list)
    official: bool = True
    single_page: bool = False


@dataclass(slots=True)
class Candidate:
    company: str
    source_id: str
    source_name: str
    source_type: str
    url: str
    title: str = ""
    published_at: str | None = None
    snippet: str = ""
    tier_hint: SourceTier | None = None
    official_hint: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Document:
    company: str
    source_id: str
    source_name: str
    source_type: str
    url: str
    canonical_url: str
    title: str
    published_at: str | None
    text: str
    content_hash: str
    tier: SourceTier
    official: bool
    people: list[dict[str, str]] = field(default_factory=list)
    attribution_status: str = "unverified"
    verification_reason: str = ""
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Analysis:
    document_id: int
    core_points: list[str]
    technical_signals: list[dict[str, Any]]
    attributed_statements: list[dict[str, Any]]
    trend_summary: str
    trend_directions: list[dict[str, Any]]
    evidence_level: EvidenceLevel
    confidence: float
    time_window: str
    model: str
    grounding_passed: bool
    analysis_method: str
    analyzed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["evidence_level"] = str(self.evidence_level)
        return value
