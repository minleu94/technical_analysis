"""由 immutable Direct OOC parent 建立有界 h5 線性 shadow release。

這個 CLI 只重用 parent 的 frozen base/OOF artifact，重新 fit 57 欄 raw OOF
meta、建立 prior-fold isotonic calibrator，並把 fold-004 留作 withheld replay。
它不修改 Direct store，也不宣稱 formal OOS promotion；執行前可用
``--preflight-only`` 檢查容量與來源 lineage。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.ml_storage_capacity import (  # noqa: E402
    BYTES_PER_GIB,
    StorageCapacityError,
    resolve_heavy_chain_lock_path,
    resolve_heavy_chain_safety_reserve,
)
from ml_module.allocation_ooc_release_builder import (  # noqa: E402
    AllocationDerivedOOCReleaseRequest,
    build_allocation_derived_ooc_release,
    preflight_allocation_derived_ooc_release,
)
from ml_module.allocation_rank_contract import (  # noqa: E402
    DEFAULT_RANK_CONTRACT,
    RANK_CONTRACT_V1,
    RANK_CONTRACT_V2,
)
from ml_module.allocation_family_weight_contract import (  # noqa: E402
    FAMILY_WEIGHT_POLICY_COEFFICIENT_V1,
    FAMILY_WEIGHT_POLICY_DEGENERATE_EQUAL_V1,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--parent-training-manifest",
        type=Path,
        required=True,
        help="immutable allocation-ooc-training.v5 parent manifest.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="獨立 repo output root；既有內容拒絕覆寫",
    )
    parser.add_argument(
        "--model-id",
        default="baldr-ml-allocation-derived-h5-v4",
    )
    parser.add_argument("--policy-id", default="balanced-v4-operational")
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--heldout-fold-count", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=8_192)
    parser.add_argument("--memory-budget-mb", type=int, default=4_096)
    parser.add_argument(
        "--persistent-new-bytes-budget",
        type=int,
        default=BYTES_PER_GIB,
    )
    parser.add_argument(
        "--temporary-peak-bytes-budget",
        type=int,
        default=BYTES_PER_GIB,
    )
    parser.add_argument(
        "--safety-reserve-bytes",
        type=int,
        default=200 * BYTES_PER_GIB,
    )
    parser.add_argument("--heavy-lock-path", type=Path)
    parser.add_argument(
        "--rank-contract",
        choices=(RANK_CONTRACT_V1, RANK_CONTRACT_V2),
        default=DEFAULT_RANK_CONTRACT,
        help="版本化的橫截面 rank 契約；v2 同值採同 rank。",
    )
    parser.add_argument(
        "--family-weight-policy",
        choices=(
            FAMILY_WEIGHT_POLICY_COEFFICIENT_V1,
            FAMILY_WEIGHT_POLICY_DEGENERATE_EQUAL_V1,
        ),
        default=FAMILY_WEIGHT_POLICY_COEFFICIENT_V1,
        help=(
            "版本化的 feature family coverage 權重政策；退化 target "
            "才可選 deterministic equal。"
        ),
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="只做來源／selection／容量檢查，不寫入 derived release",
    )
    return parser


def _request(args: argparse.Namespace) -> AllocationDerivedOOCReleaseRequest:
    # CLI 是 production boundary；即使 request dataclass 為了既有 fixture
    # 相容而保留正數驗證，這裡仍必須拒絕舊的 20/125 GiB safety 值。
    safety_reserve_bytes = resolve_heavy_chain_safety_reserve(
        args.safety_reserve_bytes
    )
    heavy_lock_path = resolve_heavy_chain_lock_path(
        args.parent_training_manifest,
        explicit_path=args.heavy_lock_path,
    )
    return AllocationDerivedOOCReleaseRequest(
        parent_training_manifest_path=args.parent_training_manifest,
        output_root=args.output_root,
        model_id=args.model_id,
        policy_id=args.policy_id,
        horizon=args.horizon,
        heldout_fold_count=args.heldout_fold_count,
        batch_size=args.batch_size,
        memory_budget_mb=args.memory_budget_mb,
        persistent_new_bytes_budget=args.persistent_new_bytes_budget,
        temporary_peak_bytes_budget=args.temporary_peak_bytes_budget,
        safety_reserve_bytes=safety_reserve_bytes,
        heavy_lock_path=heavy_lock_path,
        acquire_heavy_lock=not args.preflight_only,
        rank_contract=args.rank_contract,
        family_weight_policy=args.family_weight_policy,
    )


def _blocked(exc: Exception) -> dict[str, Any]:
    body: dict[str, Any] = {
        "status": "blocked",
        "error_type": type(exc).__name__,
        "message": str(exc),
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "production_action_allowed": False,
        "broker_order_allowed": False,
    }
    if isinstance(exc, StorageCapacityError):
        body["capacity_preflight"] = dict(exc.preflight)
    return body


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8()
    args = _parser().parse_args(argv)
    try:
        request = _request(args)
        if args.preflight_only:
            result: Mapping[str, Any] = preflight_allocation_derived_ooc_release(
                request
            )
        else:
            publication = build_allocation_derived_ooc_release(request)
            result = {
                "status": "release_completed",
                "release_root": str(publication.release_root),
                "release_manifest": str(publication.release_manifest_path),
                "derived_manifest": str(publication.derived_manifest_path),
                "derived_manifest_hash": publication.derived_manifest_hash,
                "release_identity_hash": publication.release_identity_hash,
                "model_artifact_hash": publication.model_artifact_hash,
                "heldout_evaluation": str(publication.heldout_evaluation_path),
                "heldout_evaluation_hash": publication.heldout_evaluation_hash,
                "output_size_bytes": publication.output_size_bytes,
                "family_weight_policy": args.family_weight_policy,
                "heldout_fold_id": publication.heldout_fold_id,
                "selected_oof_artifact_count": publication.selected_oof_artifact_count,
                "selected_oof_row_count": publication.selected_oof_row_count,
                "meta_fit_row_count": publication.meta_fit_row_count,
                "calibration_id": publication.calibration_id,
                "calibration_fit_fold_ids": list(
                    publication.calibration_fit_fold_ids
                ),
                "calibration_fit_row_count": publication.calibration_fit_row_count,
                "rank_contract": args.rank_contract,
                "capacity_preflight": dict(publication.capacity_preflight),
                "formal_oos_allowed": publication.formal_oos_allowed,
                "production_alpha_bp": publication.production_alpha_bp,
                "production_action_allowed": publication.production_action_allowed,
                "broker_order_allowed": publication.broker_order_allowed,
            }
    except (OSError, TypeError, ValueError, KeyError, StorageCapacityError) as exc:
        print(
            json.dumps(_blocked(exc), ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(result, ensure_ascii=False, sort_keys=True),
    )
    return 0


def _configure_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


if __name__ == "__main__":
    raise SystemExit(main())
