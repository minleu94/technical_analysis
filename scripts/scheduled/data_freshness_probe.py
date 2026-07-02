from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path


def _parse_date(value: object) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only baldr data freshness probe.")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--status-path", required=True)
    parser.add_argument("--log-path", required=True)
    parser.add_argument("--stale-days", type=int, default=7)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_root = Path(args.data_root)
    output_root = Path(args.output_root)
    db_path = Path(args.db_path)
    status_path = Path(args.status_path)
    log_path = Path(args.log_path)
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
                    age_days = (date.today() - parsed).days
                    checks[f"{table}_age_days"] = age_days
                    if age_days > args.stale_days:
                        warnings.append(f"{table}_stale")
        except Exception as exc:  # noqa: BLE001
            errors.append("sqlite_read_failed")
            checks["sqlite_error"] = str(exc)

    status = "failed" if errors else "degraded" if warnings else "passed"
    payload = {
        "task": "baldr-data-freshness-check-daily",
        "status": status,
        "read_only": True,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
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
