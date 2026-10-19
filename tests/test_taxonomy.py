from ai_tech_intelligence.taxonomy import adoption_stage, classify_text, infer_maturity


def test_classify_frontier_technology_categories() -> None:
    categories = classify_text([
        "原生多模态世界模型支持机器人 VLA，后训练采用强化学习",
    ], max_categories=5)
    ids = {item["id"] for item in categories}
    assert {"multimodal", "world_model", "embodied", "posttraining"}.issubset(ids)


def test_maturity_and_adoption_use_observable_product_language() -> None:
    record = {
        "title": "模型 API 已上线并服务企业客户",
        "trend_summary": "产品进入规模化部署",
        "confidence": 0.82,
        "technical_signals": [{"tag": "agent"}, {"tag": "tool use"}],
    }
    stage, _ = infer_maturity(record)
    assert stage >= 4
    assert adoption_stage(record, stage) == "规模应用"
