"""Build governed monthly revenue availability rows from official TWSE data."""

from __future__ import annotations

import csv
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Mapping


TWSE_MONTHLY_REVENUE_SOURCE = "twse.monthly_revenue_announcement"
TWSE_MONTHLY_REVENUE_SOURCE_VERSION_PREFIX = "twse-openapi-t187ap05-p"


MonthlyRevenueAvailabilityRow = dict[str, str]
RawRevenuePeriod = tuple[str, str]


@dataclass(frozen=True)
class MonthlyRevenueAvailabilityBuildResult:
    rows: list[MonthlyRevenueAvailabilityRow]
    skipped_not_in_raw_count: int
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "rows", [dict(row) for row in self.rows])
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


def build_monthly_revenue_availability_rows(
    official_rows: Iterable[Mapping[str, str]],
    *,
    raw_periods: set[RawRevenuePeriod],
    fetch_date: date,
    available_lag_days: int = 1,
) -> MonthlyRevenueAvailabilityBuildResult:
    rows: list[MonthlyRevenueAvailabilityRow] = []
    diagnostics: list[str] = []
    skipped_not_in_raw_count = 0
    source_version = (
        f"{TWSE_MONTHLY_REVENUE_SOURCE_VERSION_PREFIX}-{fetch_date.isoformat()}"
    )

    for official_row in official_rows:
        stock_code = str(official_row.get("公司代號", "")).strip()
        try:
            period = _parse_roc_year_month(str(official_row.get("資料年月", "")))
            announced_date = _parse_roc_date(str(official_row.get("出表日期", "")))
        except ValueError as exc:
            field_name = str(exc)
            diagnostics.append(
                "invalid official monthly revenue row; "
                f"stock_code={stock_code}; field={field_name}"
            )
            continue

        if (stock_code, period) not in raw_periods:
            skipped_not_in_raw_count += 1
            continue

        as_of_date = _period_end(period)
        available_date = announced_date + timedelta(days=available_lag_days)
        rows.append(
            {
                "stock_code": stock_code,
                "period": period,
                "as_of_date": as_of_date.isoformat(),
                "announced_date": announced_date.isoformat(),
                "available_date": available_date.isoformat(),
                "source": TWSE_MONTHLY_REVENUE_SOURCE,
                "source_version": source_version,
            }
        )

    rows.sort(key=lambda row: (row["stock_code"], row["period"]))
    return MonthlyRevenueAvailabilityBuildResult(
        rows=rows,
        skipped_not_in_raw_count=skipped_not_in_raw_count,
        diagnostics=tuple(diagnostics),
    )


def load_raw_monthly_revenue_periods(raw_dir: Path) -> set[RawRevenuePeriod]:
    periods: set[RawRevenuePeriod] = set()
    for csv_path in sorted(Path(raw_dir).glob("*_monthly_revenue.csv")):
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                stock_code = str(row.get("stock_id", "")).strip()
                revenue_year = str(row.get("revenue_year", "")).strip()
                revenue_month = str(row.get("revenue_month", "")).strip()
                if not stock_code or not revenue_year or not revenue_month:
                    continue
                try:
                    periods.add(
                        (stock_code, f"{int(revenue_year):04d}-{int(revenue_month):02d}")
                    )
                except ValueError:
                    continue
    return periods


def _parse_roc_year_month(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) != 5 or not cleaned.isdigit():
        raise ValueError("資料年月")
    year = int(cleaned[:3]) + 1911
    month = int(cleaned[3:])
    if month < 1 or month > 12:
        raise ValueError("資料年月")
    return f"{year:04d}-{month:02d}"


def _parse_roc_date(value: str) -> date:
    cleaned = value.strip()
    if len(cleaned) != 7 or not cleaned.isdigit():
        raise ValueError("出表日期")
    year = int(cleaned[:3]) + 1911
    month = int(cleaned[3:5])
    day = int(cleaned[5:])
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise ValueError("出表日期") from exc


def _period_end(period: str) -> date:
    year_text, month_text = period.split("-", maxsplit=1)
    year = int(year_text)
    month = int(month_text)
    return date(year, month, monthrange(year, month)[1])
