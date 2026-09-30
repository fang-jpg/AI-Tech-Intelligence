from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_tech_intelligence.collectors import WebFetcher
from ai_tech_intelligence.config import PROJECT_ROOT, load_env_file, load_registry
from ai_tech_intelligence.db import IntelligenceDB
from ai_tech_intelligence.models import Candidate, Document, SourceTier
from ai_tech_intelligence.pipeline import IntelligencePipeline
from ai_tech_intelligence.pipeline.quality import is_relevant_document
from ai_tech_intelligence.pipeline.verify import source_is_usable, verify_candidate
from ai_tech_intelligence.utils import canonicalize_url, sha256_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Import curated built-in web-search results into the intelligence database")
    parser.add_argument("input", type=Path)
    parser.add_argument("--database", type=Path, default=PROJECT_ROOT / "data" / "intelligence.db")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.txt")
    args = parser.parse_args()

    load_env_file(args.env_file)
    registry = load_registry()
    entries = json.loads(args.input.read_text(encoding="utf-8"))
    stats = {"entries": len(entries), "inserted": 0, "updated": 0, "fallback_excerpt": 0, "skipped": 0, "errors": []}

    with IntelligenceDB(args.database) as db:
        pipeline = IntelligencePipeline(registry, db)
        with WebFetcher(delay_seconds=float(registry.defaults.get("request_delay_seconds", 0.8))) as fetcher:
            for entry in entries:
                candidate = Candidate(
                    company=str(entry["company"]),
                    source_id=f"chatgpt_web_{entry['company']}",
                    source_name=str(entry["source_name"]),
                    source_type=str(entry["source_type"]),
                    url=str(entry["url"]),
                    title=str(entry.get("title", "")),
                    published_at=str(entry.get("published_at", "")) or None,
                    tier_hint=SourceTier.A,
                    official_hint=False,
                    metadata={
                        "discovery_method": "OpenAI built-in web search",
                        "discovery_run": "2026-09-21",
                        "requested_model_family": "GPT-5.6",
                    },
                )
                try:
                    document = pipeline._fetch_candidate(candidate, fetcher)
                    if not document:
                        if str(entry.get("fallback_text", "")).strip():
                            raise RuntimeError("fetched page did not yield an eligible document")
                        stats["skipped"] += 1
                        continue
                    _, inserted = db.upsert_document(document)
                    stats["inserted" if inserted else "updated"] += 1
                except Exception as exc:
                    fallback_text = str(entry.get("fallback_text", "")).strip()
                    if fallback_text:
                        verification = verify_candidate(candidate, candidate.title, fallback_text, registry)
                        relevant, relevance_reason = is_relevant_document(candidate, candidate.title, fallback_text, registry)
                        if source_is_usable(verification) and relevant:
                            document = Document(
                                company=candidate.company,
                                source_id=candidate.source_id,
                                source_name=candidate.source_name,
                                source_type=candidate.source_type,
                                url=candidate.url,
                                canonical_url=canonicalize_url(candidate.url),
                                title=candidate.title,
                                published_at=candidate.published_at,
                                text=fallback_text,
                                content_hash=sha256_text(fallback_text),
                                tier=verification.tier,
                                official=verification.official,
                                people=verification.people,
                                attribution_status=verification.attribution_status,
                                verification_reason=f"{verification.reason}; full-page fetch failed, using built-in search excerpt",
                                metadata={**candidate.metadata, "content_basis": "built-in search excerpt", "relevance_reason": relevance_reason},
                            )
                            _, inserted = db.upsert_document(document)
                            stats["inserted" if inserted else "updated"] += 1
                            stats["fallback_excerpt"] += 1
                            continue
                    stats["errors"].append(f"{entry['url']}: {type(exc).__name__}: {exc}")

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
