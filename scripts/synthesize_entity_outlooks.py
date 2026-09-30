from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from ai_tech_intelligence.config import PROJECT_ROOT, load_env_file, load_registry
from ai_tech_intelligence.db import IntelligenceDB
from ai_tech_intelligence.pipeline.analyze import CompatibleLLMClient


LOGGER = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是高校和科研机构前沿 AI 技术路线分析师。只能使用输入中的公开来源事实，不得补充外部知识。
请对单一机构的多条信号做机构级综合，不要逐篇复述。

输出严格 JSON：
{
  "executive_summary": "2-4句，指出机构独有的技术组合、变化机制和未来重点",
  "directions": [
    {
      "direction": "互不重复的具体方向",
      "mechanism": "为何这些证据会导致该方向",
      "evidence_document_ids": [1, 2],
      "evidence_urls": ["https://..."],
      "evidence_level": "Explicit|Strong inference|Speculative",
      "confidence": 0.0,
      "probability_low": 0.0,
      "probability_base": 0.0,
      "probability_high": 0.0,
      "horizon_months": 12,
      "observable_metric": "未来可核验的具体指标",
      "forecast_range": "带单位的区间，或明确写分析估计",
      "assumptions": ["关键假设"],
      "falsifiers": ["何种观察会推翻判断"]
    }
  ],
  "portfolio_metrics": {
    "expected_major_outputs_12m_low": 0,
    "expected_major_outputs_12m_base": 0,
    "expected_major_outputs_12m_high": 0,
    "definition": "major output 的机构特定定义"
  },
  "limitations": ["数据缺口或不确定性"]
}

