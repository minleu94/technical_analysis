from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.config import TWStockConfig
from data_module.tpex_daily_price_history_plan import build_tpex_daily_price_history_plan
from data_module.tpex_daily_price_source import TPEX_DAILY_CLOSE_URL


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run TPEX historical daily price backfill plan.")
    parser.add_argument("--db-file", type=Path, default=None)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--source-json-dir", type=Path, default=None)
    parser.add_argument("--delay-seconds", type=int, default=4)
    args = parser.parse_args(argv)

    config = TWStockConfig()
    db_file = args.db_file or config.db_file

    def fetch_rows(date_key: str) -> list[Mapping[str, Any]]:
        if args.source_json_dir is not None:
            path = args.source_json_dir / f"{date_key}.json"
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            response = requests.get(
                TPEX_DAILY_CLOSE_URL,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, list):
            raise ValueError(f"TPEX source for {date_key} is not a list")
        return data

    plan = build_tpex_daily_price_history_plan(
        db_file=db_file,
        start_date=args.start_date,
        end_date=args.end_date,
        fetch_rows_for_date=fetch_rows,
        delay_seconds=args.delay_seconds,
    )
    print(plan.to_markdown())
    if plan.failed_dates:
        print("")
        print("## Failed Dates")
        for date_key in plan.failed_dates:
            print(f"- {date_key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

