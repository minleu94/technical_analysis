from __future__ import annotations

import argparse
from datetime import datetime
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_module.source_candidate_readiness import (
    SourceCandidateReadinessService,
    build_sample_source_candidate_report,
    render_source_candidate_markdown,
)
from data_module.config import TWStockConfig


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Read-only Phase 3C source candidate readiness dry-run for institutional, credit, and TDCC sources."
    )
    parser.add_argument("--sample", action="store_true", help="Use built-in sample rows; do not read a production DB.")
    parser.add_argument("--db-path", type=Path, help="Existing SQLite DB opened in read-only mode.")
    parser.add_argument(
        "--decision-date",
        help="Decision date boundary, YYYY-MM-DD. Defaults to the current Asia/Taipei date.",
    )
    parser.add_argument("--format", choices=("json", "markdown"), default="json", help="Output format.")
    parser.add_argument("--output", type=Path, help="Optional output path.")
    args = parser.parse_args(argv)
    decision_date = args.decision_date or datetime.now(
        ZoneInfo("Asia/Taipei")
    ).date().isoformat()

    if args.sample:
        report = build_sample_source_candidate_report(decision_date=decision_date)
    else:
        db_path = args.db_path if args.db_path is not None else TWStockConfig().db_file
        report = SourceCandidateReadinessService.from_sqlite(
            db_path,
            decision_date=decision_date,
        ).build_report()

    rendered = (
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
        if args.format == "json"
        else render_source_candidate_markdown(report)
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
