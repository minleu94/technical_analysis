"""Dry-run planning for historical TPEX daily price backfill."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
from typing import Callable, Mapping, Any

from data_module.tpex_daily_price_backfill import normalize_tpex_daily_price_rows


@dataclass(frozen=True)
class TpexDailyPriceHistoryPlan:
    start_date: str
    end_date: str
    date_count: int
    source_row_count: int
    existing_count: int
    candidate_insert_count: int
    failed_dates: tuple[str, ...]
    estimated_seconds: int
    db_file: Path

    def to_markdown(self) -> str:
        return "\n".join(
            [
                "# TPEX Historical Daily Price Dry-run Plan",
                "",
                f"- start_date: {self.start_date}",
                f"- end_date: {self.end_date}",
                f"- date_count: {self.date_count}",
                f"- source_row_count: {self.source_row_count}",
                f"- existing_count: {self.existing_count}",
                f"- candidate_insert_count: {self.candidate_insert_count}",
                f"- failed_dates: {len(self.failed_dates)}",
                f"- estimated_seconds: {self.estimated_seconds}",
                f"- db_file: {self.db_file}",
            ]
        )


def build_tpex_daily_price_history_plan(
    *,
    db_file: Path,
    start_date: str,
    end_date: str,
    fetch_rows_for_date: Callable[[str], list[Mapping[str, Any]]],
    delay_seconds: int = 4,
) -> TpexDailyPriceHistoryPlan:
    db_file = Path(db_file)
    date_keys = tuple(_iter_weekday_date_keys(start_date, end_date))
    source_row_count = 0
    existing_count = 0
    candidate_insert_count = 0
    failed_dates: list[str] = []

    with sqlite3.connect(db_file) as conn:
        for date_key in date_keys:
            try:
                source_rows = fetch_rows_for_date(date_key)
                source_row_count += len(source_rows)
                normalized = normalize_tpex_daily_price_rows(
                    source_rows,
                    fallback_date=date_key,
                    strict=False,
                )
                rows_for_date = [row for row in normalized.rows if row.get("日期") == date_key]
                if not rows_for_date:
                    failed_dates.append(date_key)
                    continue
                for row in rows_for_date:
                    exists = conn.execute(
                        'SELECT 1 FROM daily_prices WHERE "證券代號" = ? AND "日期" = ? LIMIT 1',
                        (row["證券代號"], row["日期"]),
                    ).fetchone()
                    if exists:
                        existing_count += 1
                    else:
                        candidate_insert_count += 1
            except Exception:
                failed_dates.append(date_key)

    return TpexDailyPriceHistoryPlan(
        start_date=_date_key(start_date),
        end_date=_date_key(end_date),
        date_count=len(date_keys),
        source_row_count=source_row_count,
        existing_count=existing_count,
        candidate_insert_count=candidate_insert_count,
        failed_dates=tuple(failed_dates),
        estimated_seconds=max(len(date_keys) - 1, 0) * delay_seconds,
        db_file=db_file,
    )


def _iter_weekday_date_keys(start_date: str, end_date: str) -> list[str]:
    start = datetime.strptime(_date_key(start_date), "%Y%m%d")
    end = datetime.strptime(_date_key(end_date), "%Y%m%d")
    if start > end:
        raise ValueError("start_date must be <= end_date")
    values: list[str] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            values.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return values


def _date_key(value: str) -> str:
    text = str(value).strip().replace("-", "").replace("/", "")
    if len(text) == 8 and text.isdigit():
        return text
    raise ValueError(f"Unsupported date format: {value}")

