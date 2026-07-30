"""唯讀產出全欄位 ML eligibility、PIT coverage 與 dataset manifests。"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.ml_all_field_snapshot_provider import (  # noqa: E402
    AllFieldPITSnapshot,
    MLAllFieldSnapshotProvider,
)
from ml_module.feature_eligibility import (  # noqa: E402
    ALL_FIELD_SOURCE_TABLES,
    FeatureEligibilityRecord,
)


_CORE_TABLES = frozenset(
    {
        "daily_prices",
        "technical_indicators",
        "market_indices",
        "industry_indices",
    }
)
_FORMAL_ENRICHED_STATUSES = frozenset(
    {"formal_backfill", "first_seen_only"}
)
_RESEARCH_SHADOW_STATUSES = frozenset(
    {"formal_backfill", "first_seen_only", "research_shadow"}
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect all SQLite table.column eligibility and build read-only "
            "core_long_history/all_field_enriched PIT readiness manifests."
        )
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=_default_database_path(),
        help="Existing SQLite DB; opened with mode=ro/query_only.",
    )
    parser.add_argument(
        "--decision-at",
        required=True,
        help="Decision timestamp; date-only input means 08:30 Asia/Taipei.",
    )
    parser.add_argument(
        "--history-start-date",
        default="2014-01-01",
        help="Inclusive event-history start date.",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=("2330",),
        help="Bounded stock universe used for the PIT snapshot.",
    )
    parser.add_argument(
        "--industry-index-names",
        nargs="*",
        default=(),
        help="Optional bounded industry index names; empty means all industry rows.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help=(
            "Optional explicit output directory, e.g. "
            "$OUTPUT_ROOT/release_v4. Omit for stdout-only."
        ),
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print stdout JSON.")
    return parser


def build_readiness_report(
    *,
    provider: MLAllFieldSnapshotProvider,
    decision_at: str,
    history_start_date: str,
    symbols: tuple[str, ...],
    industry_index_names: tuple[str, ...] = (),
) -> dict[str, Any]:
    """可重播的 service API；不寫 DB 或輸出檔。"""

    eligibility = provider.inspect_eligibility()
    snapshot = provider.load(
        decision_at=decision_at,
        history_start_date=history_start_date,
        symbols=symbols,
        industry_index_names=industry_index_names,
    )
    core_manifest = _dataset_manifest(
        dataset_id="core_long_history",
        records=(
            record
            for record in eligibility.records
            if record.table_name in _CORE_TABLES
            and record.eligibility_status == "formal_backfill"
            and record.is_numeric_feature
        ),
        snapshot=snapshot,
        included_statuses=("formal_backfill",),
    )
    all_field_manifest = _dataset_manifest(
        dataset_id="all_field_enriched",
        records=(
            record
            for record in eligibility.records
            if record.eligibility_status in _FORMAL_ENRICHED_STATUSES
            and record.is_numeric_feature
        ),
        snapshot=snapshot,
        included_statuses=(
            "formal_backfill",
            "first_seen_only",
        ),
    )
    research_shadow_manifest = _dataset_manifest(
        dataset_id="research_shadow_all_fields",
        records=(
            record
            for record in eligibility.records
            if record.eligibility_status in _RESEARCH_SHADOW_STATUSES
            and record.is_numeric_feature
        ),
        snapshot=snapshot,
        included_statuses=(
            "formal_backfill",
            "first_seen_only",
            "research_shadow",
        ),
    )
    status_counts = Counter(
        record.eligibility_status for record in eligibility.records
    )
    source_unreviewed = tuple(
        record
        for record in eligibility.unreviewed_records
        if record.table_name in ALL_FIELD_SOURCE_TABLES
    )
    report: dict[str, Any] = {
        "schema_version": "ml-all-field-readiness.v1",
        "decision_at": snapshot.decision_at,
        "history_start_date": snapshot.history_start_date,
        "eligibility": {
            "manifest_hash": eligibility.manifest_hash,
            "inspected_tables": list(eligibility.inspected_tables),
            "missing_source_tables": list(eligibility.missing_tables),
            "table_count": len(eligibility.inspected_tables),
            "column_count": len(eligibility.records),
            "status_counts": dict(sorted(status_counts.items())),
            "unreviewed_count": len(eligibility.unreviewed_records),
            "unreviewed_feature_ids": [
                record.feature_id for record in eligibility.unreviewed_records
            ],
            "source_unreviewed_count": len(source_unreviewed),
            "source_unreviewed_feature_ids": [
                record.feature_id for record in source_unreviewed
            ],
            "unknown_columns_fail_closed": True,
            "records": [_eligibility_payload(record) for record in eligibility.records],
        },
        "datasets": {
            "core_long_history": core_manifest,
            "all_field_enriched": all_field_manifest,
            "research_shadow_all_fields": research_shadow_manifest,
        },
        "pack_coverage": [
            asdict(family) for family in snapshot.family_availability
        ],
        "masks": _mask_summary(snapshot),
        "snapshot": {
            "snapshot_hash": snapshot.snapshot_hash,
            "source_fingerprint": snapshot.source_fingerprint,
            "eligibility_manifest_hash": snapshot.eligibility_manifest_hash,
            "core_feature_as_of_date": snapshot.core_feature_as_of_date,
            "observation_count": len(snapshot.observations),
            "query_count": snapshot.query_count,
        },
        "safety": {
            "sqlite_mode": "ro",
            "query_only": snapshot.query_only,
            "shadow_only": snapshot.shadow_only,
            "production_action_allowed": snapshot.production_action_allowed,
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
            "raw_float_persistence_allowed": False,
            "unreviewed_training_allowed": False,
        },
    }
    report["report_hash"] = _sha256(_canonical_json(report))
    return report


def write_readiness_outputs(report: dict[str, Any], *, output_dir: Path) -> tuple[Path, ...]:
    """只在呼叫端明確指定的 output dir 原子寫入 JSON artifacts。"""

    resolved = output_dir.resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "ml_all_field_readiness.json": report,
        "feature_eligibility_matrix.json": report["eligibility"],
        "core_long_history_manifest.json": report["datasets"]["core_long_history"],
        "all_field_enriched_manifest.json": report["datasets"]["all_field_enriched"],
        "research_shadow_all_fields_manifest.json": report["datasets"][
            "research_shadow_all_fields"
        ],
    }
    written: list[Path] = []
    for filename, payload in artifacts.items():
        destination = resolved / filename
        _atomic_write_json(destination, payload)
        written.append(destination)
    return tuple(written)


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_stdio()
    args = build_parser().parse_args(argv)
    provider = MLAllFieldSnapshotProvider(args.database)
    report = build_readiness_report(
        provider=provider,
        decision_at=args.decision_at,
        history_start_date=args.history_start_date,
        symbols=tuple(args.symbols),
        industry_index_names=tuple(args.industry_index_names),
    )
    if args.output_dir is not None:
        written = write_readiness_outputs(report, output_dir=args.output_dir)
        report["written_artifacts"] = [str(path) for path in written]
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            indent=2 if args.pretty else None,
            separators=None if args.pretty else (",", ":"),
        )
    )
    return 0


def _dataset_manifest(
    *,
    dataset_id: str,
    records: Iterable[FeatureEligibilityRecord],
    snapshot: AllFieldPITSnapshot,
    included_statuses: tuple[str, ...],
) -> dict[str, Any]:
    ordered_records = tuple(sorted(records, key=lambda record: record.feature_id))
    feature_ids = tuple(record.feature_id for record in ordered_records)
    feature_id_set = set(feature_ids)
    matching_values = tuple(
        value
        for observation in snapshot.observations
        for value in observation.values
        if value.feature_id in feature_id_set
    )
    observation_hashes = tuple(
        observation.source_row_hash
        for observation in snapshot.observations
        if any(value.feature_id in feature_id_set for value in observation.values)
    )
    missing_count = sum(1 for value in matching_values if value.missing_mask)
    stale_count = sum(1 for value in matching_values if value.staleness_mask)
    observed_count = len(matching_values) - missing_count
    coverage_bp = _ratio_bp(observed_count, len(matching_values))
    payload: dict[str, Any] = {
        "schema_version": "ml-dataset-readiness-manifest.v1",
        "dataset_id": dataset_id,
        "decision_at": snapshot.decision_at,
        "history_start_date": snapshot.history_start_date,
        "included_statuses": list(included_statuses),
        "feature_ids": list(feature_ids),
        "feature_record_hashes": [
            record.record_hash for record in ordered_records
        ],
        "feature_count": len(feature_ids),
        "observation_count": len(observation_hashes),
        "feature_value_count": len(matching_values),
        "observed_value_count": observed_count,
        "missing_value_count": missing_count,
        "stale_value_count": stale_count,
        "coverage_bp": coverage_bp,
        "observation_hashes": list(observation_hashes),
        "source_snapshot_hash": snapshot.snapshot_hash,
        "eligibility_manifest_hash": snapshot.eligibility_manifest_hash,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
    }
    payload["manifest_hash"] = _sha256(_canonical_json(payload))
    return payload


def _mask_summary(snapshot: AllFieldPITSnapshot) -> dict[str, Any]:
    by_family: dict[str, dict[str, int]] = {}
    for observation in snapshot.observations:
        counters = by_family.setdefault(
            observation.family,
            {
                "feature_value_count": 0,
                "missing_value_count": 0,
                "stale_value_count": 0,
                "formal_training_eligible_value_count": 0,
            },
        )
        for value in observation.values:
            counters["feature_value_count"] += 1
            counters["missing_value_count"] += int(value.missing_mask)
            counters["stale_value_count"] += int(value.staleness_mask)
            counters["formal_training_eligible_value_count"] += int(
                value.formal_training_eligible
            )
    totals = {
        key: sum(family.get(key, 0) for family in by_family.values())
        for key in (
            "feature_value_count",
            "missing_value_count",
            "stale_value_count",
            "formal_training_eligible_value_count",
        )
    }
    return {
        "missing_is_not_zero": True,
        "staleness_is_explicit": True,
        "totals": totals,
        "by_family": dict(sorted(by_family.items())),
    }


def _eligibility_payload(record: FeatureEligibilityRecord) -> dict[str, Any]:
    payload = asdict(record)
    payload["feature_id"] = record.feature_id
    payload["is_numeric_feature"] = record.is_numeric_feature
    payload["formal_training_eligible"] = record.formal_training_eligible
    return payload


def _ratio_bp(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return (numerator * 10_000 + denominator // 2) // denominator


def _atomic_write_json(path: Path, payload: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"
    try:
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _default_database_path() -> Path:
    data_root = Path(os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data"))
    if os.environ.get("PROFILE", "prod") == "test":
        data_root = data_root / "_test"
    return data_root / "sqlite" / "twstock.db"


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
