"""唯讀資料新鮮度與完整性 probe。

這個 probe 是排程的觀測邊界，不會修資料、建立表或同步 SQLite。日資料的
expected period 必須先通過 ``OfficialTradingCalendar``；因此週末、國定休市日、
臨時休市或官方日曆服務不可用時，不會以工作日或 ``MAX(日期)`` 猜測市場狀態。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from datetime import date, datetime, time
from pathlib import Path
import sys
from typing import Any, Iterable
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.official_trading_calendar import (
    OfficialTradingCalendar,
    OfficialTradingCalendarError,
)
from scripts.scheduled.scheduled_clock import scheduled_now


PACIFIC = ZoneInfo("America/Los_Angeles")
DAILY_DATA_CUTOFF_LOCAL = time(4, 30)
_DATE_RE = re.compile(r"(?<!\d)(\d{8})(?!\d)")
_ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")


def _parse_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=PACIFIC)
    return parsed


def _parse_date(value: object) -> date | None:
    timestamp = _parse_timestamp(value)
    if timestamp is not None:
        return timestamp.date()
    if value is None:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text[:8], fmt).date()
        except ValueError:
            continue
    return None


def _date_key(value: object) -> str | None:
    parsed = _parse_date(value)
    if parsed is not None:
        return parsed.strftime("%Y%m%d")
    if value is None:
        return None
    text = str(value).strip().replace("-", "")
    return text if len(text) == 8 and text.isdigit() else None


def _date_from_key(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {
        str(row[1])
        for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    }


def _latest_date(conn: sqlite3.Connection, table: str) -> str | None:
    columns = _table_columns(conn, table)
    date_column = next(
        (column for column in ("日期", "trade_date", "date", "decision_date") if column in columns),
        None,
    )
    if date_column is None:
        return None
    row = conn.execute(f'SELECT MAX("{date_column}") FROM "{table}"').fetchone()
    return _date_key(row[0]) if row and row[0] is not None else None


def _db_date_summary(
    conn: sqlite3.Connection,
    table: str,
    date_key: str,
) -> dict[str, Any]:
    columns = _table_columns(conn, table)
    if not columns:
        return {
            "table_exists": False,
            "date": date_key,
            "row_count": 0,
            "distinct_code_count": None,
            "duplicate_key_count": None,
        }
    date_column = next(
        (column for column in ("日期", "trade_date", "date", "decision_date") if column in columns),
        None,
    )
    code_column = next(
        (column for column in ("證券代號", "stock_code", "stock_id", "code") if column in columns),
        None,
    )
    if date_column is None:
        return {
            "table_exists": True,
            "date": date_key,
            "row_count": 0,
            "distinct_code_count": None,
            "duplicate_key_count": None,
        }
    if code_column is None:
        row = conn.execute(
            f'SELECT COUNT(*) FROM "{table}" WHERE "{date_column}"=?',
            (date_key,),
        ).fetchone()
        return {
            "table_exists": True,
            "date": date_key,
            "row_count": int(row[0] or 0),
            "distinct_code_count": None,
            "duplicate_key_count": None,
        }
    row = conn.execute(
        f'''SELECT COUNT(*), COUNT(DISTINCT "{code_column}")
            FROM "{table}" WHERE "{date_column}"=?''',
        (date_key,),
    ).fetchone()
    row_count = int(row[0] or 0)
    distinct_count = int(row[1] or 0)
    return {
        "table_exists": True,
        "date": date_key,
        "row_count": row_count,
        "distinct_code_count": distinct_count,
        "duplicate_key_count": max(row_count - distinct_count, 0),
    }


def _db_codes_for_date(
    conn: sqlite3.Connection,
    table: str,
    date_key: str,
) -> set[str]:
    columns = _table_columns(conn, table)
    date_column = next(
        (column for column in ("日期", "trade_date", "date", "decision_date") if column in columns),
        None,
    )
    code_column = next(
        (column for column in ("證券代號", "stock_code", "stock_id", "code") if column in columns),
        None,
    )
    if date_column is None or code_column is None:
        return set()
    return {
        str(row[0]).strip()
        for row in conn.execute(
            f'SELECT DISTINCT "{code_column}" FROM "{table}" WHERE "{date_column}"=?',
            (date_key,),
        ).fetchall()
        if row[0] is not None and str(row[0]).strip()
    }


def _db_date_keys(
    conn: sqlite3.Connection,
    table: str,
    expected_keys: Iterable[str],
) -> set[str]:
    columns = _table_columns(conn, table)
    date_column = next(
        (column for column in ("日期", "trade_date", "date", "decision_date") if column in columns),
        None,
    )
    keys = tuple(expected_keys)
    if date_column is None or not keys:
        return set()
    placeholders = ",".join("?" for _ in keys)
    result: set[str] = set()
    for row in conn.execute(
        f'SELECT DISTINCT "{date_column}" FROM "{table}" WHERE "{date_column}" IN ({placeholders})',
        keys,
    ).fetchall():
        key = _date_key(row[0])
        if key is not None:
            result.add(key)
    return result


def _read_csv_summary(
    path: Path,
    *,
    expected_date_key: str | None = None,
    code_columns: tuple[str, ...] = ("證券代號", "stock_code", "code", "證券代碼"),
    date_columns: tuple[str, ...] = ("日期", "date", "trade_date", "Date"),
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "row_count": 0,
        "distinct_code_count": 0,
        "duplicate_code_count": 0,
        "invalid_code_count": 0,
        "schema_missing": [],
        "date_values": [],
        "read_error": None,
    }
    if not path.is_file():
        return summary
    codes: set[str] = set()
    date_values: set[str] = set()
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = tuple(reader.fieldnames or ())
            code_column = next((column for column in code_columns if column in fields), None)
            date_column = next((column for column in date_columns if column in fields), None)
            summary["schema_missing"] = [
                column for column in ("證券代號", "收盤價") if column not in fields
            ]
            for row in reader:
                summary["row_count"] += 1
                if code_column is not None:
                    code = str(row.get(code_column, "") or "").strip()
                    if code:
                        if code in codes:
                            summary["duplicate_code_count"] += 1
                        codes.add(code)
                    else:
                        summary["invalid_code_count"] += 1
                if date_column is not None:
                    value = _date_key(row.get(date_column))
                    if value is not None:
                        date_values.add(value)
    except (OSError, UnicodeError, csv.Error) as exc:
        summary["read_error"] = f"{type(exc).__name__}:{exc}"
        return summary
    summary["distinct_code_count"] = len(codes)
    summary["date_values"] = sorted(date_values)
    # Kept private for the in-process raw↔SQLite reconciliation; never emit a
    # full symbol set in the status artifact.
    summary["_codes"] = codes
    summary["date_mismatch"] = bool(
        expected_date_key is not None
        and date_values
        and date_values != {expected_date_key}
    )
    summary["code_sample"] = sorted(codes)[:12]
    return summary


def _file_date_key(path: Path) -> str | None:
    match = _DATE_RE.search(path.stem)
    if match:
        return match.group(1)
    iso_match = _ISO_DATE_RE.search(path.stem)
    if iso_match:
        return iso_match.group(1).replace("-", "")
    return None


def _available_file_date_keys(root: Path, *, recursive: bool = False) -> set[str]:
    if not root.is_dir():
        return set()
    iterator = root.rglob("*.csv") if recursive else root.glob("*.csv")
    return {
        key
        for path in iterator
        for key in [_file_date_key(path)]
        if key is not None
    }


def _local_now(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=PACIFIC)
    return value.astimezone(PACIFIC)


def _expected_quick_update_date(
    today: date,
    *,
    calendar: OfficialTradingCalendar | None = None,
) -> date:
    """Compatibility helper backed by the shared official calendar."""

    resolver = calendar or OfficialTradingCalendar()
    records = resolver.get_recent_official_trading_days(
        today,
        1,
        include_reference=True,
        allow_online_probe=True,
    )
    return date.fromisoformat(str(records[-1]["date_str"]))


def _coverage_bp(covered: int, eligible: int) -> int | None:
    if eligible <= 0:
        return None
    return (covered * 10000) // eligible


def _expected_latest_monthly_period(reference_date: date) -> str:
    months_back = 2 if reference_date.day < 10 else 1
    month_index = reference_date.year * 12 + reference_date.month - 1 - months_back
    year, month_zero = divmod(month_index, 12)
    return f"{year:04d}-{month_zero + 1:02d}"


def _expected_latest_statement_period(reference_date: date) -> str:
    current_quarter = (reference_date.month - 1) // 3 + 1
    index = reference_date.year * 4 + current_quarter - 2
    year, quarter_zero = divmod(index, 4)
    return f"{year:04d}-Q{quarter_zero + 1}"


def _static_file_status(
    path: Path,
    *,
    source_id: str,
    authority: str,
    update_entry: str = "static inventory observation only",
    scheduled_task: str = "not scheduled for production ingestion",
    owner: str = "Data Engineering + source owner",
    downstream: list[str] | None = None,
    candidate_only: bool = False,
) -> dict[str, Any]:
    exists = path.is_file()
    observed_at = None
    size = None
    if exists:
        try:
            stat = path.stat()
            observed_at = datetime.fromtimestamp(stat.st_mtime, tz=PACIFIC).isoformat(timespec="seconds")
            size = int(stat.st_size)
        except OSError:
            observed_at = None
    return {
        "source_id": source_id,
        "authority": authority,
        "frequency": "static/event snapshot",
        "actual_period": None,
        "published_at": None,
        "available_at": None,
        "last_successful_check_at": observed_at,
        "time_provenance": "local_observation_only; upstream_publish_time_not_recorded",
        "coverage": {"file_exists": exists, "bytes": size},
        "missing_periods": [],
        "duplicate_key_count": None,
        "freshness_status": "not_applicable" if exists else "unknown",
        "reason": "static_file_present_without_upstream_validity_window" if exists else "file_missing",
        "update_entry": update_entry,
        "scheduled_task": scheduled_task,
        "owner": owner,
        "downstream": list(downstream or []),
        "candidate_only": candidate_only,
    }


def _default_calendar_cache_path() -> Path | None:
    """Use the existing immutable official-calendar cache when available."""

    path = REPO_ROOT / "output" / "paper_execution_eod_replay" / "calendar_cache"
    return path if path.is_dir() else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only baldr data freshness probe.")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--status-path")
    parser.add_argument("--log-path")
    parser.add_argument("--stale-days", type=int, default=7)
    parser.add_argument("--calendar-cache-path")
    parser.add_argument("--temporary-closure-path")
    parser.add_argument("--calendar-window-sessions", type=int, default=10)
    return parser


def _write_artifact(path: Path, text: str, *, label: str) -> str | None:
    """Best-effort write that keeps ACL failures visible as structured output."""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        return f"{label}_artifact_write_failed:{type(exc).__name__}"
    return None


def _append_warning(warnings: list[str], value: str) -> None:
    if value not in warnings:
        warnings.append(value)


def _source_status(
    *,
    source_id: str,
    authority: str,
    frequency: str,
    actual_period: str | None,
    published_at: str | None,
    available_at: str | None,
    expected_period: str | None,
    coverage: dict[str, Any],
    missing_periods: list[str],
    duplicate_key_count: int | None,
    freshness_status: str,
    reason: str,
    update_entry: str,
    scheduled_task: str,
    owner: str,
    downstream: list[str],
    candidate_only: bool = False,
    time_provenance: str = "source_publish_or_fetch_receipt_not_recorded",
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "authority": authority,
        "frequency": frequency,
        "actual_period": actual_period,
        "published_at": published_at,
        "available_at": available_at,
        "time_provenance": time_provenance,
        "expected_period": expected_period,
        "coverage": coverage,
        "missing_periods": missing_periods,
        "duplicate_key_count": duplicate_key_count,
        "freshness_status": freshness_status,
        "reason": reason,
        "update_entry": update_entry,
        "scheduled_task": scheduled_task,
        "owner": owner,
        "downstream": downstream,
        "candidate_only": candidate_only,
    }


def _build_operational_source_statuses(
    *,
    conn: sqlite3.Connection,
    data_root: Path,
    expected_records: list[dict[str, Any]],
    quick_payload: dict[str, Any] | None,
    run_now: datetime,
    warnings: list[str],
    checks: dict[str, Any],
) -> list[dict[str, Any]]:
    expected_keys = [str(item["date_str"]).replace("-", "") for item in expected_records]
    expected_key = expected_keys[-1]
    expected_date = _date_from_key(expected_key)
    local_now = _local_now(run_now)
    after_cutoff = local_now.time() >= DAILY_DATA_CUTOFF_LOCAL
    twse_path = data_root / "daily_price" / f"{expected_key}.csv"
    tpex_path = data_root / "daily_price_tpex" / f"{expected_key}.csv"
    twse = _read_csv_summary(twse_path)
    tpex = _read_csv_summary(tpex_path, expected_date_key=expected_key)
    twse_dates = _available_file_date_keys(data_root / "daily_price")
    tpex_dates = _available_file_date_keys(data_root / "daily_price_tpex")
    twse_missing = sorted(set(expected_keys) - twse_dates)
    tpex_missing = sorted(set(expected_keys) - tpex_dates)

    quick_checked_at = None
    if quick_payload:
        quick_checked_at = _parse_timestamp(
            quick_payload.get("completed_at") or quick_payload.get("checked_at")
        )
    receipt_at = quick_checked_at.isoformat(timespec="seconds") if quick_checked_at else None
    source_statuses: list[dict[str, Any]] = []

    for source_id, authority, path, summary, missing in (
        ("twse.daily_prices.raw", "TWSE MI_INDEX / ALLBUT0999", twse_path, twse, twse_missing),
        ("tpex.daily_prices.raw", "TPEx OpenAPI daily close quotes", tpex_path, tpex, tpex_missing),
    ):
        status = "current"
        reason = "official source file matches expected official session"
        if not summary["exists"] or summary.get("read_error"):
            status = "expected_wait" if not after_cutoff else "stale"
            reason = "source file is not yet locally available" if not summary["read_error"] else "source file unreadable"
        elif summary.get("schema_missing"):
            status = "failed"
            reason = "source schema missing required fields"
        elif summary.get("date_mismatch") or summary.get("duplicate_code_count", 0) > 0:
            status = "partial"
            reason = "source file contains a date mismatch or duplicate code"
        elif missing:
            if expected_key in missing:
                status = "expected_wait" if not after_cutoff else "stale"
                reason = "target official session file is not yet locally available"
            else:
                status = "partial"
                reason = "older official session files are missing inside the bounded audit window"
        elif summary.get("row_count", 0) == 0:
            status = "failed"
            reason = "source file is present but contains no data rows"
        available_dates = (
            twse_dates
            if source_id == "twse.daily_prices.raw"
            else tpex_dates
        )
        actual_period = max(available_dates) if available_dates else None
        source_file_mtime = None
        if summary["exists"]:
            try:
                source_file_mtime = datetime.fromtimestamp(
                    path.stat().st_mtime,
                    tz=PACIFIC,
                ).isoformat(timespec="seconds")
            except OSError:
                source_file_mtime = None
        available_at = source_file_mtime or receipt_at
        source_statuses.append(
            _source_status(
                source_id=source_id,
                authority=authority,
                frequency="daily after official close/publication",
                actual_period=actual_period,
                published_at=None,
                available_at=available_at,
                expected_period=expected_key,
                coverage={
                    "row_count": int(summary.get("row_count", 0)),
                    "distinct_code_count": int(summary.get("distinct_code_count", 0)),
                    "duplicate_code_count": int(summary.get("duplicate_code_count", 0)),
                    "file_exists": bool(summary["exists"]),
                    "path": str(path),
                    "source_file_mtime": source_file_mtime,
                    "quick_update_receipt_at": receipt_at,
                },
                missing_periods=missing,
                duplicate_key_count=int(summary.get("duplicate_code_count", 0)),
                freshness_status=status,
                reason=reason,
                update_entry="UpdateService.update_daily / update_tpex_daily_price_range",
                scheduled_task="baldr-data-update-quick-daily",
                owner="Data Engineering",
                downstream=["sqlite.daily_prices", "technical_indicators", "paper/raw consumers"],
            )
        )

    daily_db = _db_date_summary(conn, "daily_prices", expected_key)
    daily_dates = _db_date_keys(conn, "daily_prices", expected_keys)
    daily_missing = sorted(set(expected_keys) - daily_dates)
    raw_rows = int(twse.get("row_count", 0)) + int(tpex.get("row_count", 0))
    raw_codes: set[str] = set()
    raw_codes.update(twse.get("_codes", set()))
    raw_codes.update(tpex.get("_codes", set()))
    db_codes = _db_codes_for_date(conn, "daily_prices", expected_key)
    code_set_comparable = bool(twse.get("exists") and tpex.get("exists"))
    db_matches_raw = (
        raw_rows > 0
        and daily_db.get("row_count") == raw_rows
        and (
            not code_set_comparable
            or (
                daily_db.get("distinct_code_count") == raw_rows
                and db_codes == raw_codes
            )
        )
    )
    if expected_key in daily_missing:
        daily_status = "expected_wait" if not after_cutoff else "stale"
        daily_reason = "target official session is not yet present in SQLite"
    elif daily_missing:
        daily_status = "partial"
        daily_reason = "SQLite daily_prices is missing older official sessions in the bounded audit window"
    elif db_matches_raw:
        daily_status = "current"
        daily_reason = "SQLite row count and code set match both official market files"
    else:
        daily_status = "partial" if raw_rows or daily_db.get("row_count") else "stale"
        daily_reason = "SQLite daily_prices does not reconcile to the bounded official raw files"
    if daily_status == "partial":
        _append_warning(warnings, "sqlite_daily_prices_raw_reconciliation_partial")
    source_statuses.append(
        _source_status(
            source_id="sqlite.daily_prices",
            authority="SQLite synchronized from TWSE + TPEx official raw files",
            frequency="daily synchronized read model",
            actual_period=_latest_date(conn, "daily_prices"),
            published_at=None,
            available_at=receipt_at,
            expected_period=expected_key,
            coverage={
                "db_row_count": int(daily_db.get("row_count", 0)),
                "db_distinct_code_count": daily_db.get("distinct_code_count"),
                "raw_row_count": raw_rows,
                "reconciles_to_raw": db_matches_raw,
                "observed_official_sessions": len(daily_dates),
                "expected_official_sessions": len(expected_keys),
            },
            missing_periods=daily_missing,
            duplicate_key_count=daily_db.get("duplicate_key_count"),
            freshness_status=daily_status,
            reason=daily_reason,
            update_entry="UpdateService.sync_source_to_sqlite('daily_price_files')",
            scheduled_task="baldr-data-update-quick-daily",
            owner="Data Engineering",
            downstream=["technical_indicators", "all SQLite-first market consumers"],
        )
    )

    for source_id, table, authority, downstream, update_entry in (
        (
            "sqlite.market_indices",
            "market_indices",
            "TWSE FMTQIK / market index CSV",
            ["market regime", "benchmark consumers"],
            "UpdateService.update_market + sync_source_to_sqlite('market_index')",
        ),
        (
            "sqlite.industry_indices",
            "industry_indices",
            "TWSE MI_INDEX industry index CSV",
            ["industry mapper", "sector rotation", "benchmark consumers"],
            "UpdateService.update_industry + sync_source_to_sqlite('industry_index')",
        ),
        (
            "sqlite.broker_flows",
            "broker_flows",
            "MoneyDJ branch daily pages / broker registry",
            ["broker flow repository", "research-only microstructure"],
            "UpdateService.update_broker_branch + sync_source_to_sqlite('broker_branch_files')",
        ),
    ):
        summary = _db_date_summary(conn, table, expected_key)
        dates = _db_date_keys(conn, table, expected_keys)
        status = "current" if summary.get("row_count", 0) > 0 else "stale"
        reason = "target official session has SQLite rows" if status == "current" else "target official session has no SQLite rows"
        missing = sorted(set(expected_keys) - dates)
        if expected_key in missing:
            status = "stale"
            reason = "target official session has no SQLite rows"
        elif missing:
            status = "partial"
            reason = "bounded official session window is incomplete"
        elif summary.get("duplicate_key_count", 0) and table != "broker_flows":
            status = "partial"
            reason = "target official session contains duplicate date/code keys"
        source_statuses.append(
            _source_status(
                source_id=source_id,
                authority=authority,
                frequency="daily official session",
                actual_period=_latest_date(conn, table),
                published_at=None,
                available_at=receipt_at,
                expected_period=expected_key,
                coverage={
                    "target_row_count": int(summary.get("row_count", 0)),
                    "target_distinct_code_count": summary.get("distinct_code_count"),
                    "observed_official_sessions": len(dates),
                    "expected_official_sessions": len(expected_keys),
                },
                missing_periods=missing,
                duplicate_key_count=summary.get("duplicate_key_count"),
                freshness_status=status,
                reason=reason,
                update_entry=update_entry,
                scheduled_task="baldr-data-update-quick-daily",
                owner="Data Engineering",
                downstream=downstream,
            )
        )

    technical = _db_date_summary(conn, "technical_indicators", expected_key)
    technical_dates = _db_date_keys(conn, "technical_indicators", expected_keys)
    technical_missing = sorted(set(expected_keys) - technical_dates)
    daily_latest = _latest_date(conn, "daily_prices")
    technical_latest = _latest_date(conn, "technical_indicators")
    eligible = 0
    covered = 0
    if _table_exists(conn, "daily_prices") and _table_exists(conn, "technical_indicators"):
        row = conn.execute(
            '''WITH latest AS (
                   SELECT MAX("日期") AS latest_date FROM daily_prices
               ), eligible AS (
                   SELECT "證券代號" AS stock_code
                   FROM daily_prices
                   GROUP BY "證券代號"
                   HAVING COUNT(*) >= 30
                      AND MAX("日期") = (SELECT latest_date FROM latest)
               ), covered AS (
                   SELECT DISTINCT "證券代號" AS stock_code
                   FROM technical_indicators
                   WHERE "日期" = (SELECT latest_date FROM latest)
               )
               SELECT (SELECT COUNT(*) FROM eligible),
                      (SELECT COUNT(*) FROM eligible e JOIN covered c ON c.stock_code=e.stock_code)'''
        ).fetchone()
        eligible = int(row[0] or 0)
        covered = int(row[1] or 0)
    technical_current = bool(
        daily_latest == expected_key
        and technical_latest == expected_key
        and daily_latest == technical_latest
        and not technical_missing
        and eligible > 0
        and covered >= eligible
    )
    technical_status = "current" if technical_current else "partial" if technical.get("row_count", 0) else "stale"
    if not technical_current:
        _append_warning(warnings, "technical_indicators_latest_coverage_partial")
    source_statuses.append(
        _source_status(
            source_id="sqlite.technical_indicators",
            authority="derived from SQLite daily_prices by UpdateService calculator",
            frequency="after each daily price update",
            actual_period=technical_latest,
            published_at=None,
            available_at=receipt_at,
            expected_period=expected_key,
            coverage={
                "target_row_count": int(technical.get("row_count", 0)),
                "eligible_stock_count": eligible,
                "covered_stock_count": covered,
                "coverage_bp": _coverage_bp(covered, eligible),
                "observed_official_sessions": len(technical_dates),
                "expected_official_sessions": len(expected_keys),
                "eligibility_excluded_count": max(
                    int(daily_db.get("distinct_code_count") or 0) - eligible,
                    0,
                ),
            },
            missing_periods=technical_missing,
            duplicate_key_count=technical.get("duplicate_key_count"),
            freshness_status=technical_status,
            reason=(
                "latest daily official session has full eligible technical coverage"
                if technical_current
                else "technical latest date or eligible-stock coverage is incomplete"
            ),
            update_entry="UpdateService.calculate_technical_indicators",
            scheduled_task="baldr-data-update-quick-daily",
            owner="Data Engineering",
            downstream=["recommendation", "decision desk", "research consumers"],
        )
    )

    revenue_latest = None
    revenue_available = None
    revenue_count = 0
    if _table_exists(conn, "fundamental_monthly_revenues"):
        row = conn.execute(
            'SELECT MAX("period"), MAX("available_date"), COUNT(*) FROM fundamental_monthly_revenues'
        ).fetchone()
        revenue_latest = str(row[0]) if row and row[0] is not None else None
        revenue_available = str(row[1]) if row and row[1] is not None else None
        revenue_count = int(row[2] or 0)
    revenue_expected = _expected_latest_monthly_period(expected_date)
    revenue_present = _table_exists(conn, "fundamental_monthly_revenues")
    revenue_status = (
        "current" if revenue_latest == revenue_expected else "stale"
        if revenue_present else "not_applicable"
    )
    if revenue_status == "stale":
        _append_warning(warnings, "monthly_revenue_expected_period_not_available")
    source_statuses.append(
        _source_status(
            source_id="fundamental.monthly_revenues",
            authority="TWSE / TPEx / MOPS announcement lanes recorded in availability map",
            frequency="monthly; normally announced by the 10th of the following month",
            actual_period=revenue_latest,
            published_at=None,
            available_at=revenue_available,
            expected_period=revenue_expected,
            coverage={"db_row_count": revenue_count},
            missing_periods=[revenue_expected] if revenue_status == "stale" else [],
            duplicate_key_count=None,
            freshness_status=revenue_status,
            reason=(
                "expected monthly period is present"
                if revenue_status == "current"
                else "candidate source table is not present in this database"
                if revenue_status == "not_applicable"
                else "expected monthly period is absent; source publication or candidate acceptance is required"
            ),
            update_entry="UpdateService.dry_run/apply MOPS monthly revenue backfill",
            scheduled_task="not in daily quick update; candidate route only",
            owner="Data Engineering + Fundamental Data owner",
            downstream=["fundamental snapshot", "valuation consumers"],
            candidate_only=True,
        )
    )

    statement_latest = None
    statement_available = None
    statement_count = 0
    if _table_exists(conn, "fundamental_statement_items"):
        row = conn.execute(
            'SELECT MAX("period"), MAX("available_date"), COUNT(*) FROM fundamental_statement_items'
        ).fetchone()
        statement_latest = str(row[0]) if row and row[0] is not None else None
        statement_available = str(row[1]) if row and row[1] is not None else None
        statement_count = int(row[2] or 0)
    statement_expected = _expected_latest_statement_period(expected_date)
    statement_present = _table_exists(conn, "fundamental_statement_items")
    statement_status = (
        "current" if statement_latest == statement_expected else "stale"
        if statement_present else "not_applicable"
    )
    if statement_status == "stale":
        _append_warning(warnings, "quarterly_statement_expected_period_not_available")
    source_statuses.append(
        _source_status(
            source_id="fundamental.quarterly_statements",
            authority="MOPS financial statement publication/document lanes",
            frequency="quarterly; latest quarter only after official publication",
            actual_period=statement_latest,
            published_at=None,
            available_at=statement_available,
            expected_period=statement_expected,
            coverage={"db_row_count": statement_count},
            missing_periods=[statement_expected] if statement_status == "stale" else [],
            duplicate_key_count=None,
            freshness_status=statement_status,
            reason=(
                "expected quarter is present"
                if statement_status == "current"
                else "candidate statement table is not present in this database"
                if statement_status == "not_applicable"
                else "statement table is behind the official quarterly publication cadence"
            ),
            update_entry="candidate MOPS statement publication acquisition",
            scheduled_task="not in daily quick update; candidate route only",
            owner="Data Engineering + Fundamental Data owner",
            downstream=["fundamental snapshot", "PIT research only"],
            candidate_only=True,
        )
    )

    checks["expected_official_session"] = expected_key
    checks["expected_official_session_window"] = expected_keys
    legacy_key = _date_key(checks.get("daily_prices_latest_date")) or expected_key
    legacy_twse_path = data_root / "daily_price" / f"{legacy_key}.csv"
    legacy_tpex_path = data_root / "daily_price_tpex" / f"{legacy_key}.csv"
    checks["twse_daily_price_file_exists_for_latest_date"] = legacy_twse_path.exists()
    checks["tpex_daily_price_file_exists_for_latest_date"] = legacy_tpex_path.exists()
    checks["twse_daily_price_file"] = str(legacy_twse_path)
    checks["tpex_daily_price_file"] = str(legacy_tpex_path)
    checks["daily_price_latest_date_key"] = legacy_key
    if not legacy_twse_path.exists():
        _append_warning(warnings, f"twse_daily_price_file_missing:{legacy_key}")
    if not legacy_tpex_path.exists():
        _append_warning(warnings, f"tpex_daily_price_file_missing:{legacy_key}")
    checks["technical_coverage"] = {
        "eligible_stock_count": eligible,
        "covered_stock_count": covered,
        "coverage_bp": _coverage_bp(covered, eligible),
    }
    return source_statuses


def _candidate_and_static_statuses(
    *,
    conn: sqlite3.Connection,
    data_root: Path,
) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    table_specs = (
        ("institutional_flows", "institutional_flows", "TWSE T86", "candidate P0 table; production ingestion disabled"),
        ("credit_transactions", "credit_transactions", "TWSE MI_MARGN", "candidate P0 table; production ingestion disabled"),
        ("tdcc_shareholding", "tdcc_shareholding", "TDCC public holdings lanes", "candidate P0 table; production ingestion disabled"),
    )
    for source_id, table, authority, reason in table_specs:
        exists = _table_exists(conn, table)
        count = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]) if exists else 0
        statuses.append(
            _source_status(
                source_id=source_id,
                authority=authority,
                frequency="daily / weekly candidate source",
                actual_period=_latest_date(conn, table) if exists else None,
                published_at=None,
                available_at=None,
                expected_period=None,
                coverage={"table_exists": exists, "db_row_count": count},
                missing_periods=[],
                duplicate_key_count=None,
                freshness_status="not_applicable",
                reason=reason,
                update_entry="P0 candidate acquisition routes",
                scheduled_task="not scheduled for production ingestion",
                owner="Data Engineering + P0 source owners",
                downstream=[],
                candidate_only=True,
            )
        )

    static_specs = (
        ("company.master_data", data_root / "meta_data" / "companies.csv", "company registry / official listing metadata"),
        ("broker.branch_registry", data_root / "meta_data" / "broker_branch_registry.csv", "broker registry and MoneyDJ route mapping"),
        ("fundamental.monthly_availability_map", data_root / "meta_data" / "monthly_revenue_availability.csv", "TWSE / TPEx / MOPS availability map"),
        ("fundamental.statement_availability_map", data_root / "meta_data" / "fundamental_statement_availability.csv", "MOPS statement availability map"),
        ("calendar.local_date_table", data_root / "meta_data" / "Date_table.csv", "local calendar artifact; not authoritative without official evidence"),
        ("legacy.aggregate_stock_snapshot", data_root / "meta_data" / "stock_data_whole.csv", "legacy aggregate; source receipt required for prod acceptance"),
        ("legacy.all_stocks_snapshot", data_root / "meta_data" / "all_stocks_data.csv", "legacy aggregate; not a daily completeness proof"),
        ("derived.industry_analysis", data_root / "industry_analysis", "derived industry analysis files"),
        ("derived.features", data_root / "features", "derived feature files"),
    )
    for source_id, path, authority in static_specs:
        if path.is_dir():
            files = list(path.rglob("*"))
            file_items = [item for item in files if item.is_file()]
            observed = max((item.stat().st_mtime for item in file_items), default=None)
            statuses.append(_source_status(
                source_id=source_id,
                authority=authority,
                frequency="derived/static",
                actual_period=None,
                published_at=None,
                available_at=(
                    datetime.fromtimestamp(observed, tz=PACIFIC).isoformat(timespec="seconds")
                    if observed is not None else None
                ),
                expected_period=None,
                coverage={
                    "directory_exists": path.is_dir(),
                    "file_count": len(file_items),
                },
                missing_periods=[],
                duplicate_key_count=None,
                freshness_status="not_applicable" if file_items else "unknown",
                reason=(
                    "derived/static source; no official release cadence registered"
                    if file_items else "directory missing or empty"
                ),
                update_entry="derived consumer-specific refresh; no daily source updater",
                scheduled_task="not scheduled by daily data update",
                owner="Downstream data owner",
                downstream=[],
            ))
        else:
            statuses.append(_static_file_status(
                path,
                source_id=source_id,
                authority=authority,
                update_entry="static registry refresh / source-specific updater",
                scheduled_task="not scheduled by daily data update",
                owner="Data Engineering + source owner",
                downstream=[],
            ))

    for source_id, authority, reason in (
        ("derivatives.futures_options", "No registered local official futures/options source", "source type is not present in configured roots, schema, or updater registry"),
        ("corporate_actions.production_table", "TWSE / TPEx corporate-action candidate routes", "only candidate/event artifacts exist; no production SQLite table is registered"),
        ("microstructure.restrictions.production_table", "TWSE restriction candidate routes", "only candidate/event artifacts exist; no production SQLite table is registered"),
    ):
        statuses.append(
            _source_status(
                source_id=source_id,
                authority=authority,
                frequency="event-driven",
                actual_period=None,
                published_at=None,
                available_at=None,
                expected_period=None,
                coverage={"present": False},
                missing_periods=[],
                duplicate_key_count=None,
                freshness_status="not_applicable",
                reason=reason,
                update_entry="candidate source registry only",
                scheduled_task="not scheduled for production ingestion",
                owner="Data Engineering + source owner",
                downstream=[],
                candidate_only=True,
            )
        )
    return statuses


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_root = Path(args.data_root)
    output_root = Path(args.output_root)
    db_path = Path(args.db_path)
    run_root = output_root / "scheduled" / "data_freshness"
    run_now = scheduled_now()
    run_date = _local_now(run_now).date()
    today_key = run_date.isoformat().replace("-", "")
    status_path = Path(args.status_path) if args.status_path else run_root / "latest_status.json"
    log_path = Path(args.log_path) if args.log_path else run_root / f"{today_key}_data_freshness.log"

    checks: dict[str, Any] = {
        "data_root_exists": data_root.exists(),
        "db_path": str(db_path),
        "db_exists": db_path.exists(),
        "calendar_cutoff_local": DAILY_DATA_CUTOFF_LOCAL.strftime("%H:%M"),
        "read_only": True,
    }
    warnings: list[str] = []
    errors: list[str] = []

    if not data_root.exists():
        errors.append("data_root_missing")
    if not db_path.exists():
        errors.append("sqlite_db_missing")

    quick_update_status_path = output_root / "scheduled" / "data_update_quick" / "latest_status.json"
    quick_payload: dict[str, Any] | None = None
    if not quick_update_status_path.exists():
        checks["data_update_quick_status"] = "missing"
        _append_warning(warnings, "data_update_quick_status_missing")
    else:
        try:
            parsed = json.loads(quick_update_status_path.read_text(encoding="utf-8"))
            quick_payload = parsed if isinstance(parsed, dict) else None
            quick_status = str((quick_payload or {}).get("status", "unknown"))
            checks["data_update_quick_status"] = quick_status
            if quick_status == "failed":
                _append_warning(warnings, "data_update_quick_failed")
            quick_checked_at = _parse_timestamp(
                (quick_payload or {}).get("completed_at") or (quick_payload or {}).get("checked_at")
            )
            checks["data_update_quick_checked_at"] = quick_checked_at.isoformat(timespec="seconds") if quick_checked_at else None
        except (OSError, json.JSONDecodeError):
            _append_warning(warnings, "data_update_quick_status_unreadable")

    source_statuses: list[dict[str, Any]] = []
    if db_path.exists():
        try:
            uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
            with sqlite3.connect(uri, uri=True) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA query_only=ON")
                checks["sqlite_journal_mode"] = str(conn.execute("PRAGMA journal_mode").fetchone()[0])
                checks["sqlite_query_only"] = int(conn.execute("PRAGMA query_only").fetchone()[0])
                for table in ("daily_prices", "technical_indicators"):
                    checks[f"{table}_latest_date"] = _latest_date(conn, table)

                calendar = OfficialTradingCalendar(
                    db_path=db_path,
                    calendar_cache_path=(
                        args.calendar_cache_path
                        or _default_calendar_cache_path()
                    ),
                    temporary_closure_path=args.temporary_closure_path,
                )
                try:
                    expected_records = calendar.get_recent_official_trading_days(
                        run_date,
                        max(1, int(args.calendar_window_sessions)),
                        include_reference=True,
                        allow_online_probe=True,
                    )
                except (OfficialTradingCalendarError, ValueError) as exc:
                    checks["official_calendar"] = {
                        "freshness_status": "failed",
                        "reason": f"{type(exc).__name__}:{exc}",
                    }
                    errors.append("official_calendar_unavailable")
                    expected_records = []
                else:
                    checks["official_calendar"] = {
                        "freshness_status": "current",
                        "source": "TWSE holidaySchedule + temporary closure evidence",
                        "records": [
                            {key: value for key, value in record.items() if key != "date"}
                            for record in expected_records
                        ],
                    }

                if expected_records:
                    expected_latest = str(expected_records[-1]["date_str"]).replace("-", "")
                    expected_date = _date_from_key(expected_latest)
                    checks["data_update_quick_expected_date"] = expected_date.isoformat()
                    quick_checked_at = _parse_timestamp(
                        (quick_payload or {}).get("completed_at") or (quick_payload or {}).get("checked_at")
                    )
                    quick_checked_date = _local_now(quick_checked_at).date() if quick_checked_at else None
                    checks["data_update_quick_checked_date"] = quick_checked_date.isoformat() if quick_checked_date else None
                    if quick_payload is not None and (
                        quick_checked_date is None or quick_checked_date < expected_date
                    ):
                        _append_warning(warnings, "data_update_quick_status_stale")
                    elif (
                        quick_checked_date == expected_date
                        and _local_now(run_now).time() < DAILY_DATA_CUTOFF_LOCAL
                    ):
                        checks["data_update_quick_waiting_for_cutoff"] = True
                    elif quick_payload and str(quick_payload.get("status")) not in {"passed", "passed_with_warnings"}:
                        _append_warning(warnings, "data_update_quick_status_not_successful")

                    source_statuses.extend(
                        _build_operational_source_statuses(
                            conn=conn,
                            data_root=data_root,
                            expected_records=expected_records,
                            quick_payload=quick_payload,
                            run_now=run_now,
                            warnings=warnings,
                            checks=checks,
                        )
                    )
                source_statuses.extend(
                    _candidate_and_static_statuses(conn=conn, data_root=data_root)
                )
        except Exception as exc:  # noqa: BLE001 - read failure must be visible
            errors.append("sqlite_read_failed")
            checks["sqlite_error"] = f"{type(exc).__name__}:{exc}"

    checks["source_statuses"] = source_statuses
    expected_key = checks.get("expected_official_session")
    for item in source_statuses:
        source_status = str(item.get("freshness_status", ""))
        if source_status not in {"stale", "partial", "failed"}:
            continue
        if item.get("candidate_only"):
            continue
        # Preserve the legacy per-file diagnostics for an old local snapshot,
        # while ensuring a current-session source problem can never result in
        # a green overall probe merely because MAX(date) exists.
        _append_warning(
            warnings,
            f"source_freshness_degraded:{item.get('source_id')}",
        )
    checks["source_status_counts"] = {
        status: sum(1 for item in source_statuses if item.get("freshness_status") == status)
        for status in sorted({str(item.get("freshness_status")) for item in source_statuses})
    }
    status = "failed" if errors else "degraded" if warnings else "passed"
    payload = {
        "task": "baldr-data-freshness-check-daily",
        "status": status,
        "read_only": True,
        "checked_at": run_now.isoformat(timespec="seconds"),
        "data_root": str(data_root),
        "output_root": str(output_root),
        "checks": checks,
        "source_statuses": source_statuses,
        "warnings": warnings,
        "errors": errors,
        "stale_days": args.stale_days,
        "status_vocabulary": ["current", "expected_wait", "stale", "failed", "partial", "not_applicable", "unknown"],
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str)
    write_errors: list[str] = []
    for label, path in (("status", status_path), ("log", log_path)):
        write_error = _write_artifact(path, text + "\n", label=label)
        if write_error is not None:
            write_errors.append(write_error)

    if write_errors:
        errors.extend(write_errors)
        payload["status"] = "failed"
        payload["errors"] = errors
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str)
        for label, path in (("status_retry", status_path), ("log_retry", log_path)):
            _write_artifact(path, text + "\n", label=label)
    print(text)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
