"""市場資料可見性唯讀服務。

本服務只從 SQLite 建立研究摘要；不建立資料表、不回填資料，也不觸發抓取器。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import closing
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from app_module.market_data_visibility_dtos import (
    InstitutionalFlowMarketSummary,
    MarketDataVisibilitySummary,
    MonthlyRevenueBreadthSummary,
    SourceVisibilityStatus,
)


_MISSING_WARNING = "尚未匯入（0 筆）"
_SOURCE_LABELS = {
    "fundamental_monthly_revenues": "月營收",
    "institutional_flows": "三大法人",
    "credit_transactions": "信用交易",
    "tdcc_shareholding": "集保股權分散",
    "broker_flows": "券商分點",
}
_SOURCE_ORDER = tuple(_SOURCE_LABELS)


class _VisibilityReadError(RuntimeError):
    pass


class MarketDataVisibilityService:
    def __init__(self, db_file: Path) -> None:
        self._db_file = Path(db_file)

    def build_summary(self, *, as_of_date: date) -> MarketDataVisibilitySummary:
        try:
            with closing(self._connect_read_only()) as conn:
                revenue_rows, revenue_error = self._load_rows(
                    conn,
                    """
                    SELECT stock_code, period, as_of_date, available_date, revenue,
                           source, source_version, quality, created_at
                    FROM fundamental_monthly_revenues
                    """,
                )
                institutional_rows, institutional_error = self._load_rows(
                    conn,
                    """
                    SELECT stock_code, decision_date, available_date, quality,
                           foreign_investor_net, investment_trust_net, dealer_net
                    FROM institutional_flows
                    """,
                )
                credit_rows, credit_error = self._load_rows(
                    conn,
                    """
                    SELECT stock_code, decision_date, available_date, quality
                    FROM credit_transactions
                    """,
                )
                tdcc_rows, tdcc_error = self._load_rows(
                    conn,
                    """
                    SELECT stock_code, decision_date, available_date, quality
                    FROM tdcc_shareholding
                    """,
                )
                broker_rows, broker_error = self._load_rows(
                    conn,
                    'SELECT 證券代號 AS stock_code, 日期 AS decision_date FROM broker_flows',
                )
        except (sqlite3.Error, OSError, _VisibilityReadError) as exc:
            return self._missing_summary(as_of_date, f"資料庫無法唯讀開啟：{exc}")

        legal_revenue_rows = _latest_legal_revenue_revisions(
            revenue_rows,
            as_of_date=as_of_date,
        )
        legal_institutional_rows = _legal_dated_rows(
            institutional_rows,
            as_of_date=as_of_date,
        )
        legal_credit_rows = _legal_dated_rows(credit_rows, as_of_date=as_of_date)
        legal_tdcc_rows = _legal_dated_rows(tdcc_rows, as_of_date=as_of_date)
        legal_broker_rows = _legal_observation_rows(broker_rows, as_of_date=as_of_date)

        monthly_revenue = _monthly_revenue_summary(legal_revenue_rows)
        institutional_flow = _institutional_flow_summary(legal_institutional_rows)
        statuses = (
            _source_status(
                source_id="fundamental_monthly_revenues",
                as_of_date=as_of_date,
                rows=legal_revenue_rows,
                observation_key="period",
                error=revenue_error,
                summary_quality=monthly_revenue.quality,
            ),
            _source_status(
                source_id="institutional_flows",
                as_of_date=as_of_date,
                rows=legal_institutional_rows,
                observation_key="decision_date",
                error=institutional_error,
                summary_quality=institutional_flow.quality,
            ),
            _source_status(
                source_id="credit_transactions",
                as_of_date=as_of_date,
                rows=legal_credit_rows,
                observation_key="decision_date",
                error=credit_error,
            ),
            _source_status(
                source_id="tdcc_shareholding",
                as_of_date=as_of_date,
                rows=legal_tdcc_rows,
                observation_key="decision_date",
                error=tdcc_error,
            ),
            _source_status(
                source_id="broker_flows",
                as_of_date=as_of_date,
                rows=legal_broker_rows,
                observation_key="decision_date",
                error=broker_error,
                has_available_date=False,
            ),
        )
        overall_quality = _overall_quality(statuses)
        warnings = _unique_warnings(status.warnings for status in statuses)
        return MarketDataVisibilitySummary(
            as_of_date=as_of_date.isoformat(),
            monthly_revenue=monthly_revenue,
            institutional_flow=institutional_flow,
            source_statuses=statuses,
            overall_quality=overall_quality,
            warnings=warnings,
        )

    def _connect_read_only(self) -> sqlite3.Connection:
        uri = f"{self._db_file.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        query_only = conn.execute("PRAGMA query_only").fetchone()
        if query_only is None or int(query_only[0]) != 1:
            conn.close()
            raise _VisibilityReadError("SQLite query_only 未啟用")
        return conn

    @staticmethod
    def _load_rows(
        conn: sqlite3.Connection,
        query: str,
    ) -> tuple[tuple[dict[str, Any], ...], str | None]:
        try:
            return tuple(dict(row) for row in conn.execute(query).fetchall()), None
        except sqlite3.Error as exc:
            return (), f"資料表或 schema 無法讀取：{exc}"

    @staticmethod
    def _missing_summary(as_of_date: date, warning: str) -> MarketDataVisibilitySummary:
        statuses = tuple(
            SourceVisibilityStatus(
                source_id=source_id,
                display_name=_SOURCE_LABELS[source_id],
                as_of_date=as_of_date.isoformat(),
                latest_observation_date=None,
                available_date=None,
                row_count=0,
                stock_count=0,
                quality="MISSING",
                pit_status="missing",
                eligibility="none",
                warnings=(warning,),
            )
            for source_id in _SOURCE_ORDER
        )
        return MarketDataVisibilitySummary(
            as_of_date=as_of_date.isoformat(),
            monthly_revenue=_missing_revenue_summary(warning),
            institutional_flow=_missing_institutional_summary(warning),
            source_statuses=statuses,
            overall_quality="MISSING",
            warnings=(warning,),
        )


def _latest_legal_revenue_revisions(
    rows: Iterable[dict[str, Any]],
    *,
    as_of_date: date,
) -> tuple[dict[str, Any], ...]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        available = _parse_iso_date(row.get("available_date"))
        observation = _parse_iso_date(row.get("as_of_date"))
        period = str(row.get("period") or "")
        stock_code = str(row.get("stock_code") or "")
        if (
            available is None
            or observation is None
            or available > as_of_date
            or observation > as_of_date
            or not stock_code
            or not _valid_period(period)
        ):
            continue
        key = (stock_code, period)
        candidate_order = (
            available.isoformat(),
            str(row.get("created_at") or ""),
            str(row.get("source_version") or ""),
        )
        current = latest.get(key)
        if current is None or candidate_order > current["_revision_order"]:
            selected = dict(row)
            selected["_revision_order"] = candidate_order
            latest[key] = selected
    return tuple(
        latest[key]
        for key in sorted(latest, key=lambda item: (item[1], item[0]))
    )


def _legal_dated_rows(
    rows: Iterable[dict[str, Any]],
    *,
    as_of_date: date,
) -> tuple[dict[str, Any], ...]:
    legal: list[dict[str, Any]] = []
    for row in rows:
        observation = _parse_iso_date(row.get("decision_date"))
        available = _parse_iso_date(row.get("available_date"))
        if (
            observation is None
            or available is None
            or observation > as_of_date
            or available > as_of_date
        ):
            continue
        legal.append(row)
    return tuple(legal)


def _legal_observation_rows(
    rows: Iterable[dict[str, Any]],
    *,
    as_of_date: date,
) -> tuple[dict[str, Any], ...]:
    return tuple(
        row
        for row in rows
        if (observed := _parse_iso_date(row.get("decision_date"))) is not None
        and observed <= as_of_date
    )


def _monthly_revenue_summary(
    rows: tuple[dict[str, Any], ...],
) -> MonthlyRevenueBreadthSummary:
    if not rows:
        return _missing_revenue_summary(_MISSING_WARNING)
    latest_period = max(str(row["period"]) for row in rows)
    previous_period = _shift_period(latest_period, months=-1)
    year_ago_period = _shift_period(latest_period, months=-12)
    by_key = {
        (str(row["stock_code"]), str(row["period"])): row for row in rows
    }
    latest_rows = tuple(row for row in rows if row["period"] == latest_period)
    mom_comparable = 0
    mom_positive = 0
    yoy_comparable = 0
    yoy_positive = 0
    invalid_value_seen = False
    for current_row in latest_rows:
        stock_code = str(current_row["stock_code"])
        current = _decimal_or_none(current_row.get("revenue"))
        previous = _decimal_or_none(
            by_key.get((stock_code, previous_period), {}).get("revenue")
        )
        year_ago = _decimal_or_none(
            by_key.get((stock_code, year_ago_period), {}).get("revenue")
        )
        if current is None:
            invalid_value_seen = True
            continue
        if previous is not None:
            mom_comparable += 1
            mom_positive += int(current > previous)
        if year_ago is not None:
            yoy_comparable += 1
            yoy_positive += int(current > year_ago)
    degraded = invalid_value_seen or any(
        str(row.get("quality") or "").lower() != "observed" for row in rows
    )
    warnings: list[str] = []
    if degraded:
        warnings.append("historical_pit_unverified")
    if mom_comparable == 0:
        warnings.append("月增率缺少可比較基期")
    if yoy_comparable == 0:
        warnings.append("年增率缺少可比較基期")
    return MonthlyRevenueBreadthSummary(
        latest_period=latest_period,
        stock_count=len({str(row["stock_code"]) for row in latest_rows}),
        mom_comparable_count=mom_comparable,
        mom_positive_count=mom_positive,
        mom_positive_ratio_bp=_ratio_bp(mom_positive, mom_comparable),
        yoy_comparable_count=yoy_comparable,
        yoy_positive_count=yoy_positive,
        yoy_positive_ratio_bp=_ratio_bp(yoy_positive, yoy_comparable),
        quality="DEGRADED" if degraded else "OBSERVED",
        warnings=tuple(warnings),
    )


def _institutional_flow_summary(
    rows: tuple[dict[str, Any], ...],
) -> InstitutionalFlowMarketSummary:
    if not rows:
        return _missing_institutional_summary(_MISSING_WARNING)
    latest_date = max(str(row["decision_date"]) for row in rows)
    latest_rows = tuple(row for row in rows if row["decision_date"] == latest_date)
    required = (
        "foreign_investor_net",
        "investment_trust_net",
        "dealer_net",
    )
    values: dict[str, int] = {}
    for field in required:
        field_values = [_integer_or_none(row.get(field)) for row in latest_rows]
        if any(value is None for value in field_values):
            return InstitutionalFlowMarketSummary(
                latest_date=latest_date,
                stock_count=len({str(row["stock_code"]) for row in latest_rows}),
                foreign_net_shares=None,
                investment_trust_net_shares=None,
                dealer_net_shares=None,
                quality="DEGRADED",
                warnings=("三大法人淨買賣欄位缺值",),
            )
        values[field] = sum(value for value in field_values if value is not None)
    degraded = any(
        str(row.get("quality") or "").lower() != "observed" for row in latest_rows
    )
    return InstitutionalFlowMarketSummary(
        latest_date=latest_date,
        stock_count=len({str(row["stock_code"]) for row in latest_rows}),
        foreign_net_shares=values["foreign_investor_net"],
        investment_trust_net_shares=values["investment_trust_net"],
        dealer_net_shares=values["dealer_net"],
        quality="DEGRADED" if degraded else "OBSERVED",
        warnings=("來源品質降級",) if degraded else (),
    )


def _source_status(
    *,
    source_id: str,
    as_of_date: date,
    rows: tuple[dict[str, Any], ...],
    observation_key: str,
    error: str | None,
    summary_quality: str | None = None,
    has_available_date: bool = True,
) -> SourceVisibilityStatus:
    if not rows:
        warning = error or _MISSING_WARNING
        return SourceVisibilityStatus(
            source_id=source_id,
            display_name=_SOURCE_LABELS[source_id],
            as_of_date=as_of_date.isoformat(),
            latest_observation_date=None,
            available_date=None,
            row_count=0,
            stock_count=0,
            quality="MISSING",
            pit_status="missing",
            eligibility="none",
            warnings=(warning,),
        )
    latest_observation = max(str(row[observation_key]) for row in rows)
    available_dates = tuple(
        str(row["available_date"])
        for row in rows
        if row.get("available_date") is not None
    )
    quality = summary_quality or (
        "DEGRADED"
        if any(str(row.get("quality") or "").lower() != "observed" for row in rows)
        else "OBSERVED"
    )
    warnings: tuple[str, ...] = ()
    pit_status = "verified"
    if not has_available_date:
        quality = "DEGRADED"
        pit_status = "observation_date_only"
        warnings = ("來源未提供 available_date；僅供可見性研究",)
    elif quality == "DEGRADED":
        pit_status = "historical_pit_unverified"
        warnings = ("historical_pit_unverified",)
    return SourceVisibilityStatus(
        source_id=source_id,
        display_name=_SOURCE_LABELS[source_id],
        as_of_date=as_of_date.isoformat(),
        latest_observation_date=latest_observation,
        available_date=max(available_dates) if available_dates else None,
        row_count=len(rows),
        stock_count=len({str(row.get("stock_code") or "") for row in rows}),
        quality=quality,
        pit_status=pit_status,
        eligibility="research_only",
        warnings=warnings,
    )


def _missing_revenue_summary(warning: str) -> MonthlyRevenueBreadthSummary:
    return MonthlyRevenueBreadthSummary(
        latest_period=None,
        stock_count=0,
        mom_comparable_count=0,
        mom_positive_count=0,
        mom_positive_ratio_bp=None,
        yoy_comparable_count=0,
        yoy_positive_count=0,
        yoy_positive_ratio_bp=None,
        quality="MISSING",
        warnings=(warning,),
    )


def _missing_institutional_summary(warning: str) -> InstitutionalFlowMarketSummary:
    return InstitutionalFlowMarketSummary(
        latest_date=None,
        stock_count=0,
        foreign_net_shares=None,
        investment_trust_net_shares=None,
        dealer_net_shares=None,
        quality="MISSING",
        warnings=(warning,),
    )


def _overall_quality(statuses: tuple[SourceVisibilityStatus, ...]) -> str:
    qualities = {status.quality for status in statuses}
    if qualities == {"MISSING"}:
        return "MISSING"
    if qualities == {"OBSERVED"}:
        return "OBSERVED"
    return "DEGRADED"


def _unique_warnings(groups: Iterable[tuple[str, ...]]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(warning for group in groups for warning in group))


def _valid_period(value: str) -> bool:
    try:
        year_text, month_text = value.split("-")
        year = int(year_text)
        month = int(month_text)
    except (TypeError, ValueError):
        return False
    return year > 0 and 1 <= month <= 12


def _shift_period(value: str, *, months: int) -> str:
    year, month = (int(part) for part in value.split("-"))
    zero_based = year * 12 + month - 1 + months
    shifted_year, shifted_month = divmod(zero_based, 12)
    return f"{shifted_year:04d}-{shifted_month + 1:02d}"


def _parse_iso_date(value: object) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _integer_or_none(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _ratio_bp(positive: int, comparable: int) -> int | None:
    if comparable == 0:
        return None
    return int(
        (Decimal(positive) * Decimal(10_000) / Decimal(comparable)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )
