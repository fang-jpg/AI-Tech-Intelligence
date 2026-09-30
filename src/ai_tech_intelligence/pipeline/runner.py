from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..collectors import OfficialWebCollector, SearchCollector, WebFetcher, YouTubeCollector
from ..config import Registry
from ..db import IntelligenceDB
from ..models import Candidate, Document
from ..utils import canonicalize_url, parse_date, sha256_text
from .analyze import IntelligenceAnalyzer
from .discover import build_search_queries
from .quality import is_relevant_document
from .verify import source_is_usable, verify_candidate


LOGGER = logging.getLogger(__name__)


class IntelligencePipeline:
    def __init__(self, registry: Registry, db: IntelligenceDB):
        self.registry = registry
        self.db = db
        self.db.initialize(registry)

    def collect(
        self,
        companies: list[str],
        days: int = 30,
        include_official: bool = True,
        include_search: bool = True,
        include_youtube: bool = False,
        search_provider: str = "auto",
        max_links_per_source: int = 12,
        max_search_queries: int = 3,
        max_results_per_query: int = 4,
        refresh_existing: bool = False,
        include_leads: bool = False,
    ) -> dict[str, Any]:
        run_id = self.db.start_run()
        stats: dict[str, Any] = {"candidates": 0, "fetched": 0, "inserted": 0, "updated": 0, "skipped": 0, "errors": []}
        try:
            candidates: list[Candidate] = []
            with WebFetcher(delay_seconds=float(self.registry.defaults.get("request_delay_seconds", 0.8))) as fetcher:
                if include_official:
                    official = OfficialWebCollector(fetcher)
                    for company in companies:
                        for source in self.registry.sources_for(company):
                            try:
                                candidates.extend(official.discover(source, max_links_per_source))
                            except Exception as exc:
                                stats["errors"].append(f"discover {source.id}: {type(exc).__name__}: {exc}")

                if include_search:
                    try:
                        with SearchCollector(search_provider) as search:
                            stats["search_provider"] = search.provider
                            for company in companies:
                                queries = build_search_queries(self.registry, company, max_search_queries)
                                try:
                                    candidates.extend(search.discover(company, queries, max_results_per_query))
                                except Exception as exc:
                                    stats["errors"].append(f"search {company}: {type(exc).__name__}: {exc}")
                    except Exception as exc:
                        stats["errors"].append(f"search setup: {type(exc).__name__}: {exc}")

                if include_youtube and self.registry.youtube.get("enabled"):
                    try:
                        youtube = YouTubeCollector()
                        for channel in self.registry.youtube.get("channels", []):
                            if channel.get("company") not in companies:
                                continue
                            candidates.extend(
                                youtube.discover(
                                    str(channel["company"]),
                                    str(channel["channel_id"]),
                                    str(channel.get("channel_name", "YouTube")),
                                    int(self.registry.youtube.get("max_results_per_channel", 10)),
                                    "AI model agent interview keynote",
                                )
                            )
                        youtube.close()
                    except Exception as exc:
                        stats["errors"].append(f"youtube: {type(exc).__name__}: {exc}")

                deduplicated: dict[str, Candidate] = {}
                for candidate in candidates:
                    canonical = canonicalize_url(candidate.url)
                    if canonical:
                        deduplicated.setdefault(canonical, candidate)
                candidates = list(deduplicated.values())
                stats["candidates"] = len(candidates)
                if not refresh_existing:
                    existing = self.db.existing_urls(deduplicated)
                    candidates = [candidate for candidate in candidates if canonicalize_url(candidate.url) not in existing]
                    stats["skipped"] += len(existing)

                cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
                for candidate in candidates:
                    if candidate.published_at and candidate.published_at < cutoff:
                        stats["skipped"] += 1
                        continue
                    try:
                        document = self._fetch_candidate(candidate, fetcher, include_leads=include_leads)
                        if not document:
                            stats["skipped"] += 1
                            continue
                        if document.published_at and document.published_at < cutoff:
                            stats["skipped"] += 1
                            continue
                        _, inserted = self.db.upsert_document(document)
                        stats["fetched"] += 1
                        stats["inserted" if inserted else "updated"] += 1
                    except Exception as exc:
                        stats["errors"].append(f"fetch {candidate.url}: {type(exc).__name__}: {exc}")
            self.db.finish_run(run_id, "completed", stats)
            return stats
        except Exception as exc:
            self.db.finish_run(run_id, "failed", stats, f"{type(exc).__name__}: {exc}")
            raise

    def _fetch_candidate(self, candidate: Candidate, fetcher: WebFetcher, include_leads: bool = False) -> Document | None:
        if candidate.source_type == "official_video":
            extracted = {
                "url": candidate.url,
                "title": candidate.title,
                "published_at": candidate.published_at,
                "text": candidate.snippet,
                "metadata": candidate.metadata,
            }
        else:
            extracted = fetcher.extract(candidate.url)
        text = str(extracted.get("text", "")).strip()
        if len(text) < 120:
            return None
        title = str(extracted.get("title") or candidate.title or candidate.url)
        published_at = parse_date(str(extracted.get("published_at") or candidate.published_at or ""))
        final_url = str(extracted.get("url") or candidate.url)
        verification = verify_candidate(candidate, title, text, self.registry)
        if not source_is_usable(verification, include_leads=include_leads):
            return None
        relevant, relevance_reason = is_relevant_document(candidate, title, text, self.registry)
        if not relevant:
            return None
        metadata = dict(candidate.metadata)
        metadata.update(dict(extracted.get("metadata") or {}))
        metadata["relevance_reason"] = relevance_reason
        return Document(
            company=candidate.company,
            source_id=candidate.source_id,
            source_name=candidate.source_name,
            source_type=candidate.source_type,
            url=final_url,
            canonical_url=canonicalize_url(final_url),
            title=title,
            published_at=published_at,
            text=text,
            content_hash=sha256_text(text),
            tier=verification.tier,
            official=verification.official,
            people=verification.people,
            attribution_status=verification.attribution_status,
            verification_reason=verification.reason,
            metadata=metadata,
        )

    def analyze(self, companies: list[str] | None = None, limit: int = 0, workers: int = 1) -> dict[str, Any]:
        analyzer = IntelligenceAnalyzer()
        documents = self.db.documents_for_analysis(companies, limit)
        stats: dict[str, Any] = {"pending": len(documents), "analyzed": 0, "heuristic": 0, "errors": []}
        import json

        prepared: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        timelines = {str(row["company_id"]): self.db.recent_timeline(str(row["company_id"])) for row in documents}
        for row in documents:
            document = dict(row)
            document["people_json"] = json.loads(document.get("people_json") or "[]")
            prepared.append((document, timelines[str(document["company_id"])]))

        def save_result(document: dict[str, Any], analysis: Any) -> None:
            self.db.save_analysis(analysis)
            stats["analyzed"] += 1
            if analysis.analysis_method == "heuristic_fallback":
                stats["heuristic"] += 1

        if workers <= 1:
            for document, timeline in prepared:
                try:
                    save_result(document, analyzer.analyze(document, timeline))
                except Exception as exc:
                    stats["errors"].append(f"document {document['id']}: {type(exc).__name__}: {exc}")
            stats["attribution_sanitization"] = self.db.sanitize_attributions(self.registry)
            return stats

        with ThreadPoolExecutor(max_workers=max(1, min(workers, 8)), thread_name_prefix="intel-analysis") as executor:
            future_to_document = {
                executor.submit(analyzer.analyze, document, timeline): document for document, timeline in prepared
            }
            for future in as_completed(future_to_document):
                document = future_to_document[future]
                try:
                    save_result(document, future.result())
                except Exception as exc:
                    stats["errors"].append(f"document {document['id']}: {type(exc).__name__}: {exc}")
        stats["attribution_sanitization"] = self.db.sanitize_attributions(self.registry)
        return stats
