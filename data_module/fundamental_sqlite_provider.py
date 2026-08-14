"""SQLite read providers for governed fundamental records."""

from __future__ import annotations

import csv
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Mapping, cast

from data_module.data_quality_firewall import DataQualityFirewall
from data_module.fundamental_availability_sources import (
    FundamentalAvailabilityOverride,
    load_monthly_revenue_availability_overrides_csv,
)
from data_module.fundamental_data import MonthlyRevenueRecord
from data_module.fundamental_statement_data import StatementItemRecord
from data_module.valuation_data import (
    ValuationObservationBuildResult,
    build_valuation_observations,
)
from decision_module.factors.factor_dtos import FactorQuality


class FundamentalSQLiteProvider:
    def __init__(
        self,
        db_file: Path,
        firewall: DataQualityFirewall | None = None,
        *,
        monthly_revenue_availability_file: Path | None = None,
    ):
        self.db_file = Path(db_file)
        self.firewall = firewall or DataQualityFirewall()
        self.monthly_revenue_availability_file = (
            Path(monthly_revenue_availability_file)
            if monthly_revenue_availability_file is not None
            else _default_monthly_revenue_availability_file(self.db_file)
        )
        self._monthly_revenue_mapping_signature: tuple[int, int] | None = None
        self._monthly_revenue_mapping_cache: Mapping[
            tuple[str, str], FundamentalAvailabilityOverride
        ] = {}

    def load_monthly_revenues(
        self,
        *,
        stock_code: str,
        decision_date: date,
    ) -> tuple[MonthlyRevenueRecord, ...]:
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT stock_code, period, as_of_date, announced_date, available_date,
                       revenue, source, source_version, quality
                FROM fundamental_monthly_revenues
                WHERE stock_code = ? AND available_date <= ?
                ORDER BY period ASC, source_version ASC
                """,
                (stock_code, decision_date.isoformat()),
            ).fetchall()

        formal_availability = self._load_formal_monthly_revenue_availability()
        valid_records: list[MonthlyRevenueRecord] = []
        for row in rows:
            if not _monthly_revenue_row_has_formal_availability(
                row,
                formal_availability,
            ):
                continue
            eval_res = self.firewall.evaluate_pit_availability(
                decision_date=decision_date.isoformat(),
                available_date=str(row["available_date"]) if row["available_date"] else None,
                announced_date=str(row["announced_date"]) if row["announced_date"] else None,
                require_announced_date=True,
            )
            if eval_res.is_usable:
                valid_records.append(_monthly_revenue_record(row))
        return tuple(valid_records)

    def _load_formal_monthly_revenue_availability(
        self,
    ) -> Mapping[tuple[str, str], FundamentalAvailabilityOverride]:
        """讀取可供正式線使用的月營收 availability mapping。

        mapping 缺失、無法讀取或沒有通過 v2／受限 legacy 契約時，一律回傳空集合。
        這條邊界刻意只會少讀資料，不會把 first-seen、retroactive baseline 或
        未經驗證的 SQLite row 當成正式 PIT 特徵。
        """

        try:
            stat = self.monthly_revenue_availability_file.stat()
        except OSError:
            self._monthly_revenue_mapping_signature = None
            self._monthly_revenue_mapping_cache = {}
            return self._monthly_revenue_mapping_cache

        signature = (stat.st_mtime_ns, stat.st_size)
        if signature == self._monthly_revenue_mapping_signature:
            return self._monthly_revenue_mapping_cache

        try:
            loaded = load_monthly_revenue_availability_overrides_csv(
                self.monthly_revenue_availability_file
            )
        except (OSError, UnicodeError, ValueError, csv.Error):
            self._monthly_revenue_mapping_signature = signature
            self._monthly_revenue_mapping_cache = {}
            return self._monthly_revenue_mapping_cache

        self._monthly_revenue_mapping_signature = signature
        self._monthly_revenue_mapping_cache = {
            key: override
            for key, override in loaded.overrides.items()
            if override.provenance_mode
            in {"formal_v2", "legacy_official_compatibility"}
        }
        return self._monthly_revenue_mapping_cache

    def load_valuation_observations(
        self,
        *,
        stock_code: str,
        decision_date: date,
    ) -> ValuationObservationBuildResult:
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT stock_code, as_of_date, available_date, metric_name,
                       value AS metric_value, industry, industry_percentile_bp,
                       source, source_version, quality
                FROM fundamental_valuation_metrics
                WHERE stock_code = ? AND available_date <= ?
                ORDER BY as_of_date ASC, metric_name ASC, source_version ASC
                """,
                (stock_code, decision_date.isoformat()),
            ).fetchall()

        valid_rows: list[Mapping[str, str]] = []
        for row in rows:
            eval_res = self.firewall.evaluate_pit_availability(
                decision_date=decision_date.isoformat(),
                available_date=str(row["available_date"]) if row["available_date"] else None,
            )
            if eval_res.is_usable:
                valid_rows.append(cast(Mapping[str, str], dict(row)))

        return build_valuation_observations(valid_rows)

    def load_statement_items(
        self,
        *,
        stock_code: str,
        decision_date: date,
    ) -> tuple[StatementItemRecord, ...]:
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT stock_code, statement_type, period, as_of_date, announced_date,
                       available_date, item_code, item_name, value, source,
                       source_version, quality
                FROM fundamental_statement_items
                WHERE stock_code = ? AND available_date <= ?
                ORDER BY period ASC, statement_type ASC, item_code ASC, source_version ASC
                """,
                (stock_code, decision_date.isoformat()),
            ).fetchall()

        valid_records: list[StatementItemRecord] = []
        for row in rows:
            eval_res = self.firewall.evaluate_pit_availability(
                decision_date=decision_date.isoformat(),
                available_date=str(row["available_date"]) if row["available_date"] else None,
                announced_date=str(row["announced_date"]) if row["announced_date"] else None,
                require_announced_date=False,
            )
            if eval_res.is_usable:
                valid_records.append(_statement_item_record(row))
        return tuple(valid_records)


def _monthly_revenue_record(row: sqlite3.Row) -> MonthlyRevenueRecord:
    return MonthlyRevenueRecord(
        stock_code=row["stock_code"],
        period=row["period"],
        as_of_date=_parse_date(row["as_of_date"]),
        raw_date=_parse_date(row["as_of_date"]),
        announced_date=_parse_optional_date(row["announced_date"]),
        available_date=_parse_date(row["available_date"]),
        revenue=Decimal(row["revenue"]),
        source=row["source"],
        source_version=row["source_version"],
        quality=FactorQuality(row["quality"]),
    )


def _default_monthly_revenue_availability_file(db_file: Path) -> Path:
    """推導正式資料根目錄慣例，並支援隔離測試資料庫的相鄰 meta_data。"""

    candidates = (
        db_file.parent.parent / "meta_data" / "monthly_revenue_availability.csv",
        db_file.parent / "meta_data" / "monthly_revenue_availability.csv",
    )
    return next((candidate for candidate in candidates if candidate.exists()), candidates[0])


def _monthly_revenue_row_has_formal_availability(
    row: sqlite3.Row,
    formal_availability: Mapping[tuple[str, str], FundamentalAvailabilityOverride],
) -> bool:
    """確認 SQLite row 與獨立、受治理的正式公告 mapping 完整對應。"""

    stock_code = str(row["stock_code"] or "").strip()
    period = str(row["period"] or "").strip()
    mapping = formal_availability.get((stock_code, period))
    if mapping is None:
        return False

    try:
        row_as_of_date = _parse_date(str(row["as_of_date"]))
        row_announced_date = _parse_optional_date(row["announced_date"])
        row_available_date = _parse_date(str(row["available_date"]))
    except (TypeError, ValueError):
        return False

    return (
        row_as_of_date == mapping.as_of_date
        and row_announced_date == mapping.announced_date
        and row_available_date == mapping.available_date
    )


def _statement_item_record(row: sqlite3.Row) -> StatementItemRecord:
    return StatementItemRecord(
        stock_code=row["stock_code"],
        statement_type=row["statement_type"],
        period=row["period"],
        as_of_date=_parse_date(row["as_of_date"]),
        announced_date=_parse_optional_date(row["announced_date"]),
        available_date=_parse_date(row["available_date"]),
        item_code=row["item_code"],
        item_name=row["item_name"],
        value=Decimal(row["value"]),
        source=row["source"],
        source_version=row["source_version"],
        quality=FactorQuality(row["quality"]),
    )


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_optional_date(value: str | None) -> date | None:
    if value is None or not value.strip():
        return None
    return _parse_date(value)
