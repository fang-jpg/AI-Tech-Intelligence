from ai_tech_intelligence.config import PROJECT_ROOT, load_registry


def test_registry_has_requested_companies_and_unique_sources() -> None:
    registry = load_registry(PROJECT_ROOT / "config")
    expected = {
        "openai",
        "google_deepmind",
        "baidu",
        "tencent",
        "bytedance",
        "minimax",
        "alibaba",
        "deepseek",
        "moonshot",
        "zhipu",
        "xiaomi",
    }
    assert expected.issubset(registry.companies)
    assert sum(company.entity_type == "institution" for company in registry.companies.values()) == 51
    assert sum(company.entity_type == "researcher" for company in registry.companies.values()) == 48
    assert len({source.id for source in registry.sources}) == len(registry.sources)
    assert all(registry.people_for(company) for company in expected)
