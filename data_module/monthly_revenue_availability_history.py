"""月營收公告日 historical availability 候選產生器。"""

from __future__ import annotations

import json
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Mapping
from urllib.request import Request, urlopen

from data_module.monthly_revenue_availability_builder import (
    MonthlyRevenueAvailabilityRow,
    RawRevenuePeriod,
)
from decision_module.factors.factor_dtos import FactorDiagnostic


TWSE_HISTORY_SOURCE = "twse.monthly_revenue_announcement"
TPEX_HISTORY_SOURCE = "tpex.monthly_revenue_announcement"
TWSE_HISTORY_SOURCE_VERSION_PREFIX = "twse-openapi-t187ap05-l"
TPEX_HISTORY_SOURCE_VERSION_PREFIX = "tpex-openapi-mopsfin-t187ap05-o"

OFFICIAL_OPENAPI_URLS = {
    "twse": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
    "tpex": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O",
}

_MARKET_SOURCES = {
    "twse": (TWSE_HISTORY_SOURCE, TWSE_HISTORY_SOURCE_VERSION_PREFIX),
    "tpex": (TPEX_HISTORY_SOURCE, TPEX_HISTORY_SOURCE_VERSION_PREFIX),
}


@dataclass(frozen=True)
class MonthlyRevenueAvailabilityHistoryResult:
    rows: list[MonthlyRevenueAvailabilityRow]
    requested_periods: tuple[str, ...]
    fetched_periods: tuple[str, ...]
    matched_raw_monthly_revenue_rows: int
    missing_availability_count: int
    duplicate_mapping_rows: int
    diagnostics: tuple[FactorDiagnostic, ...] = ()
    diagnostics_by_source: dict[str, int] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "rows", [dict(row) for row in self.rows])
        object.__setattr__(self, "requested_periods", tuple(self.requested_periods))
        object.__setattr__(self, "fetched_periods", tuple(self.fetched_periods))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        object.__setattr__(
            self,
            "diagnostics_by_source",
            dict(self.diagnostics_by_source or {}),
        )

    @property
    def valid_candidate(self) -> bool:
        return bool(self.rows) and self.duplicate_mapping_rows == 0

    def to_markdown(self, sample_size: int = 5) -> str:
        lines = [
            "# Monthly Revenue Availability Historical Candidate",
            "",
            f"- requested_periods: {len(self.requested_periods)}",
            f"- fetched_periods: {len(self.fetched_periods)}",
            f"- matched_raw_monthly_revenue_rows: {self.matched_raw_monthly_revenue_rows}",
            f"- missing_availability_rows: {self.missing_availability_count}",
            f"- duplicate_mapping_rows: {self.duplicate_mapping_rows}",
            f"- diagnostics: {len(self.diagnostics)}",
            "- diagnostics_by_source: "
            + (
                ", ".join(
                    f"{source}={count}"
                    for source, count in sorted((self.diagnostics_by_source or {}).items())
                )
                or "none"
            ),
            "",
            "## Sample Rows",
        ]
        for row in self.rows[:sample_size]:
            lines.append(
                "- "
                + ", ".join(
                    f"{key}={row[key]}"
                    for key in (
                        "stock_code",
                        "period",
                        "announced_date",
                        "available_date",
                        "source",
                        "source_version",
                    )
                )
            )
        if not self.rows:
            lines.append("- none")
        return "\n".join(lines)


def build_historical_monthly_revenue_availability(
    *,
    official_rows_by_market: Mapping[str, Iterable[Mapping[str, str]]],
    raw_periods: set[RawRevenuePeriod],
    start_period: str,
    end_period: str,
    markets: tuple[str, ...],
    fetch_date: date,
    stock_code: str | None = None,
    available_lag_days: int = 1,
) -> MonthlyRevenueAvailabilityHistoryResult:
    requested_periods = tuple(_iter_periods(start_period, end_period))
    requested_period_set = set(requested_periods)
    rows: list[MonthlyRevenueAvailabilityRow] = []
    diagnostics: list[FactorDiagnostic] = []
    diagnostics_by_source: dict[str, int] = {}
    seen_keys: set[RawRevenuePeriod] = set()
    duplicate_mapping_rows = 0
    fetched_periods: set[str] = set()

    scoped_raw_periods = {
        item
        for item in raw_periods
        if item[1] in requested_period_set and (stock_code is None or item[0] == stock_code)
    }

    for market in markets:
        source, source_version_prefix = _market_source(market)
        source_version = f"{source_version_prefix}-{fetch_date.isoformat()}"
        for official_row in official_rows_by_market.get(market, ()):
            row_stock_code = str(official_row.get("公司代號", "")).strip()
            if stock_code is not None and row_stock_code != stock_code:
                continue

            try:
                period = parse_revenue_period(str(official_row.get("資料年月", "")))
            except ValueError:
                diagnostics.append(
                    _diagnostic(
                        "monthly_revenue_availability.invalid_period",
                        market,
                        row_stock_code,
                        "official monthly revenue row has invalid period",
                    )
                )
                diagnostics_by_source[market] = diagnostics_by_source.get(market, 0) + 1
                continue

            if period not in requested_period_set:
                continue
            fetched_periods.add(period)

            announced_text = str(official_row.get("出表日期", "")).strip()
            if not announced_text:
                diagnostics.append(
                    _diagnostic(
                        "monthly_revenue_availability.missing_announced_date",
                        market,
                        row_stock_code,
                        f"official monthly revenue row has no 出表日期; period={period}",
                    )
                )
                diagnostics_by_source[market] = diagnostics_by_source.get(market, 0) + 1
                continue

            try:
                announced_date = parse_announcement_date(announced_text)
            except ValueError:
                diagnostics.append(
                    _diagnostic(
                        "monthly_revenue_availability.invalid_announced_date",
                        market,
                        row_stock_code,
                        f"official monthly revenue row has invalid 出表日期; period={period}",
                    )
                )
                diagnostics_by_source[market] = diagnostics_by_source.get(market, 0) + 1
                continue

            key = (row_stock_code, period)
            if key not in scoped_raw_periods:
                continue
            if key in seen_keys:
                duplicate_mapping_rows += 1
                continue
            seen_keys.add(key)
            rows.append(
                {
                    "stock_code": row_stock_code,
                    "period": period,
                    "as_of_date": _period_end(period).isoformat(),
                    "announced_date": announced_date.isoformat(),
                    "available_date": (
                        announced_date + timedelta(days=available_lag_days)
                    ).isoformat(),
                    "source": source,
                    "source_version": source_version,
                }
            )

    rows.sort(key=lambda row: (row["stock_code"], row["period"]))
    missing_availability_count = len(scoped_raw_periods - seen_keys)
    return MonthlyRevenueAvailabilityHistoryResult(
        rows=rows,
        requested_periods=requested_periods,
        fetched_periods=tuple(sorted(fetched_periods)),
        matched_raw_monthly_revenue_rows=len(rows),
        missing_availability_count=missing_availability_count,
        duplicate_mapping_rows=duplicate_mapping_rows,
        diagnostics=tuple(diagnostics),
        diagnostics_by_source=diagnostics_by_source,
    )


