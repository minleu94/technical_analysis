from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path


def _read_status(path: Path) -> str:
    if not path.exists():
        return "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return "unreadable"
    return str(payload.get("status", "unknown"))


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

    freshness_status = _read_status(freshness_status_path)
    status = "passed" if completed.returncode == 0 else "failed"
    if status == "passed" and freshness_status != "passed":
        status = "degraded"

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
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    status_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
