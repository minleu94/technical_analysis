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
        self._monthly_revenue_mapping_history_cache: Mapping[
            tuple[str, str],
            tuple[FundamentalAvailabilityOverride, ...],
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

        formal_availability_history = (
            self._load_formal_monthly_revenue_availability_history()
        )
        latest_by_period: dict[str, sqlite3.Row] = {}
        ambiguous_periods: set[str] = set()
        for row in rows:
            mapping_history = formal_availability_history.get(
                (str(row["stock_code"] or "").strip(), str(row["period"] or "").strip()),
                (),
            )
            if not any(
                _monthly_revenue_row_matches_formal_availability(row, mapping)
                for mapping in mapping_history
            ):
                continue
            eval_res = self.firewall.evaluate_pit_availability(
                decision_date=decision_date.isoformat(),
                available_date=str(row["available_date"]) if row["available_date"] else None,
                announced_date=str(row["announced_date"]) if row["announced_date"] else None,
                require_announced_date=True,
            )
            if eval_res.is_usable:
                period = str(row["period"])
                if period in ambiguous_periods:
                    continue
                previous = latest_by_period.get(period)
                if previous is None:
                    latest_by_period[period] = row
                    continue
                current_available = _monthly_revenue_row_available_date(row)
                previous_available = _monthly_revenue_row_available_date(previous)
                if current_available > previous_available:
                    latest_by_period[period] = row
                elif current_available == previous_available:
                    if _monthly_revenue_row_content_fingerprint(
                        row
                    ) == _monthly_revenue_row_content_fingerprint(previous):
                        # 同一可用日的同內容重抓只保留一列；source_version
                        # 是 lineage，不作內容優先序，採固定字典序讓插入順序
                        # 不影響結果。
                        if str(row["source_version"]) < str(previous["source_version"]):
                            latest_by_period[period] = row
                    else:
                        # 同一可用日的不同內容沒有序時證據，不能以 hash 或字串
                        # 任選一版，否則回測結果會隨插入順序改變。
                        ambiguous_periods.add(period)
                        latest_by_period.pop(period, None)
        return tuple(
            _monthly_revenue_record(latest_by_period[period])
            for period in sorted(latest_by_period)
            if period not in ambiguous_periods
        )

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
            self._monthly_revenue_mapping_history_cache = {}
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
            self._monthly_revenue_mapping_history_cache = {}
            return self._monthly_revenue_mapping_cache

        self._monthly_revenue_mapping_signature = signature
        self._monthly_revenue_mapping_cache = {
            key: override
            for key, override in loaded.overrides.items()
            if override.provenance_mode
            in {"formal_v2", "legacy_official_compatibility"}
        }
        self._monthly_revenue_mapping_history_cache = {
            key: tuple(
                override
                for override in loaded.revision_history.get(key, ())
                if override.provenance_mode
                in {"formal_v2", "legacy_official_compatibility"}
            )
            for key in self._monthly_revenue_mapping_cache
        }
        for key, override in self._monthly_revenue_mapping_cache.items():
            if not self._monthly_revenue_mapping_history_cache.get(key):
                self._monthly_revenue_mapping_history_cache[key] = (override,)
        return self._monthly_revenue_mapping_cache

    def _load_formal_monthly_revenue_availability_history(
        self,
    ) -> Mapping[
        tuple[str, str],
        tuple[FundamentalAvailabilityOverride, ...],
    ]:
        """讀取完整 revision chain，讓歷史 decision 仍能看到舊 mapping。"""

        self._load_formal_monthly_revenue_availability()
        return self._monthly_revenue_mapping_history_cache

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
            sidecar_columns = {
                str(info[1])
                for info in conn.execute(
                    "PRAGMA table_info(mops_statement_consumer_metadata)"
                ).fetchall()
            }
            if sidecar_columns:
                sidecar_select = _statement_sidecar_select(sidecar_columns)
                rows = conn.execute(
                    f"""
                    SELECT f.stock_code, f.statement_type, f.period, f.as_of_date,
                           f.announced_date, f.available_date, f.item_code,
                           f.item_name, f.value, f.source, f.source_version, f.quality,
                           {sidecar_select}
                    FROM fundamental_statement_items AS f
                    LEFT JOIN mops_statement_consumer_metadata AS m
                      ON m.stock_code = f.stock_code
                     AND m.statement_type = f.statement_type
                     AND m.period = f.period
                     AND m.item_code = f.item_code
                     AND m.materialized_source_version = f.source_version
                    WHERE f.stock_code = ? AND f.available_date <= ?
                    ORDER BY f.period ASC, f.statement_type ASC, f.item_code ASC,
                             f.source_version ASC
                    """,
                    (stock_code, decision_date.isoformat()),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT stock_code, statement_type, period, as_of_date, announced_date,
                           available_date, item_code, item_name, value, source,
                           source_version, quality, 'consolidated' AS report_basis,
                           {_statement_sidecar_select(set())}
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


def _monthly_revenue_row_available_date(row: sqlite3.Row) -> date:
    """取得已通過正式 mapping 的月營收版本可用日。"""
    return _parse_date(str(row["available_date"]))


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
    return _monthly_revenue_row_matches_formal_availability(row, mapping)


def _monthly_revenue_row_matches_formal_availability(
    row: sqlite3.Row,
    mapping: FundamentalAvailabilityOverride,
) -> bool:
    """確認 SQLite row 與某一個正式 mapping revision 完整對應。"""

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


def _monthly_revenue_row_content_fingerprint(
    row: sqlite3.Row,
) -> tuple[str, ...]:
    """取得不含來源版本身份的月營收內容指紋。"""

    return (
        str(row["stock_code"] or "").strip(),
        str(row["period"] or "").strip(),
        str(row["as_of_date"] or "").strip(),
        str(row["announced_date"] or "").strip(),
        str(row["available_date"] or "").strip(),
        str(row["revenue"] or "").strip(),
        str(row["quality"] or "").strip(),
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
        report_basis=str(row["report_basis"] or ""),
        raw_item_code=_optional_text(row["raw_item_code"]),
        item_code_source=_optional_text(row["item_code_source"]),
        item_code_lineage_sha256=_optional_text(row["item_code_lineage_sha256"]),
        official_item_name=_optional_text(row["official_item_name"]),
        xbrl_concept=_optional_text(row["xbrl_concept"]),
        candidate_source_version=_optional_text(row["candidate_source_version"]),
        industry_category=_optional_text(row["industry_category"]),
        semantic_mapping_source=_optional_text(row["semantic_mapping_source"]),
        period_start=_parse_optional_date(row["period_start"]),
        period_end=_parse_optional_date(row["period_end"]),
        period_basis=_optional_text(row["period_basis"]),
        value_unit=_optional_text(row["value_unit"]),
        value_scale=_optional_int(row["value_scale"]),
    )


def _statement_sidecar_select(sidecar_columns: set[str]) -> str:
    """建立受限 sidecar 欄位選取，不對缺欄資料補造來源語意。"""

    selected = []
    for column in (
        "report_basis",
        "raw_item_code",
        "item_code_source",
        "item_code_lineage_sha256",
        "official_item_name",
        "xbrl_concept",
        "candidate_source_version",
        "industry_category",
        "semantic_mapping_source",
        "period_start",
        "period_end",
        "period_basis",
        "value_unit",
        "value_scale",
    ):
        expression = f"m.{column}" if column in sidecar_columns else "NULL"
        selected.append(f"{expression} AS {column}")
    return ", ".join(selected)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_optional_date(value: str | None) -> date | None:
    if value is None or not value.strip():
        return None
    return _parse_date(value)
