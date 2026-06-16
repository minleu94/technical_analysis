"""月營收公告日 historical availability 候選產生器。"""

from __future__ import annotations

import json
import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Mapping
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from data_module.monthly_revenue_availability_builder import (
    MonthlyRevenueAvailabilityRow,
    RawRevenuePeriod,
)
from decision_module.factors.factor_dtos import FactorDiagnostic


TWSE_HISTORY_SOURCE = "twse.monthly_revenue_announcement"
TPEX_HISTORY_SOURCE = "tpex.monthly_revenue_announcement"
MOPS_HISTORY_SOURCE = "mops.monthly_revenue_announcement"
TWSE_HISTORY_SOURCE_VERSION_PREFIX = "twse-openapi-t187ap05-l"
TPEX_HISTORY_SOURCE_VERSION_PREFIX = "tpex-openapi-mopsfin-t187ap05-o"
MOPS_HISTORY_SOURCE_VERSION_PREFIX = "mops-t05st10-ifrs"
MONTHLY_REVENUE_MAX_AVAILABLE_LAG_DAYS = 45

OFFICIAL_OPENAPI_URLS = {
    "twse": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
    "tpex": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O",
}
MOPS_REDIRECT_API_URL = "https://mops.twse.com.tw/mops/api/redirectToOld"
MOPS_STATIC_TYPEK = {
    "twse": "sii0",
    "tpex": "otc0",
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
    max_available_lag_days: int = MONTHLY_REVENUE_MAX_AVAILABLE_LAG_DAYS,
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
        default_source, default_source_version_prefix = _market_source(market)
        for official_row in official_rows_by_market.get(market, ()):
            source = str(official_row.get("__availability_source") or default_source)
            source_version_prefix = str(
                official_row.get("__source_version_prefix") or default_source_version_prefix
            )
            source_version = f"{source_version_prefix}-{fetch_date.isoformat()}"
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
            as_of_date = _period_end(period)
            available_date = announced_date + timedelta(days=available_lag_days)
            if available_date > as_of_date + timedelta(days=max_available_lag_days):
                diagnostics.append(
                    _diagnostic(
                        "monthly_revenue_availability.available_date_unreasonably_late",
                        market,
                        row_stock_code,
                        (
                            "monthly revenue availability row is outside the allowed "
                            f"disclosure window; period={period}; "
                            f"as_of_date={as_of_date.isoformat()}; "
                            f"available_date={available_date.isoformat()}; "
                            f"max_lag_days={max_available_lag_days}"
                        ),
                    )
                )
                diagnostics_by_source[market] = diagnostics_by_source.get(market, 0) + 1
                continue
            if key in seen_keys:
                duplicate_mapping_rows += 1
                continue
            seen_keys.add(key)
            rows.append(
                {
                    "stock_code": row_stock_code,
                    "period": period,
                    "as_of_date": as_of_date.isoformat(),
                    "announced_date": announced_date.isoformat(),
                    "available_date": available_date.isoformat(),
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
    mops_html_dir: Path | None = None,
    mops_static: bool = False,
    start_period: str | None = None,
    end_period: str | None = None,
) -> tuple[dict[str, list[dict[str, str]]], tuple[FactorDiagnostic, ...]]:
    rows_by_market: dict[str, list[dict[str, str]]] = {}
    diagnostics: list[FactorDiagnostic] = []
    for market in markets:
        try:
            if mops_html_dir is not None:
                rows, parse_diagnostics = _load_mops_html_rows(
                    Path(mops_html_dir),
                    market=market,
                    start_period=start_period,
                    end_period=end_period,
                )
                rows_by_market[market] = rows
                diagnostics.extend(parse_diagnostics)
            elif mops_static:
                rows, parse_diagnostics = _load_mops_static_rows(
                    market=market,
                    start_period=start_period,
                    end_period=end_period,
                )
                rows_by_market[market] = rows
                diagnostics.extend(parse_diagnostics)
            elif source_json_dir is not None:
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


def parse_mops_monthly_revenue_html(
    html: str,
    *,
    market: str,
    period: str,
) -> tuple[list[dict[str, str]], tuple[FactorDiagnostic, ...]]:
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(" ", strip=True)
    announced_date_text = _find_mops_announcement_date(page_text)
    if announced_date_text is None:
        return [], (
            _diagnostic(
                "monthly_revenue_availability.mops_missing_announced_date",
                market,
                "",
                f"MOPS monthly revenue HTML has no 出表日期; period={period}",
            ),
        )

    try:
        announced_date = parse_announcement_date(announced_date_text)
    except ValueError:
        return [], (
            _diagnostic(
                "monthly_revenue_availability.mops_invalid_announced_date",
                market,
                "",
                f"MOPS monthly revenue HTML has invalid 出表日期; period={period}",
            ),
        )

    rows: list[dict[str, str]] = []
    seen_stock_codes: set[str] = set()
    for table in soup.find_all("table"):
        parsed_rows = _parse_mops_table(table)
        for parsed_row in parsed_rows:
            stock_code = parsed_row.get("公司代號", "").strip()
            if not stock_code or not stock_code.isdigit():
                continue
            if stock_code in seen_stock_codes:
                continue
            seen_stock_codes.add(stock_code)
            rows.append(
                {
                    "資料年月": period,
                    "公司代號": stock_code,
                    "出表日期": announced_date.isoformat(),
                }
            )

    diagnostics: list[FactorDiagnostic] = []
    if not rows:
        diagnostics.append(
            _diagnostic(
                "monthly_revenue_availability.mops_no_data_rows",
                market,
                "",
                f"MOPS monthly revenue HTML has no parseable company rows; period={period}",
            )
        )
    return rows, tuple(diagnostics)


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


def _load_mops_html_rows(
    directory: Path,
    *,
    market: str,
    start_period: str | None,
    end_period: str | None,
) -> tuple[list[dict[str, str]], tuple[FactorDiagnostic, ...]]:
    periods = tuple(_iter_periods(start_period, end_period)) if start_period and end_period else ()
    rows: list[dict[str, str]] = []
    diagnostics: list[FactorDiagnostic] = []
    for period in periods:
        path = directory / f"{market}_{period}.html"
        if not path.exists():
            diagnostics.append(
                _diagnostic(
                    "monthly_revenue_availability.mops_html_missing",
                    market,
                    "",
                    f"MOPS monthly revenue HTML file missing; path={path}",
                )
            )
            continue
        parsed_rows, parse_diagnostics = parse_mops_monthly_revenue_html(
            path.read_text(encoding="utf-8-sig"),
            market=market,
            period=period,
        )
        for row in parsed_rows:
            row["__availability_source"] = MOPS_HISTORY_SOURCE
            row["__source_version_prefix"] = MOPS_HISTORY_SOURCE_VERSION_PREFIX
        rows.extend(parsed_rows)
        diagnostics.extend(parse_diagnostics)
    return rows, tuple(diagnostics)


def _load_mops_static_rows(
    *,
    market: str,
    start_period: str | None,
    end_period: str | None,
) -> tuple[list[dict[str, str]], tuple[FactorDiagnostic, ...]]:
    periods = tuple(_iter_periods(start_period, end_period)) if start_period and end_period else ()
    rows: list[dict[str, str]] = []
    diagnostics: list[FactorDiagnostic] = []
    for period in periods:
        try:
            html = _fetch_mops_static_monthly_revenue_html(market=market, period=period)
        except Exception as exc:
            diagnostics.append(
                _diagnostic(
                    "monthly_revenue_availability.mops_static_fetch_failed",
                    market,
                    "",
                    f"failed to fetch MOPS static monthly revenue report; period={period}; error={exc}",
                )
            )
            continue
        parsed_rows, parse_diagnostics = parse_mops_monthly_revenue_html(
            html,
            market=market,
            period=period,
        )
        for row in parsed_rows:
            row["__availability_source"] = MOPS_HISTORY_SOURCE
            row["__source_version_prefix"] = MOPS_HISTORY_SOURCE_VERSION_PREFIX
        rows.extend(parsed_rows)
        diagnostics.extend(parse_diagnostics)
    return rows, tuple(diagnostics)


def _fetch_mops_static_monthly_revenue_html(*, market: str, period: str) -> str:
    typek = MOPS_STATIC_TYPEK[market]
    year_text, month_text = period.split("-", maxsplit=1)
    roc_year = int(year_text) - 1911
    redirect_payload = json.dumps(
        {
            "apiName": "ajax_t21sc04_ifrs",
            "parameters": {
                "TYPEK": typek,
                "year": str(roc_year),
                "month": month_text,
                "encodeURIComponent": 1,
                "firstin": 1,
                "step": 1,
                "off": 1,
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        MOPS_REDIRECT_API_URL,
        data=redirect_payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://mops.twse.com.tw",
            "Referer": "https://mops.twse.com.tw/mops/#/web/t21sc04_ifrs",
            "User-Agent": "Mozilla/5.0",
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        redirect_response = json.loads(response.read().decode("utf-8-sig"))
    report_url = str(redirect_response.get("result", {}).get("url", ""))
    if not report_url:
        raise ValueError("MOPS redirect response has no report URL")
    popup_html = _fetch_text(report_url, encoding="utf-8")
    static_path = _extract_mops_static_path(popup_html)
    if static_path is None:
        raise ValueError("MOPS redirect report has no static nas path")
    return _fetch_text(f"https://mopsov.twse.com.tw{static_path}", encoding="big5")


def _fetch_text(url: str, *, encoding: str) -> str:
    request = Request(
        url,
        headers={
            "Referer": "https://mops.twse.com.tw/mops/#/web/t21sc04_ifrs",
            "User-Agent": "Mozilla/5.0",
        },
    )
    with urlopen(request, timeout=30) as response:
        return response.read().decode(encoding, errors="replace")


def _extract_mops_static_path(html: str) -> str | None:
    match = re.search(r"window\.open\('([^']+)'", html)
    if match is None:
        return None
    return match.group(1)


def _find_mops_announcement_date(text: str) -> str | None:
    match = re.search(
        r"出表日期\s*[:：]?\s*(\d{3,4}[/-]\d{1,2}[/-]\d{1,2}|\d{7,8})",
        text,
    )
    if match is None:
        return None
    return match.group(1)


def _parse_mops_table(table) -> list[dict[str, str]]:
    table_rows = table.find_all("tr")
    if not table_rows:
        return []
    fallback_rows: list[dict[str, str]] = []
    for row in table_rows:
        cells = [cell.get_text(strip=True) for cell in row.find_all(["th", "td"])]
        if cells and re.fullmatch(r"\d{4,6}", cells[0] or ""):
            fallback_rows.append({"公司代號": cells[0]})
    if fallback_rows:
        return fallback_rows

    headers = [cell.get_text(strip=True) for cell in table_rows[0].find_all(["th", "td"])]
    if "公司代號" not in headers:
        return []
    parsed_rows: list[dict[str, str]] = []
    for row in table_rows[1:]:
        cells = [cell.get_text(strip=True) for cell in row.find_all(["th", "td"])]
        if len(cells) < len(headers):
            continue
        parsed_rows.append(dict(zip(headers, cells, strict=False)))
    return parsed_rows


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
