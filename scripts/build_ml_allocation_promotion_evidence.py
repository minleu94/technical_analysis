"""建立 hash-bound allocation-promotion-v4 compatible evidence。"""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import os
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ml_module.allocation_promotion_evidence_builder import (  # noqa: E402
    AllocationPromotionEvidenceBuildRequest,
    build_compatible_allocation_promotion_evidence,
)


def _default_output_root() -> Path:
    data_root = Path(
        os.environ.get(
            "DATA_ROOT",
            "D:/Min/Python/Project/FA_Data",
        )
    )
    output_root = Path(
        os.environ.get("OUTPUT_ROOT", str(data_root / "output"))
    )
    return (
        output_root
        / "release_v4"
        / "ml_allocation_promotion_evidence"
    )


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "decision-at must be an ISO timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError(
            "decision-at must include a timezone offset"
        )
    return parsed


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "as-of-date must be YYYY-MM-DD"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate formal OOC/replay/shadow/reference custody and build "
            "unsigned allocation-promotion-v4 compatible evidence."
        )
    )
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument(
        "--decision-at",
        required=True,
        type=_aware_datetime,
    )
    parser.add_argument("--as-of-date", type=_iso_date)
    parser.add_argument(
        "--training-manifest",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--dataset-manifest",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--replay-primary",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--replay-verification",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--shadow-sidecar",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--promotion-reference",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--promotion-reference-metrics",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--expected-promotion-reference-file-hash",
    )
    parser.add_argument(
        "--minimum-matured-days",
        type=int,
        default=20,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=_default_output_root(),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    decision_at: datetime = args.decision_at
    as_of_date = (
        args.as_of_date
        if args.as_of_date is not None
        else decision_at.date()
    )
    result = build_compatible_allocation_promotion_evidence(
        AllocationPromotionEvidenceBuildRequest(
            experiment_id=args.experiment_id,
            decision_at=decision_at,
            as_of_date=as_of_date,
            training_manifest_path=args.training_manifest,
            dataset_manifest_path=args.dataset_manifest,
            replay_primary_path=args.replay_primary,
            replay_verification_path=args.replay_verification,
            shadow_sidecar_database_path=args.shadow_sidecar,
            promotion_reference_path=args.promotion_reference,
            promotion_reference_metrics_path=(
                args.promotion_reference_metrics
            ),
            output_root=args.output_root,
            expected_promotion_reference_file_hash=(
                args.expected_promotion_reference_file_hash
            ),
            minimum_matured_days=args.minimum_matured_days,
        )
    )
    print(
        json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    # Evidence 不足是預期營運狀態，scheduler 不應把它誤判為程式崩潰。
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
