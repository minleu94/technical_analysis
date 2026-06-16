"""MOPS 月營收歷史快照候選抓取器。

本模組只建立可追溯的 raw/candidate snapshot，不產生 availability mapping，
也不寫入 SQLite。snapshot 的 period 是營收月份，不得被解讀為 available_date。
"""

from __future__ import annotations

import csv
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from bs4 import BeautifulSoup

from data_module.monthly_revenue_availability_history import (
    _fetch_mops_static_monthly_revenue_html,
    _iter_periods,
)
from decision_module.factors.factor_dtos import FactorDiagnostic


MOPS_SNAPSHOT_SOURCE = "mops.monthly_revenue_static_snapshot"
MOPS_SNAPSHOT_COLUMNS = [
    "market",
    "period",
    "stock_code",
    "company_name",
    "current_month_revenue",
    "previous_month_revenue",
    "previous_year_month_revenue",
    "mom_pct",
    "yoy_pct",
    "cumulative_revenue",
    "previous_year_cumulative_revenue",
    "cumulative_yoy_pct",
    "note",
    "fetched_at",
    "source",
    "source_version",
]


@dataclass(frozen=True)
class MopsMonthlyRevenueSnapshotResult:
    rows: list[dict[str, str]]
    requested_periods: tuple[str, ...]
    fetched_periods: tuple[str, ...]
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    @property
    def valid_candidate(self) -> bool:
        return bool(self.fetched_periods) and not any(
            diagnostic.code.endswith("fetch_failed") for diagnostic in self.diagnostics
        )

    def to_markdown(self, sample_size: int = 5) -> str:
        lines = [
            "# MOPS Monthly Revenue Snapshot Candidate",
            "",
            f"- requested_periods: {len(self.requested_periods)}",
            f"- fetched_periods: {len(self.fetched_periods)}",
            f"- parsed_rows: {len(self.rows)}",
            f"- diagnostics: {len(self.diagnostics)}",
            "",
            "## Sample Rows",
        ]
        for row in self.rows[:sample_size]:
            lines.append(
                "- "
                + ", ".join(
                    f"{key}={row[key]}"
                    for key in (
                        "market",
                        "period",
                        "stock_code",
                        "company_name",
                        "current_month_revenue",
                        "source_version",
                    )
                )
            )
        if not self.rows:
            lines.append("- none")
        return "\n".join(lines)


def fetch_mops_static_monthly_revenue_html(*, market: str, period: str) -> str:
    return _fetch_mops_static_monthly_revenue_html(market=market, period=period)


def build_mops_monthly_revenue_snapshot(
    *,
    start_period: str,
    end_period: str,
    markets: tuple[str, ...],
    fetch_date: date,
    fetch_html: Callable[..., str] = fetch_mops_static_monthly_revenue_html,
    save_html_dir: Path | None = None,
    sleep_seconds: float = 0.0,
    sleep: Callable[[float], object] = time.sleep,
) -> MopsMonthlyRevenueSnapshotResult:
    requested_periods = tuple(_iter_periods(start_period, end_period))
    rows: list[dict[str, str]] = []
    fetched_periods: set[str] = set()
    diagnostics: list[FactorDiagnostic] = []
    fetched_at = _utc_now_text()
    source_version = f"mops-static-{fetch_date.isoformat()}"

    request_pairs = [(market, period) for period in requested_periods for market in markets]
    for index, (market, period) in enumerate(request_pairs):
            try:
                html = fetch_html(market=market, period=period)
            except Exception as exc:
                diagnostics.append(
                    _diagnostic(
                        "monthly_revenue_snapshot.mops_static_fetch_failed",
                        market,
                        f"failed to fetch MOPS static monthly revenue; period={period}; error={exc}",
                    )
                )
                continue
            fetched_periods.add(period)
            if save_html_dir is not None:
                save_html_dir.mkdir(parents=True, exist_ok=True)
                (save_html_dir / f"{market}_{period}.html").write_text(
                    html,
                    encoding="utf-8-sig",
                )
            parsed_rows, parse_diagnostics = parse_mops_monthly_revenue_snapshot_html(
                html,
                market=market,
                period=period,
                fetched_at=fetched_at,
                source_version=source_version,
            )
            rows.extend(parsed_rows)
            diagnostics.extend(parse_diagnostics)
            if sleep_seconds > 0 and index < len(request_pairs) - 1:
                sleep(sleep_seconds)

    rows.sort(key=lambda row: (row["period"], row["market"], row["stock_code"]))
    return MopsMonthlyRevenueSnapshotResult(
        rows=rows,
        requested_periods=requested_periods,
        fetched_periods=tuple(sorted(fetched_periods)),
        diagnostics=tuple(diagnostics),
    )


