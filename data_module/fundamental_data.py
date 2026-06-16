"""基本面 raw CSV 的唯讀正規化契約。"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping

from data_module.fundamental_availability import (
    FundamentalAvailabilityInput,
    resolve_fundamental_availability,
)
from decision_module.factors.factor_dtos import FactorDiagnostic, FactorQuality


AvailableDateKey = tuple[str, str]


@dataclass(frozen=True)
class MonthlyRevenueRecord:
    stock_code: str
    period: str
    as_of_date: date
    raw_date: date
    announced_date: date | None
    available_date: date
    revenue: Decimal
    source: str
    source_version: str
    quality: FactorQuality


@dataclass(frozen=True)
class MonthlyRevenueParseResult:
    records: tuple[MonthlyRevenueRecord, ...] = ()
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


def parse_monthly_revenue_rows(
    rows: Iterable[Mapping[str, str]],
    *,
    available_dates: Mapping[AvailableDateKey, date],
    source_version: str,
) -> MonthlyRevenueParseResult:
    records: list[MonthlyRevenueRecord] = []
    diagnostics: list[FactorDiagnostic] = []

    for row in rows:
        stock_code = row.get("stock_id", "").strip()
        period = _period(row)
        factor_name = "fundamental.revenue"

        try:
            revenue = Decimal(row.get("revenue", "").strip())
        except (InvalidOperation, AttributeError):
            diagnostics.append(
                FactorDiagnostic(
                    code="fundamental_revenue.invalid_revenue",
                    factor_name=factor_name,
                    stock_code=stock_code,
                    message="monthly revenue value is not a valid Decimal",
                )
            )
            continue

        availability = resolve_fundamental_availability(
            FundamentalAvailabilityInput(
                stock_code=stock_code,
                period=period,
                as_of_date=_month_end(row),
                announced_date=None,
                explicit_available_date=available_dates.get((stock_code, period)),
                source="financial_data.monthly_revenue_csv",
            )
        )
        diagnostics.extend(availability.diagnostics)
        if availability.available_date is None:
            continue

        records.append(
            MonthlyRevenueRecord(
                stock_code=stock_code,
                period=period,
                as_of_date=_month_end(row),
                raw_date=_parse_iso_date(row["date"]),
                announced_date=availability.announced_date,
                available_date=availability.available_date,
                revenue=revenue,
                source="financial_data.monthly_revenue_csv",
                source_version=source_version,
                quality=availability.quality,
            )
        )

    return MonthlyRevenueParseResult(records=tuple(records), diagnostics=tuple(diagnostics))


def _period(row: Mapping[str, str]) -> str:
    year = int(row["revenue_year"])
    month = int(row["revenue_month"])
    return f"{year:04d}-{month:02d}"


def _month_end(row: Mapping[str, str]) -> date:
    year = int(row["revenue_year"])
    month = int(row["revenue_month"])
    return date(year, month, monthrange(year, month)[1])


def _parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()
