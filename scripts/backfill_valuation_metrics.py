from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.config import TWStockConfig
from data_module.valuation_metrics_backfill import (
    apply_valuation_metrics_backfill,
    load_industry_by_stock_from_companies,
    plan_valuation_metrics_backfill,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run or apply daily P/E valuation metrics backfill."
    )
    parser.add_argument("--db-file", type=Path, default=None)
    parser.add_argument("--companies-file", type=Path, default=None)
    parser.add_argument("--backup-dir", type=Path, default=None)
    parser.add_argument("--as-of-date", default=None)
    parser.add_argument("--source-version", default=f"daily-prices-pe-{date.today().isoformat()}")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", choices=["apply-valuation-metrics-backfill"], default=None)
    args = parser.parse_args(argv)

    config = TWStockConfig()
    db_file = args.db_file or config.db_file
    companies_file = args.companies_file or (config.meta_data_dir / "companies.csv")
    backup_dir = args.backup_dir or config.backup_dir
    industry_by_stock = load_industry_by_stock_from_companies(companies_file)

    if args.apply:
        if args.confirm != "apply-valuation-metrics-backfill":
            print(
                "Applying valuation metrics backfill requires "
                "--confirm apply-valuation-metrics-backfill"
            )
            return 2
        result = apply_valuation_metrics_backfill(
            db_file=db_file,
            backup_dir=backup_dir,
            as_of_date=args.as_of_date,
            industry_by_stock=industry_by_stock,
            source_version=args.source_version,
        )
        print(result.plan.to_markdown())
        print(f"- applied: {str(result.applied).lower()}")
        print(f"- inserted_count: {result.inserted_count}")
        print(f"- backup_file: {result.backup_file or 'none'}")
        for diagnostic in result.plan.diagnostics:
            print(f"- {diagnostic.code}: {diagnostic.stock_code} {diagnostic.message}".rstrip())
        return 0 if result.applied else 1

    plan = plan_valuation_metrics_backfill(
        db_file=db_file,
        as_of_date=args.as_of_date,
        industry_by_stock=industry_by_stock,
        source_version=args.source_version,
    )
    print(plan.to_markdown())
    for diagnostic in plan.diagnostics:
        print(f"- {diagnostic.code}: {diagnostic.stock_code} {diagnostic.message}".rstrip())
    return 0 if plan.ready_for_apply else 1


if __name__ == "__main__":
    raise SystemExit(main())
