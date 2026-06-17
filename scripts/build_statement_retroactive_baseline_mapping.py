from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.config import TWStockConfig
from data_module.fundamental_availability import RETROACTIVE_STATEMENT_BASELINE_SOURCE
from data_module.fundamental_statement_availability_sources import (
    STATEMENT_AVAILABILITY_COLUMNS,
)


STATEMENT_FILE_SUFFIXES = {
    "income_statement": "_income_statement.csv",
    "balance_sheet": "_balance_sheet.csv",
    "cash_flows_statement": "_cash_flows_statement.csv",
}


@dataclass(frozen=True)
class StatementRetroactiveBaselinePlan:
    rows: tuple[dict[str, str], ...]
    raw_row_count: int
    duplicate_raw_period_rows: int

    @property
    def ready_for_output(self) -> bool:
        return bool(self.rows)

    def to_markdown(self, sample_size: int = 5) -> str:
        lines = [
            "# Statement Retroactive Baseline Mapping",
            "",
            f"- ready_for_output: {str(self.ready_for_output).lower()}",
            f"- raw_row_count: {self.raw_row_count}",
            f"- candidate_row_count: {len(self.rows)}",
            f"- duplicate_raw_period_rows: {self.duplicate_raw_period_rows}",
            f"- source: {RETROACTIVE_STATEMENT_BASELINE_SOURCE}",
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
                        "statement_type",
                        "period",
                        "as_of_date",
                        "available_date",
                    )
                )
            )
        if not self.rows:
            lines.append("- none")
        return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build candidate quarterly statement availability mapping for "
            "retroactive baseline use. This is not an official announcement-date mapping."
        )
    )
    parser.add_argument("--raw-dir", type=Path, default=None)
    parser.add_argument("--statement-types", default="income_statement,balance_sheet,cash_flows_statement")
    parser.add_argument("--start-period", default=None)
    parser.add_argument("--end-period", default=None)
    parser.add_argument("--available-date", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    config = TWStockConfig()
    raw_dir = args.raw_dir or (config.data_root / "financial_data")
    statement_types = tuple(
        item.strip() for item in args.statement_types.split(",") if item.strip()
    )
    plan = build_statement_retroactive_baseline_mapping(
        raw_dir=raw_dir,
        statement_types=statement_types,
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


def build_statement_retroactive_baseline_mapping(
    *,
    raw_dir: Path,
    statement_types: tuple[str, ...],
    start_period: str | None,
    end_period: str | None,
    available_date: date,
    source_version: str,
) -> StatementRetroactiveBaselinePlan:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    raw_row_count = 0
    duplicate_count = 0

    for statement_type in statement_types:
        suffix = STATEMENT_FILE_SUFFIXES[statement_type]
        for csv_path in sorted(Path(raw_dir).glob(f"*{suffix}")):
            with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                for source_row in reader:
                    raw_row_count += 1
                    stock_code = (source_row.get("stock_id") or "").strip()
                    as_of_date = _parse_iso_date(source_row.get("date", ""))
                    period = _quarter_period(as_of_date)
                    if start_period is not None and period < start_period:
                        continue
                    if end_period is not None and period > end_period:
                        continue
                    key = (stock_code, statement_type, period)
                    if key in seen:
                        duplicate_count += 1
                        continue
                    seen.add(key)
                    rows.append(
                        {
                            "stock_code": stock_code,
                            "statement_type": statement_type,
                            "period": period,
                            "as_of_date": as_of_date.isoformat(),
                            "announced_date": "",
                            "available_date": available_date.isoformat(),
                            "source": RETROACTIVE_STATEMENT_BASELINE_SOURCE,
                            "source_version": source_version,
                        }
                    )

    rows.sort(key=lambda row: (row["stock_code"], row["statement_type"], row["period"]))
    return StatementRetroactiveBaselinePlan(
        rows=tuple(rows),
        raw_row_count=raw_row_count,
        duplicate_raw_period_rows=duplicate_count,
    )


def _write_mapping(output: Path, rows: tuple[dict[str, str], ...]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=STATEMENT_AVAILABILITY_COLUMNS,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _quarter_period(value: date) -> str:
    quarter = ((value.month - 1) // 3) + 1
    return f"{value.year:04d}-Q{quarter}"


def _parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


if __name__ == "__main__":
    raise SystemExit(main())