约束：
1. directions 只输出 1-3 个，必须互相独立；禁止重复写“推理、Agent、多模态”而不解释机构特有机制。
2. 所有 evidence_document_ids 和 evidence_urls 必须来自输入。
3. 概率是分析师估计，不是来源事实；low <= base <= high，均为 0-1。
4. horizon_months 只能为 12、24、36。
5. 没有数值基线时，不得编造参数量、算力、成本或榜单分数。可以预测“重大公开产出数量”或方向发生概率，但必须注明分析估计。
6. portfolio_metrics 的 major output 可包括正式模型、开放权重、数据集、评测框架或重大系统发布；区间必须与当前证据密度相称。
7. executive_summary 必须能区分当前机构与其他机构，不得使用通用套话。"""


def _companies(value: str | None, registry: Any) -> list[str]:
    if value and value.strip().lower() != "academic":
        return [item.strip() for item in value.split(",") if item.strip()]
    return [company_id for company_id, company in registry.companies.items() if company.entity_type == "institution"]


def _evidence_pack(rows: list[dict[str, Any]], max_documents: int) -> list[dict[str, Any]]:
    ranked = sorted(
        (row for row in rows if row.get("analyzed_at")),
        key=lambda row: (
            bool(row.get("grounding_passed")),
            float(row.get("confidence") or 0.0),
            str(row.get("published_at") or ""),
        ),
        reverse=True,
    )[:max_documents]
    output = []
    for row in ranked:
        output.append(
            {
                "document_id": row.get("id"),
                "title": row.get("title"),
                "date": row.get("published_at"),
                "url": row.get("url"),
                "source_tier": row.get("tier"),
                "grounding_passed": bool(row.get("grounding_passed")),
                "core_points": (row.get("core_points_json") or [])[:5],
                "technical_signals": (row.get("technical_signals_json") or [])[:8],
                "attributed_statements": (row.get("attributed_statements_json") or [])[:4],
            }
        )
    return output


def _clamp_probability(value: Any) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 4)
    except (TypeError, ValueError):
        return 0.5


def _normalize_result(company_id: str, name: str, raw: dict[str, Any], pack: list[dict[str, Any]], model: str) -> dict[str, Any]:
    valid_ids = {int(item["document_id"]) for item in pack if item.get("document_id") is not None}
    url_by_id = {int(item["document_id"]): str(item.get("url", "")) for item in pack if item.get("document_id") is not None}
    directions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw.get("directions", []) if isinstance(raw.get("directions"), list) else []:
        if not isinstance(item, dict):
            continue
        direction = str(item.get("direction", "")).strip()
        key = "".join(direction.casefold().split())
        if not direction or key in seen:
            continue
        seen.add(key)
        ids = []
        for value in item.get("evidence_document_ids", []):
            try:
                document_id = int(value)
            except (TypeError, ValueError):
                continue
            if document_id in valid_ids and document_id not in ids:
                ids.append(document_id)
        urls = [url_by_id[document_id] for document_id in ids if url_by_id.get(document_id)]
        low = _clamp_probability(item.get("probability_low", 0.35))
        base = _clamp_probability(item.get("probability_base", 0.55))
        high = _clamp_probability(item.get("probability_high", 0.75))
        low, base, high = sorted((low, base, high))
        try:
            horizon = int(item.get("horizon_months", 24))
        except (TypeError, ValueError):
            horizon = 24
        if horizon not in {12, 24, 36}:
            horizon = min((12, 24, 36), key=lambda value: abs(value - horizon))
        directions.append(
            {
                "direction": direction,
                "mechanism": str(item.get("mechanism", "")).strip(),
                "evidence_document_ids": ids,
                "evidence_urls": urls,
                "evidence_level": str(item.get("evidence_level", "Speculative")),
                "confidence": _clamp_probability(item.get("confidence", base)),
                "probability_low": low,
                "probability_base": base,
                "probability_high": high,
                "horizon_months": horizon,
                "observable_metric": str(item.get("observable_metric", "")).strip(),
                "forecast_range": str(item.get("forecast_range", "分析估计，待后续公开结果校准")).strip(),
                "assumptions": [str(value) for value in item.get("assumptions", []) if str(value).strip()][:3],
                "falsifiers": [str(value) for value in item.get("falsifiers", []) if str(value).strip()][:2],
            }
        )
        if len(directions) >= 3:
            break
    metrics = raw.get("portfolio_metrics") if isinstance(raw.get("portfolio_metrics"), dict) else {}
    counts = []
    for key in ("expected_major_outputs_12m_low", "expected_major_outputs_12m_base", "expected_major_outputs_12m_high"):
        try:
            counts.append(max(0, int(round(float(metrics.get(key, 0))))))
        except (TypeError, ValueError):
            counts.append(0)
    counts.sort()
    return {
        "company_id": company_id,
        "entity_name": name,
        "executive_summary": str(raw.get("executive_summary", "公开信号不足，暂不形成机构级量化判断。")).strip(),
        "directions": directions,
        "portfolio_metrics": {
            "expected_major_outputs_12m_low": counts[0],
            "expected_major_outputs_12m_base": counts[1],
            "expected_major_outputs_12m_high": counts[2],
            "definition": str(metrics.get("definition", "正式模型、开放权重、数据集、评测框架或重大系统发布")).strip(),
        },
        "limitations": [str(value) for value in raw.get("limitations", []) if str(value).strip()][:4],
        "evidence_document_count": len(pack),
        "grounded_document_count": sum(bool(item.get("grounding_passed")) for item in pack),
        "model": model,
        "analysis_method": "llm_entity_synthesis_with_quantitative_ranges",
    }


def _fallback(company_id: str, name: str, pack: list[dict[str, Any]], error: str) -> dict[str, Any]:
    tags = Counter(
        str(signal.get("tag", "")).strip()
        for item in pack
        for signal in item.get("technical_signals", [])
        if str(signal.get("tag", "")).strip()
    )
    top = [tag for tag, _ in tags.most_common(3)]
    return {
        "company_id": company_id,
        "entity_name": name,
        "executive_summary": "公开证据已汇总，但机构级大模型综合调用失败；当前仅保留高频技术信号，不输出伪精确量化结论。",
        "directions": [],
        "portfolio_metrics": {
            "expected_major_outputs_12m_low": 0,
            "expected_major_outputs_12m_base": 0,
            "expected_major_outputs_12m_high": 0,
            "definition": "未估计",
        },
        "limitations": [f"LLM synthesis failed: {error}", f"top signals: {', '.join(top) or 'none'}"],
        "evidence_document_count": len(pack),
        "grounded_document_count": sum(bool(item.get("grounding_passed")) for item in pack),
        "model": "fallback-no-quantification",
        "analysis_method": "deterministic_fallback",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthesize non-duplicative institution-level outlooks with calibrated quantitative ranges")
    parser.add_argument("output", type=Path)
    parser.add_argument("--database", type=Path, default=PROJECT_ROOT / "data" / "intelligence.db")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.txt")
    parser.add_argument("--companies", default="academic")
    parser.add_argument("--max-documents", type=int, default=12)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()

    load_env_file(args.env_file)
    registry = load_registry()
    selected = _companies(args.companies, registry)
    client = CompatibleLLMClient()
    if not client.available:
        raise RuntimeError("未配置可用的 LLM，无法生成机构级量化展望")

    jobs: list[tuple[str, str, list[dict[str, Any]]]] = []
    with IntelligenceDB(args.database) as db:
        db.initialize(registry)
        for company_id in selected:
            rows = db.report_rows([company_id])
            pack = _evidence_pack(rows, max(1, args.max_documents))
            if pack:
                jobs.append((company_id, registry.companies[company_id].name, pack))

    def synthesize(job: tuple[str, str, list[dict[str, Any]]]) -> dict[str, Any]:
        company_id, name, pack = job
        user = json.dumps({"institution": name, "institution_id": company_id, "evidence_pack": pack}, ensure_ascii=False)
        try:
            raw, model = client.complete_json(SYSTEM_PROMPT, user, max_tokens=3600)
            return _normalize_result(company_id, name, raw, pack, model)
        except Exception as exc:  # noqa: BLE001 - preserve batch progress
            LOGGER.exception("institution synthesis failed: %s", company_id)
            return _fallback(company_id, name, pack, f"{type(exc).__name__}: {exc}")

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 6))) as executor:
        future_to_id = {executor.submit(synthesize, job): job[0] for job in jobs}
        for future in as_completed(future_to_id):
            results.append(future.result())
    results.sort(key=lambda item: item["entity_name"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "institutions_requested": len(selected),
        "institutions_with_evidence": len(results),
        "directions": sum(len(item["directions"]) for item in results),
        "fallbacks": sum(item["analysis_method"] == "deterministic_fallback" for item in results),
        "output": str(args.output.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
