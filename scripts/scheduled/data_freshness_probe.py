from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.scheduled.scheduled_clock import scheduled_now


def _parse_date(value: object) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    return None


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _latest_date(conn: sqlite3.Connection, table: str) -> str | None:
    if not _table_exists(conn, table):
        return None
    row = conn.execute(f'SELECT MAX("日期") FROM "{table}"').fetchone()
    return str(row[0]) if row and row[0] is not None else None


def _date_key(value: object) -> str | None:
    parsed = _parse_date(value)
    if parsed is not None:
        return parsed.strftime("%Y%m%d")
    if value is None:
        return None
    text = str(value).strip().replace("-", "")
    return text if len(text) == 8 and text.isdigit() else None


def _expected_quick_update_date(today: date) -> date:
    expected = today
    while expected.weekday() >= 5:
        expected = expected.fromordinal(expected.toordinal() - 1)
    return expected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only baldr data freshness probe.")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--status-path")
    parser.add_argument("--log-path")
    parser.add_argument("--stale-days", type=int, default=7)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_root = Path(args.data_root)
    output_root = Path(args.output_root)
    db_path = Path(args.db_path)
    run_root = output_root / "scheduled" / "data_freshness"
    run_now = scheduled_now()
    run_date = run_now.date()
    today_key = run_date.isoformat().replace("-", "")
    status_path = Path(args.status_path) if args.status_path else run_root / "latest_status.json"
    log_path = Path(args.log_path) if args.log_path else run_root / f"{today_key}_data_freshness.log"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    checks: dict[str, object] = {
        "data_root_exists": data_root.exists(),
        "db_path": str(db_path),
        "db_exists": db_path.exists(),
    }
    warnings: list[str] = []
    errors: list[str] = []

    if not data_root.exists():
        errors.append("data_root_missing")
    if not db_path.exists():
        errors.append("sqlite_db_missing")

    quick_update_status_path = (
        output_root / "scheduled" / "data_update_quick" / "latest_status.json"
    )
    if not quick_update_status_path.exists():
        checks["data_update_quick_status"] = "missing"
        warnings.append("data_update_quick_status_missing")
    else:
        try:
            quick_update_payload = json.loads(
                quick_update_status_path.read_text(encoding="utf-8")
            )
            quick_update_status = str(quick_update_payload.get("status", "unknown"))
            checks["data_update_quick_status"] = quick_update_status
            if quick_update_status == "failed":
                warnings.append("data_update_quick_failed")
            checked_at = _parse_date(quick_update_payload.get("checked_at"))
            expected_date = _expected_quick_update_date(run_date)
            checks["data_update_quick_expected_date"] = expected_date.isoformat()
            checks["data_update_quick_checked_date"] = (
                checked_at.isoformat() if checked_at is not None else None
            )
            if checked_at is None or checked_at < expected_date:
                warnings.append("data_update_quick_status_stale")
        except (OSError, json.JSONDecodeError):
            warnings.append("data_update_quick_status_unreadable")

    if db_path.exists():
        try:
            uri = f"file:{db_path.as_posix()}?mode=ro"
            with sqlite3.connect(uri, uri=True) as conn:
                for table in ("daily_prices", "technical_indicators"):
                    latest = _latest_date(conn, table)
                    checks[f"{table}_latest_date"] = latest
                    parsed = _parse_date(latest)
                    if parsed is None:
                        warnings.append(f"{table}_latest_date_missing")
                        continue
                    age_days = (run_date - parsed).days
                    checks[f"{table}_age_days"] = age_days
                    if age_days > args.stale_days:
                        warnings.append(f"{table}_stale")

                daily_latest_key = _date_key(checks.get("daily_prices_latest_date"))
                if daily_latest_key:
                    twse_file = data_root / "daily_price" / f"{daily_latest_key}.csv"
                    tpex_file = data_root / "daily_price_tpex" / f"{daily_latest_key}.csv"
                    twse_exists = twse_file.exists()
                    tpex_exists = tpex_file.exists()
                    checks["daily_price_latest_date_key"] = daily_latest_key
                    checks["twse_daily_price_file"] = str(twse_file)
                    checks["tpex_daily_price_file"] = str(tpex_file)
                    checks["twse_daily_price_file_exists_for_latest_date"] = twse_exists
                    checks["tpex_daily_price_file_exists_for_latest_date"] = tpex_exists
                    if not twse_exists:
                        warnings.append(f"twse_daily_price_file_missing:{daily_latest_key}")
                    if not tpex_exists:
                        warnings.append(f"tpex_daily_price_file_missing:{daily_latest_key}")
        except Exception as exc:  # noqa: BLE001
            errors.append("sqlite_read_failed")
            checks["sqlite_error"] = str(exc)

    status = "failed" if errors else "degraded" if warnings else "passed"
    payload = {
        "task": "baldr-data-freshness-check-daily",
        "status": status,
        "read_only": True,
        "checked_at": run_now.isoformat(timespec="seconds"),
        "data_root": str(data_root),
        "output_root": str(output_root),
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
        "stale_days": args.stale_days,
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    status_path.write_text(text + "\n", encoding="utf-8")
    log_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
