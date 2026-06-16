from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.config import TWStockConfig
from data_module.tpex_daily_price_backfill import (
    apply_tpex_daily_price_backfill,
    build_tpex_daily_price_plan,
)

TPEX_DAILY_CLOSE_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run or apply TPEX daily price backfill.")
    parser.add_argument("--db-file", type=Path, default=None)
    parser.add_argument("--backup-dir", type=Path, default=None)
    parser.add_argument("--source-json", type=Path, default=None)
    parser.add_argument("--date", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", choices=["apply-tpex-daily-price-backfill"], default=None)
    args = parser.parse_args(argv)

    config = TWStockConfig()
    db_file = args.db_file or config.db_file
    backup_dir = args.backup_dir or config.backup_dir
    source_rows = _load_source_rows(args.source_json)

    if args.apply:
        if args.confirm != "apply-tpex-daily-price-backfill":
            print("Applying TPEX daily price backfill requires --confirm apply-tpex-daily-price-backfill")
            return 2
        result = apply_tpex_daily_price_backfill(
            db_file=db_file,
            backup_dir=backup_dir,
            source_rows=source_rows,
            fallback_date=args.date,
        )
        print(result.plan.to_markdown())
        print(f"- applied: {str(result.applied).lower()}")
        print(f"- inserted_count: {result.inserted_count}")
        print(f"- backup_file: {result.backup_file or 'none'}")
        return 0 if result.applied else 1

    plan = build_tpex_daily_price_plan(
        db_file=db_file,
        source_rows=source_rows,
        fallback_date=args.date,
    )
    print(plan.to_markdown())
    for diagnostic in plan.diagnostics:
        print(f"- {diagnostic.code}: {diagnostic.stock_code} {diagnostic.message}".rstrip())
    return 0 if plan.ready_for_apply else 1


def _load_source_rows(source_json: Path | None) -> list[dict[str, Any]]:
    if source_json is not None:
        data = json.loads(Path(source_json).read_text(encoding="utf-8"))
    else:
        response = requests.get(
            TPEX_DAILY_CLOSE_URL,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, list):
        raise ValueError("TPEX daily close response is not a list")
    return data


if __name__ == "__main__":
    raise SystemExit(main())