def parse_mops_monthly_revenue_snapshot_html(
    html: str,
    *,
    market: str,
    period: str,
    fetched_at: str,
    source_version: str,
) -> tuple[list[dict[str, str]], tuple[FactorDiagnostic, ...]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, str]] = []
    diagnostics: list[FactorDiagnostic] = []
    saw_company_column = False
    saw_required_columns = False
    seen_stock_codes: set[str] = set()

    for table in soup.find_all("table"):
        header: list[str] | None = None
        for tr in table.find_all("tr"):
            cells = [_cell_text(cell) for cell in tr.find_all(["th", "td"])]
            if not cells:
                continue
            normalized_cells = [_normalize_header(cell) for cell in cells]
            if "公司代號" in normalized_cells:
                saw_company_column = True
                if _has_required_headers(normalized_cells):
                    saw_required_columns = True
                    header = normalized_cells
                continue
            if header is None:
                continue
            mapped = dict(zip(header, cells, strict=False))
            stock_code = _clean_text(mapped.get("公司代號", ""))
            if not re.fullmatch(r"\d{4,6}", stock_code):
                continue
            if stock_code in seen_stock_codes:
                continue
            seen_stock_codes.add(stock_code)
            rows.append(
                {
                    "market": market,
                    "period": period,
                    "stock_code": stock_code,
                    "company_name": _clean_text(mapped.get("公司名稱", "")),
                    "current_month_revenue": _clean_number(mapped.get("當月營收", "")),
                    "previous_month_revenue": _clean_number(mapped.get("上月營收", "")),
                    "previous_year_month_revenue": _clean_number(
                        mapped.get("去年當月營收", "")
                    ),
                    "mom_pct": _clean_number(_lookup(mapped, ("上月比較增減(%)", "上月比較增減%"))),
                    "yoy_pct": _clean_number(_lookup(mapped, ("去年同月增減(%)", "去年同月增減%"))),
                    "cumulative_revenue": _clean_number(mapped.get("當月累計營收", "")),
                    "previous_year_cumulative_revenue": _clean_number(
                        mapped.get("去年累計營收", "")
                    ),
                    "cumulative_yoy_pct": _clean_number(
                        _lookup(mapped, ("前期比較增減(%)", "前期比較增減%"))
                    ),
                    "note": _clean_text(mapped.get("備註", "")),
                    "fetched_at": fetched_at,
                    "source": MOPS_SNAPSHOT_SOURCE,
                    "source_version": source_version,
                }
            )

    if not saw_company_column or not saw_required_columns:
        diagnostics.append(
            _diagnostic(
                "monthly_revenue_snapshot.mops_missing_required_columns",
                market,
                f"MOPS monthly revenue snapshot missing required columns; period={period}",
            )
        )
    elif not rows:
        diagnostics.append(
            _diagnostic(
                "monthly_revenue_snapshot.mops_no_data_rows",
                market,
                f"MOPS monthly revenue snapshot has no parseable company rows; period={period}",
            )
        )
    return rows, tuple(diagnostics)


def write_mops_snapshot_csv(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MOPS_SNAPSHOT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _has_required_headers(headers: list[str]) -> bool:
    required = {
        "公司代號",
        "公司名稱",
        "當月營收",
        "上月營收",
        "去年當月營收",
        "當月累計營收",
        "去年累計營收",
    }
    return required.issubset(set(headers))


def _lookup(row: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        if name in row:
            return row[name]
    return ""


def _cell_text(cell) -> str:
    return cell.get_text("", strip=True).replace("\xa0", " ")


def _clean_text(value: str) -> str:
    return str(value).strip().replace("\xa0", " ")


def _normalize_header(value: str) -> str:
    cleaned = _clean_text(value)
    cleaned = re.sub(r"\s+", "", cleaned)
    cleaned = cleaned.replace("％", "%")
    return cleaned


def _clean_number(value: str) -> str:
    cleaned = _clean_text(value)
    cleaned = cleaned.replace(",", "").replace("％", "").replace("%", "")
    return cleaned


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _diagnostic(code: str, market: str, message: str) -> FactorDiagnostic:
    return FactorDiagnostic(
        code=code,
        factor_name=f"fundamental.monthly_revenue_snapshot.{market}",
        stock_code="",
        message=message,
    )
