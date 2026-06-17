"""Controlled quarterly statement item backfill into fundamental SQLite tables."""

from __future__ import annotations

import csv
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from data_module.fundamental_statement_availability_sources import (
    load_statement_availability_overrides_csv,
)
from data_module.fundamental_statement_data import (
    StatementItemRecord,
    parse_statement_rows,
)
from decision_module.factors.factor_dtos import FactorDiagnostic


STATEMENT_FILE_SUFFIXES = {
    "income_statement": "_income_statement.csv",
    "balance_sheet": "_balance_sheet.csv",
    "cash_flows_statement": "_cash_flows_statement.csv",
}


@dataclass(frozen=True)
class StatementItemsBackfillPlan:
    records: tuple[StatementItemRecord, ...]
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
                "# Statement Items Backfill Plan",
                "",
                f"- ready_for_apply: {str(self.ready_for_apply).lower()}",
                f"- raw_row_count: {self.raw_row_count}",
                f"- normalized_record_count: {len(self.records)}",
                f"- diagnostics: {len(self.diagnostics)}",
            ]
        )


@dataclass(frozen=True)
class StatementItemsBackfillApplyResult:
    applied: bool
    inserted_count: int
    backup_file: Path | None
    plan: StatementItemsBackfillPlan


def plan_statement_items_backfill(
    *,
    raw_dir: Path,
    availability_file: Path,
    source_version: str,
    statement_types: tuple[str, ...],
) -> StatementItemsBackfillPlan:
    availability_result = load_statement_availability_overrides_csv(Path(availability_file))
    if availability_result.diagnostics:
        return StatementItemsBackfillPlan(
            records=(),
            diagnostics=availability_result.diagnostics,
            raw_row_count=0,
        )

    records: list[StatementItemRecord] = []
    diagnostics: list[FactorDiagnostic] = []
    raw_row_count = 0
    for statement_type in statement_types:
        raw_rows = list(_iter_statement_rows(Path(raw_dir), statement_type=statement_type))
        raw_row_count += len(raw_rows)
        parse_result = parse_statement_rows(
            raw_rows,
            statement_type=statement_type,
            available_dates=availability_result.overrides,
            source_version=source_version,
        )
        records.extend(parse_result.records)
        diagnostics.extend(parse_result.diagnostics)

    return StatementItemsBackfillPlan(
        records=tuple(records),
        diagnostics=tuple(diagnostics),
        raw_row_count=raw_row_count,
    )


def apply_statement_items_backfill(
    *,
    db_file: Path,
    backup_dir: Path,
    raw_dir: Path,
    availability_file: Path,
    source_version: str,
    statement_types: tuple[str, ...],
) -> StatementItemsBackfillApplyResult:
    plan = plan_statement_items_backfill(
        raw_dir=raw_dir,
        availability_file=availability_file,
        source_version=source_version,
        statement_types=statement_types,
    )
    if not plan.ready_for_apply:
        return StatementItemsBackfillApplyResult(
            applied=False,
            inserted_count=0,
            backup_file=None,
            plan=plan,
        )

    db_file = Path(db_file)
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / f"{db_file.stem}_statement_items_backfill_{_timestamp()}{db_file.suffix}"
    shutil.copy2(db_file, backup_file)

    conn = sqlite3.connect(db_file)
    try:
        inserted_count = _insert_statement_item_records(conn, plan.records)
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

    return StatementItemsBackfillApplyResult(
        applied=True,
        inserted_count=inserted_count,
        backup_file=backup_file,
        plan=plan,
    )


def _iter_statement_rows(raw_dir: Path, *, statement_type: str) -> Iterable[dict[str, str]]:
    suffix = STATEMENT_FILE_SUFFIXES[statement_type]
    for csv_path in sorted(Path(raw_dir).glob(f"*{suffix}")):
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            yield from reader


def _insert_statement_item_records(
    conn: sqlite3.Connection,
    records: tuple[StatementItemRecord, ...],
) -> int:
    conn.executemany(
        """
        INSERT OR REPLACE INTO fundamental_statement_items(
            stock_code, statement_type, period, as_of_date, announced_date,
            available_date, item_code, item_name, value, source, source_version, quality
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                record.stock_code,
                record.statement_type,
                record.period,
                record.as_of_date.isoformat(),
                record.announced_date.isoformat() if record.announced_date else None,
                record.available_date.isoformat(),
                record.item_code,
                record.item_name,
                str(record.value),
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
