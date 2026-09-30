from ai_tech_intelligence.config import PROJECT_ROOT, load_registry
from ai_tech_intelligence.db import IntelligenceDB
from ai_tech_intelligence.models import Document, SourceTier
from ai_tech_intelligence.pipeline.analyze import CompatibleLLMClient, IntelligenceAnalyzer
from ai_tech_intelligence.utils import sha256_text


def _document() -> Document:
    text = (
        "公司未来将继续加强 Agent 工具调用、复杂推理和多模态理解，支持端到端软件工程任务。"
        "官方文章进一步说明，模型需要在真实工作流中完成多步骤规划、执行和反馈，而不只是回答静态问题。"
        "研发团队也会优化推理效率，并通过更可靠的评测检查模型在长链路任务中的表现。"
    )
    return Document(
        company="openai",
        source_id="openai_news",
        source_name="OpenAI Newsroom",
        source_type="official_blog",
        url="https://openai.com/index/test-roadmap",
        canonical_url="https://openai.com/index/test-roadmap",
        title="Roadmap update",
        published_at="2026-09-01",
        text=text,
        content_hash=sha256_text(text),
        tier=SourceTier.A,
        official=True,
        attribution_status="official_editorial",
        verification_reason="test",
    )


def test_database_roundtrip_and_heuristic_analysis(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("GENERAL_AI_REPORT_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    registry = load_registry(PROJECT_ROOT / "config")
    with IntelligenceDB(tmp_path / "test.db") as db:
        db.initialize(registry)
        doc_id, inserted = db.upsert_document(_document())
        assert inserted is True
        row = dict(db.documents_for_analysis(["openai"])[0])
        row["people_json"] = []
        analyzer = IntelligenceAnalyzer(CompatibleLLMClient())
        analysis = analyzer.analyze(row, [])
        assert analysis.document_id == doc_id
        assert analysis.analysis_method == "heuristic_fallback"
        assert {signal["tag"] for signal in analysis.technical_signals} >= {"agent", "reasoning", "multimodal", "coding"}
        db.save_analysis(analysis)
        report = db.report_rows(["openai"])
        assert report[0]["trend_summary"]
        assert report[0]["grounding_passed"] == 1
