from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Thin wrapper around the AI Tech Intelligence pipeline")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--companies", default="all")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--extra", nargs=argparse.REMAINDER, default=[])
    args = parser.parse_args()
    command = [sys.executable, str(args.project_root / "main.py"), "run", "--companies", args.companies, "--days", str(args.days), *args.extra]
    return subprocess.call(command, cwd=args.project_root)


if __name__ == "__main__":
    raise SystemExit(main())

