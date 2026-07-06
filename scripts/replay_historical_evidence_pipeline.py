from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.historical_evidence_replay import (  # noqa: E402
    HistoricalEvidenceReplayRequest,
    HistoricalEvidenceReplayReport,
    HistoricalEvidenceReplayService,
)
from data_module.config import TWStockConfig  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay historical evidence pipeline dates in a working-copy DB.")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--source-db-path", required=True)
    parser.add_argument("--replay-db-path", required=True)
    parser.add_argument("--sources", default="all")
    parser.add_argument("--windows", default="5,10,20,60")
    parser.add_argument("--group-by", default="event_type")
    parser.add_argument("--window", type=int, default=20)
    parser.add_argument("--min-sample-size", type=int, default=10)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--overwrite-replay-db", action="store_true")
    parser.add_argument("--json-output", action="store_true")
    parser.add_argument("--report-output")
    parser.add_argument("--data-root")
    parser.add_argument("--output-root")
    return parser


def _config_from_args(args: argparse.Namespace) -> TWStockConfig:
    kwargs = {}
    if args.data_root:
        kwargs["data_root"] = Path(args.data_root)
    if args.output_root:
        kwargs["output_root"] = Path(args.output_root)
    return TWStockConfig(**kwargs)


def _tuple_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in str(value or "").split(",") if item.strip())


def _windows(value: str) -> tuple[int, ...]:
    return tuple(int(item.strip()) for item in str(value or "").split(",") if item.strip())


def render_replay_report(report: HistoricalEvidenceReplayReport) -> str:
    rows = "\n".join(
        "| {date} | {result} | {events} | {created} | {pending} | {diagnostics} |".format(
            date=day.decision_date,
            result=day.selected_recommendation_result_id or "",
            events=day.events_seen,
            created=day.events_inserted,
            pending=day.outcomes_pending,
            diagnostics=", ".join(day.diagnostics),
        )
        for day in report.days
    )
    payload = report.to_dict()
    return (
        "# Historical Evidence Replay Report\n\n"
        "## Boundary\n\n"
        "- This report is historical research evidence only.\n"
        "- It does not replace real weekly history, multi-day dry-run records, or production scheduler approval.\n"
        "- Existing scheduled dry-run tasks remain separate from this replay.\n\n"
        "## Run Metadata\n\n"
        f"- replay_run_id: `{report.replay_run_id}`\n"
        f"- replay_mode: `{report.replay_mode}`\n"
        f"- source_label: `{report.source_label}`\n"
        f"- dry_run: `{str(report.dry_run).lower()}`\n"
        f"- confirm: `{str(report.confirm).lower()}`\n"
        f"- source_db_path: `{report.source_db_path}`\n"
        f"- replay_db_path: `{report.replay_db_path}`\n\n"
        "## Daily Summary\n\n"
        "| Decision date | Recommendation result | Events seen | Events inserted | Outcomes pending | Diagnostics |\n"
        "|---|---|---:|---:|---:|---|\n"
        f"{rows or '| | | 0 | 0 | 0 | |'}\n\n"
        "## JSON Summary\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)}\n```\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = _config_from_args(args)
    request = HistoricalEvidenceReplayRequest(
        start_date=args.start_date,
        end_date=args.end_date,
        source_db_path=args.source_db_path,
        replay_db_path=args.replay_db_path,
        sources=_tuple_csv(args.sources),
        windows=_windows(args.windows),
        group_by=args.group_by,
        window=args.window,
        min_sample_size=args.min_sample_size,
        limit=args.limit,
        confirm=bool(args.confirm),
        overwrite_replay_db=bool(args.overwrite_replay_db),
    )
    try:
        report = HistoricalEvidenceReplayService(config).run(request)
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 2

    if args.report_output:
        report_path = Path(args.report_output)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_replay_report(report), encoding="utf-8")

    print(json.dumps(report.to_dict(), ensure_ascii=True, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
