"""擷取 TWSE MI_INDEX 歷史日價 response，建立唯讀研究 evidence。

此入口只允許建立 repo output 下的 candidate evidence；不寫入 DATA_ROOT、
SQLite、daily CSV、feature 或 label。指定日期是歷史回補，擷取完成時間不會
被宣告為原決策時點的可得時間。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.twse_historical_daily_capture import (  # noqa: E402
    capture_twse_historical_daily,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--daily-price-dir", type=Path, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--symbol", action="append", dest="symbols", required=True)
    parser.add_argument("--historical-backup", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--request-type", choices=("ALL", "ALLBUT0999"), default="ALL")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = capture_twse_historical_daily(
        sqlite_path=args.sqlite,
        canonical_daily_price_dir=args.daily_price_dir,
        date_value=args.date,
        symbols=tuple(args.symbols),
        output_root=args.output_root,
        historical_backup_path=args.historical_backup,
        request_type=args.request_type,
        timeout_seconds=args.timeout_seconds,
    )
    print(
        json.dumps(
            {
                "capture_id": result.capture_id,
                "capture_directory": str(result.capture_directory.resolve()),
                "response_path": str(result.response_path.resolve()),
                "receipt_path": str(result.receipt_path.resolve()),
                "comparison_path": str(result.comparison_path.resolve()),
                "response_sha256": result.response_sha256,
                "comparison_hash": result.comparison_hash,
                "candidate_count": result.candidate_count,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
