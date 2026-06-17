from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app_module.fundamental_factor_service import FundamentalFactorService
from data_module.config import TWStockConfig


@dataclass(frozen=True)
class StockFactorSummary:
    stock_code: str
    record_count: int
    diagnostic_count: int
    latest_revenue_period: str | None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect governed fundamental factor records from SQLite without writing data."
    )
    parser.add_argument("--db-file", type=Path, default=None)
    parser.add_argument("--decision-date", default=date.today().isoformat())
    parser.add_argument("--stock-code", action="append", default=[])
    parser.add_argument("--all-monthly-revenue-stocks", action="store_true")
    parser.add_argument("--diagnostic-limit", type=int, default=20)
    parser.add_argument("--stock-summary-limit", type=int, default=50)
    args = parser.parse_args(argv)

    config = TWStockConfig()
    db_file = args.db_file or config.db_file
    decision_date = date.fromisoformat(args.decision_date)
    stock_codes = _resolve_stock_codes(
        db_file=db_file,
        explicit_stock_codes=tuple(args.stock_code or ()),
        all_monthly_revenue_stocks=args.all_monthly_revenue_stocks,
        decision_date=decision_date,
    )

    if not stock_codes:
        print("# Fundamental Factor Inspection")
        print("")
        print(f"- db_file: {db_file}")
        print(f"- decision_date: {decision_date.isoformat()}")
        print("- stock_count: 0")
        print("- factor_record_count: 0")
        print("- diagnostic_count: 1")
        print("")
        print("## Diagnostics by code")
        print("- inspect_fundamental_factors.no_stock_codes: 1")
        return 1

    service = FundamentalFactorService(db_file)
    factor_counts: Counter[str] = Counter()
    diagnostic_counts: Counter[str] = Counter()
    stock_summaries: list[StockFactorSummary] = []
    diagnostic_lines: list[str] = []

    for stock_code in stock_codes:
        snapshot = service.build_snapshot(
            stock_code=stock_code,
            decision_date=decision_date,
        )
        factor_counts.update(record.factor_name for record in snapshot.records)
        diagnostic_counts.update(diagnostic.code for diagnostic in snapshot.diagnostics)
        for diagnostic in snapshot.diagnostics[: max(0, args.diagnostic_limit)]:
            diagnostic_lines.append(
                f"- {diagnostic.stock_code} {diagnostic.factor_name} "
                f"{diagnostic.code}: {diagnostic.message}"
            )
        stock_summaries.append(
            StockFactorSummary(
                stock_code=stock_code,
                record_count=len(snapshot.records),
                diagnostic_count=len(snapshot.diagnostics),
                latest_revenue_period=_latest_revenue_period(
                    db_file=db_file,
                    stock_code=stock_code,
                    decision_date=decision_date,
                ),
            )
        )

    print("# Fundamental Factor Inspection")
    print("")
    print(f"- db_file: {db_file}")
    print(f"- decision_date: {decision_date.isoformat()}")
    print(f"- stock_count: {len(stock_codes)}")
    print(f"- factor_record_count: {sum(factor_counts.values())}")
    print(f"- diagnostic_count: {sum(diagnostic_counts.values())}")
    print("- writes_data: false")
    print("- scoring_engine_connected: false")
    print("")

    print("## Factors by name")
    if factor_counts:
        for name, count in sorted(factor_counts.items()):
            print(f"- {name}: {count}")
    else:
        print("- none: 0")
    print("")

    print("## Diagnostics by code")
    if diagnostic_counts:
        for code, count in sorted(diagnostic_counts.items()):
            print(f"- {code}: {count}")
    else:
        print("- none: 0")
    print("")

    print("## Stock summaries")
    summary_limit = max(0, args.stock_summary_limit)
    for summary in stock_summaries[:summary_limit]:
        latest = summary.latest_revenue_period or "none"
        print(
            f"- {summary.stock_code}: records={summary.record_count} "
            f"diagnostics={summary.diagnostic_count} latest_revenue_period={latest}"
        )
    omitted_count = max(0, len(stock_summaries) - summary_limit)
    if omitted_count:
        print(f"- ... {omitted_count} more stocks omitted")

    if diagnostic_lines:
        print("")
        print("## Diagnostic samples")
        for line in diagnostic_lines[: max(0, args.diagnostic_limit)]:
            print(line)

    return 0


def _resolve_stock_codes(
    *,
    db_file: Path,
    explicit_stock_codes: tuple[str, ...],
    all_monthly_revenue_stocks: bool,
    decision_date: date,
) -> tuple[str, ...]:
    cleaned = tuple(dict.fromkeys(code.strip() for code in explicit_stock_codes if code.strip()))
    if cleaned and not all_monthly_revenue_stocks:
        return cleaned

    if not all_monthly_revenue_stocks:
        return cleaned

    with sqlite3.connect(db_file) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT stock_code
            FROM fundamental_monthly_revenues
            WHERE available_date <= ?
            ORDER BY stock_code ASC
            """,
            (decision_date.isoformat(),),
        ).fetchall()
    all_codes = tuple(row[0] for row in rows)
    if cleaned:
        return tuple(dict.fromkeys((*cleaned, *all_codes)))
    return all_codes


def _latest_revenue_period(
    *,
    db_file: Path,
    stock_code: str,
    decision_date: date,
) -> str | None:
    with sqlite3.connect(db_file) as conn:
        row = conn.execute(
            """
            SELECT MAX(period)
            FROM fundamental_monthly_revenues
            WHERE stock_code = ? AND available_date <= ?
            """,
            (stock_code, decision_date.isoformat()),
        ).fetchone()
    if row is None:
        return None
    return row[0]


if __name__ == "__main__":
    raise SystemExit(main())
