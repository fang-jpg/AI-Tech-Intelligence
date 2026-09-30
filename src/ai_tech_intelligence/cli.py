from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import sys
from pathlib import Path

from .collectors import available_search_providers
from .config import PROJECT_ROOT, load_env_file, load_registry
from .db import IntelligenceDB
from .evaluation import run_evaluation
from .pipeline import IntelligencePipeline
from .reports import export_reports


def _companies(value: str | None) -> list[str] | None:
    if not value or value.strip().lower() == "all":
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI 模型厂商高管技术情报流水线")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.txt")
    parser.add_argument("--config-dir", type=Path, default=PROJECT_ROOT / "config")
    parser.add_argument("--database", type=Path, default=PROJECT_ROOT / "data" / "intelligence.db")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "outputs")
    parser.add_argument("--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="初始化 SQLite 和注册表")
    subparsers.add_parser("doctor", help="检查环境与配置，不显示密钥值")
    subparsers.add_parser("list-companies", help="列出厂商、人物和来源")

    collect = subparsers.add_parser("collect", help="采集并校验来源")
    _add_collection_args(collect)

    analyze = subparsers.add_parser("analyze", help="分析尚未处理的文档")
    analyze.add_argument("--companies", default="all")
    analyze.add_argument("--limit", type=int, default=0)
    analyze.add_argument("--workers", type=int, default=1, help="并发分析数，建议 1-4")

    report = subparsers.add_parser("report", help="导出 Excel、CSV、Markdown")
    report.add_argument("--companies", default="all")
    report.add_argument("--days", type=int)

    run = subparsers.add_parser("run", help="执行采集、分析和导出")
    _add_collection_args(run)
    run.add_argument("--analysis-limit", type=int, default=0)
    run.add_argument("--workers", type=int, default=1, help="并发分析数，建议 1-4")

    subparsers.add_parser("eval", help="运行证据与去重评测")
    return parser


def _add_collection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--companies", default="all", help="逗号分隔厂商 ID，默认全部")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--search-provider", default=os.getenv("ATI_SEARCH_PROVIDER", "auto"))
    parser.add_argument("--max-links-per-source", type=int, default=12)
    parser.add_argument("--max-search-queries", type=int, default=3)
    parser.add_argument("--max-results-per-query", type=int, default=4)
    parser.add_argument("--skip-official", action="store_true")
    parser.add_argument("--skip-search", action="store_true")
    parser.add_argument("--youtube", action="store_true")
    parser.add_argument("--refresh-existing", action="store_true")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    load_env_file(args.env_file)
    try:
        registry = load_registry(args.config_dir)
        with IntelligenceDB(args.database) as db:
            pipeline = IntelligencePipeline(registry, db)
            if args.command == "init":
                print(json.dumps(db.stats(), ensure_ascii=False, indent=2))
            elif args.command == "doctor":
                print(json.dumps(_doctor(registry, db), ensure_ascii=False, indent=2))
            elif args.command == "list-companies":
                print(json.dumps(_list_companies(registry), ensure_ascii=False, indent=2))
            elif args.command == "collect":
                selected = registry.selected_companies(_companies(args.companies))
                print(json.dumps(_collect(pipeline, selected, args), ensure_ascii=False, indent=2))
            elif args.command == "analyze":
                selected = registry.selected_companies(_companies(args.companies))
                print(json.dumps(pipeline.analyze(selected, args.limit, args.workers), ensure_ascii=False, indent=2))
            elif args.command == "report":
                selected = registry.selected_companies(_companies(args.companies))
                rows = db.report_rows(selected, args.days)
                outputs = export_reports(rows, args.output_dir)
                print(json.dumps({key: str(value.resolve()) for key, value in outputs.items()}, ensure_ascii=False, indent=2))
            elif args.command == "run":
                selected = registry.selected_companies(_companies(args.companies))
                collection = _collect(pipeline, selected, args)
                analysis = pipeline.analyze(selected, args.analysis_limit, args.workers)
                outputs = export_reports(db.report_rows(selected, args.days), args.output_dir)
                print(json.dumps({"collection": collection, "analysis": analysis, "outputs": {key: str(value.resolve()) for key, value in outputs.items()}}, ensure_ascii=False, indent=2))
            elif args.command == "eval":
                print(json.dumps(run_evaluation(db), ensure_ascii=False, indent=2))
        return 0
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        logging.error("%s", exc)
        return 2


def _collect(pipeline: IntelligencePipeline, selected: list[str], args: argparse.Namespace) -> dict:
    return pipeline.collect(
        companies=selected,
        days=args.days,
        include_official=not args.skip_official,
        include_search=not args.skip_search,
        include_youtube=args.youtube,
        search_provider=args.search_provider,
        max_links_per_source=args.max_links_per_source,
        max_search_queries=args.max_search_queries,
        max_results_per_query=args.max_results_per_query,
        refresh_existing=args.refresh_existing,
    )


def _doctor(registry: object, db: IntelligenceDB) -> dict:
    from .config import Registry

    assert isinstance(registry, Registry)
    llm_models = [os.getenv(f"GENERAL_AI_REPORT_LLM_MODEL{suffix}", "") for suffix in ("", "_2", "_3", "_4")]
    return {
        "python": platform.python_version(),
        "project_root": str(PROJECT_ROOT),
        "database": str(db.path),
        "registry": {"companies": len(registry.companies), "people": len(registry.people), "sources": len(registry.sources)},
        "database_counts": db.stats(),
        "search_providers_configured": available_search_providers(),
        "llm_configured": bool((os.getenv("GENERAL_AI_REPORT_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")) and any(llm_models)),
        "youtube_configured": bool(os.getenv("YOUTUBE_API_KEY")),
        "youtube_enabled": bool(registry.youtube.get("enabled")),
    }


def _list_companies(registry: object) -> list[dict]:
    from .config import Registry

    assert isinstance(registry, Registry)
    return [
        {
            "id": company_id,
            "name": company.name,
            "people": [{"name": person.name, "role": person.role} for person in registry.people_for(company_id)],
            "sources": [{"id": source.id, "name": source.name, "url": source.url} for source in registry.sources_for(company_id)],
        }
        for company_id, company in registry.companies.items()
    ]


if __name__ == "__main__":
    raise SystemExit(main())
