from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.config import TWStockConfig
from data_module.fundamental_migration import apply_fundamental_schema_migration
from data_module.fundamental_schema import generate_fundamental_schema_copy_dry_run_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run or apply fundamental SQLite schema.")
    parser.add_argument("--db-file", type=Path, default=None)
    parser.add_argument("--working-copy", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", choices=["apply-fundamental-schema"], default=None)
    args = parser.parse_args(argv)

    config = TWStockConfig()
    db_file = args.db_file or config.db_file
    if args.dry_run or not args.apply:
        working_copy = args.working_copy or db_file.with_name("twstock_fundamental_schema_dry_run.db")
        report = generate_fundamental_schema_copy_dry_run_report(db_file, working_copy)
        print(report.to_markdown())
        return 0 if report.existing_tables_preserved else 1

    if args.confirm != "apply-fundamental-schema":
        print("Applying formal fundamental schema requires --confirm apply-fundamental-schema")
        return 2

    result = apply_fundamental_schema_migration(db_file, backup_dir=config.backup_dir)
    if result.report is not None:
        print(result.report.to_markdown())
    print(f"backup_file: {result.backup_file}")
    return 0 if result.applied else 1


if __name__ == "__main__":
    raise SystemExit(main())
