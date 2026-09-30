from ai_tech_intelligence.config import PROJECT_ROOT, load_registry
from ai_tech_intelligence.models import Candidate, SourceTier
from ai_tech_intelligence.pipeline.verify import verify_candidate


def test_official_source_and_person_are_verified_separately() -> None:
    registry = load_registry(PROJECT_ROOT / "config")
    candidate = Candidate(
        company="openai",
        source_id="search_tavily",
        source_name="search",
        source_type="search_discovery",
        url="https://openai.com/index/example",
    )
    result = verify_candidate(candidate, "Update from Sam Altman", "Sam Altman discussed reasoning models.", registry)
    assert result.tier == SourceTier.A
    assert result.official is True
    assert result.people[0]["name"] == "Sam Altman"
    assert result.attribution_status == "named_person_mention"


def test_official_editorial_is_not_person_statement() -> None:
    registry = load_registry(PROJECT_ROOT / "config")
    candidate = Candidate(
        company="deepseek",
        source_id="deepseek_news",
        source_name="DeepSeek News",
        source_type="official_news",
        url="https://www.deepseek.com/news/model-update",
        official_hint=True,
    )
    result = verify_candidate(candidate, "Model update", "We introduce a new reasoning model.", registry)
    assert result.tier == SourceTier.A
    assert result.people == []
    assert result.attribution_status == "official_editorial"


def test_company_hosted_community_is_not_official() -> None:
    registry = load_registry(PROJECT_ROOT / "config")
    candidate = Candidate(
        company="openai",
        source_id="search_tavily",
        source_name="search",
        source_type="search_discovery",
        url="https://community.openai.com/t/user-post/123",
    )
    result = verify_candidate(candidate, "User post", "A community member discusses a model.", registry)
    assert result.tier == SourceTier.D
    assert result.official is False
