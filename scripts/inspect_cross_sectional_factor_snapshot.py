from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from app_module.cross_sectional_factor_attribution import (
    build_cross_sectional_factor_attribution_summary,
    render_cross_sectional_factor_summary_markdown,
)
from app_module.cross_sectional_factor_repository import CrossSectionalFactorRepository
from app_module.research_run_dtos import canonical_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect V1.6 cross-sectional factor snapshot summary.",
    )
    parser.add_argument("--db-path", required=True, help="SQLite DB path to inspect.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--snapshot-id", help="Snapshot id to inspect.")
    target.add_argument("--latest", action="store_true", help="Inspect latest snapshot.")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="Print JSON output.")
    output.add_argument("--markdown", action="store_true", help="Print Markdown output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"db_path_missing:{db_path}", file=sys.stderr)
        return 2

    repository = CrossSectionalFactorRepository(db_path, ensure_schema=False)
    snapshot_id = args.snapshot_id
    if args.latest:
        snapshot_id = repository.get_latest_snapshot_id()
        if snapshot_id is None:
            print("snapshot_missing", file=sys.stderr)
            return 1
    if snapshot_id is None:
        print("snapshot_id_missing", file=sys.stderr)
        return 1

    try:
        summary = build_cross_sectional_factor_attribution_summary(
            repository,
            snapshot_id=str(snapshot_id),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"snapshot_inspection_failed:{exc}", file=sys.stderr)
        return 1

    if args.markdown:
        print(render_cross_sectional_factor_summary_markdown(summary), end="")
    else:
        print(canonical_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
