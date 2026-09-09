"""官方基本面現況快照；抓取時間不是歷史公告時間，不供 PIT 因子使用。"""

from __future__ import annotations

import csv
from calendar import monthrange
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import re
import sqlite3


TABLE = "fundamental_current_observations"
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    stock_code TEXT NOT NULL, kind TEXT NOT NULL, period TEXT NOT NULL,
    as_of_date TEXT NOT NULL, item_code TEXT NOT NULL, item_name TEXT NOT NULL,
    value TEXT NOT NULL, unit TEXT NOT NULL, observed_at TEXT NOT NULL,
    source TEXT NOT NULL, source_version TEXT NOT NULL, market TEXT NOT NULL,
    PRIMARY KEY(stock_code, kind, period, item_code, source_version)
);
CREATE INDEX IF NOT EXISTS idx_current_fundamental_lookup
ON {TABLE}(stock_code, kind, period DESC, observed_at DESC);
"""
COLUMNS = ("stock_code", "kind", "period", "as_of_date", "item_code", "item_name",
           "value", "unit", "observed_at", "source", "source_version", "market")


def monthly_snapshot_rows(path: Path) -> list[dict[str, str]]:
    """MOPS HTML 金額單位千元，轉成 Decimal TWD，保留每個版本。"""
    records: list[dict[str, str]] = []
    keys: set[tuple[str, str]] = set()
    # 舊 harvester fetched_at 是批次開始時間；採本次驗證時間，不能提早可見。
    verified_at = datetime.now(timezone.utc).isoformat()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            code, period = row["stock_code"], row["period"]
            if not re.fullmatch(r"\d{4,6}", code) or not re.fullmatch(r"\d{4}-\d{2}", period):
                raise ValueError("invalid monthly snapshot identity")
            year, month = map(int, period.split("-"))
            end = date(year, month, monthrange(year, month)[1])
            observed = datetime.fromisoformat(row["fetched_at"].replace("Z", "+00:00"))
            if observed.tzinfo is None or observed > datetime.now(timezone.utc):
                raise ValueError("snapshot observation must be timezone-aware and not future")
            if end > observed.date():
                raise ValueError("monthly period ends after observation")
            amount = Decimal(row["current_month_revenue"].replace(",", ""))
            if not amount.is_finite():
                raise ValueError("non-finite revenue")
            key = (code, period)
            if key in keys:
                raise ValueError(f"duplicate monthly snapshot key: {key}")
            keys.add(key)
            version = row["source_version"].strip()
            if not version or row["market"] not in {"twse", "tpex"}:
                raise ValueError("missing source version or unknown market")
            records.append(dict(zip(COLUMNS, (
                code, "monthly_revenue", period, end.isoformat(), "revenue", "月營收",
                str(amount * Decimal(1000)), "TWD", verified_at,
                row["source"], version, row["market"],
            ))))
    if not records:
        raise ValueError("empty monthly snapshot")
    return records


def insert_observations(connection: sqlite3.Connection, records: list[dict[str, str]]) -> int:
    """呼叫者負責備份與 commit；相同內容版本冪等，原始檔與 PIT 表不變。"""
    for statement in SCHEMA.split(";"):
        if statement.strip():
            connection.execute(statement)
    before = connection.total_changes
    immutable_columns = tuple(column for column in COLUMNS if column != "observed_at")
    for row in records:
        existing = connection.execute(
            f"SELECT {','.join(immutable_columns)} FROM {TABLE} WHERE stock_code=? AND kind=? AND period=? AND item_code=? AND source_version=?",
            tuple(row[column] for column in ("stock_code", "kind", "period", "item_code", "source_version")),
        ).fetchone()
        if existing is not None and tuple(existing) != tuple(row[column] for column in immutable_columns):
            raise ValueError("same source version contains conflicting observation values")
    connection.executemany(
        f"INSERT OR IGNORE INTO {TABLE} ({','.join(COLUMNS)}) VALUES ({','.join('?' for _ in COLUMNS)})",
        [tuple(row[column] for column in COLUMNS) for row in records],
    )
    return connection.total_changes - before
