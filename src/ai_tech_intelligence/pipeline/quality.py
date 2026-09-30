from __future__ import annotations

from urllib.parse import urlsplit

from ..config import Registry
from ..models import Candidate


EXCLUDED_TITLE_PHRASES = (
    "terms of service",
    "privacy policy",
    "cookie policy",
    "user agreement",
    "will announce",
    "to report 2025 full year financial results",
    "服务条款",
    "隐私政策",
    "用户协议",
)

EXCLUDED_PATH_FRAGMENTS = (
    "/help/",
    "/terms",
    "/privacy",
    "/careers",
    "/jobs/",
)

GENERIC_TECH_TERMS = (
    "model",
    "agent",
    "reasoning",
    "multimodal",
    "inference",
    "training",
    "coding",
    "context",
    "模型",
    "智能体",
    "推理",
    "多模态",
    "训练",
    "上下文",
    "代码",
)

GENERIC_INDEX_TITLES = {
    "publications",
    "evals",
    "research",
    "研究",
    "news",
    "blog",
    "deepseek | into the unknown",
    "hi i'm zcode",
}


def is_relevant_document(candidate: Candidate, title: str, text: str, registry: Registry) -> tuple[bool, str]:
    title_lower = title.casefold().strip()
    path_lower = urlsplit(candidate.url).path.casefold()
    if title_lower in GENERIC_INDEX_TITLES:
        return False, "通用索引页"
    if any(phrase in title_lower for phrase in EXCLUDED_TITLE_PHRASES):
        return False, "法律、隐私或结果预告页面"
    if any(fragment in path_lower for fragment in EXCLUDED_PATH_FRAGMENTS):
        return False, "帮助、法律或招聘页面"
    combined = f"{title}\n{text[:12000]}".casefold()
    company = registry.companies[candidate.company]
    topic_matches = sum(1 for topic in company.query_topics if topic.casefold() in combined)
    generic_matches = sum(1 for term in GENERIC_TECH_TERMS if term in combined)
    if topic_matches == 0 and generic_matches < 2:
        return False, "缺少足够的大模型技术信号"
    return True, "通过技术相关性过滤"

