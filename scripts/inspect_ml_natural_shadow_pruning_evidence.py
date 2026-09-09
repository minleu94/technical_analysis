"""Read-only natural shadow maturity/pruning evidence projection."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ml_module.natural_shadow_pruning_evidence import (  # noqa: E402
    NaturalShadowPruningEvidenceError,
    build_natural_shadow_pruning_evidence,
    write_natural_shadow_pruning_evidence,
)


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "as-of-date must be YYYY-MM-DD"
        ) from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read the existing ML shadow sidecar and emit a hash-bound "
            "natural maturity/pruning review projection. No prune or "
            "promotion action is performed."
        )
    )
    parser.add_argument("--shadow-sidecar", required=True, type=Path)
    parser.add_argument("--as-of-date", required=True, type=_iso_date)
    parser.add_argument("--expected-model-hash")
    parser.add_argument("--expected-dataset-identity-hash")
    parser.add_argument("--expected-policy-hash")
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional create-only JSON output; its parent must already exist.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = build_natural_shadow_pruning_evidence(
            args.shadow_sidecar,
            as_of_date=args.as_of_date,
            expected_model_hash=args.expected_model_hash,
            expected_dataset_identity_hash=args.expected_dataset_identity_hash,
            expected_policy_hash=args.expected_policy_hash,
        )
        if args.output is not None:
            write_natural_shadow_pruning_evidence(args.output, evidence)
    except (NaturalShadowPruningEvidenceError, OSError) as error:
        print(
            json.dumps(
                {"status": "invalid_request", "error": str(error)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            evidence,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
