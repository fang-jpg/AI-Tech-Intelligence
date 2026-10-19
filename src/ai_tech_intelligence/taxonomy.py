from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


TAXONOMY_PATH = Path(__file__).resolve().parents[2] / "config" / "technology_taxonomy.json"
MATURITY_LABELS = {
    1: "早期研究",
    2: "多项研究/原型",
    3: "可复现实验/持续项目",
    4: "产品化/规模采用",
    5: "成熟基础设施/标准生态",
}


@lru_cache(maxsize=1)
def load_technology_taxonomy() -> list[dict[str, Any]]:
    return json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))


def classify_text(parts: Iterable[Any], max_categories: int = 3) -> list[dict[str, Any]]:
    text = "\n".join(str(value or "") for value in parts).casefold()
    scored: list[dict[str, Any]] = []
    for category in load_technology_taxonomy():
        matches: list[str] = []
        score = 0
        for keyword in category["keywords"]:
            normalized = str(keyword).casefold()
            count = len(re.findall(re.escape(normalized), text))
            if count:
                matches.append(str(keyword))
                score += min(count, 3)
        if score:
            scored.append({**category, "score": score, "matched_keywords": matches})
    scored.sort(key=lambda item: (-int(item["score"]), load_technology_taxonomy().index(next(cat for cat in load_technology_taxonomy() if cat["id"] == item["id"]))))
    return scored[:max_categories]


def classify_record(record: dict[str, Any], max_categories: int = 3) -> list[dict[str, Any]]:
    signals = record.get("technical_signals_json") or record.get("technical_signals") or []
    signal_text = " ".join(
        " ".join(str(signal.get(key, "")) for key in ("tag", "description", "evidence"))
        if isinstance(signal, dict) else str(signal)
        for signal in signals
    )
    core_points = record.get("core_points_json") or record.get("core_points") or []
    return classify_text(
        [
            record.get("title"),
            signal_text,
            " ".join(str(value) for value in core_points),
            record.get("trend_summary"),
            record.get("statement"),
        ],
        max_categories=max_categories,
    )


def infer_maturity(record: dict[str, Any]) -> tuple[int, str]:
    text = " ".join(
        str(record.get(key, ""))
        for key in ("title", "trend_summary", "statement", "source_type")
    ).casefold()
    confidence = float(record.get("confidence") or 0.0)
    stage = 1
    if len(record.get("technical_signals_json") or record.get("technical_signals") or []) >= 2:
        stage = 2
    if re.search(r"benchmark|评测|prototype|原型|demo|演示|release|发布|open weight|开放权重|持续项目", text):
        stage = max(stage, 3)
    if re.search(r"production|deployed|deployment|commercial|产品|客户|用户|收入|api|maas|规模化|量产|上线", text):
        stage = max(stage, 4)
    if re.search(r"standardized|standardisation|standardization|行业标准|标准化|广泛采用|widely adopted", text) and confidence >= 0.8:
        stage = 5
    if confidence and confidence < 0.45:
        stage = min(stage, 2)
    return stage, MATURITY_LABELS[stage]


def adoption_stage(record: dict[str, Any], maturity: int | None = None) -> str:
    maturity = maturity or infer_maturity(record)[0]
    text = " ".join(str(record.get(key, "")) for key in ("title", "trend_summary", "statement")).casefold()
    if maturity >= 4 and re.search(r"commercial|客户|用户|收入|production|规模化|量产|上线|api|maas", text):
        return "规模应用"
    if maturity >= 3:
        return "工程验证/产品导入"
    if maturity >= 2:
        return "研究原型"
    return "研究探索"


def matched_modules(category: dict[str, Any], text: str, limit: int = 3) -> list[str]:
    lowered = str(text).casefold()
    modules = [term for term in category.get("module_terms", []) if str(term).casefold() in lowered]
    if modules:
        return modules[:limit]
    return [str(value) for value in category.get("module_terms", [])[:limit]]
