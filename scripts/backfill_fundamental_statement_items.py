from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.config import TWStockConfig
from data_module.fundamental_statement_backfill import (
    apply_statement_items_backfill,
    plan_statement_items_backfill,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run or apply quarterly statement item fundamental backfill."
    )
    parser.add_argument("--db-file", type=Path, default=None)
    parser.add_argument("--raw-dir", type=Path, default=None)
    parser.add_argument("--availability-file", type=Path, default=None)
    parser.add_argument("--backup-dir", type=Path, default=None)
    parser.add_argument("--statement-types", default="income_statement,balance_sheet,cash_flows_statement")
    parser.add_argument("--source-version", default=f"financial-data-statements-{date.today().isoformat()}")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", choices=["apply-statement-items-backfill"], default=None)
    args = parser.parse_args(argv)

    if args.apply and args.confirm != "apply-statement-items-backfill":
        print(
            "Applying statement items backfill requires "
            "--confirm apply-statement-items-backfill"
        )
        return 2

    config: TWStockConfig | None = None
    if (
        args.raw_dir is None
        or args.availability_file is None
        or (args.apply and (args.db_file is None or args.backup_dir is None))
    ):
        config = TWStockConfig()

    if args.raw_dir is not None:
        raw_dir = args.raw_dir
    else:
        assert config is not None
        raw_dir = config.data_root / "financial_data"
    if args.availability_file is not None:
        availability_file = args.availability_file
    else:
        assert config is not None
        availability_file = config.statement_availability_file
    statement_types = tuple(
        item.strip() for item in args.statement_types.split(",") if item.strip()
    )

    if args.apply:
        if args.db_file is not None:
            db_file = args.db_file
        else:
            assert config is not None
            db_file = config.db_file
        if args.backup_dir is not None:
            backup_dir = args.backup_dir
        else:
            assert config is not None
            backup_dir = config.backup_dir
        result = apply_statement_items_backfill(
            db_file=db_file,
            backup_dir=backup_dir,
            raw_dir=raw_dir,
            availability_file=availability_file,
            source_version=args.source_version,
            statement_types=statement_types,
        )
        print(result.plan.to_markdown())
        print(f"- applied: {str(result.applied).lower()}")
        print(f"- inserted_count: {result.inserted_count}")
        print(f"- backup_file: {result.backup_file or 'none'}")
        for diagnostic in result.plan.diagnostics:
            print(f"- {diagnostic.code}: {diagnostic.message}")
        return 0 if result.applied else 1

    plan = plan_statement_items_backfill(
        raw_dir=raw_dir,
        availability_file=availability_file,
        source_version=args.source_version,
        statement_types=statement_types,
        diagnostic_limit=20,
    )
    print(plan.to_markdown())
    for diagnostic in plan.diagnostics:
        print(f"- {diagnostic.code}: {diagnostic.message}")
    if len(plan.diagnostics) < plan.diagnostic_count:
        print(f"- diagnostics_shown: {len(plan.diagnostics)} (bounded)")
    return 0 if plan.ready_for_apply else 1


if __name__ == "__main__":
    raise SystemExit(main())
