from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from ..models import Analysis, EvidenceLevel, SourceTier
from ..taxonomy import adoption_stage, classify_text, infer_maturity
from ..utils import compact_excerpt, extract_json_object, normalized_for_match


SIGNAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "agent": ("agent", "智能体", "computer use", "tool use", "工具调用"),
    "reasoning": ("reasoning", "推理", "深度思考", "chain of thought"),
    "coding": ("coding", "code model", "代码", "软件工程", "swe-bench"),
    "multimodal": ("multimodal", "多模态", "vision", "视觉", "audio", "视频理解"),
    "long_context": ("long context", "long-context", "长上下文", "长文本", "million-token", "1m context"),
    "efficiency": ("efficiency", "efficient", "inference", "推理效率", "训练效率", "moe", "sparse", "稀疏"),
    "open_source": ("open source", "open-source", "开源", "model weights", "模型权重"),
    "robotics_embodied": ("robotics", "robot", "机器人", "具身", "embodied"),
    "world_model": ("world model", "世界模型", "interactive environment", "交互环境"),
    "ai_for_science": ("ai for science", "scientific discovery", "科学研究", "科学发现"),
    "on_device": ("on-device", "edge ai", "端侧", "端上模型", "设备端"),
}


TREND_LABELS = {
    "agent": "模型向可规划、可调用工具并完成长链路任务的 Agent 演进",
    "reasoning": "继续加强复杂推理与可验证思考能力",
    "coding": "编码能力从代码生成扩展到端到端软件工程交付",
    "multimodal": "原生多模态理解与生成将成为统一模型能力",
    "long_context": "长上下文将与检索、记忆和复杂任务执行结合",
    "efficiency": "架构、训练与推理效率仍是降低部署成本的核心路线",
    "open_source": "通过开放权重与工具链扩大开发者生态",
    "robotics_embodied": "模型能力向机器人与物理世界交互延伸",
    "world_model": "世界模型与可交互环境生成成为新的能力轴",
    "ai_for_science": "加强面向科学发现的推理、仿真与研究代理能力",
    "on_device": "更多能力将下沉到端侧并与硬件协同优化",
}


class CompatibleLLMClient:
    def __init__(self):
        self.api_key = os.getenv("GENERAL_AI_REPORT_LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        self.base_url = (os.getenv("GENERAL_AI_REPORT_LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.models = [
            os.getenv(f"GENERAL_AI_REPORT_LLM_MODEL{suffix}", "").strip()
            for suffix in ("", "_2", "_3", "_4")
        ]
        self.models = [model for model in self.models if model]
        if not self.models and os.getenv("OPENAI_MODEL"):
            self.models = [os.environ["OPENAI_MODEL"]]
        self.timeout = float(os.getenv("GENERAL_AI_REPORT_LLM_TIMEOUT", "90"))
        self.retries_per_model = int(os.getenv("GENERAL_AI_REPORT_LLM_RETRIES_PER_MODEL", "2"))
        self.endpoint = self.base_url if self.base_url.endswith("/chat/completions") else f"{self.base_url}/chat/completions"

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.models)

    def complete_json(self, system: str, user: str, max_tokens: int = 2200) -> tuple[dict[str, Any], str]:
        if not self.available:
            raise RuntimeError("未配置可用的 LLM API key/model")
        last_error: Exception | None = None
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            for model in self.models:
                for attempt in range(self.retries_per_model):
                    payload: dict[str, Any] = {
                        "model": model,
                        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                        "temperature": 0.1,
                        "max_tokens": max_tokens,
                        "response_format": {"type": "json_object"},
                    }
                    try:
                        response = client.post(self.endpoint, headers=headers, json=payload)
                        if response.status_code >= 400 and attempt == 0:
                            payload.pop("response_format", None)
                            response = client.post(self.endpoint, headers=headers, json=payload)
                        response.raise_for_status()
                        content = response.json()["choices"][0]["message"]["content"]
                        parsed = extract_json_object(content)
                        if not parsed:
                            raise ValueError("LLM 未返回有效 JSON 对象")
                        return parsed, model
                    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
                        last_error = exc
        raise RuntimeError(f"所有 LLM 模型均调用失败: {type(last_error).__name__}: {last_error}")


