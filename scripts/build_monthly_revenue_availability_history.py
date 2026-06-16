from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.config import TWStockConfig
from data_module.fundamental_availability_sources import (
    MONTHLY_REVENUE_AVAILABILITY_COLUMNS,
)
from data_module.monthly_revenue_availability_builder import (
    load_raw_monthly_revenue_periods,
)
from data_module.monthly_revenue_availability_history import (
    MonthlyRevenueAvailabilityHistoryResult,
    TEJ_PIT_HISTORY_SOURCE,
    build_historical_monthly_revenue_availability,
    load_official_rows_for_markets,
    load_pit_announcement_rows,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build historical monthly revenue availability candidate mapping."
    )
    parser.add_argument("--start-period", required=True)
    parser.add_argument("--end-period", required=True)
    parser.add_argument("--markets", default="twse,tpex")
    parser.add_argument("--stock-code", default=None)
    parser.add_argument("--raw-dir", type=Path, default=None)
    parser.add_argument("--source-json-dir", type=Path, default=None)
    parser.add_argument("--mops-html-dir", type=Path, default=None)
    parser.add_argument("--mops-static", action="store_true")
    parser.add_argument("--pit-csv", type=Path, default=None)
    parser.add_argument("--pit-source", default=TEJ_PIT_HISTORY_SOURCE)
    parser.add_argument("--pit-source-version", default="")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fetch-date", default=date.today().isoformat())
    args = parser.parse_args(argv)

    markets = tuple(item.strip() for item in args.markets.split(",") if item.strip())
    config = TWStockConfig()
    raw_dir = args.raw_dir or (config.data_root / "financial_data")
    if args.pit_csv is not None:
        pit_rows, fetch_diagnostics = load_pit_announcement_rows(
            args.pit_csv,
            source=args.pit_source,
            source_version=args.pit_source_version,
        )
        build_markets = (markets[0],) if markets else ("twse",)
        official_rows_by_market = {build_markets[0]: pit_rows}
    else:
        official_rows_by_market, fetch_diagnostics = load_official_rows_for_markets(
            markets=markets,
            source_json_dir=args.source_json_dir,
            mops_html_dir=args.mops_html_dir,
            mops_static=args.mops_static,
            start_period=args.start_period,
            end_period=args.end_period,
        )
        build_markets = markets
    raw_periods = load_raw_monthly_revenue_periods(raw_dir)
    result = build_historical_monthly_revenue_availability(
        official_rows_by_market=official_rows_by_market,
        raw_periods=raw_periods,
        start_period=args.start_period,
        end_period=args.end_period,
        markets=build_markets,
        stock_code=args.stock_code,
        fetch_date=date.fromisoformat(args.fetch_date),
    )
    if fetch_diagnostics:
        result = _with_fetch_diagnostics(result, fetch_diagnostics)

    if args.output is not None and result.rows:
        _write_candidate_csv(args.output, result)

    print(result.to_markdown())
    if args.output is not None and result.rows:
        print(f"- output: {args.output}")
    for diagnostic in result.diagnostics:
        print(f"- {diagnostic.code}: {diagnostic.message}")
    return 0 if result.valid_candidate else 1


def _write_candidate_csv(
    output: Path,
    result: MonthlyRevenueAvailabilityHistoryResult,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=MONTHLY_REVENUE_AVAILABILITY_COLUMNS,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(result.rows)


def _with_fetch_diagnostics(
    result: MonthlyRevenueAvailabilityHistoryResult,
    fetch_diagnostics: tuple,
) -> MonthlyRevenueAvailabilityHistoryResult:
    diagnostics = tuple(result.diagnostics) + tuple(fetch_diagnostics)
    diagnostics_by_source = dict(result.diagnostics_by_source or {})
    for diagnostic in fetch_diagnostics:
        source = diagnostic.factor_name.rsplit(".", maxsplit=1)[-1]
        diagnostics_by_source[source] = diagnostics_by_source.get(source, 0) + 1
    return MonthlyRevenueAvailabilityHistoryResult(
        rows=result.rows,
        requested_periods=result.requested_periods,
        fetched_periods=result.fetched_periods,
        matched_raw_monthly_revenue_rows=result.matched_raw_monthly_revenue_rows,
        missing_availability_count=result.missing_availability_count,
        duplicate_mapping_rows=result.duplicate_mapping_rows,
        diagnostics=diagnostics,
        diagnostics_by_source=diagnostics_by_source,
    )


if __name__ == "__main__":
    raise SystemExit(main())
