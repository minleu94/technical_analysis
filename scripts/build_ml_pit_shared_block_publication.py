"""把既有 PIT dataset manifest 發布成 shared immutable shard references。"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.ml_pit_shared_block_resolver import (  # noqa: E402
    build_shared_pit_publication,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Publish an existing PIT dataset's gzip shards as immutable "
            "cross-run references without copying shards into the new run."
        )
    )
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument("--shared-store", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--lock-path", type=Path)
    parser.add_argument("--max-store-bytes", type=int, default=256 * 1024 * 1024)
    parser.add_argument("--maturity-policy", default="raw_observed_only.v1")
    parser.add_argument(
        "--lane",
        choices=("formal", "research_shadow"),
        default="research_shadow",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    publication = build_shared_pit_publication(
        dataset_manifest_path=args.dataset_manifest,
        shared_store_root=args.shared_store,
        output_root=args.output_dir,
        lock_path=args.lock_path,
        max_store_bytes=args.max_store_bytes,
        maturity_policy=args.maturity_policy,
        lane=args.lane,
    )
    payload = {
        **asdict(publication),
        "output_root": str(publication.output_root),
        "manifest_path": str(publication.manifest_path),
        "latest_manifest_path": str(publication.latest_manifest_path),
        "block_results": [dict(item) for item in publication.block_results],
        "source_database_opened": False,
        "production_action_allowed": False,
        "alpha_bp": 0,
    }
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2 if args.pretty else None,
            separators=None if args.pretty else (",", ":"),
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