class IntelligenceAnalyzer:
    def __init__(self, client: CompatibleLLMClient | None = None, context_chars: int | None = None):
        self.client = client or CompatibleLLMClient()
        self.context_chars = context_chars or int(os.getenv("TECHNICAL_ARTICLE_CONTEXT_CHARS", "30000"))

    def analyze(self, document: dict[str, Any], timeline: list[dict[str, Any]]) -> Analysis:
        if not self.client.available:
            return self._heuristic(document)
        try:
            facts, fact_model = self._extract_facts(document)
            trends, trend_model = self._reason_trends(document, facts, timeline)
            return self._assemble(document, facts, trends, trend_model or fact_model)
        except Exception:
            return self._heuristic(document)

    def _extract_facts(self, document: dict[str, Any]) -> tuple[dict[str, Any], str]:
        system = """你是技术情报事实抽取器。只使用给定原文，不补充外部知识，不把公司官方文章自动归因给高管。
输出严格 JSON，键为 core_points、technical_signals、attributed_statements、future_commitments。
technical_signals 每项包含 tag、description、evidence；evidence 必须是原文中的短字符串。
attributed_statements 每项包含 speaker、statement、evidence；只有原文明确出现说话人和对应表述时才输出。
future_commitments 每项包含 direction、evidence；只收集明确的未来计划或承诺。无法确认时输出空数组。"""
        known_people = document.get("people_json") or []
        user = json.dumps(
            {
                "title": document.get("title"),
                "published_at": document.get("published_at"),
                "source_type": document.get("source_type"),
                "official": bool(document.get("official")),
                "known_people_mentions": known_people,
                "text": str(document.get("text", ""))[: self.context_chars],
            },
            ensure_ascii=False,
        )
        return self.client.complete_json(system, user)

    def _reason_trends(
        self,
        document: dict[str, Any],
        facts: dict[str, Any],
        timeline: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], str]:
        system = """你是谨慎的前沿 AI 技术路线分析师。只能基于所给事实与历史信号推断，不得引入外部知识。
输出严格 JSON：trend_summary、directions、overall_evidence_level、overall_confidence、time_window。

质量要求：
1. trend_summary 写 2-4 句，必须指出该机构/人物最具区分度的技术信号、变化机制与潜在下一步，禁止套用“加强推理、多模态、Agent”等可复制到任何主体的模板句。
2. directions 输出 1-3 个互不重复的方向；若两个方向的机制或可观察结果相同，合并为一个。
3. directions 每项必须包含 technology_domain、technical_module、direction、evolution_mechanism、maturity_stage_1_5、adoption_status、representative_examples、product_implications、reasoning、evidence、evidence_level、confidence、quantitative_outlook。
4. technology_domain 必须从 LLM架构与语言能力、多模态理解与生成、世界模型与仿真、具身智能与机器人、训练范式：预训练、训练范式：后训练、Agent与工具使用、推理、规划与可验证计算、长上下文、记忆与检索、训练推理效率与基础设施、AI for Science与专业模型、安全、对齐与评测、开源、数据与开发者生态、端侧AI与软硬件协同中选择。technical_module 写到 Attention、MoE、VLA、RLHF、Agent规划、KV Cache 等可比较的模块层；禁止只重复大类名称。
5. maturity_stage_1_5 使用 1=早期研究、2=多项研究/原型、3=可复现实验或持续项目、4=产品化/规模采用、5=成熟基础设施或标准生态。adoption_status 只能是研究探索、研究原型、工程验证/产品导入、规模应用之一。representative_examples 只能使用输入证据中的模型、系统、数据集、评测或产品名。
6. product_implications 必须回答“这条演进对模型/产品/基础设施的具体决策意味着什么”，不得写空泛的“提升能力”或“保持领先”。evolution_mechanism 必须说明从当前信号到下一步的机制链。
7. quantitative_outlook 必须包含 probability_low、probability_base、probability_high、horizon_months、observable_metric、forecast_range、assumptions、counter_signals、falsifiers。
8. 三个 probability 是分析师估计的方向发生概率，取值 0-1，且 low <= base <= high；它们不是来源事实。horizon_months 只能为 12、24 或 36。
9. observable_metric 必须是未来能核验的指标，例如正式模型/数据集发布次数、公开评测覆盖数、推理成本变化、基准改善或开放权重规模。forecast_range 写带单位的区间；没有原文数字基线时，必须写“分析估计”，不得伪造当前参数量、成本或基准成绩。
10. assumptions 列出 1-3 个关键假设，counter_signals 与 falsifiers 各列出 1-2 个降低或推翻判断的观察条件。

evidence_level 只能是 Explicit、Strong inference、Speculative。Explicit 仅用于原文明确未来计划；Strong inference 需要多个一致信号；单一模糊信号只能是 Speculative。confidence 为 0 到 1。
trend_summary 必须明确这是“基于公开信号的推断”，不能写成确定事实。"""
        timeline_compact = timeline[:12]
        user = json.dumps(
            {
                "company": document.get("company_id"),
                "current_document_id": document.get("id"),
                "facts": facts,
                "recent_company_timeline": timeline_compact,
            },
            ensure_ascii=False,
        )
        return self.client.complete_json(system, user)

    def _assemble(
        self,
        document: dict[str, Any],
        facts: dict[str, Any],
        trends: dict[str, Any],
        model: str,
    ) -> Analysis:
        text_match = normalized_for_match(str(document.get("text", "")))
        signals = facts.get("technical_signals") if isinstance(facts.get("technical_signals"), list) else []
        statements = facts.get("attributed_statements") if isinstance(facts.get("attributed_statements"), list) else []
        evidence_values = [str(item.get("evidence", "")) for item in [*signals, *statements] if isinstance(item, dict)]
        grounded = bool(evidence_values) and all(
            normalized_for_match(value) in text_match for value in evidence_values if normalized_for_match(value)
        )
        level_value = str(trends.get("overall_evidence_level", "Speculative"))
        try:
            level = EvidenceLevel(level_value)
        except ValueError:
            level = EvidenceLevel.SPECULATIVE
        confidence = _clamp_float(trends.get("overall_confidence", 0.5))
        if not grounded:
            confidence = min(confidence, 0.45)
            if level == EvidenceLevel.EXPLICIT:
                level = EvidenceLevel.SPECULATIVE
        raw_directions = trends.get("directions") if isinstance(trends.get("directions"), list) else []
        directions = [
            _normalize_direction_fields(item)
            for item in _deduplicate_directions([item for item in raw_directions if isinstance(item, dict)])
        ]
        return Analysis(
            document_id=int(document["id"]),
            core_points=[str(value) for value in facts.get("core_points", []) if str(value).strip()][:8],
            technical_signals=[item for item in signals if isinstance(item, dict)][:12],
            attributed_statements=[item for item in statements if isinstance(item, dict)][:8],
            trend_summary=str(trends.get("trend_summary", "基于当前公开信号，尚不足以形成可靠趋势判断。")),
            trend_directions=directions[:3],
            evidence_level=level,
            confidence=confidence,
            time_window=str(trends.get("time_window", "未来 6-12 个月")),
            model=model,
            grounding_passed=grounded,
            analysis_method="llm_two_stage",
        )

    def _heuristic(self, document: dict[str, Any]) -> Analysis:
        text = str(document.get("text", ""))
        lowered = text.casefold()
        signals: list[dict[str, Any]] = []
        for tag, keywords in SIGNAL_KEYWORDS.items():
            matched = next((keyword for keyword in keywords if keyword.casefold() in lowered), None)
            if not matched:
                continue
            match = re.search(re.escape(matched), text, flags=re.I)
            evidence = compact_excerpt(text[max(0, (match.start() if match else 0) - 80) : (match.end() if match else 0) + 160])
            signals.append({"tag": tag, "description": TREND_LABELS[tag], "evidence": evidence})
        forward_markers = ("will", "plan to", "next generation", "future", "将", "计划", "未来", "下一代", "继续推进")
        explicit = any(marker in lowered for marker in forward_markers)
        if explicit and signals:
            level = EvidenceLevel.EXPLICIT
            confidence = 0.72 if document.get("official") else 0.58
        elif len(signals) >= 2:
            level = EvidenceLevel.STRONG_INFERENCE
            confidence = 0.62 if document.get("official") else 0.48
        else:
            level = EvidenceLevel.SPECULATIVE
            confidence = 0.35 if signals else 0.2
        directions = []
        for item in signals[:5]:
            categories = classify_text([item["tag"], item["description"], item["evidence"]], max_categories=1)
            category = categories[0] if categories else {"name": "其他前沿技术与应用", "module_terms": [item["tag"]], "product_focus": "需要更多证据后判断产品影响。"}
            maturity, _ = infer_maturity({"technical_signals": signals, "title": document.get("title"), "trend_summary": item["description"], "confidence": confidence})
            directions.append(
                {
                    "technology_domain": category["name"],
                    "technical_module": "、".join(category.get("module_terms", [])[:3]),
                    "direction": TREND_LABELS[item["tag"]],
                    "evolution_mechanism": f"原文出现 {item['tag']} 相关信号，规则分析将其映射到统一技术分类。",
                    "maturity_stage_1_5": maturity,
                    "adoption_status": adoption_stage({"title": document.get("title"), "trend_summary": item["description"], "confidence": confidence}, maturity),
                    "representative_examples": [],
                    "product_implications": category.get("product_focus", "需要更多证据后判断产品影响。"),
                    "reasoning": f"原文出现 {item['tag']} 相关信号；规则分析未使用外部信息。",
                    "evidence": item["evidence"],
                    "evidence_level": str(level),
                    "confidence": confidence,
                    "quantitative_outlook": {
                        "probability_low": max(0.0, confidence - 0.2),
                        "probability_base": confidence,
                        "probability_high": min(1.0, confidence + 0.15),
                        "horizon_months": 12,
                        "observable_metric": "同方向正式模型、数据集、评测或产品发布数量",
                        "forecast_range": "分析估计，待后续公开结果校准",
                        "assumptions": ["当前技术信号在预测窗口内持续"],
                        "counter_signals": ["公开资源转向其他技术路线"],
                        "falsifiers": ["预测窗口内未出现同方向可核验发布"],
                    },
                }
            )
        trend_text = "；".join(item["direction"] for item in directions)
        if trend_text:
            summary = f"基于该公开来源的关键词信号推断：{trend_text}。该结论为规则降级分析，需结合更多时间线证据复核。"
        else:
            summary = "当前文本未检出足够明确的模型路线信号，暂不作方向性判断。"
        people = document.get("people_json") or []
        statements = []
        if people and explicit:
            statements = [{"speaker": person.get("name", ""), "statement": "原文包含未来方向表述，需人工核对上下文。", "evidence": signals[0]["evidence"] if signals else ""} for person in people[:2]]
        return Analysis(
            document_id=int(document["id"]),
            core_points=[compact_excerpt(text, 260)] if text else [],
            technical_signals=signals,
            attributed_statements=statements,
            trend_summary=summary,
            trend_directions=directions,
            evidence_level=level,
            confidence=confidence,
            time_window="未来 6-12 个月",
            model="heuristic-v1",
            grounding_passed=all(normalized_for_match(item["evidence"]) in normalized_for_match(text) for item in signals),
            analysis_method="heuristic_fallback",
        )


