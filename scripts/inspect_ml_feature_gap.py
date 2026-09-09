"""Bounded read-only probe for the V4 market/technical feature gaps."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml_module.feature_gap_diagnostics import (  # noqa: E402
    FeatureGapDiagnosticError,
    diagnose_sqlite_feature_gaps,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--expected-price-date", required=True)
    parser.add_argument("--previous-price-date", required=True)
    parser.add_argument(
        "--symbols",
        nargs="+",
        required=True,
        help="bounded stock codes; no implicit full-table scan",
    )
    parser.add_argument("--market-entity", default="TAIEX")
    parser.add_argument(
        "--post-freeze-parent-input",
        type=Path,
        default=None,
        help="optional frozen v2 post-freeze input for PIT market evidence",
    )
    parser.add_argument(
        "--expected-post-freeze-parent-input-compressed-hash",
        default=None,
    )
    parser.add_argument(
        "--post-freeze-raw-dataset-manifest",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--expected-post-freeze-raw-publication-manifest-hash",
        default=None,
    )
    parser.add_argument(
        "--expected-post-freeze-raw-dataset-manifest-hash",
        default=None,
    )
    parser.add_argument(
        "--post-freeze-calendar-database",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--post-freeze-calendar-cache-path",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--post-freeze-temporary-closure-path",
        type=Path,
        default=None,
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_standard_streams_utf8()
    args = _parser().parse_args(argv)
    try:
        report = diagnose_sqlite_feature_gaps(
            args.database,
            expected_price_date=args.expected_price_date,
            previous_price_date=args.previous_price_date,
            symbols=tuple(args.symbols),
            market_entity=args.market_entity,
            post_freeze_parent_input=args.post_freeze_parent_input,
            expected_post_freeze_parent_input_compressed_hash=(
                args.expected_post_freeze_parent_input_compressed_hash
            ),
            post_freeze_raw_dataset_manifest=args.post_freeze_raw_dataset_manifest,
            expected_post_freeze_raw_publication_manifest_hash=(
                args.expected_post_freeze_raw_publication_manifest_hash
            ),
            expected_post_freeze_raw_dataset_manifest_hash=(
                args.expected_post_freeze_raw_dataset_manifest_hash
            ),
            post_freeze_calendar_database=args.post_freeze_calendar_database,
            post_freeze_calendar_cache_path=args.post_freeze_calendar_cache_path,
            post_freeze_temporary_closure_path=(
                args.post_freeze_temporary_closure_path
            ),
        )
    except (FeatureGapDiagnosticError, OSError, TypeError, ValueError) as exc:
        payload = {
            "schema_version": "v4-ml-feature-gap-diagnostic.v1",
            "status": "blocked",
            "error_type": type(exc).__name__,
            "message": str(exc),
            "source_read_only": True,
            "bounded_query": True,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2

    payload = {
        **report,
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }
    raw = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(raw)
    print(json.dumps({**payload, "output": str(output)}, ensure_ascii=False, sort_keys=True))
    return 0


def _configure_standard_streams_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                pass


if __name__ == "__main__":
    raise SystemExit(main())
