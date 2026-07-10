from __future__ import annotations

import argparse
import json
from json import JSONDecodeError
import subprocess
import sys
from datetime import date, datetime
from typing import Any
from pathlib import Path


def _read_status(path: Path) -> str:
    if not path.exists():
        return "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return "unreadable"
    return str(payload.get("status", "unknown"))


def _extract_json_object(text: str) -> dict[str, Any] | None:
    end = text.rfind("}")
    if end < 0:
        return None
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload = json.loads(text[start : end + 1])
        except JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _pipeline_status_fields(summary: dict[str, Any] | None) -> dict[str, Any]:
    if not summary:
        return {"pipeline_summary_available": False}
    source_coverage = summary.get("source_coverage")
    if not isinstance(source_coverage, dict):
        source_coverage = {}
    warning_counts = _warning_counts(summary.get("warning_counts"))
    advisory_counts = _warning_counts(summary.get("advisory_counts"))
    return {
        "pipeline_summary_available": True,
        "pipeline_overall_status": str(summary.get("overall_status") or "unknown"),
        "pipeline_warnings_count": int(summary.get("warnings_count") or 0),
        "pipeline_warning_counts": warning_counts,
        "pipeline_warning_unique_count": _warning_unique_count(summary, warning_counts),
        "pipeline_warning_top_counts": _top_warning_counts(warning_counts),
        "pipeline_advisories_count": int(summary.get("advisories_count") or 0),
        "pipeline_advisory_counts": advisory_counts,
        "pipeline_advisory_unique_count": _advisory_unique_count(summary, advisory_counts),
        "pipeline_advisory_top_counts": _top_advisory_counts(advisory_counts),
        "pipeline_errors_count": int(summary.get("errors_count") or 0),
        "pipeline_blocking_gaps": list(summary.get("blocking_gaps") or []),
        "pipeline_diagnostic_codes": list(summary.get("diagnostic_codes") or []),
        "scheduler_readiness_before": summary.get("scheduler_readiness_before"),
        "scheduler_readiness_after": summary.get("scheduler_readiness_after"),
        "source_coverage_warnings": list(source_coverage.get("warnings") or []),
        "source_coverage_blocking_gaps": list(source_coverage.get("blocking_gaps") or []),
        "source_coverage_basis": source_coverage.get("source_coverage_basis"),
        "recommendation_screening_matrix_available": bool(
            source_coverage.get("recommendation_screening_matrix_available")
        ),
        "recommendation_exclusion_payload_available": bool(
            source_coverage.get("recommendation_exclusion_payload_available")
        ),
        "why_not_capture_ready": bool(source_coverage.get("why_not_capture_ready")),
        "liquidity_gate_capture_ready": bool(source_coverage.get("liquidity_gate_capture_ready")),
        "screening_matrix_capture_ready": bool(source_coverage.get("screening_matrix_capture_ready")),
    }


def _warning_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    counts: dict[str, int] = {}
    for key, raw_count in value.items():
        token = str(key).strip()
        if not token:
            continue
        try:
            count = int(raw_count)
        except (TypeError, ValueError):
            continue
        if count > 0:
            counts[token] = count
    return dict(sorted(counts.items()))


def _warning_unique_count(summary: dict[str, Any], warning_counts: dict[str, int]) -> int:
    try:
        parsed = int(summary.get("warning_unique_count"))
    except (TypeError, ValueError):
        return len(warning_counts)
    return parsed if parsed >= 0 else len(warning_counts)


def _top_warning_counts(warning_counts: dict[str, int], *, limit: int = 10) -> list[dict[str, int | str]]:
    rows = [
        {"warning": token, "count": count}
        for token, count in warning_counts.items()
        if token and count > 0
    ]
    return sorted(rows, key=lambda item: (-int(item["count"]), str(item["warning"])))[:limit]


def _advisory_unique_count(summary: dict[str, Any], advisory_counts: dict[str, int]) -> int:
    try:
        parsed = int(summary.get("advisory_unique_count"))
    except (TypeError, ValueError):
        return len(advisory_counts)
    return parsed if parsed >= 0 else len(advisory_counts)


def _top_advisory_counts(advisory_counts: dict[str, int], *, limit: int = 10) -> list[dict[str, int | str]]:
    rows = [
        {"advisory": token, "count": count}
        for token, count in advisory_counts.items()
        if token and count > 0
    ]
    return sorted(rows, key=lambda item: (-int(item["count"]), str(item["advisory"])))[:limit]


def _scheduled_status(
    *,
    return_code: int,
    freshness_status: str,
    pipeline_summary: dict[str, Any] | None,
) -> str:
    if return_code != 0 or freshness_status == "failed":
        return "failed"
    if not pipeline_summary:
        return "degraded"

    pipeline_status = str(pipeline_summary.get("overall_status") or "unknown")
    errors_count = int(pipeline_summary.get("errors_count") or 0)
    warnings_count = int(pipeline_summary.get("warnings_count") or 0)
    blocking_gaps = list(pipeline_summary.get("blocking_gaps") or [])
    if pipeline_status == "failed" or errors_count > 0:
        return "failed"
    if freshness_status == "passed" and pipeline_status == "ready_with_advisories" and not blocking_gaps:
        return "ready_with_advisories"
    if (
        freshness_status != "passed"
        or pipeline_status != "ready"
        or warnings_count > 0
        or blocking_gaps
    ):
        return "degraded"
    return "passed"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scheduled evidence pipeline dry-run wrapper.")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--sources", default="all")
    parser.add_argument("--dry-run", action="store_true", help="Required marker for scheduled dry-run mode.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.dry_run:
        raise SystemExit("scheduled evidence wrapper requires --dry-run")
    output_root = Path(args.output_root)
    run_root = output_root / "scheduled" / "evidence_pipeline_dry_run"
    report_root = run_root / "reports"
    run_root.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)

    decision_date = date.today().isoformat()
    today_key = decision_date.replace("-", "")
    status_path = run_root / "latest_status.json"
    log_path = run_root / f"{today_key}_evidence_pipeline_dry_run.log"
    report_path = report_root / f"{today_key}_evidence_pipeline_dry_run.md"
    freshness_status_path = output_root / "scheduled" / "data_freshness" / "latest_status.json"

    command = [
        sys.executable,
        "scripts/run_evidence_pipeline.py",
        "--decision-date",
        decision_date,
        "--dry-run",
        "--db-path",
        args.db_path,
        "--sources",
        args.sources,
        "--report-output",
        str(report_path),
        "--json-output",
    ]
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    log_path.write_text(completed.stdout, encoding="utf-8")
    pipeline_summary = _extract_json_object(completed.stdout)

    freshness_status = _read_status(freshness_status_path)
    status = _scheduled_status(
        return_code=completed.returncode,
        freshness_status=freshness_status,
        pipeline_summary=pipeline_summary,
    )

    payload = {
        "task": "baldr-evidence-pipeline-dry-run-daily",
        "status": status,
        "dry_run": True,
        "writes_evidence_db": False,
        "decision_date": decision_date,
        "db_path": args.db_path,
        "freshness_status": freshness_status,
        "freshness_status_path": str(freshness_status_path),
        "report_path": str(report_path),
        "log_path": str(log_path),
        "exit_code": completed.returncode,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }
    payload.update(_pipeline_status_fields(pipeline_summary))
    status_text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    stdout_text = json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2)
    status_path.write_text(status_text + "\n", encoding="utf-8")
    print(stdout_text)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
