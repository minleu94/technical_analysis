from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.pre_v2_readiness_service import (  # noqa: E402
    PreV2ReadinessService,
    render_pre_v2_readiness_markdown,
)
from data_module.config import TWStockConfig  # noqa: E402


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect non-scheduler Pre-V2 readiness gates in read-only mode."
    )
    parser.add_argument("--db-path", help="Evidence SQLite DB path. Missing DB is reported, not created.")
    parser.add_argument("--research-db-path", help="Research Run SQLite DB path. Missing DB is reported, not created.")
    parser.add_argument("--decision-date")
    parser.add_argument("--multi-day-record-path")
    parser.add_argument("--min-weekly-records", type=int, default=3)
    parser.add_argument("--min-dry-run-days", type=int, default=3)
    parser.add_argument("--agent-report-limit", type=int, default=5)
    parser.add_argument(
        "--approved-weekly-history-projection",
        help=(
            "具名 owner 核准的 approved-weekly-history-projection.v1 路徑；"
            "未指定時沿用 WEEKLY_EVIDENCE_HISTORY_PROJECTION_PATH。"
        ),
    )
    parser.add_argument("--json-output", action="store_true", help="Emit JSON output. JSON is the default.")
    parser.add_argument("--markdown", action="store_true", help="Emit a Markdown report.")
    parser.add_argument("--report-output", help="Optional path to write the emitted JSON or Markdown report.")
    parser.add_argument("--data-root")
    parser.add_argument("--output-root")
    return parser


def _config_from_args(args: argparse.Namespace) -> TWStockConfig:
    kwargs: dict[str, Any] = {}
    if args.data_root:
        kwargs["data_root"] = Path(args.data_root)
    if args.output_root:
        kwargs["output_root"] = Path(args.output_root)
    config = TWStockConfig(**kwargs)
    if args.db_path:
        config.db_file = Path(args.db_path)
    if args.research_db_path:
        config.research_run_db_file = Path(args.research_db_path)
    return config


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = _config_from_args(args)
    service = PreV2ReadinessService(
        config,
        evidence_db_path=Path(args.db_path) if args.db_path else None,
        research_db_path=Path(args.research_db_path) if args.research_db_path else None,
        approved_weekly_history_projection_path=(
            args.approved_weekly_history_projection
            or os.environ.get("WEEKLY_EVIDENCE_HISTORY_PROJECTION_PATH")
        ),
    )
    report = service.inspect(
        decision_date=args.decision_date,
        multi_day_record_path=args.multi_day_record_path,
        min_weekly_records=args.min_weekly_records,
        min_dry_run_days=args.min_dry_run_days,
        agent_report_limit=args.agent_report_limit,
    )
    if args.markdown:
        output = render_pre_v2_readiness_markdown(report) + "\n"
    else:
        output = json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.report_output:
        Path(args.report_output).write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
