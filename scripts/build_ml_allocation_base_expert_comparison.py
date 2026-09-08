"""建立固定 fold 的 base expert／causal Rule／Equal Weight 成本後研究比較。

CLI 只讀 immutable Direct/OOC parent 與三個 h5 ridge/logistic base OOF，
不讀 Meta targets、不重訓模型、不修改正式資料。預設輸出 strict sector
情境與明確標示不可 promotion 的 no-sector-cap research 情境；後者只為在
歷史 PIT sector source 缺失時觀察同一成交／費用政策下的 counterfactual。
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
from ml_module.allocation_base_expert_comparison import (  # noqa: E402
    AllocationBaseExpertComparisonRequest,
    build_allocation_base_expert_comparison,
    preflight_allocation_base_expert_comparison,
)


_MAX_BUDGET_BYTES = 256 * 1024 * 1024


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
        help="獨立 repo output root；已存在內容只允許同 identity 重用",
    )
    parser.add_argument("--fold-id", default="fold-004")
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument(
        "--algorithm",
        action="append",
        default=None,
        choices=("ridge_logistic",),
        help="可重複指定；bounded scope 只接受 ridge_logistic",
    )
    parser.add_argument(
        "--pack-id",
        action="append",
        default=None,
        help="可重複指定三個完整 feature pack；省略即全選",
    )
    parser.add_argument("--batch-size", type=int, default=8_192)
    parser.add_argument("--memory-budget-mb", type=int, default=4_096)
    parser.add_argument(
        "--persistent-new-bytes-budget",
        type=int,
        default=_MAX_BUDGET_BYTES,
    )
    parser.add_argument(
        "--temporary-peak-bytes-budget",
        type=int,
        default=_MAX_BUDGET_BYTES,
    )
    parser.add_argument(
        "--safety-reserve-bytes",
        type=int,
        default=200 * BYTES_PER_GIB,
    )
    parser.add_argument("--heavy-lock-path", type=Path)
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="只查核 parent/OOF/容量，不取得 heavy lock 或寫輸出",
    )
    return parser


def _request(args: argparse.Namespace) -> AllocationBaseExpertComparisonRequest:
    algorithms = (
        ("ridge_logistic",)
        if args.algorithm is None
        else tuple(str(item) for item in args.algorithm)
    )
    pack_ids = () if args.pack_id is None else tuple(str(item) for item in args.pack_id)
    # CLI 是 production/research artifact 的 capacity boundary；低於中央
    # 200 GiB 的舊 reserve 參數不得繞過 caller policy。
    safety_reserve_bytes = resolve_heavy_chain_safety_reserve(
        args.safety_reserve_bytes
    )
    heavy_lock_path = resolve_heavy_chain_lock_path(
        args.parent_training_manifest,
        explicit_path=args.heavy_lock_path,
    )
    return AllocationBaseExpertComparisonRequest(
        parent_training_manifest_path=args.parent_training_manifest,
        output_root=args.output_root,
        fold_id=args.fold_id,
        horizon=args.horizon,
        algorithms=algorithms,
        pack_ids=pack_ids,
        batch_size=args.batch_size,
        memory_budget_mb=args.memory_budget_mb,
        persistent_new_bytes_budget=args.persistent_new_bytes_budget,
        temporary_peak_bytes_budget=args.temporary_peak_bytes_budget,
        safety_reserve_bytes=safety_reserve_bytes,
        heavy_lock_path=heavy_lock_path,
        acquire_heavy_lock=not args.preflight_only,
    )


def _blocked(exc: Exception) -> dict[str, Any]:
    body: dict[str, Any] = {
        "status": "blocked",
        "error_type": type(exc).__name__,
        "message": str(exc),
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
    }
    if isinstance(exc, StorageCapacityError):
        body["capacity_preflight"] = dict(exc.preflight)
    return body


def _configure_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8()
    args = _parser().parse_args(argv)
    try:
        request = _request(args)
        if args.preflight_only:
            result: Mapping[str, Any] = preflight_allocation_base_expert_comparison(
                request
            )
        else:
            publication = build_allocation_base_expert_comparison(request)
            result = {
                "status": "comparison_completed",
                "comparison_path": str(publication.comparison_path),
                "comparison_hash": publication.comparison_hash,
                "latest_pointer_path": str(publication.latest_pointer_path),
                "run_id": publication.run_id,
                "output_size_bytes": publication.output_size_bytes,
                "capacity_preflight": dict(publication.capacity_preflight),
                "idempotent": publication.idempotent,
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
                "broker_order_allowed": False,
            }
    except (OSError, TypeError, ValueError, KeyError, StorageCapacityError) as exc:
        result = _blocked(exc)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
