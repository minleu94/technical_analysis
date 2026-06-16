from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.config import TWStockConfig
from data_module.finmind_monthly_revenue_create_time import (
    calculate_sleep_seconds,
    fetch_finmind_monthly_revenue_rows,
    harvest_finmind_monthly_revenue_create_time,
    load_finmind_token,
    load_stock_codes_from_raw_monthly_revenue_dir,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch FinMind monthly revenue create_time candidate observations."
    )
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--raw-dir", type=Path, default=None)
    parser.add_argument("--stock-code", action="append", default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--state-file", type=Path, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-requests-per-hour", type=int, default=540)
    parser.add_argument("--fetch-date", default=date.today().isoformat())
    parser.add_argument("--token-file", type=Path, default=None)
    args = parser.parse_args(argv)

    config = TWStockConfig()
    raw_dir = args.raw_dir or (config.data_root / "financial_data")
    output_dir = args.output_dir or config.resolve_output_path(
        "monthly_revenue_finmind_create_time"
    )
    stock_codes = (
        tuple(args.stock_code)
        if args.stock_code
        else load_stock_codes_from_raw_monthly_revenue_dir(raw_dir)
    )
    token = load_finmind_token(args.token_file)
    result = harvest_finmind_monthly_revenue_create_time(
        stock_codes=stock_codes,
        start_date=args.start_date,
        end_date=args.end_date,
        token=token,
        fetch_rows=fetch_finmind_monthly_revenue_rows,
        output_dir=output_dir,
        state_file=args.state_file or (output_dir / "finmind_monthly_revenue_fetch_state.json"),
        resume=args.resume,
        fetch_date=date.fromisoformat(args.fetch_date),
        sleep_seconds=calculate_sleep_seconds(args.max_requests_per_hour),
    )

    _safe_print(result.to_markdown())
    if result.row_output is not None:
        _safe_print(f"- output_csv: {result.row_output}")
    if result.group_output is not None:
        _safe_print(f"- group_csv: {result.group_output}")
    if result.state_file is not None:
        _safe_print(f"- state_file: {result.state_file}")
    return 0 if result.failed_stock_count == 0 else 1


def _safe_print(text: str) -> None:
    stream = sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        stream.write(text + "\n")
    except UnicodeEncodeError:
        safe_text = text.encode(encoding, errors="backslashreplace").decode(encoding)
        stream.write(safe_text + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
