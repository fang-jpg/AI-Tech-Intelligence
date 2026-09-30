from __future__ import annotations

import json
from collections import Counter
from typing import Any

from ..db import IntelligenceDB
from ..utils import normalized_for_match


def run_evaluation(db: IntelligenceDB) -> dict[str, Any]:
    rows = db.report_rows()
    analyzed = [row for row in rows if row.get("analyzed_at")]
    official_or_direct = [row for row in rows if row.get("tier") in {"A", "B"}]
    source_precision_proxy = len(official_or_direct) / len(rows) if rows else 0.0

    hashes = Counter(str(row.get("content_hash", "")) for row in rows if row.get("content_hash"))
    duplicates = sum(count - 1 for count in hashes.values() if count > 1)
    duplicate_rate = duplicates / len(rows) if rows else 0.0

    grounding_pass = sum(1 for row in analyzed if row.get("grounding_passed"))
    grounding_rate = grounding_pass / len(analyzed) if analyzed else 0.0

    attribution_total = 0
    attribution_valid = 0
    evidence_total = 0
    evidence_valid = 0
    for row in analyzed:
        text = normalized_for_match(str(row.get("text", "")))
        known_people = {str(person.get("name", "")) for person in row.get("people_json") or []}
        for statement in row.get("attributed_statements_json") or []:
            attribution_total += 1
            speaker = str(statement.get("speaker", ""))
            speaker_match = normalized_for_match(speaker)
            if any(
                normalized_for_match(person) == speaker_match
                or normalized_for_match(person) in speaker_match
                for person in known_people
            ):
                attribution_valid += 1
            evidence = normalized_for_match(str(statement.get("evidence", "")))
            if evidence:
                evidence_total += 1
                if evidence in text:
                    evidence_valid += 1
        for signal in row.get("technical_signals_json") or []:
            evidence = normalized_for_match(str(signal.get("evidence", "")))
            if evidence:
                evidence_total += 1
                if evidence in text:
                    evidence_valid += 1

    return {
        "counts": {"documents": len(rows), "analyzed": len(analyzed), "official_or_direct": len(official_or_direct)},
        "metrics": {
            "source_precision_proxy": round(source_precision_proxy, 4),
            "duplicate_rate": round(duplicate_rate, 4),
            "trend_grounding_rate": round(grounding_rate, 4),
            "speaker_attribution_accuracy": round(attribution_valid / attribution_total, 4) if attribution_total else None,
            "evidence_exact_match_rate": round(evidence_valid / evidence_total, 4) if evidence_total else None,
        },
        "notes": {
            "source_precision_proxy": "Tier A/B 占比，仅是自动化代理指标；严格 precision/recall 需要人工金标集。",
            "speaker_attribution_accuracy": "检查分析中的 speaker 是否已被正文人物匹配器识别。",
            "evidence_exact_match_rate": "检查证据短句能否在清洗后的原文中精确匹配。",
        },
    }


def evaluation_json(db: IntelligenceDB) -> str:
    return json.dumps(run_evaluation(db), ensure_ascii=False, indent=2)
