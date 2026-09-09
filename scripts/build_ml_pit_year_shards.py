"""建立全欄位 ML 的年度 gzip JSONL PIT shards。"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
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
from data_module.ml_daily_price_source_quality import (  # noqa: E402
    DailyPriceSourceQualityError,
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


_SOURCE_QUALITY_SAMPLE_LIMIT = 12
_SOURCE_QUALITY_DATE_LIMIT = 64


def _compact_source_quality_summary(
    report: Mapping[str, object],
    *,
    sample_limit: int = _SOURCE_QUALITY_SAMPLE_LIMIT,
    date_limit: int = _SOURCE_QUALITY_DATE_LIMIT,
) -> dict[str, object]:
    """Return bounded quarantine evidence for a failed builder invocation.

    The exporter already has the full in-memory report when the guard raises.
    A scheduled caller must not persist that potentially multi-million-row
    candidate list, so the execution boundary emits counts, top affected dates,
    and a small deterministic sample only.  The report hash still binds this
    summary to the complete report that caused the failure.
    """

    def _string_int_mapping(value: object) -> dict[str, int]:
        if not isinstance(value, Mapping):
            return {}
        result: dict[str, int] = {}
        for key, item in value.items():
            if isinstance(key, str) and isinstance(item, int) and not isinstance(item, bool):
                result[key] = item
        return dict(sorted(result.items()))

    classification_counts = _string_int_mapping(report.get("classification_counts"))
    date_counts = _string_int_mapping(report.get("affected_date_counts"))
    top_dates = [
        {"date": day, "candidate_count": count}
        for day, count in sorted(
            date_counts.items(), key=lambda item: (-item[1], item[0])
        )[: max(0, date_limit)]
    ]

    candidates = report.get("candidates")
    samples: list[dict[str, object]] = []
    if isinstance(candidates, list):
        for candidate in candidates[: max(0, sample_limit)]:
            if not isinstance(candidate, Mapping):
                continue
            sample: dict[str, object] = {}
            for key in ("symbol", "date", "classification", "differing_fields"):
                if key in candidate:
                    value = candidate[key]
                    if key == "differing_fields" and isinstance(value, list):
                        sample[key] = [str(item) for item in value[:16]]
                    elif isinstance(value, (str, int, bool)) or value is None:
                        sample[key] = value
            detector = candidate.get("detector")
            if isinstance(detector, Mapping):
                sample["detector"] = {
                    key: detector[key]
                    for key in (
                        "previous_close",
                        "current_open",
                        "next_open",
                        "threshold_factor",
                        "policy_version",
                        "future_source_row_used",
                    )
                    if key in detector
                }
            canonical_file = candidate.get("canonical_file")
            if isinstance(canonical_file, Mapping):
                sample["canonical_file"] = {
                    key: canonical_file[key]
                    for key in (
                        "path",
                        "status",
                        "file_sha256",
                        "market",
                        "source_directory",
                    )
                    if key in canonical_file
                }
            canonical_candidates = candidate.get("canonical_candidates")
            if isinstance(canonical_candidates, list):
                route_samples: list[dict[str, object]] = []
                for entry in canonical_candidates[:4]:
                    if not isinstance(entry, Mapping):
                        continue
                    candidate_file = entry.get("file")
                    if isinstance(candidate_file, Mapping):
                        route_samples.append(
                            {
                                key: candidate_file[key]
                                for key in (
                                    "path",
                                    "status",
                                    "file_sha256",
                                    "market",
                                    "source_directory",
                                )
                                if key in candidate_file
                            }
                        )
                if route_samples:
                    sample["canonical_candidates"] = route_samples
            canonical_invalid_candidates = candidate.get(
                "canonical_invalid_candidates"
            )
            if isinstance(canonical_invalid_candidates, list):
                invalid_route_samples: list[dict[str, object]] = []
                for entry in canonical_invalid_candidates[:4]:
                    if not isinstance(entry, Mapping):
                        continue
                    candidate_file = entry.get("file")
                    candidate_row = entry.get("row")
                    invalid_sample: dict[str, object] = {}
                    if isinstance(candidate_file, Mapping):
                        invalid_sample["file"] = {
                            key: candidate_file[key]
                            for key in (
                                "path",
                                "status",
                                "file_sha256",
                                "market",
                                "source_directory",
                            )
                            if key in candidate_file
                        }
                    if isinstance(candidate_row, Mapping):
                        invalid_sample["row"] = dict(candidate_row)
                    if invalid_sample:
                        invalid_route_samples.append(invalid_sample)
                if invalid_route_samples:
                    sample["canonical_invalid_candidates"] = invalid_route_samples
            research_contract = candidate.get("research_contract")
            if isinstance(research_contract, Mapping):
                sample["research_contract"] = {
                    key: research_contract[key]
                    for key in (
                        "schema_version",
                        "status",
                        "symbol",
                        "date",
                        "field_status",
                        "missing_mask",
                        "affected_window",
                        "disposition",
                    )
                    if key in research_contract
                }
            samples.append(sample)

    return {
        "schema_version": report.get("schema_version"),
        "status": report.get("status"),
        "read_only": report.get("read_only"),
        "repair_performed": report.get("repair_performed"),
        "formal_training_allowed": report.get("formal_training_allowed"),
        "quality_timing": report.get("quality_timing"),
        "scope": report.get("scope"),
        "policy": report.get("policy"),
        "source": report.get("source"),
        "candidate_count": report.get("candidate_count"),
        "research_price_unavailable_count": report.get(
            "research_price_unavailable_count"
        ),
        "research_price_invalid_count": report.get(
            "research_price_invalid_count"
        ),
        "candidate_sample_count": report.get("candidate_sample_count"),
        "candidate_sample_limit": report.get("candidate_sample_limit"),
        "candidate_samples_truncated": report.get(
            "candidate_samples_truncated"
        ),
        "candidate_digest": report.get("candidate_digest"),
        "classification_counts": classification_counts,
        "affected_date_count": len(date_counts),
        "affected_date_counts_top": top_dates,
        "sample_limit": max(0, sample_limit),
        "samples": samples,
        "report_hash": report.get("report_hash"),
    }


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
        action="append",
        dest="daily_price_source_dirs",
        help=(
            "repeatable canonical daily CSV roots (TWSE and TPEX); enables "
            "read-only source quality guard before PIT staging"
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
        "--source-quality-candidate-sample-limit",
        type=int,
        default=64,
        help=(
            "maximum source-quality candidate evidence rows retained; "
            "full counts remain available"
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
                daily_price_source_dir=(
                    None
                    if not args.daily_price_source_dirs
                    else args.daily_price_source_dirs[0]
                ),
                daily_price_source_dirs=(
                    None
                    if not args.daily_price_source_dirs
                    else tuple(args.daily_price_source_dirs)
                ),
                source_quality_report_path=args.source_quality_report,
                source_quality_known_at=args.source_quality_known_at,
                source_quality_candidate_sample_limit=(
                    args.source_quality_candidate_sample_limit
                ),
            )
        )
    except DailyPriceSourceQualityError as exc:
        # The full report remains an in-memory guard artifact.  Emit only a
        # bounded summary at this process boundary so scheduled receipts do
        # not grow to millions of candidate rows.
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "formal_oos_allowed": False,
                    "production_alpha_bp": 0,
                    "source_quality_summary": _compact_source_quality_summary(
                        exc.report
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
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
