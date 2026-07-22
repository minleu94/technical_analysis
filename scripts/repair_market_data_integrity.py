"""Controlled repair for invalid daily-price rows and unnamed TAIEX market-index rows.

The script defaults to dry-run.  Apply mode takes one SQLite backup, preserves all
raw CSV files, and only removes rows whose date has been verified as a TWSE
non-trading session or whose stock code is missing.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_module.config import TWStockConfig
from data_module.market_data_integrity import is_weekend_date_key, normalize_market_index_frame


CONFIRM_TOKEN = "apply-market-data-integrity-repair"
TWSE_SESSION_URL = "https://www.twse.com.tw/exchangeReport/MI_INDEX"


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _daily_columns(connection: sqlite3.Connection) -> tuple[str, str]:
    columns = [row[1] for row in connection.execute("PRAGMA table_info(daily_prices)")]
    return columns[0], columns[1]


def _official_twse_session_exists(date_key: str) -> bool:
    response = requests.get(
        TWSE_SESSION_URL,
        params={"response": "json", "date": date_key, "type": "ALLBUT0999"},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    return payload.get("stat") == "OK" and bool(payload.get("data"))


def _verified_non_trading_dates(connection: sqlite3.Connection) -> tuple[list[str], dict[str, str]]:
    date_column, _ = _daily_columns(connection)
    dates = [
        str(row[0])
        for row in connection.execute(
            f"SELECT DISTINCT {_quote(date_column)} FROM daily_prices WHERE {_quote(date_column)} IS NOT NULL"
        )
    ]
    weekend_dates = []
    for date_key in dates:
        try:
            if is_weekend_date_key(date_key):
                weekend_dates.append(date_key)
        except ValueError:
            continue
    evidence: dict[str, str] = {}
    verified = []
    for date_key in sorted(weekend_dates):
        try:
            if not _official_twse_session_exists(date_key):
                verified.append(date_key)
                evidence[date_key] = "twse_mi_index_empty"
            else:
                evidence[date_key] = "twse_mi_index_has_data"
        except requests.RequestException as exc:
            evidence[date_key] = f"twse_lookup_error:{type(exc).__name__}"
    return verified, evidence


def _build_plan(config: TWStockConfig, db_path: Path) -> dict[str, Any]:
    with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        date_column, stock_column = _daily_columns(connection)
        non_trading_dates, evidence = _verified_non_trading_dates(connection)
        placeholders = ",".join("?" for _ in non_trading_dates) or "NULL"
        weekend_rows = connection.execute(
            f"SELECT COUNT(*) FROM daily_prices WHERE {_quote(date_column)} IN ({placeholders})",
            non_trading_dates,
        ).fetchone()[0]
        null_rows = connection.execute(
            f"SELECT COUNT(*) FROM daily_prices WHERE {_quote(stock_column)} IS NULL OR TRIM(COALESCE({_quote(stock_column)}, '')) = ''"
        ).fetchone()[0]
        overlap_rows = connection.execute(
            f"SELECT COUNT(*) FROM daily_prices WHERE ({_quote(stock_column)} IS NULL OR TRIM(COALESCE({_quote(stock_column)}, '')) = '') "
            f"AND {_quote(date_column)} IN ({placeholders})",
            non_trading_dates,
        ).fetchone()[0]
    return {
        "db_path": str(db_path),
        "market_index_csv": str(config.market_index_file),
        "verified_non_trading_dates": non_trading_dates,
        "session_evidence": evidence,
        "weekend_rows_to_remove": int(weekend_rows),
        "null_or_blank_stock_rows_to_remove": int(null_rows),
        "overlap_rows": int(overlap_rows),
        "unique_daily_price_rows_to_remove": int(weekend_rows + null_rows - overlap_rows),
    }


def _backup_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"twstock_before_market_data_integrity_{datetime.now():%Y%m%d_%H%M%S}.db"
    with sqlite3.connect(db_path) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
    with sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True) as verification:
        if verification.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError(f"backup quick_check failed: {target}")
    return target


def _apply_plan(config: TWStockConfig, db_path: Path, plan: dict[str, Any]) -> Path:
    backup = _backup_database(db_path, config.sqlite_dir / "backups")
    dates = list(plan["verified_non_trading_dates"])
    with sqlite3.connect(db_path) as connection:
        date_column, stock_column = _daily_columns(connection)
        placeholders = ",".join("?" for _ in dates)
        delete_sql = (
            f"DELETE FROM daily_prices WHERE {_quote(stock_column)} IS NULL "
            f"OR TRIM(COALESCE({_quote(stock_column)}, '')) = ''"
        )
        if placeholders:
            delete_sql += f" OR {_quote(date_column)} IN ({placeholders})"
        connection.execute(delete_sql, dates)
        market_frame = pd.read_csv(config.market_index_file, encoding="utf-8-sig")
        normalized_market = normalize_market_index_frame(market_frame)
        connection.execute("DELETE FROM market_indices")
        normalized_market.to_sql("market_indices", connection, if_exists="append", index=False)
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm")
    parser.add_argument("--json-output", action="store_true")
    args = parser.parse_args()
    config = TWStockConfig()
    db_path = (args.db_path or config.db_file).resolve()
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    plan = _build_plan(config, db_path)
    result: dict[str, Any] = {"mode": "dry_run", "plan": plan, "backup_path": None}
    if args.apply:
        if args.confirm != CONFIRM_TOKEN:
            raise ValueError(f"--apply requires --confirm {CONFIRM_TOKEN}")
        if db_path != config.db_file.resolve():
            raise ValueError("apply mode only accepts the configured production DB path")
        result["backup_path"] = str(_apply_plan(config, db_path, plan))
        result["mode"] = "applied"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
