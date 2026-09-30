from ai_tech_intelligence.config import PROJECT_ROOT, load_registry
from ai_tech_intelligence.models import Candidate
from ai_tech_intelligence.pipeline.quality import is_relevant_document


def test_quality_filter_rejects_terms_and_index_pages() -> None:
    registry = load_registry(PROJECT_ROOT / "config")
    candidate = Candidate("minimax", "search", "search", "search_discovery", "https://www.minimax.io/terms-of-service")
    assert is_relevant_document(candidate, "Terms of Service", "AI model agent", registry)[0] is False
    candidate = Candidate("zhipu", "search", "search", "search_discovery", "https://www.zhipuai.cn/zh/research")
    assert is_relevant_document(candidate, "研究", "GLM model agent reasoning", registry)[0] is False


def test_quality_filter_accepts_technical_release() -> None:
    registry = load_registry(PROJECT_ROOT / "config")
    candidate = Candidate("bytedance", "seed", "Seed", "official_blog", "https://seed.bytedance.com/zh/blog/release")
    accepted, _ = is_relevant_document(candidate, "Seed agent model release", "The model improves agent, coding and multimodal reasoning.", registry)
    assert accepted is True
