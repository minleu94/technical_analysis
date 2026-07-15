from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.corporate_action_availability_history import (
    build_corporate_action_availability_history,
    write_corporate_action_availability_history,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build corporate PIT timeline in staging.")
    parser.add_argument("--evidence-json", type=Path, required=True)
    parser.add_argument("--coverage-json", type=Path, required=True)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    result = build_corporate_action_availability_history(
        evidence_rows=json.loads(args.evidence_json.read_text(encoding="utf-8-sig")),
        coverage_rows=json.loads(args.coverage_json.read_text(encoding="utf-8-sig")),
        as_of_date=date.fromisoformat(args.as_of_date),
    )
    outputs = write_corporate_action_availability_history(
        result,
        output_root=args.output_root,
        forbidden_roots=(Path(os.environ["DATA_ROOT"]),) if os.environ.get("DATA_ROOT") else (),
    )
    print(json.dumps({key: str(path) for key, path in outputs.items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
