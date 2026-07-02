from __future__ import annotations

import argparse
import json
from datetime import datetime
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
    parser = argparse.ArgumentParser(description="Write scheduled wrapper latest_status.json.")
    parser.add_argument("--task", required=True)
    parser.add_argument("--status-path", required=True)
    parser.add_argument("--log-path", required=True)
    parser.add_argument("--report-path")
    parser.add_argument("--decision-date")
    parser.add_argument("--db-path")
    parser.add_argument("--source-db-path")
    parser.add_argument("--working-copy-db-path")
    parser.add_argument("--freshness-status-path")
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--mode", choices=["evidence-dry-run", "working-copy-smoke"], required=True)
    parser.add_argument("--repeat", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    status_path = Path(args.status_path)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    freshness_status = None
    if args.freshness_status_path:
        freshness_status = _read_status(Path(args.freshness_status_path))

    status = "passed" if args.exit_code == 0 else "failed"
    if args.mode == "evidence-dry-run" and status == "passed" and freshness_status != "passed":
        status = "degraded"

    payload: dict[str, object] = {
        "task": args.task,
        "status": status,
        "log_path": args.log_path,
        "exit_code": args.exit_code,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }
    if args.mode == "evidence-dry-run":
        payload.update(
            {
                "dry_run": True,
                "writes_evidence_db": False,
                "decision_date": args.decision_date,
                "db_path": args.db_path,
                "freshness_status": freshness_status,
                "freshness_status_path": args.freshness_status_path,
                "report_path": args.report_path,
            }
        )
    else:
        payload.update(
            {
                "manual_only": True,
                "writes_source_db": False,
                "writes_working_copy_db": True,
                "decision_date": args.decision_date,
                "source_db_path": args.source_db_path,
                "working_copy_db_path": args.working_copy_db_path,
                "repeat": args.repeat,
                "report_path": args.report_path,
            }
        )

    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    status_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
