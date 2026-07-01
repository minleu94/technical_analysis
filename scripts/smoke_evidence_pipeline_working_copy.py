from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.evidence_pipeline_runner import EvidencePipelineRunner, write_pipeline_report
from app_module.evidence_pipeline_runner_dtos import EvidencePipelineRunRequest
from data_module.config import TWStockConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run evidence pipeline confirm smoke on a DB working copy.")
    parser.add_argument("--source-db-path", required=True)
    parser.add_argument("--working-copy-db-path", required=True)
    parser.add_argument("--decision-date", required=True)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--sources", default="all")
    parser.add_argument("--windows", default="5,10,20,60")
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--report-output")
    parser.add_argument("--json-output", action="store_true")
    parser.add_argument("--keep-working-copy", action="store_true")
    parser.add_argument("--data-root")
    parser.add_argument("--output-root")
    return parser


def _config_from_args(args: argparse.Namespace, db_path: Path) -> TWStockConfig:
    kwargs = {}
    if args.data_root:
        kwargs["data_root"] = Path(args.data_root)
    if args.output_root:
        kwargs["output_root"] = Path(args.output_root)
    config = TWStockConfig(**kwargs)
    config.db_file = db_path
    config.db_file.parent.mkdir(parents=True, exist_ok=True)
    return config


def _tuple_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in str(value or "").split(",") if item.strip())


def _windows(value: str) -> tuple[int, ...]:
    return tuple(int(item.strip()) for item in str(value or "").split(",") if item.strip())


def _production_db_path() -> Path:
    return (Path(os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data")) / "sqlite" / "twstock.db").resolve()


def _is_production_like(path: Path) -> bool:
    return path.resolve() == _production_db_path()


def _prepare_working_copy(source_db: Path, working_copy: Path) -> None:
    if source_db.resolve() == working_copy.resolve():
        raise ValueError("working-copy DB must differ from source DB")
    if _is_production_like(working_copy):
        raise ValueError("working-copy DB must not be the production DB path")
    if not source_db.exists():
        raise ValueError(f"source DB not found: {source_db}")
    if not working_copy.exists():
        working_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_db, working_copy)


def _table_count(db_path: Path, table_name: str) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone()
        if row is None:
            return 0
        return int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])


def _report_path(base: Path | None, run_number: int) -> str | None:
    if base is None:
        return None
    suffix = base.suffix or ".md"
    return str(base.with_name(f"{base.stem}_run_{run_number}{suffix}"))


def run_working_copy_smoke(args: argparse.Namespace) -> dict[str, Any]:
    source_db = Path(args.source_db_path)
    working_copy = Path(args.working_copy_db_path)
    repeat = max(2, int(args.repeat or 2))
    _prepare_working_copy(source_db, working_copy)
    config = _config_from_args(args, working_copy)
    report_base = Path(args.report_output) if args.report_output else None

    event_before = _table_count(working_copy, "evidence_events")
    outcome_before = _table_count(working_copy, "evidence_outcomes")
    run_summaries = []
    event_counts = []
    outcome_counts = []
    report_paths: list[str] = []

    for index in range(1, repeat + 1):
        per_run_report = _report_path(report_base, index)
        request = EvidencePipelineRunRequest(
            decision_date=args.decision_date,
            start_date=args.start_date,
            end_date=args.end_date,
            db_path=str(working_copy),
            sources=_tuple_csv(args.sources),
            windows=_windows(args.windows),
            dry_run=False,
            confirm=True,
            report_output=per_run_report,
        )
        summary = EvidencePipelineRunner(config, db_path=working_copy).run(request)
        run_summaries.append(summary.to_dict())
        if per_run_report:
            report_paths.append(per_run_report)
        event_counts.append(_table_count(working_copy, "evidence_events"))
        outcome_counts.append(_table_count(working_copy, "evidence_outcomes"))

    first_events = event_counts[0] if event_counts else event_before
    second_events = event_counts[1] if len(event_counts) > 1 else first_events
    first_outcomes = outcome_counts[0] if outcome_counts else outcome_before
    second_outcomes = outcome_counts[1] if len(outcome_counts) > 1 else first_outcomes
    blocking_gaps = sorted({gap for item in run_summaries for gap in item.get("blocking_gaps", [])})
    duplicate_events_detected = second_events > first_events
    idempotency_check = {
        "passed": not duplicate_events_detected and second_outcomes == first_outcomes,
        "events_stable_after_run_2": second_events == first_events,
        "outcomes_stable_after_run_2": second_outcomes == first_outcomes,
    }
    readiness = run_summaries[-1].get("scheduler_readiness_after", "not_ready") if run_summaries else "not_ready"
    payload = {
        "working_copy_db_path": str(working_copy),
        "source_db_path": str(source_db),
        "decision_date": args.decision_date,
        "repeat_count": repeat,
        "run_summaries": run_summaries,
        "idempotency_check": idempotency_check,
        "event_count_before": event_before,
        "event_count_after_run_1": first_events,
        "event_count_after_run_2": second_events,
        "duplicate_events_detected": duplicate_events_detected,
        "outcome_count_before": outcome_before,
        "outcome_count_after_run_1": first_outcomes,
        "outcome_count_after_run_2": second_outcomes,
        "readiness_after_smoke": readiness,
        "blocking_gaps": blocking_gaps,
        "report_paths": report_paths,
    }
    if report_base is not None:
        _write_smoke_report(payload, report_base)
        payload["report_paths"].append(str(report_base))
    return payload


def _write_smoke_report(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        return
    lines = [
        "# Evidence Pipeline Working-copy Smoke Report",
        "",
        "## Run Comparison",
        f"- repeat_count: {payload['repeat_count']}",
        f"- event_count_before: {payload['event_count_before']}",
        f"- event_count_after_run_1: {payload['event_count_after_run_1']}",
        f"- event_count_after_run_2: {payload['event_count_after_run_2']}",
        f"- outcome_count_before: {payload['outcome_count_before']}",
        f"- outcome_count_after_run_1: {payload['outcome_count_after_run_1']}",
        f"- outcome_count_after_run_2: {payload['outcome_count_after_run_2']}",
        f"- idempotency_passed: {payload['idempotency_check']['passed']}",
        "",
        "## Blocking Gaps",
        *(f"- {gap}" for gap in payload["blocking_gaps"]),
        "",
        "## Evidence Boundary",
        "- This report is research evidence only.",
        "- Close-to-close forward return is not executable live performance.",
        "- No trading recommendation is produced.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = run_working_copy_smoke(args)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
