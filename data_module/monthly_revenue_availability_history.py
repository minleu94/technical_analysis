"""月營收公告日 historical availability 候選產生器。"""

from __future__ import annotations

import csv
import json
import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from data_module.fundamental_availability import (
    AvailabilityCoverageDiagnostics,
    AvailabilityEvidenceRecord,
    AvailabilityEvidenceValidationError,
    FORMAL_AVAILABILITY_CONTRACT_VERSION,
    OFFICIAL_ANNOUNCEMENT_EVIDENCE_CLASS,
    append_availability_revision,
    summarize_availability_coverage,
    visible_evidence_as_of,
)
from data_module.monthly_revenue_availability_builder import (
    MonthlyRevenueAvailabilityRow,
    RawRevenuePeriod,
    _official_row_source_hash,
)
from decision_module.factors.factor_dtos import FactorDiagnostic


TWSE_HISTORY_SOURCE = "twse.monthly_revenue_announcement"
TPEX_HISTORY_SOURCE = "tpex.monthly_revenue_announcement"
MOPS_HISTORY_SOURCE = "mops.monthly_revenue_announcement"
TEJ_PIT_HISTORY_SOURCE = "tej.monthly_revenue_announcement_pit"
TWSE_HISTORY_SOURCE_VERSION_PREFIX = "twse-openapi-t187ap05-l"
TPEX_HISTORY_SOURCE_VERSION_PREFIX = "tpex-openapi-mopsfin-t187ap05-o"
MOPS_HISTORY_SOURCE_VERSION_PREFIX = "mops-t05st10-ifrs"
MONTHLY_REVENUE_MAX_AVAILABLE_LAG_DAYS = 45
_TAIPEI_TZ = ZoneInfo("Asia/Taipei")

OFFICIAL_OPENAPI_URLS = {
    "twse": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
    "tpex": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O",
}
MOPS_REDIRECT_API_URL = "https://mops.twse.com.tw/mops/api/redirectToOld"
MOPS_STATIC_TYPEK = {
    "twse": "sii0",
    "tpex": "otc0",
}
MOPS_STATIC_MARKET_PATH = {
    "twse": "sii",
    "tpex": "otc",
}

_MARKET_SOURCES = {
    "twse": (TWSE_HISTORY_SOURCE, TWSE_HISTORY_SOURCE_VERSION_PREFIX),
    "tpex": (TPEX_HISTORY_SOURCE, TPEX_HISTORY_SOURCE_VERSION_PREFIX),
}


@dataclass(frozen=True)
class GovernedMonthlyRevenueMappingResult:
    records: tuple[AvailabilityEvidenceRecord, ...]
    coverage: AvailabilityCoverageDiagnostics
    unmatched_reasons: dict[RawRevenuePeriod, str]
    source_manifest: tuple[tuple[str, str, str], ...]

    def visible_as_of(self, as_of_date: date) -> tuple[AvailabilityEvidenceRecord, ...]:
        return visible_evidence_as_of(self.records, as_of_date=as_of_date)


