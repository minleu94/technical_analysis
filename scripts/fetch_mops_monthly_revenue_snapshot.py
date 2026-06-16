from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.config import TWStockConfig
from data_module.monthly_revenue_snapshot_harvester import (
    build_mops_monthly_revenue_snapshot,
    fetch_mops_static_monthly_revenue_html,
    write_mops_snapshot_csv,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch MOPS static monthly revenue full-market snapshot candidates."
    )
    parser.add_argument("--start-period", required=True)
    parser.add_argument("--end-period", required=True)
    parser.add_argument("--markets", default="twse,tpex")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--fetch-date", default=date.today().isoformat())
    parser.add_argument("--no-save-html", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=0.5)
    args = parser.parse_args(argv)

    markets = tuple(item.strip() for item in args.markets.split(",") if item.strip())
    fetch_date = date.fromisoformat(args.fetch_date)
    output_dir = args.output_dir or TWStockConfig().resolve_output_path(
        "monthly_revenue_mops_snapshots"
    )
    html_dir = None if args.no_save_html else output_dir / "raw_html"
    result = build_mops_monthly_revenue_snapshot(
        start_period=args.start_period,
        end_period=args.end_period,
        markets=markets,
        fetch_date=fetch_date,
        fetch_html=fetch_mops_static_monthly_revenue_html,
        save_html_dir=html_dir,
        sleep_seconds=args.sleep_seconds,
    )

    output_csv = output_dir / (
        f"mops_monthly_revenue_snapshot_{args.start_period}_{args.end_period}_"
        f"{fetch_date.isoformat()}.csv"
    )
    if result.rows:
        write_mops_snapshot_csv(output_csv, result.rows)

    _safe_print(result.to_markdown())
    if result.rows:
        _safe_print(f"- output_csv: {output_csv}")
    if html_dir is not None:
        _safe_print(f"- raw_html_dir: {html_dir}")
    for diagnostic in result.diagnostics:
        _safe_print(f"- {diagnostic.code}: {diagnostic.message}")
    return 0 if result.valid_candidate else 1


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