def load_official_rows_for_markets(
    *,
    markets: tuple[str, ...],
    source_json_dir: Path | None = None,
) -> tuple[dict[str, list[dict[str, str]]], tuple[FactorDiagnostic, ...]]:
    rows_by_market: dict[str, list[dict[str, str]]] = {}
    diagnostics: list[FactorDiagnostic] = []
    for market in markets:
        try:
            if source_json_dir is not None:
                rows_by_market[market] = _load_json_rows(Path(source_json_dir) / f"{market}.json")
            else:
                rows_by_market[market] = _fetch_openapi_rows(market)
        except Exception as exc:
            rows_by_market[market] = []
            diagnostics.append(
                _diagnostic(
                    "monthly_revenue_availability.fetch_failed",
                    market,
                    "",
                    f"failed to fetch official monthly revenue rows; market={market}; error={exc}",
                )
            )
    return rows_by_market, tuple(diagnostics)


def parse_revenue_period(value: str) -> str:
    cleaned = value.strip().replace("/", "-")
    if len(cleaned) == 5 and cleaned.isdigit():
        year = int(cleaned[:3]) + 1911
        month = int(cleaned[3:])
    else:
        parts = cleaned.split("-")
        if len(parts) != 2:
            raise ValueError("invalid period")
        year = int(parts[0])
        if year < 1911:
            year += 1911
        month = int(parts[1])
    if month < 1 or month > 12:
        raise ValueError("invalid period")
    return f"{year:04d}-{month:02d}"


def parse_announcement_date(value: str) -> date:
    cleaned = value.strip().replace("/", "-")
    if len(cleaned) == 7 and cleaned.isdigit():
        return _date_from_parts(int(cleaned[:3]) + 1911, int(cleaned[3:5]), int(cleaned[5:]))
    parts = cleaned.split("-")
    if len(parts) != 3:
        raise ValueError("invalid announcement date")
    year = int(parts[0])
    if year < 1911:
        year += 1911
    return _date_from_parts(year, int(parts[1]), int(parts[2]))


def _load_json_rows(path: Path) -> list[dict[str, str]]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _fetch_openapi_rows(market: str) -> list[dict[str, str]]:
    url = OFFICIAL_OPENAPI_URLS[market]
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=30) as response:
        payload = response.read().decode("utf-8-sig")
    return json.loads(payload)


def _iter_periods(start_period: str, end_period: str) -> Iterable[str]:
    start_year, start_month = (int(part) for part in start_period.split("-", maxsplit=1))
    end_year, end_month = (int(part) for part in end_period.split("-", maxsplit=1))
    year = start_year
    month = start_month
    while (year, month) <= (end_year, end_month):
        yield f"{year:04d}-{month:02d}"
        month += 1
        if month == 13:
            year += 1
            month = 1


def _market_source(market: str) -> tuple[str, str]:
    if market not in _MARKET_SOURCES:
        raise ValueError(f"unsupported market: {market}")
    return _MARKET_SOURCES[market]


def _period_end(period: str) -> date:
    year_text, month_text = period.split("-", maxsplit=1)
    year = int(year_text)
    month = int(month_text)
    return date(year, month, monthrange(year, month)[1])


def _date_from_parts(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise ValueError("invalid announcement date") from exc


def _diagnostic(code: str, market: str, stock_code: str, message: str) -> FactorDiagnostic:
    return FactorDiagnostic(
        code=code,
        factor_name=f"fundamental.availability.{market}",
        stock_code=stock_code,
        message=message,
    )