def build_governed_monthly_revenue_mapping(
    *,
    raw_periods: set[RawRevenuePeriod],
    evidence_rows: Iterable[Mapping[str, object]],
    feature_cutoff: date,
) -> GovernedMonthlyRevenueMappingResult:
    """建立不猜公告日的月營收 canonical mapping。"""

    history: tuple[AvailabilityEvidenceRecord, ...] = ()
    matched_keys: set[RawRevenuePeriod] = set()
    unmatched_reasons: dict[RawRevenuePeriod, str] = {}
    manifest: set[tuple[str, str, str]] = set()

    for row in evidence_rows:
        stock_code = str(row.get("stock_code") or "").strip()
        period = str(row.get("period") or "").strip()
        key = (stock_code, period)
        if key not in raw_periods:
            continue
        source_id = str(row.get("source_id") or "").strip()
        tier = str(row.get("evidence_tier") or "").strip()
        announcement_text = str(row.get("announcement_date") or "").strip()
        observed_text = str(row.get("first_observed_date") or "").strip()
        available_text = str(row.get("available_date") or "").strip()
        if source_id.startswith("finmind.") and not announcement_text and not observed_text:
            unmatched_reasons[key] = "non_authoritative_create_time"
            continue
        if tier == "official" and not announcement_text:
            unmatched_reasons[key] = "missing_official_announcement"
            continue
        if tier == "observed_only" and not observed_text:
            unmatched_reasons[key] = "missing_first_observed"
            continue
        if not available_text:
            unmatched_reasons[key] = "missing_explicit_available_date"
            continue

        try:
            record = AvailabilityEvidenceRecord(
                source_id=source_id,
                source_version=str(row.get("source_version") or "").strip(),
                source_hash=str(row.get("source_hash") or "").strip(),
                symbol=stock_code,
                data_family="monthly_revenue",
                period_or_event_date=_period_end(period),
                announcement_at=(
                    parse_announcement_date(announcement_text)
                    if announcement_text
                    else None
                ),
                first_observed_at=(
                    parse_announcement_date(observed_text) if observed_text else None
                ),
                available_at=parse_announcement_date(available_text),
                revision=int(str(row.get("revision") or "1")),
                parent_revision=(
                    int(str(row["parent_revision"]))
                    if str(row.get("parent_revision") or "").strip()
                    else None
                ),
                effective_at=None,
                quality_tier=tier,
                match_method=(
                    "official_natural_key"
                    if tier == "official"
                    else "historical_first_observed"
                ),
                content_hash=str(row.get("content_hash") or "").strip(),
            )
            history = append_availability_revision(history, record)
        except (ValueError, AvailabilityEvidenceValidationError) as exc:
            unmatched_reasons[key] = str(exc)
            continue
        matched_keys.add(key)
        manifest.add((record.source_id, record.source_version, record.source_hash))

    for key in raw_periods - matched_keys:
        unmatched_reasons.setdefault(key, "no_matching_availability_evidence")

    records = tuple(
        sorted(history, key=lambda item: (item.symbol, item.period_or_event_date, item.revision))
    )
    raw_coverage = summarize_availability_coverage(
        records,
        feature_cutoff=feature_cutoff,
    )
    coverage = AvailabilityCoverageDiagnostics(
        total=len(records) + len(unmatched_reasons),
        matched_official=raw_coverage.matched_official,
        matched_observed_only=raw_coverage.matched_observed_only,
        unmatched=len(unmatched_reasons),
        duplicate=raw_coverage.duplicate,
        revision=raw_coverage.revision,
        future_blocked=raw_coverage.future_blocked,
        eligible=raw_coverage.eligible,
    )
    return GovernedMonthlyRevenueMappingResult(
        records=records,
        coverage=coverage,
        unmatched_reasons=unmatched_reasons,
        source_manifest=tuple(sorted(manifest)),
    )


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
    snapshot_captured_at: str | None = None,
    stock_code: str | None = None,
    available_lag_days: int = 1,
    max_available_lag_days: int = MONTHLY_REVENUE_MAX_AVAILABLE_LAG_DAYS,
) -> MonthlyRevenueAvailabilityHistoryResult:
    requested_periods = tuple(_iter_periods(start_period, end_period))
    requested_period_set = set(requested_periods)
    snapshot_available_date = (
        _snapshot_session_available_date(snapshot_captured_at)
        if snapshot_captured_at
        else None
    )
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
            explicit_source_version = str(official_row.get("__source_version") or "").strip()
            source_version_prefix = str(
                official_row.get("__source_version_prefix") or default_source_version_prefix
            )
            source_version = (
                explicit_source_version
                if explicit_source_version
                else f"{source_version_prefix}-{fetch_date.isoformat()}"
            )
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
            if snapshot_available_date is not None:
                # MOPS static 可能在原公告後被修訂；沒有修訂時間線時，
                # 值至少只能從本次台北盤後 session 可用。
                available_date = max(available_date, snapshot_available_date)
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
                    "availability_contract_version": FORMAL_AVAILABILITY_CONTRACT_VERSION,
                    "evidence_class": OFFICIAL_ANNOUNCEMENT_EVIDENCE_CLASS,
                    "source_hash": _official_row_source_hash(official_row),
                    "revision": "1",
                    "parent_revision": "",
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


