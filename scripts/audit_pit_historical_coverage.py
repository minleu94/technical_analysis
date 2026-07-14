from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.pit_historical_coverage_audit import audit_pit_historical_coverage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit PIT historical coverage read-only.")
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--audit-cutoff", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = audit_pit_historical_coverage(
        db_path=args.db_path,
        audit_cutoff=date.fromisoformat(args.audit_cutoff),
    )
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output), "database_open_mode": "read_only"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
