from __future__ import annotations

import argparse
import csv
import sys
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.fundamental_availability import RETROACTIVE_BASELINE_SOURCE
from data_module.fundamental_availability_sources import (
    MONTHLY_REVENUE_AVAILABILITY_COLUMNS,
)


@dataclass(frozen=True)
class RetroactiveBaselineMappingPlan:
    rows: tuple[dict[str, str], ...]
    snapshot_row_count: int
    duplicate_snapshot_rows: int

    @property
    def ready_for_output(self) -> bool:
        return bool(self.rows)

    def to_markdown(self, sample_size: int = 5) -> str:
        lines = [
            "# Monthly Revenue Retroactive Baseline Mapping",
            "",
            f"- ready_for_output: {str(self.ready_for_output).lower()}",
            f"- snapshot_row_count: {self.snapshot_row_count}",
            f"- candidate_row_count: {len(self.rows)}",
            f"- duplicate_snapshot_rows: {self.duplicate_snapshot_rows}",
            f"- source: {RETROACTIVE_BASELINE_SOURCE}",
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
                        "as_of_date",
                        "available_date",
                        "source_version",
                    )
                )
            )
        if not self.rows:
            lines.append("- none")
        return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build candidate monthly revenue availability mapping for retroactive "
            "baseline use from a MOPS snapshot. This is not an official announcement "
            "date mapping and should not be used for historical backtests before "
            "the explicit available date."
        )
    )
    parser.add_argument("--snapshot-file", type=Path, required=True)
    parser.add_argument("--start-period", default=None)
    parser.add_argument("--end-period", default=None)
    parser.add_argument("--available-date", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    plan = build_retroactive_baseline_mapping(
        snapshot_file=args.snapshot_file,
        start_period=args.start_period,
        end_period=args.end_period,
        available_date=date.fromisoformat(args.available_date),
        source_version=args.source_version,
    )
    if args.output is not None and plan.ready_for_output:
        _write_mapping(args.output, plan.rows)

    print(plan.to_markdown())
    if args.output is not None and plan.ready_for_output:
        print(f"- output: {args.output}")
    return 0 if plan.ready_for_output else 1


def build_retroactive_baseline_mapping(
    *,
    snapshot_file: Path,
    start_period: str | None = None,
    end_period: str | None = None,
    available_date: date,
    source_version: str,
) -> RetroactiveBaselineMappingPlan:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    duplicate_count = 0
    snapshot_row_count = 0

    with Path(snapshot_file).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for source_row in reader:
            snapshot_row_count += 1
            stock_code = (source_row.get("stock_code") or "").strip()
            period = (source_row.get("period") or "").strip()
            if not stock_code or not period:
                continue
            if start_period is not None and period < start_period:
                continue
            if end_period is not None and period > end_period:
                continue
            key = (stock_code, period)
            if key in seen:
                duplicate_count += 1
                continue
            seen.add(key)
            rows.append(
                {
                    "stock_code": stock_code,
                    "period": period,
                    "as_of_date": _period_end(period).isoformat(),
                    "announced_date": "",
                    "available_date": available_date.isoformat(),
                    "source": RETROACTIVE_BASELINE_SOURCE,
                    "source_version": source_version,
                }
            )

    rows.sort(key=lambda row: (row["stock_code"], row["period"]))
    return RetroactiveBaselineMappingPlan(
        rows=tuple(rows),
        snapshot_row_count=snapshot_row_count,
        duplicate_snapshot_rows=duplicate_count,
    )


def _write_mapping(output: Path, rows: tuple[dict[str, str], ...]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=MONTHLY_REVENUE_AVAILABILITY_COLUMNS,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _period_end(period: str) -> date:
    year_text, month_text = period.split("-", maxsplit=1)
    year = int(year_text)
    month = int(month_text)
    return date(year, month, monthrange(year, month)[1])


if __name__ == "__main__":
    raise SystemExit(main())
