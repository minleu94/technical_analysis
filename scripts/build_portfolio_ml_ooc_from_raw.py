"""建立 checkpointed legacy 配置 shards 與 OOC store（非 direct numeric）。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.portfolio_ml_raw_to_ooc_pipeline import (  # noqa: E402
    PortfolioMLRawToOOCBuilder,
    PortfolioMLRawToOOCRequest,
)
from data_module.ml_storage_capacity import (  # noqa: E402
    BYTES_PER_GIB,
    CANONICAL_HEAVY_CHAIN_SAFETY_RESERVE_BYTES,
    MLStorageChainReservationHandoff,
    StorageCapacityError,
    acquire_heavy_chain_reservation,
    release_heavy_chain_reservation,
    heavy_chain_lock_path,
    resolve_heavy_chain_lock_path,
    validate_heavy_chain_reservation_handoff,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--training-as-of", required=True)
    parser.add_argument("--benchmark-entity", required=True)
    parser.add_argument("--sector-membership", type=Path)
    parser.add_argument("--corporate-action-manifest", type=Path)
    parser.add_argument("--formal-portfolio-ledger", type=Path)
    parser.add_argument("--formal-rule-champion-history", type=Path)
    parser.add_argument("--research-shadow-manifest", type=Path)
    parser.add_argument(
        "--research-symbol",
        action="append",
        dest="research_symbols",
    )
    parser.add_argument("--years", nargs="*", type=int, default=())
    parser.add_argument("--minimum-train-dates", type=int, default=252)
    parser.add_argument("--test-date-count", type=int, default=63)
    parser.add_argument("--purge-trading-days", type=int, default=60)
    parser.add_argument("--embargo-trading-days", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=8_192)
    parser.add_argument("--compression-level", type=int, default=6)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--memory-budget-mb", type=int, default=4_096)
    parser.add_argument(
        "--temporary-storage-budget-bytes",
        type=int,
        default=BYTES_PER_GIB,
        help="中介 SQLite/JSONL 的硬上限；低於 raw 壓縮檔下界即 fail closed。",
    )
    parser.add_argument(
        "--persistent-storage-budget-bytes",
        "--persistent-new-bytes-budget",
        dest="persistent_storage_budget_bytes",
        type=int,
        default=BYTES_PER_GIB,
        help="raw-to-OOC 本次持久新增 bytes 上限",
    )
    parser.add_argument(
        "--safety-reserve-bytes",
        type=int,
        default=CANONICAL_HEAVY_CHAIN_SAFETY_RESERVE_BYTES,
        help="heavy chain 執行後必須保留的 filesystem bytes",
    )
    parser.add_argument(
        "--heavy-lock-path",
        type=Path,
        help="可選；正式 release_v4 output 必須與 canonical lock 相同",
    )
    parser.add_argument("--no-resume", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_streams()
    args = _parser().parse_args(argv)
    reservation = None
    handoff: MLStorageChainReservationHandoff | None = None
    try:
        lock_path = resolve_heavy_chain_lock_path(
            args.output_dir,
            explicit_path=args.heavy_lock_path,
        )
        if lock_path is None:
            lock_path = heavy_chain_lock_path(args.output_dir)
        handoff = validate_heavy_chain_reservation_handoff(
            lock_path
        )
        if lock_path is not None and handoff is None:
            reservation = acquire_heavy_chain_reservation(lock_path)
            if reservation is None:
                raise StorageCapacityError(
                    "ML heavy-chain reservation is already held",
                    preflight={
                        "lock_path": str(lock_path),
                        "blocker": "heavy_chain_reservation_unavailable",
                    },
                )
        publication = PortfolioMLRawToOOCBuilder().build(
            PortfolioMLRawToOOCRequest(
                raw_manifest_path=args.raw_manifest,
                output_root=args.output_dir,
                training_as_of=args.training_as_of,
                benchmark_entity_id=args.benchmark_entity,
                sector_membership_path=args.sector_membership,
                corporate_action_manifest_path=(
                    args.corporate_action_manifest
                ),
                formal_portfolio_ledger_path=args.formal_portfolio_ledger,
                formal_rule_champion_history_path=(
                    args.formal_rule_champion_history
                ),
                research_shadow_manifest_path=(
                    args.research_shadow_manifest
                ),
                research_symbols=(
                    None
                    if args.research_symbols is None
                    else tuple(args.research_symbols)
                ),
                years=tuple(args.years),
                minimum_train_dates=args.minimum_train_dates,
                test_date_count=args.test_date_count,
                purge_trading_days=args.purge_trading_days,
                embargo_trading_days=args.embargo_trading_days,
                batch_size=args.batch_size,
                compression_level=args.compression_level,
                workers=args.workers,
                memory_budget_mb=args.memory_budget_mb,
                temporary_storage_budget_bytes=(
                    args.temporary_storage_budget_bytes
                ),
                persistent_storage_budget_bytes=(
                    args.persistent_storage_budget_bytes
                ),
                safety_reserve_bytes=args.safety_reserve_bytes,
                resume=not args.no_resume,
            )
        )
    except (
        OSError,
        StorageCapacityError,
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
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    finally:
        if handoff is not None:
            handoff.close()
        release_heavy_chain_reservation(reservation)
    print(
        json.dumps(
            {
                "status": "complete",
                "pipeline_id": publication.pipeline_id,
                "manifest_path": str(publication.manifest_path),
                "training_manifest_path": str(
                    publication.training_manifest_path
                ),
                "store_manifest_path": str(
                    publication.store_publication.manifest_path
                ),
                "store_manifest_hash": (
                    publication.store_publication.manifest_hash
                ),
                "completed_raw_shard_count": (
                    publication.completed_raw_shard_count
                ),
                "research_union_manifest_path": (
                    None
                    if publication.research_union_manifest_path is None
                    else str(publication.research_union_manifest_path)
                ),
                "research_store_manifest_path": (
                    None
                    if publication.research_store_publication is None
                    else str(
                        publication.research_store_publication.manifest_path
                    )
                ),
                "research_only": (
                    publication.research_store_publication is not None
                ),
                "direct_numeric_store": False,
                "full_market_ready": False,
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
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
