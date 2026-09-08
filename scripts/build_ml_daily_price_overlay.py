"""建立隔離 daily price candidate overlay；不修改任何 D source。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.ml_daily_price_overlay import build_daily_price_overlay  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--daily-price-dir", type=Path, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--symbol", action="append", dest="symbols", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-manifest-hash")
    parser.add_argument("--official-capture-comparison", type=Path)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_stdio()
    args = build_parser().parse_args(argv)
    output = build_daily_price_overlay(
        sqlite_path=args.sqlite,
        canonical_daily_price_dir=args.daily_price_dir,
        date_value=args.date,
        symbols=tuple(args.symbols),
        output_path=args.output,
        source_manifest_hash=args.source_manifest_hash,
        official_capture_comparison_path=args.official_capture_comparison,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["overlay_path"] = str(output)
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2 if args.pretty else None,
            separators=None if args.pretty else (",", ":"),
        )
    )
    return 0


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
