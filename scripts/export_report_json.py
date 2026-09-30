from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_tech_intelligence.config import PROJECT_ROOT, load_registry
from ai_tech_intelligence.db import IntelligenceDB


def main() -> int:
    parser = argparse.ArgumentParser(description="Export analyzed intelligence rows as JSON for workbook authoring")
    parser.add_argument("output", type=Path)
    parser.add_argument("--database", type=Path, default=PROJECT_ROOT / "data" / "intelligence.db")
    args = parser.parse_args()
    registry = load_registry()
    with IntelligenceDB(args.database) as db:
        db.initialize(registry)
        rows = db.report_rows()
    for row in rows:
        company = registry.companies.get(str(row.get("company_id", "")))
        row["entity_type"] = company.entity_type if company else "vendor"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"rows": len(rows), "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
