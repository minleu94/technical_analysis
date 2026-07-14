from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.quarterly_statement_availability_history import (
    build_quarterly_statement_availability_history,
    write_quarterly_statement_availability_history,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build PIT quarterly statement mappings into an explicit staging root."
    )
    parser.add_argument("--statement-keys-json", type=Path, required=True)
    parser.add_argument("--evidence-json", type=Path, required=True)
    parser.add_argument("--feature-cutoff", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)

    key_rows = json.loads(args.statement_keys_json.read_text(encoding="utf-8-sig"))
    evidence_rows = json.loads(args.evidence_json.read_text(encoding="utf-8-sig"))
    statement_keys = {
        (
            str(row["stock_code"]),
            str(row["statement_type"]),
            str(row["statement_scope"]),
            str(row["period"]),
            date.fromisoformat(str(row["period_end"])),
        )
        for row in key_rows
    }
    result = build_quarterly_statement_availability_history(
        statement_keys=statement_keys,
        evidence_rows=evidence_rows,
        feature_cutoff=date.fromisoformat(args.feature_cutoff),
    )
    outputs = write_quarterly_statement_availability_history(
        result,
        output_root=args.output_root,
    )
    print(json.dumps({key: str(path) for key, path in outputs.items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
