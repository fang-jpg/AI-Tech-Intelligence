from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_tech_intelligence.config import load_registry  # noqa: E402
from ai_tech_intelligence.db import IntelligenceDB  # noqa: E402
from ai_tech_intelligence.evaluation import run_evaluation  # noqa: E402


def main() -> int:
    database = ROOT / "data" / "intelligence.db"
    with IntelligenceDB(database) as db:
        db.initialize(load_registry(ROOT / "config"))
        print(json.dumps(run_evaluation(db), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

