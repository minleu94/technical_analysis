"""Controlled P/E valuation backfill into governed fundamental SQLite tables."""

from __future__ import annotations

import csv
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping

from data_module.valuation_data import calculate_industry_percentiles_bp
from decision_module.factors.factor_dtos import FactorDiagnostic, FactorQuality


@dataclass(frozen=True)
class ValuationMetricBackfillRecord:
    stock_code: str
    as_of_date: date
    available_date: date
    metric_name: str
    value: Decimal
    industry: str
    industry_percentile_bp: int | None
    source: str
    source_version: str
    quality: FactorQuality


@dataclass(frozen=True)
class ValuationMetricsBackfillPlan:
    records: tuple[ValuationMetricBackfillRecord, ...]
    diagnostics: tuple[FactorDiagnostic, ...]
    source_row_count: int
    as_of_date: date | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    @property
    def ready_for_apply(self) -> bool:
        return bool(self.records)

    def to_markdown(self) -> str:
        return "\n".join(
            [
                "# Valuation Metrics Backfill Plan",
                "",
                f"- ready_for_apply: {str(self.ready_for_apply).lower()}",
                f"- as_of_date: {self.as_of_date.isoformat() if self.as_of_date else 'none'}",
                f"- source_row_count: {self.source_row_count}",
                f"- normalized_record_count: {len(self.records)}",
                f"- diagnostics: {len(self.diagnostics)}",
            ]
        )


@dataclass(frozen=True)
class ValuationMetricsBackfillApplyResult:
    applied: bool
    inserted_count: int
    backup_file: Path | None
    plan: ValuationMetricsBackfillPlan


def load_industry_by_stock_from_companies(companies_file: Path) -> dict[str, str]:
    """Load the existing companies.csv stock-to-latest-primary-industry mapping."""
    companies_file = Path(companies_file)
    if not companies_file.exists():
        return {}

    selected: dict[str, tuple[str, str, str]] = {}
    with companies_file.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            stock_code = str(row.get("stock_id", "")).strip()
            industry = str(row.get("industry_category", "")).strip()
            if not stock_code or not industry:
                continue
            sort_key = (
                _companies_sort_date(row.get("date", "")),
                str(row.get("download_time", "")).strip(),
                industry,
            )
            if stock_code not in selected or sort_key > selected[stock_code]:
                selected[stock_code] = sort_key
    return {stock_code: industry for stock_code, (_, _, industry) in selected.items()}


def plan_valuation_metrics_backfill(
    *,
    db_file: Path,
    as_of_date: str | date | None,
    industry_by_stock: Mapping[str, str],
    source_version: str,
) -> ValuationMetricsBackfillPlan:
    db_file = Path(db_file)
    diagnostics: list[FactorDiagnostic] = []

    try:
        target_date = _resolve_as_of_date(db_file, as_of_date)
        if target_date is None:
            return ValuationMetricsBackfillPlan(
                records=(),
                diagnostics=(
                    FactorDiagnostic(
                        code="valuation_backfill.no_source_date",
                        factor_name="valuation.pe",
                        stock_code="",
                        message="daily_prices has no P/E source date available",
                    ),
                ),
                source_row_count=0,
                as_of_date=None,
            )
        source_rows = _load_daily_pe_rows(db_file, target_date)
    except sqlite3.Error as exc:
        return ValuationMetricsBackfillPlan(
            records=(),
            diagnostics=(
                    FactorDiagnostic(
                        code="valuation_backfill.source_query_failed",
                        factor_name="valuation.pe",
                        stock_code="",
                        message=str(exc),
                    ),
            ),
            source_row_count=0,
            as_of_date=None,
        )

    if not source_rows:
        return ValuationMetricsBackfillPlan(
            records=(),
            diagnostics=(
                    FactorDiagnostic(
                        code="valuation_backfill.no_source_rows",
                        factor_name="valuation.pe",
                        stock_code="",
                        message=f"daily_prices has no P/E rows for {target_date.isoformat()}",
                    ),
            ),
            source_row_count=0,
            as_of_date=target_date,
        )

    percentile_inputs: list[dict[str, object]] = []
    for stock_code, pe_value in source_rows:
        industry = str(industry_by_stock.get(stock_code, "")).strip()
        if not industry:
            diagnostics.append(
                FactorDiagnostic(
                    code="valuation_backfill.missing_industry",
                    factor_name="valuation.pe",
                    stock_code=stock_code,
                    message="stock has P/E source row but no companies.csv industry mapping",
                )
            )
            continue
        try:
            metric_value = Decimal(str(pe_value))
        except InvalidOperation:
            diagnostics.append(
                FactorDiagnostic(
                    code="valuation_backfill.invalid_pe",
                    factor_name="valuation.pe",
                    stock_code=stock_code,
                    message="daily_prices P/E value is not numeric",
                )
            )
            continue
        if metric_value <= 0:
            diagnostics.append(
                FactorDiagnostic(
                    code="valuation_backfill.invalid_pe",
                    factor_name="valuation.pe",
                    stock_code=stock_code,
                    message="daily_prices P/E value must be positive",
                )
            )
            continue
        percentile_inputs.append(
            {
                "stock_code": stock_code,
                "industry": industry,
                "metric_value": metric_value,
            }
        )

    percentiles = calculate_industry_percentiles_bp(percentile_inputs)
    records = [
        ValuationMetricBackfillRecord(
            stock_code=str(row["stock_code"]),
            as_of_date=target_date,
            available_date=target_date,
            metric_name="pe",
            value=row["metric_value"],
            industry=str(row["industry"]),
            industry_percentile_bp=percentiles[(str(row["stock_code"]), str(row["industry"]))],
            source="daily_prices.pe",
            source_version=source_version,
            quality=(
                FactorQuality.OBSERVED
                if percentiles[(str(row["stock_code"]), str(row["industry"]))] is not None
                else FactorQuality.DEGRADED
            ),
        )
        for row in percentile_inputs
    ]

    return ValuationMetricsBackfillPlan(
        records=tuple(records),
        diagnostics=tuple(diagnostics),
        source_row_count=len(source_rows),
        as_of_date=target_date,
    )


