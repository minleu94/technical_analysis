"""稽核 SQLite daily_prices 與 canonical daily CSV，必要時建立 quarantine。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.ml_daily_price_source_quality import (  # noqa: E402
    audit_daily_price_source,
    write_quarantine_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument(
        "--daily-price-dir",
        type=Path,
        action="append",
        dest="daily_price_dirs",
        required=True,
        help="repeat for explicit TWSE/TPEX canonical source roots",
    )
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--symbol", action="append", dest="symbols")
    parser.add_argument("--source-manifest-hash")
    parser.add_argument(
        "--quality-mode",
        choices=("retrospective_audit", "ingest_guard"),
        default="retrospective_audit",
        help=(
            "retrospective_audit reads the next row for posthoc evidence; "
            "ingest_guard never reads future rows"
        ),
    )
    parser.add_argument(
        "--quality-known-at",
        help="optional timezone-aware source receipt time; never inferred from mtime",
    )
    parser.add_argument(
        "--candidate-sample-limit",
        type=int,
        default=64,
        help=(
            "maximum candidate evidence rows retained in the report; "
            "counts remain full and zero disables samples"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="repo output quarantine/report path; never a source path",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_stdio()
    args = build_parser().parse_args(argv)
    report = audit_daily_price_source(
        sqlite_path=args.sqlite,
        canonical_daily_price_dirs=tuple(args.daily_price_dirs),
        start_date=args.start_date,
        end_date=args.end_date,
        symbols=args.symbols,
        source_manifest_hash=args.source_manifest_hash,
        quality_mode=args.quality_mode,
        quality_known_at=args.quality_known_at,
        candidate_sample_limit=args.candidate_sample_limit,
    )
    output = write_quarantine_report(
        args.output,
        report,
        source_roots=(args.sqlite.parent, *tuple(args.daily_price_dirs)),
    )
    payload = dict(report)
    payload["report_path"] = str(output.resolve())
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2 if args.pretty else None,
            separators=None if args.pretty else (",", ":"),
        )
    )
    # A quarantine is a successful audit operation but a failed source gate;
    # scheduled callers can therefore stop before building a new PIT artifact.
    return 2 if int(report["candidate_count"]) > 0 else 0


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
