"""Controlled monthly revenue backfill into the fundamental SQLite tables."""

from __future__ import annotations

import csv
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from data_module.fundamental_availability_sources import (
    load_monthly_revenue_availability_overrides_csv,
)
from data_module.fundamental_data import (
    MonthlyRevenueRecord,
    parse_monthly_revenue_rows,
)
from decision_module.factors.factor_dtos import FactorDiagnostic

MOPS_MONTHLY_REVENUE_SNAPSHOT_SOURCE = "mops.monthly_revenue_static_snapshot"


@dataclass(frozen=True)
class MonthlyRevenueBackfillPlan:
    records: tuple[MonthlyRevenueRecord, ...]
    diagnostics: tuple[FactorDiagnostic, ...]
    raw_row_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    @property
    def ready_for_apply(self) -> bool:
        return bool(self.records) and not self.diagnostics

    def to_markdown(self) -> str:
        return "\n".join(
            [
                "# Monthly Revenue Backfill Plan",
                "",
                f"- ready_for_apply: {str(self.ready_for_apply).lower()}",
                f"- raw_row_count: {self.raw_row_count}",
                f"- normalized_record_count: {len(self.records)}",
                f"- diagnostics: {len(self.diagnostics)}",
            ]
        )


@dataclass(frozen=True)
class MonthlyRevenueBackfillApplyResult:
    applied: bool
    inserted_count: int
    backup_file: Path | None
    plan: MonthlyRevenueBackfillPlan


def plan_monthly_revenue_backfill(
    *,
    raw_dir: Path,
    availability_file: Path,
    source_version: str,
) -> MonthlyRevenueBackfillPlan:
    availability_result = load_monthly_revenue_availability_overrides_csv(
        Path(availability_file)
    )
    if availability_result.diagnostics:
        return MonthlyRevenueBackfillPlan(
            records=(),
            diagnostics=availability_result.diagnostics,
            raw_row_count=0,
        )

    raw_rows = list(_iter_monthly_revenue_rows(Path(raw_dir)))
    parse_result = parse_monthly_revenue_rows(
        raw_rows,
        available_dates=availability_result.overrides,
        source_version=source_version,
    )
    return MonthlyRevenueBackfillPlan(
        records=parse_result.records,
        diagnostics=parse_result.diagnostics,
        raw_row_count=len(raw_rows),
    )


def plan_mops_snapshot_monthly_revenue_backfill(
    *,
    snapshot_file: Path,
    availability_file: Path,
    source_version: str,
) -> MonthlyRevenueBackfillPlan:
    availability_result = load_monthly_revenue_availability_overrides_csv(
        Path(availability_file)
    )
    if availability_result.diagnostics:
        return MonthlyRevenueBackfillPlan(
            records=(),
            diagnostics=availability_result.diagnostics,
            raw_row_count=0,
        )

    raw_rows = list(
        _iter_mops_snapshot_rows(
            Path(snapshot_file),
            availability_keys=set(availability_result.overrides),
        )
    )
    parse_result = parse_monthly_revenue_rows(
        raw_rows,
        available_dates=availability_result.overrides,
        source_version=source_version,
    )
    records = tuple(
        replace(
            record,
            source=MOPS_MONTHLY_REVENUE_SNAPSHOT_SOURCE,
            source_version=source_version,
        )
        for record in parse_result.records
    )
    return MonthlyRevenueBackfillPlan(
        records=records,
        diagnostics=parse_result.diagnostics,
        raw_row_count=len(raw_rows),
    )


def apply_monthly_revenue_backfill(
    *,
    db_file: Path,
    backup_dir: Path,
    raw_dir: Path,
    availability_file: Path,
    source_version: str,
) -> MonthlyRevenueBackfillApplyResult:
    plan = plan_monthly_revenue_backfill(
        raw_dir=raw_dir,
        availability_file=availability_file,
        source_version=source_version,
    )
    if not plan.ready_for_apply:
        return MonthlyRevenueBackfillApplyResult(
            applied=False,
            inserted_count=0,
            backup_file=None,
            plan=plan,
        )

    db_file = Path(db_file)
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / f"{db_file.stem}_monthly_revenue_backfill_{_timestamp()}{db_file.suffix}"
    shutil.copy2(db_file, backup_file)

    conn = sqlite3.connect(db_file)
    try:
        inserted_count = _insert_monthly_revenue_records(conn, plan.records)
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        shutil.copy2(backup_file, db_file)
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return MonthlyRevenueBackfillApplyResult(
        applied=True,
        inserted_count=inserted_count,
        backup_file=backup_file,
        plan=plan,
    )


def apply_mops_snapshot_monthly_revenue_backfill(
    *,
    db_file: Path,
    backup_dir: Path,
    snapshot_file: Path,
    availability_file: Path,
    source_version: str,
) -> MonthlyRevenueBackfillApplyResult:
    plan = plan_mops_snapshot_monthly_revenue_backfill(
        snapshot_file=snapshot_file,
        availability_file=availability_file,
        source_version=source_version,
    )
    if not plan.ready_for_apply:
        return MonthlyRevenueBackfillApplyResult(
            applied=False,
            inserted_count=0,
            backup_file=None,
            plan=plan,
        )

    db_file = Path(db_file)
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / f"{db_file.stem}_mops_monthly_revenue_backfill_{_timestamp()}{db_file.suffix}"
    shutil.copy2(db_file, backup_file)

    conn = sqlite3.connect(db_file)
    try:
        inserted_count = _insert_monthly_revenue_records(conn, plan.records)
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        shutil.copy2(backup_file, db_file)
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return MonthlyRevenueBackfillApplyResult(
        applied=True,
        inserted_count=inserted_count,
        backup_file=backup_file,
        plan=plan,
    )


def _iter_monthly_revenue_rows(raw_dir: Path) -> Iterable[dict[str, str]]:
    for csv_path in sorted(Path(raw_dir).glob("*_monthly_revenue.csv")):
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            yield from reader


def _iter_mops_snapshot_rows(
    snapshot_file: Path,
    *,
    availability_keys: set[tuple[str, str]],
) -> Iterable[dict[str, str]]:
    with Path(snapshot_file).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            stock_code = (row.get("stock_code") or "").strip()
            period = (row.get("period") or "").strip()
            if (stock_code, period) not in availability_keys:
                continue
            year, month = period.split("-", maxsplit=1)
            yield {
                "date": _raw_date_from_period(period),
                "stock_id": stock_code,
                "country": "Taiwan",
                "revenue": (row.get("current_month_revenue") or "").strip(),
                "revenue_month": str(int(month)),
                "revenue_year": year,
            }


def _insert_monthly_revenue_records(
    conn: sqlite3.Connection,
    records: tuple[MonthlyRevenueRecord, ...],
) -> int:
    conn.executemany(
        """
        INSERT OR REPLACE INTO fundamental_monthly_revenues(
            stock_code, period, as_of_date, announced_date, available_date,
            revenue, source, source_version, quality
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                record.stock_code,
                record.period,
                record.as_of_date.isoformat(),
                record.announced_date.isoformat() if record.announced_date else None,
                record.available_date.isoformat(),
                str(record.revenue),
                record.source,
                record.source_version,
                record.quality.value,
            )
            for record in records
        ],
    )
    return len(records)


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _raw_date_from_period(period: str) -> str:
    year_text, month_text = period.split("-", maxsplit=1)
    year = int(year_text)
    month = int(month_text) + 1
    if month == 13:
        year += 1
        month = 1
    return f"{year:04d}-{month:02d}-01"