def apply_valuation_metrics_backfill(
    *,
    db_file: Path,
    backup_dir: Path,
    as_of_date: str | date | None,
    industry_by_stock: Mapping[str, str],
    source_version: str,
) -> ValuationMetricsBackfillApplyResult:
    plan = plan_valuation_metrics_backfill(
        db_file=db_file,
        as_of_date=as_of_date,
        industry_by_stock=industry_by_stock,
        source_version=source_version,
    )
    if not plan.ready_for_apply:
        return ValuationMetricsBackfillApplyResult(
            applied=False,
            inserted_count=0,
            backup_file=None,
            plan=plan,
        )

    db_file = Path(db_file)
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / f"{db_file.stem}_valuation_metrics_backfill_{_timestamp()}{db_file.suffix}"
    shutil.copy2(db_file, backup_file)

    conn = sqlite3.connect(db_file)
    try:
        inserted_count = _insert_valuation_metric_records(conn, plan.records)
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

    return ValuationMetricsBackfillApplyResult(
        applied=True,
        inserted_count=inserted_count,
        backup_file=backup_file,
        plan=plan,
    )


def _resolve_as_of_date(db_file: Path, as_of_date: str | date | None) -> date | None:
    if isinstance(as_of_date, date):
        return as_of_date
    if isinstance(as_of_date, str) and as_of_date.strip():
        return _parse_date(as_of_date)

    with sqlite3.connect(db_file) as conn:
        row = conn.execute(
            'SELECT MAX("日期") FROM daily_prices WHERE "本益比" IS NOT NULL'
        ).fetchone()
    if row is None or row[0] is None:
        return None
    return _parse_date(str(row[0]))


def _load_daily_pe_rows(db_file: Path, target_date: date) -> list[tuple[str, object]]:
    db_date = target_date.strftime("%Y%m%d")
    with sqlite3.connect(db_file) as conn:
        rows = conn.execute(
            """
            SELECT "證券代號", "本益比"
            FROM daily_prices
            WHERE "日期" = ? AND "本益比" IS NOT NULL
            ORDER BY "證券代號"
            """,
            (db_date,),
        ).fetchall()
    return [(str(stock_code).strip(), pe_value) for stock_code, pe_value in rows]


def _insert_valuation_metric_records(
    conn: sqlite3.Connection,
    records: tuple[ValuationMetricBackfillRecord, ...],
) -> int:
    conn.executemany(
        """
        INSERT OR REPLACE INTO fundamental_valuation_metrics(
            stock_code, as_of_date, available_date, metric_name, value,
            industry, industry_percentile_bp, source, source_version, quality
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                record.stock_code,
                record.as_of_date.isoformat(),
                record.available_date.isoformat(),
                record.metric_name,
                str(record.value),
                record.industry,
                record.industry_percentile_bp,
                record.source,
                record.source_version,
                record.quality.value,
            )
            for record in records
        ],
    )
    return len(records)


def _parse_date(value: str) -> date:
    value = value.strip()
    if len(value) == 8 and value.isdigit():
        return datetime.strptime(value, "%Y%m%d").date()
    return datetime.strptime(value, "%Y-%m-%d").date()


def _companies_sort_date(value: str) -> str:
    value = str(value).strip()
    if not value:
        return ""
    if len(value) == 8 and value.isdigit():
        return value
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError:
        return value


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")