def load_pit_announcement_rows(
    path: Path,
    *,
    source: str,
    source_version: str,
) -> tuple[list[dict[str, str]], tuple[FactorDiagnostic, ...]]:
    if not source_version.strip():
        return [], (
            _diagnostic(
                "monthly_revenue_availability.pit_missing_source_version",
                "pit",
                "",
                "PIT monthly revenue announcement export requires a non-empty source_version",
            ),
        )

    path = Path(path)
    if not path.exists():
        return [], (
            _diagnostic(
                "monthly_revenue_availability.pit_file_missing",
                "pit",
                "",
                f"PIT monthly revenue announcement export missing; path={path}",
            ),
        )

    rows: list[dict[str, str]] = []
    diagnostics: list[FactorDiagnostic] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        stock_column = _find_column(fieldnames, ("stock_code", "公司代號", "證券代號", "coid"))
        period_column = _find_column(fieldnames, ("period", "資料年月", "年月", "revenue_period"))
        announced_column = _find_column(
            fieldnames,
            ("announced_date", "announcement_date", "公告日", "公告日期", "出表日期"),
        )
        if not stock_column or not period_column or not announced_column:
            return [], (
                _diagnostic(
                    "monthly_revenue_availability.pit_missing_columns",
                    "pit",
                    "",
                    (
                        "PIT monthly revenue announcement export missing required columns; "
                        f"path={path}; columns={','.join(fieldnames)}"
                    ),
                ),
            )

        for source_row in reader:
            stock_code = str(source_row.get(stock_column, "")).strip()
            try:
                period = parse_revenue_period(str(source_row.get(period_column, "")))
                announced_date = parse_announcement_date(
                    str(source_row.get(announced_column, ""))
                )
            except ValueError:
                diagnostics.append(
                    _diagnostic(
                        "monthly_revenue_availability.pit_invalid_row",
                        "pit",
                        stock_code,
                        f"PIT monthly revenue announcement row has invalid period/date; path={path}",
                    )
                )
                continue
            rows.append(
                {
                    "資料年月": period,
                    "公司代號": stock_code,
                    "出表日期": announced_date.isoformat(),
                    "__availability_source": source,
                    "__source_version": source_version,
                }
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
    parsed_report_url = urlparse(report_url)
    if (
        parsed_report_url.scheme != "https"
        or parsed_report_url.hostname != "mopsov.twse.com.tw"
    ):
        raise ValueError("MOPS redirect report URL is not the official mopsov HTTPS host")
    popup_html = _fetch_text(report_url, encoding="utf-8")
    static_path = _extract_mops_static_path(popup_html)
    if static_path is None:
        raise ValueError("MOPS redirect report has no static nas path")
    expected_market_path = MOPS_STATIC_MARKET_PATH.get(market)
    if expected_market_path is None:
        raise ValueError(f"unsupported MOPS market: {market}")
    if not static_path.startswith(f"/nas/t21/{expected_market_path}/"):
        raise ValueError(
            "MOPS redirect report path does not match the requested official market"
        )
    static_html = _fetch_text(
        f"https://mopsov.twse.com.tw{static_path}",
        encoding="big5",
    )
    _validate_mops_static_report(
        static_html,
        market=market,
        period=period,
        static_path=static_path,
    )
    return static_html


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
    # 現行 redirect 回應使用 ``window.open('/nas/...','')``，也有雙引號變體。
    # 只擷取相對路徑並嚴格限制在官方 /nas/t21/ 報表檔，避免外部或穿越路徑
    # 被拼接成下載網址。
    match = re.search(
        r"window\.open\(\s*(?P<quote>['\"])(?P<path>[^'\"]+)(?P=quote)",
        html,
    )
    if match is None:
        return None
    path = match.group("path").strip()
    if not re.fullmatch(
        r"/nas/t21/[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+\.html",
        path,
    ):
        return None
    return path


def _validate_mops_static_report(
    html: str,
    *,
    market: str,
    period: str,
    static_path: str,
) -> None:
    """確認 redirect 實際回傳的市場與期別仍符合請求。"""
    expected_market_path = MOPS_STATIC_MARKET_PATH.get(market)
    if expected_market_path is None:
        raise ValueError(f"unsupported MOPS market: {market}")
    path_match = re.fullmatch(
        rf"/nas/t21/{re.escape(expected_market_path)}/t21sc03_(\d{{3}})_(\d{{1,2}})_0\.html",
        static_path,
    )
    if path_match is None:
        raise ValueError("MOPS static report path has an unexpected market or filename")
    try:
        requested_year, requested_month = (int(part) for part in period.split("-", 1))
    except (TypeError, ValueError):
        raise ValueError("MOPS static report request period is invalid") from None
    response_year = int(path_match.group(1)) + 1911
    response_month = int(path_match.group(2))
    if (response_year, response_month) != (requested_year, requested_month):
        raise ValueError(
            "MOPS static report path period does not match the requested period"
        )
    market_title = "上市" if market == "twse" else "上櫃"
    title_pattern = rf"{market_title}公司{response_year - 1911:03d}年{response_month}月份"
    if re.search(title_pattern, html) is None:
        raise ValueError(
            "MOPS static report body period does not match the requested period"
        )


def _snapshot_session_available_date(fetched_at: str) -> date:
    """將帶時區的抓取時間轉成 date-only 的保守可用日。

    date-only consumer 會把整個 ``available_date`` 當成可用，因此不能在
    抓取當日盤後就讓早盤查詢看見資料；若需要同日使用，必須另以完整
    timestamp 做明確比較。這裡使用下一個台北曆日，未宣稱交易所假日後
    的實際 next session。
    """
    try:
        parsed = datetime.fromisoformat(fetched_at.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("fetched_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("fetched_at must include a timezone")
    local = parsed.astimezone(_TAIPEI_TZ)
    return local.date() + timedelta(days=1)


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


def _find_column(fieldnames: tuple[str, ...], candidates: tuple[str, ...]) -> str | None:
    normalized = {name.strip().lower(): name for name in fieldnames}
    for candidate in candidates:
        matched = normalized.get(candidate.strip().lower())
        if matched:
            return matched
    return None


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