def _clamp_float(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.5


def _deduplicate_directions(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove exact/near-identical directions without inventing replacement content."""
    output: list[dict[str, Any]] = []
    seen: list[set[str]] = []
    for item in values:
        direction = str(item.get("direction", "")).strip()
        if not direction:
            continue
        tokens = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", direction.casefold()))
        duplicate = False
        for existing in seen:
            union = tokens | existing
            similarity = len(tokens & existing) / len(union) if union else 1.0
            if similarity >= 0.82:
                duplicate = True
                break
        if duplicate:
            continue
        quantitative = item.get("quantitative_outlook")
        if not isinstance(quantitative, dict):
            item = dict(item)
            item["quantitative_outlook"] = {}
        output.append(item)
        seen.append(tokens)
    return output


def _normalize_direction_fields(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    categories = classify_text(
        [
            item.get("technology_domain"),
            item.get("technical_module"),
            item.get("direction"),
            item.get("evolution_mechanism"),
            item.get("reasoning"),
            item.get("evidence"),
        ],
        max_categories=1,
    )
    category = categories[0] if categories else None
    if not str(normalized.get("technology_domain", "")).strip():
        normalized["technology_domain"] = category["name"] if category else "其他前沿技术与应用"
    if not str(normalized.get("technical_module", "")).strip():
        normalized["technical_module"] = "、".join((category or {}).get("module_terms", [])[:3]) or "待细分"
    if not str(normalized.get("evolution_mechanism", "")).strip():
        normalized["evolution_mechanism"] = str(normalized.get("reasoning", "")).strip()
    try:
        maturity = max(1, min(5, int(normalized.get("maturity_stage_1_5", 1))))
    except (TypeError, ValueError):
        maturity = 1
    normalized["maturity_stage_1_5"] = maturity
    if normalized.get("adoption_status") not in {"研究探索", "研究原型", "工程验证/产品导入", "规模应用"}:
        normalized["adoption_status"] = {1: "研究探索", 2: "研究原型", 3: "工程验证/产品导入", 4: "规模应用", 5: "规模应用"}[maturity]
    examples = normalized.get("representative_examples")
    normalized["representative_examples"] = [str(value) for value in examples if str(value).strip()][:5] if isinstance(examples, list) else []
    if not str(normalized.get("product_implications", "")).strip():
        normalized["product_implications"] = (category or {}).get("product_focus", "需要更多证据后判断产品影响。")
    quantitative = normalized.get("quantitative_outlook")
    if not isinstance(quantitative, dict):
        quantitative = {}
    quantitative.setdefault("counter_signals", [])
    quantitative.setdefault("falsifiers", [])
    normalized["quantitative_outlook"] = quantitative
    return normalized
