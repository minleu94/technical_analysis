from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.config import TWStockConfig
from data_module.monthly_revenue_backfill import (
    apply_monthly_revenue_backfill,
    plan_monthly_revenue_backfill,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run or apply monthly revenue normalized fundamental backfill."
    )
    parser.add_argument("--db-file", type=Path, default=None)
    parser.add_argument("--raw-dir", type=Path, default=None)
    parser.add_argument("--availability-file", type=Path, default=None)
    parser.add_argument("--backup-dir", type=Path, default=None)
    parser.add_argument("--source-version", default=f"financial-data-csv-monthly-revenue-{date.today().isoformat()}")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", choices=["apply-monthly-revenue-backfill"], default=None)
    args = parser.parse_args(argv)

    config = TWStockConfig()
    db_file = args.db_file or config.db_file
    raw_dir = args.raw_dir or (config.data_root / "financial_data")
    availability_file = args.availability_file or config.monthly_revenue_availability_file
    backup_dir = args.backup_dir or config.backup_dir

    if args.apply:
        if args.confirm != "apply-monthly-revenue-backfill":
            print(
                "Applying monthly revenue backfill requires "
                "--confirm apply-monthly-revenue-backfill"
            )
            return 2
        result = apply_monthly_revenue_backfill(
            db_file=db_file,
            backup_dir=backup_dir,
            raw_dir=raw_dir,
            availability_file=availability_file,
            source_version=args.source_version,
        )
        print(result.plan.to_markdown())
        print(f"- applied: {str(result.applied).lower()}")
        print(f"- inserted_count: {result.inserted_count}")
        print(f"- backup_file: {result.backup_file or 'none'}")
        for diagnostic in result.plan.diagnostics:
            print(f"- {diagnostic.code}: {diagnostic.message}")
        return 0 if result.applied else 1

    plan = plan_monthly_revenue_backfill(
        raw_dir=raw_dir,
        availability_file=availability_file,
        source_version=args.source_version,
    )
    print(plan.to_markdown())
    for diagnostic in plan.diagnostics:
        print(f"- {diagnostic.code}: {diagnostic.message}")
    return 0 if plan.ready_for_apply else 1


if __name__ == "__main__":
    raise SystemExit(main())
