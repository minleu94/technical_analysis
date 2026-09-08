"""建立全欄位 ML 的年度 gzip JSONL PIT shards。"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.ml_pit_year_shard_exporter import (  # noqa: E402
    PITYearShardBuildRequest,
    PITYearShardExporter,
)
from data_module.ml_storage_capacity import (  # noqa: E402
    BYTES_PER_GIB,
    CANONICAL_HEAVY_CHAIN_SAFETY_RESERVE_BYTES,
    StorageCapacityError,
    acquire_heavy_chain_reservation,
    MLStorageChainReservationHandoff,
    heavy_chain_lock_path,
    release_heavy_chain_reservation,
    resolve_heavy_chain_lock_path,
    validate_heavy_chain_reservation_handoff,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Stream a read-only SQLite source into annual gzip JSONL PIT "
            "shards plus hash manifests. No Parquet dependency is used."
        )
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=_default_database_path(),
        help="Existing SQLite database; always opened mode=ro/query_only.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Publication root; versioned runs and latest_manifest.json are written here.",
    )
    parser.add_argument(
        "--decision-at",
        required=True,
        help="PIT freeze timestamp; date-only means 08:30 Asia/Taipei.",
    )
    parser.add_argument(
        "--history-start-date",
        default="2014-01-01",
        help="Earliest source event date admitted to the causal prefix.",
    )
    universe = parser.add_mutually_exclusive_group(required=True)
    universe.add_argument(
        "--symbols",
        nargs="+",
        help="Bounded stock universe for QA/replay.",
    )
    universe.add_argument(
        "--all-universe",
        action="store_true",
        help="Explicitly stream the complete stock universe.",
    )
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        default=(),
        help=(
            "Optional bounded available_at years. Omit to publish every "
            "available year."
        ),
    )
    parser.add_argument(
        "--industry-index-names",
        nargs="*",
        default=(),
        help="Optional bounded industry index names; empty includes all.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=2_048,
        help="SQLite fetchmany batch size; never a whole-table fetch.",
    )
    parser.add_argument(
        "--compression-level",
        type=int,
        default=6,
        choices=range(0, 10),
        metavar="0..9",
    )
    parser.add_argument(
        "--temporary-storage-budget-bytes",
        "--temporary-peak-bytes-budget",
        dest="temporary_storage_budget_bytes",
        type=int,
        default=BYTES_PER_GIB,
        help="raw PIT staging 暫存峰值 bytes 上限",
    )
    parser.add_argument(
        "--persistent-storage-budget-bytes",
        "--persistent-new-bytes-budget",
        dest="persistent_storage_budget_bytes",
        type=int,
        default=BYTES_PER_GIB,
        help="raw PIT publication 本次持久新增 bytes 上限",
    )
    parser.add_argument(
        "--safety-reserve-bytes",
        type=int,
        default=CANONICAL_HEAVY_CHAIN_SAFETY_RESERVE_BYTES,
        help="publication 執行後必須保留的 filesystem bytes",
    )
    parser.add_argument(
        "--daily-price-source-dir",
        type=Path,
        help=(
            "optional canonical daily CSV root; enables read-only source "
            "quality guard before PIT staging"
        ),
    )
    parser.add_argument(
        "--source-quality-report",
        type=Path,
        help="optional repo output path for the source-quality report",
    )
    parser.add_argument(
        "--source-quality-known-at",
        help=(
            "optional timezone-aware source receipt time; never inferred from "
            "file mtime"
        ),
    )
    parser.add_argument(
        "--heavy-lock-path",
        type=Path,
        help="可選；正式 release_v4 output 必須與 canonical lock 相同",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_stdio()
    args = build_parser().parse_args(argv)
    reservation = None
    handoff: MLStorageChainReservationHandoff | None = None
    try:
        lock_path = resolve_heavy_chain_lock_path(
            args.output_dir,
            explicit_path=args.heavy_lock_path,
        )
        if lock_path is None:
            # CLI 是 execution boundary；fixture／非 release_v4 output 也
            # 必須有一把可辨識的 local reservation，不能因 resolver 的
            # library fixture 相容分支而在正式入口無鎖執行。
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
        publication = PITYearShardExporter().build(
            PITYearShardBuildRequest(
                database_path=args.database,
                output_root=args.output_dir,
                decision_at=args.decision_at,
                history_start_date=args.history_start_date,
                symbols=None if args.all_universe else tuple(args.symbols),
                years=tuple(args.years),
                industry_index_names=tuple(args.industry_index_names),
                batch_size=args.batch_size,
                compression_level=args.compression_level,
                temporary_storage_budget_bytes=(
                    args.temporary_storage_budget_bytes
                ),
                persistent_storage_budget_bytes=(
                    args.persistent_storage_budget_bytes
                ),
                safety_reserve_bytes=args.safety_reserve_bytes,
                daily_price_source_dir=args.daily_price_source_dir,
                source_quality_report_path=args.source_quality_report,
                source_quality_known_at=args.source_quality_known_at,
            )
        )
    except (
        OSError,
        StorageCapacityError,
        TypeError,
        ValueError,
        KeyError,
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
            )
        )
        return 2
    finally:
        if handoff is not None:
            handoff.close()
        release_heavy_chain_reservation(reservation)
    payload = {
        **asdict(publication),
        "publication_directory": str(publication.publication_directory),
        "manifest_path": str(publication.manifest_path),
        "latest_manifest_path": str(publication.latest_manifest_path),
        "dataset_manifest_paths": {
            key: str(value)
            for key, value in publication.dataset_manifest_paths.items()
        },
        "sqlite_mode": "ro",
        "query_only": True,
        "parquet_dependency_added": False,
    }
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2 if args.pretty else None,
            separators=None if args.pretty else (",", ":"),
        )
    )
    return 0


def _default_database_path() -> Path:
    data_root = Path(os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data"))
    if os.environ.get("PROFILE", "prod") == "test":
        data_root = data_root / "_test"
    return data_root / "sqlite" / "twstock.db"


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
