"""建立 TWSE／TPEx 公司行動與交易限制 Formal PIT publication。"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.official_market_event_backfill import (
    OfficialMarketEventBackfillBuilder,
    OfficialMarketEventBackfillRequest,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch immutable TWSE/TPEx corporate-action and "
            "trading-restriction PIT publications without writing SQLite."
        )
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--raw-custody",
        type=Path,
        help=(
            "Optional failed-custody directory/manifest; validated raw "
            "responses are replayed before fetching missing requests."
        ),
    )
    parser.add_argument("--start-year", type=int, default=2014)
    parser.add_argument(
        "--end-year",
        type=int,
        default=datetime.now().year,
    )
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--retry-delay-seconds", type=int, default=2)
    parser.add_argument("--request-delay-seconds", type=int, default=1)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    publication = OfficialMarketEventBackfillBuilder().build(
        OfficialMarketEventBackfillRequest(
            output_root=args.output_root,
            raw_custody=args.raw_custody,
            start_year=args.start_year,
            end_year=args.end_year,
            timeout_seconds=args.timeout_seconds,
            max_attempts=args.max_attempts,
            retry_delay_seconds=args.retry_delay_seconds,
            request_delay_seconds=args.request_delay_seconds,
        )
    )
    print(
        json.dumps(
            {
                "status": "published",
                "publication_id": publication.publication_id,
                "publication_directory": str(
                    publication.publication_directory
                ),
                "manifest_path": str(publication.manifest_path),
                "latest_manifest_path": str(
                    publication.latest_manifest_path
                ),
                "manifest_hash": publication.manifest_hash,
                "manifest_file_hash": publication.manifest_file_hash,
                "canonical_events_path": str(
                    publication.canonical_events_path
                ),
                "canonical_events_hash": (
                    publication.canonical_events_hash
                ),
                "canonical_event_count": (
                    publication.canonical_event_count
                ),
                "new_event_count": publication.new_event_count,
                "raw_request_count": publication.raw_request_count,
                "active_sqlite_written": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
