from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.config import TWStockConfig
from data_module.fundamental_availability_sources import (
    MONTHLY_REVENUE_AVAILABILITY_COLUMNS,
)
from data_module.monthly_revenue_availability_builder import (
    MonthlyRevenueAvailabilityBuildResult,
    build_monthly_revenue_availability_rows,
    load_raw_monthly_revenue_periods,
)


TWSE_MONTHLY_REVENUE_OPENAPI_URL = (
    "https://openapi.twse.com.tw/v1/opendata/t187ap05_P"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a governed monthly revenue availability candidate CSV."
    )
    parser.add_argument("--source-json", type=Path, default=None)
    parser.add_argument("--source-url", default=TWSE_MONTHLY_REVENUE_OPENAPI_URL)
    parser.add_argument("--raw-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fetch-date", default=date.today().isoformat())
    args = parser.parse_args(argv)

    config = TWStockConfig()
    raw_dir = args.raw_dir or (config.data_root / "financial_data")
    official_rows = _load_official_rows(args.source_json, args.source_url)
    raw_periods = load_raw_monthly_revenue_periods(raw_dir)
    result = build_monthly_revenue_availability_rows(
        official_rows,
        raw_periods=raw_periods,
        fetch_date=date.fromisoformat(args.fetch_date),
    )

    if args.output is not None and result.rows:
        _write_candidate_csv(args.output, result)

    print("# Monthly Revenue Availability Candidate")
    print("")
    print(f"- official_rows: {len(official_rows)}")
    print(f"- raw_periods: {len(raw_periods)}")
    print(f"- candidate_rows: {len(result.rows)}")
    print(f"- skipped_not_in_raw_count: {result.skipped_not_in_raw_count}")
    print(f"- diagnostics: {len(result.diagnostics)}")
    if args.output is not None and result.rows:
        print(f"- output: {args.output}")
    for diagnostic in result.diagnostics:
        print(f"- {diagnostic}")

    return 0 if result.rows and not result.diagnostics else 1


def _load_official_rows(
    source_json: Path | None,
    source_url: str,
) -> list[dict[str, str]]:
    if source_json is not None:
        return json.loads(source_json.read_text(encoding="utf-8-sig"))

    request = Request(source_url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=30) as response:
        payload = response.read().decode("utf-8-sig")
    return json.loads(payload)


def _write_candidate_csv(
    output: Path,
    result: MonthlyRevenueAvailabilityBuildResult,
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


if __name__ == "__main__":
    raise SystemExit(main())
