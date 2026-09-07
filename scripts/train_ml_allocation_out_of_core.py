"""以正式年度 memmap store 執行可續跑的全市場配置型 ML 訓練。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml_module.allocation_out_of_core_training_service import (  # noqa: E402
    AllocationOutOfCoreTrainingRequest,
    AllocationOutOfCoreTrainingService,
)
from ml_module.allocation_oos_replay_input_builder import (  # noqa: E402
    AllocationOOSReplayInputBuildRequest,
    build_allocation_oos_replay_inputs,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--algorithm",
        action="append",
        choices=("ridge_logistic", "hist_gradient_boosting"),
        dest="algorithms",
        help="可重複指定；預設同時訓練 Ridge/Logistic 與 HGB challenger。",
    )
    parser.add_argument(
        "--horizon",
        action="append",
        type=int,
        dest="horizons",
        help="可重複指定；預設使用 frozen store 全部 horizons。",
    )
    parser.add_argument("--batch-size", type=int, default=8_192)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--memory-budget-mb", type=int, default=4_096)
    parser.add_argument("--ridge-alpha-bp", type=int, default=100)
    parser.add_argument("--logistic-iterations", type=int, default=6)
    parser.add_argument("--hgb-max-iter", type=int, default=100)
    parser.add_argument("--hgb-max-fit-rows", type=int, default=250_000)
    parser.add_argument(
        "--temporary-storage-budget-bytes",
        "--temporary-peak-bytes-budget",
        dest="temporary_storage_budget_bytes",
        type=int,
        help="OOC workspace 暫存峰值 bytes 上限",
    )
    parser.add_argument(
        "--persistent-storage-budget-bytes",
        "--persistent-new-bytes-budget",
        dest="persistent_storage_budget_bytes",
        type=int,
        help="OOC run 本次持久新增 bytes 上限",
    )
    parser.add_argument(
        "--safety-reserve-bytes",
        type=int,
        help="OOC 執行後必須保留的 filesystem bytes",
    )
    parser.add_argument(
        "--profile",
        choices=("full_shadow", "minimal_linear_shadow"),
        default="full_shadow",
        help=(
            "訓練複雜度政策。minimal_linear_shadow 僅允許單一 "
            "ridge/logistic algorithm 與一個明確 horizon，供成本後增益前的 shadow 比較。"
        ),
    )
    parser.add_argument("--no-resume", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_streams()
    args = _parser().parse_args(argv)
    algorithms = tuple(
        args.algorithms
        or ("ridge_logistic", "hist_gradient_boosting")
    )
    horizons = tuple(args.horizons or ())
    if args.profile == "minimal_linear_shadow":
        if args.algorithms and tuple(args.algorithms) != ("ridge_logistic",):
            raise SystemExit(
                "minimal_linear_shadow 只允許 --algorithm ridge_logistic"
            )
        if len(horizons) != 1:
            raise SystemExit(
                "minimal_linear_shadow 必須明確提供恰好一個 --horizon"
            )
        algorithms = ("ridge_logistic",)
    complexity_policy = {
        "algorithm_count": len(algorithms),
        "horizon_count": len(horizons) if horizons else None,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
    }
    try:
        publication = AllocationOutOfCoreTrainingService().train(
            AllocationOutOfCoreTrainingRequest(
                store_manifest_path=args.store_manifest,
                output_root=args.output_dir,
                algorithms=algorithms,
                horizons=horizons,
                batch_size=args.batch_size,
                workers=args.workers,
                memory_budget_mb=args.memory_budget_mb,
                ridge_alpha_bp=args.ridge_alpha_bp,
                logistic_iterations=args.logistic_iterations,
                hgb_max_iter=args.hgb_max_iter,
                hgb_max_fit_rows=args.hgb_max_fit_rows,
                resume=not args.no_resume,
                temporary_storage_budget_bytes=(
                    args.temporary_storage_budget_bytes
                ),
                persistent_storage_budget_bytes=(
                    args.persistent_storage_budget_bytes
                ),
                safety_reserve_bytes=args.safety_reserve_bytes,
                training_profile=args.profile,
                complexity_policy=complexity_policy,
            )
        )
    except (
        MemoryError,
        OSError,
        TypeError,
        ValueError,
        KeyError,
        RuntimeError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "formal_oos_allowed": False,
                    "production_alpha_bp": 0,
                    "broker_order_allowed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    replay_inputs = build_allocation_oos_replay_inputs(
        AllocationOOSReplayInputBuildRequest(
            training_manifest_path=publication.manifest_path,
        )
    )
    print(
        json.dumps(
            {
                "status": "complete",
                "run_id": publication.run_id,
                "manifest_path": str(publication.manifest_path),
                "manifest_hash": publication.manifest_hash,
                "manifest_file_hash": publication.manifest_file_hash,
                "base_expert_count": publication.base_expert_count,
                "meta_fold_count": publication.meta_fold_count,
                "formal_oos_allowed": publication.formal_oos_allowed,
                "production_alpha_bp": publication.production_alpha_bp,
                "broker_order_allowed": False,
                "replay_input_status": replay_inputs.status,
                "replay_input_blockers": list(replay_inputs.blockers),
                "replay_input_manifest_path": (
                    None
                    if replay_inputs.manifest_path is None
                    else str(replay_inputs.manifest_path)
                ),
                "replay_input_manifest_hash": replay_inputs.manifest_hash,
                "training_profile": args.profile,
                "complexity_policy": complexity_policy,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _configure_utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
