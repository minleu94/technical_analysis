from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.evidence_weekly_collection_repository import EvidenceWeeklyCollectionRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect V4 weekly evidence into an append-only sidecar for automatic revalidation."
    )
    parser.add_argument("--source-db-path", required=True)
    parser.add_argument("--sidecar-db-path", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--period-end")
    parser.add_argument("--json-output", action="store_true")
    return parser.parse_args()


def _period_bounds(period_end_value: str | None) -> tuple[str, str]:
    period_end = date.fromisoformat(period_end_value) if period_end_value else date.today()
    period_start = period_end - timedelta(days=period_end.weekday())
    return period_start.isoformat(), period_end.isoformat()


def _read_latest_trading_date(source_db_path: Path, *, period_end: str) -> str:
    source_uri = f"{source_db_path.resolve().as_uri()}?mode=ro"
    period_end_key = period_end.replace("-", "")
    with sqlite3.connect(source_uri, uri=True) as connection:
        connection.execute("PRAGMA query_only = ON")
        row = connection.execute(
            """
            SELECT MAX(REPLACE(日期, '-', ''))
            FROM daily_prices
            WHERE REPLACE(日期, '-', '') <= ?
            """,
            (period_end_key,),
        ).fetchone()
    if row is None or row[0] is None:
        raise ValueError(f"no daily_prices trading date on or before {period_end}")
    date_key = str(row[0])
    if len(date_key) != 8 or not date_key.isdigit():
        raise ValueError(f"unsupported daily_prices date value: {date_key}")
    return f"{date_key[:4]}-{date_key[4:6]}-{date_key[6:]}"


def _report_paths(output_root: Path, *, period_end: str) -> tuple[Path, Path]:
    report_directory = output_root / "scheduled" / "v2_2_weekly_collection"
    report_directory.mkdir(parents=True, exist_ok=True)
    suffix = period_end.replace("-", "")
    return (
        report_directory / f"v2_2_weekly_collection_{suffix}.json",
        report_directory / f"v2_2_weekly_collection_{suffix}.md",
    )


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# V2.2 Weekly Evidence Collection",
        "",
        f"- Collection status: `{payload['collection_status']}`",
        f"- Period: `{payload['period_start']}` to `{payload['period_end']}`",
        f"- Last trading date: `{payload.get('last_trading_date', '')}`",
        "- Source access: `SQLite mode=ro`",
        "- Human approval required: `false`",
        f"- Automatic revalidation: `{str(payload.get('automatic_revalidation', False)).lower()}`",
        f"- Gate credit status: `{payload.get('gate_credit_status', '')}`",
    ]
    if payload.get("error"):
        error = payload["error"]
        lines.extend(["", "## Error", "", f"- Type: `{error['type']}`", f"- Message: {error['message']}"])
    return "\n".join(lines) + "\n"


def _write_reports(output_root: Path, payload: dict[str, Any]) -> None:
    json_path, markdown_path = _report_paths(output_root, period_end=str(payload["period_end"]))
    json_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(_render_markdown(payload), encoding="utf-8")


def _base_payload(*, period_start: str, period_end: str, source_db_path: Path) -> dict[str, Any]:
    return {
        "period_start": period_start,
        "period_end": period_end,
        "source_db_path": str(source_db_path),
        "source_access": "sqlite_uri_mode_ro",
        "human_approval_required": False,
        "automatic_revalidation": True,
        "source_write_allowed": False,
        "sidecar_append_allowed": True,
        "write_intent": "append_only_sidecar_and_report",
    }


def main() -> int:
    args = parse_args()
    source_db_path = Path(args.source_db_path)
    output_root = Path(args.output_root)
    repository = EvidenceWeeklyCollectionRepository(
        source_db_path,
        sidecar_path=Path(args.sidecar_db_path),
    )
    try:
        period_start, period_end = _period_bounds(args.period_end)
    except ValueError as error:
        period_start = str(args.period_end or date.today().isoformat())
        period_end = period_start
        payload = _base_payload(
            period_start=period_start,
            period_end=period_end,
            source_db_path=source_db_path,
        )
        payload.update(
            {
                "collection_status": "collection_failed",
                "error": {"type": type(error).__name__, "message": str(error)},
            }
        )
        record = repository.save_failed(
            period_start=period_start,
            period_end=period_end,
            payload_json=payload,
            error=error,
        )
        payload["collection_record"] = record.to_dict()
        _write_reports(output_root, payload)
        if args.json_output:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            print(_render_markdown(payload), end="")
        return 1

    payload = _base_payload(
        period_start=period_start,
        period_end=period_end,
        source_db_path=source_db_path,
    )
    pending_payload: dict[str, Any] | None = None
    try:
        last_trading_date = _read_latest_trading_date(source_db_path, period_end=period_end)
        payload["last_trading_date"] = last_trading_date
        pending_payload = dict(payload)
        record = repository.save_observed(
            period_start=period_start,
            period_end=period_end,
            payload_json=pending_payload,
        )
        with sqlite3.connect(repository.sidecar_path) as connection:
            observed_week_count = int(
                connection.execute(
                    """
                    SELECT COUNT(DISTINCT period_start || '|' || period_end)
                    FROM evidence_weekly_collections
                    WHERE status = 'observed_automatic'
                      AND error_type = ''
                      AND source_hash LIKE 'sha256:%'
                    """
                ).fetchone()[0]
            )
        payload["collection_status"] = "observed_automatic"
        payload["storage_status"] = record.status
        payload["observed_week_count"] = observed_week_count
        payload["required_week_count"] = 3
        payload["gate_credit_status"] = (
            "ready_for_machine_revalidation"
            if observed_week_count >= 3
            else "insufficient_evidence"
        )
        payload["collection_record"] = record.to_dict()
        _write_reports(output_root, payload)
        exit_code = 0
    except Exception as error:
        payload["error"] = {"type": type(error).__name__, "message": str(error)}
        payload["collection_status"] = "collection_failed"
        record = repository.save_failed(
            period_start=period_start,
            period_end=period_end,
            payload_json=pending_payload if pending_payload is not None else payload,
            error=error,
        )
        payload["collection_status"] = record.status
        payload["collection_record"] = record.to_dict()
        exit_code = 1

    if args.json_output:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(_render_markdown(payload), end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
