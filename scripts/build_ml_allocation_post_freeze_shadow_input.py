"""從 immutable raw PIT publication 建立 post-freeze ML shadow inference 輸入。

這個入口只組裝一個指定決策時間的 ``allocation-inference-input-v2``。
模型 schema custody 來自已凍結的 training manifest；特徵值則來自另一個、
可晚於模型 freeze 的 immutable raw PIT publication。兩者的 hash 不可混為一談：
row 使用模型 artifact 所要求的 dataset / registry / source hashes，新資料快照的
publication、dataset 與 content hashes 另寫入自簽 audit。

價格、技術、market index 與 industry index 特徵都只接受呼叫端明示且由 raw
OHLC 證明的 T-1 交易日。Portfolio state 固定為非 live、T-1、cash-only shadow；
不讀取 live ledger、Advice 或 broker，也不產生 teacher targets。所有 promotion
與 production 權限固定關閉。
"""

from __future__ import annotations

import argparse
from contextlib import nullcontext
from dataclasses import asdict, replace
from datetime import date, datetime, time, timezone
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.portfolio_ml_dataset_assembler import (  # noqa: E402
    PortfolioMLDatasetAssembler,
    _CurrentValue,
    _FeatureDefinition,
    _advance_current_features,
    _base_feature_definitions,
    _build_feature_snapshot,
    _current_values,
    _feature_pack_payloads,
    _finalize_long_format_definitions,
    _initialize_spool,
    _membership_provenance_for_decision,
    _sectors_for_decision,
    _spool_sector_memberships,
    _validate_raw_dataset_manifest,
)
from data_module.company_registry import (  # noqa: E402
    INDUSTRY_CODE_TO_CATEGORY,
)
from ml_module.allocation_contracts import (  # noqa: E402
    AllocationWeightContract,
    CausalPortfolioState,
    PITFeatureValue,
    PortfolioMLDatasetRow,
    post_freeze_shadow_decision_scope,
)
from scripts.build_ml_allocation_matured_replay_input import (  # noqa: E402
    _atomic_commit_outputs,
)


INPUT_SCHEMA_VERSION = "allocation-inference-input-v2"
AUDIT_SCHEMA_VERSION = "allocation-inference-post-freeze-shadow-audit-v2"
RAW_PUBLICATION_SCHEMA_VERSION = "ml-pit-year-shards.v1"
RAW_DATASET_SCHEMA_VERSION = "ml-pit-year-shard-dataset.v1"
TRAINING_MANIFEST_SCHEMA_VERSION = "allocation-training-output-manifest-v2"
BENCHMARK_ENTITY_ID = "TAIEX"
FORMAL_RAW_DATASET_ID = "all_field_enriched"
_TAIPEI = ZoneInfo("Asia/Taipei")
_DECISION_TIME = time(8, 30)
_STRICT_T_MINUS_ONE_TABLES = frozenset(
    {
        "daily_prices",
        "technical_indicators",
        "market_indices",
        "industry_indices",
    }
)
_ALLOWED_MODEL_ONLY_SOURCE_IDS = frozenset(
    {
        "sidecar:official_corporate_action_ledger",
        "sidecar:pit_sector_membership",
    }
)
# 目前凍結模型把產業資料定義為一般收盤產業指數。這個明確的
# feature-registry 契約不包含報酬指數；未來若增加另一種指數，必須先以
# 新 feature id 定義語意，否則 machine membership 只會保留缺值。
_INDUSTRY_PRICE_FEATURE_IDS = frozenset(
    {
        "industry_indices.收盤指數",
        "industry_indices.漲跌百分比",
        "industry_indices.漲跌點數",
    }
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-dataset-manifest",
        type=Path,
        required=True,
        help="all_field_enriched/manifest.json",
    )
    parser.add_argument(
        "--expected-raw-publication-manifest-hash",
        required=True,
        help="外部 custody 的 raw publication canonical sha256:<64 hex>",
    )
    parser.add_argument(
        "--expected-raw-dataset-manifest-hash",
        required=True,
        help="外部 custody 的 raw dataset canonical sha256:<64 hex>",
    )
    parser.add_argument(
        "--training-manifest",
        type=Path,
        required=True,
        help="凍結模型的 allocation-training-output-manifest-v2",
    )
    parser.add_argument(
        "--expected-training-manifest-file-hash",
        required=True,
        help="training manifest 檔案 bytes 的 sha256:<64 hex>",
    )
    parser.add_argument(
        "--decision-at",
        required=True,
        help=(
            "單一決策時間；正式／無 machine 輸入固定為 Asia/Taipei 08:30，"
            "machine shadow 可用已發生且帶 timezone 的實際盤後時間"
        ),
    )
    parser.add_argument(
        "--expected-price-date",
        required=True,
        help="呼叫端依官方交易日曆決定的嚴格 T-1 日期 YYYY-MM-DD",
    )
    parser.add_argument(
        "--pit-machine-operational-publication",
        type=Path,
        help=(
            "可選的受控 machine PIT operational publication；只在明確 "
            "decision_at 後讀取，不回填歷史"
        ),
    )
    parser.add_argument(
        "--expected-symbol-count",
        type=int,
        default=11,
        help="bounded raw publication 應有的股票數；正式批次固定為 11",
    )
    parser.add_argument(
        "--post-freeze-shadow-input-output",
        type=Path,
        required=True,
        help="檔名須含 post_freeze_shadow 且以 .json.gz 結尾",
    )
    parser.add_argument(
        "--audit-output",
        type=Path,
        required=True,
        help="檔名須含 post_freeze_shadow 且以 .json 結尾",
    )
    parser.add_argument("--batch-size", type=int, default=2_048)
    parser.add_argument("--compression-level", type=int, default=6)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_standard_streams_utf8()
    args = _parser().parse_args(argv)
    try:
        summary = _run(
            raw_dataset_manifest=args.raw_dataset_manifest,
            expected_raw_publication_manifest_hash=(
                args.expected_raw_publication_manifest_hash
            ),
            expected_raw_dataset_manifest_hash=(
                args.expected_raw_dataset_manifest_hash
            ),
            training_manifest=args.training_manifest,
            expected_training_manifest_file_hash=(
                args.expected_training_manifest_file_hash
            ),
            decision_at=args.decision_at,
            expected_price_date=args.expected_price_date,
            pit_machine_operational_publication=(
                args.pit_machine_operational_publication
            ),
            expected_symbol_count=args.expected_symbol_count,
            post_freeze_shadow_input_output=(
                args.post_freeze_shadow_input_output
            ),
            audit_output=args.audit_output,
            batch_size=args.batch_size,
            compression_level=args.compression_level,
        )
    except (OSError, TypeError, ValueError, KeyError, sqlite3.Error) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "mode": "post_freeze_shadow",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "live_data": False,
                    "formal_oos_allowed": False,
                    "production_action_allowed": False,
                    "production_blend_alpha_bp": 0,
                    "broker_order_allowed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _run(
    *,
    raw_dataset_manifest: Path,
    expected_raw_publication_manifest_hash: str,
    expected_raw_dataset_manifest_hash: str,
    training_manifest: Path,
    expected_training_manifest_file_hash: str,
    decision_at: str,
    expected_price_date: str,
    pit_machine_operational_publication: Path | None,
    expected_symbol_count: int,
    post_freeze_shadow_input_output: Path,
    audit_output: Path,
    batch_size: int,
    compression_level: int,
) -> dict[str, Any]:
    _validate_integer_option(
        expected_symbol_count,
        field_name="expected_symbol_count",
        minimum=1,
        maximum=100_000,
    )
    _validate_integer_option(
        batch_size,
        field_name="batch_size",
        minimum=1,
        maximum=100_000,
    )
    _validate_integer_option(
        compression_level,
        field_name="compression_level",
        minimum=0,
        maximum=9,
    )
    for field_name, value in (
        (
            "expected_raw_publication_manifest_hash",
            expected_raw_publication_manifest_hash,
        ),
        (
            "expected_raw_dataset_manifest_hash",
            expected_raw_dataset_manifest_hash,
        ),
        (
            "expected_training_manifest_file_hash",
            expected_training_manifest_file_hash,
        ),
    ):
        _require_sha256(value, field_name=field_name)

    requested_decision = _requested_decision_datetime(
        decision_at,
        machine_operational_path=pit_machine_operational_publication,
    )
    price_date = _iso_date(
        expected_price_date,
        field_name="expected_price_date",
    )
    if price_date >= requested_decision.date():
        raise ValueError(
            "expected_price_date must be a T-1-or-earlier trading date"
        )
    _validate_output_paths(
        raw_dataset_manifest=raw_dataset_manifest,
        training_manifest=training_manifest,
        post_freeze_shadow_input_output=post_freeze_shadow_input_output,
        audit_output=audit_output,
    )

    raw_manifest = _load_json_object(
        raw_dataset_manifest,
        field_name="raw dataset manifest",
    )
    _validate_raw_dataset_manifest(raw_manifest)
    if raw_manifest.get("schema_version") != RAW_DATASET_SCHEMA_VERSION:
        raise ValueError("unsupported raw dataset manifest schema")
    if raw_manifest.get("dataset_id") != FORMAL_RAW_DATASET_ID:
        raise ValueError(
            "post-freeze shadow input requires all_field_enriched"
        )
    raw_dataset_hash = _text(
        raw_manifest.get("manifest_hash"),
        field_name="raw dataset manifest_hash",
    )
    if raw_dataset_hash != expected_raw_dataset_manifest_hash:
        raise ValueError("raw dataset manifest external custody hash mismatch")

    publication_manifest_path = (
        raw_dataset_manifest.resolve().parent.parent / "manifest.json"
    )
    raw_publication = _load_raw_publication(
        publication_manifest_path,
        expected_manifest_hash=expected_raw_publication_manifest_hash,
        raw_dataset_manifest=raw_dataset_manifest,
        raw_dataset_manifest_hash=raw_dataset_hash,
    )
    _validate_eligibility_custody(
        publication_manifest_path=publication_manifest_path,
        publication=raw_publication,
        raw_dataset_manifest=raw_manifest,
    )
    symbols = _bounded_symbols(
        raw_publication,
        expected_symbol_count=expected_symbol_count,
    )
    raw_cutoff = _available_datetime(
        _text(
            raw_manifest.get("decision_at"),
            field_name="raw dataset decision_at",
        ),
        field_name="raw dataset decision_at",
    )
    publication_cutoff = _available_datetime(
        _text(
            raw_publication.get("decision_at"),
            field_name="raw publication decision_at",
        ),
        field_name="raw publication decision_at",
    )
    if raw_cutoff != publication_cutoff:
        raise ValueError(
            "raw dataset and publication decision_at must be identical"
        )
    if raw_cutoff < requested_decision:
        raise ValueError(
            "raw publication cutoff is inadequate for requested decision_at"
        )

    training = _load_training_manifest(
        training_manifest,
        expected_file_hash=expected_training_manifest_file_hash,
    )
    training_as_of = _available_datetime(
        _text(
            training.get("training_as_of"),
            field_name="training_as_of",
        ),
        field_name="training_as_of",
    )
    if requested_decision <= training_as_of:
        raise ValueError(
            "decision_at must be strictly after frozen model training_as_of"
        )
    model_dataset_identity_hash = _sha_text(
        training.get("dataset_identity_hash"),
        field_name="training.dataset_identity_hash",
    )
    model_dataset_manifest_file_hash = _sha_text(
        training.get("dataset_manifest_file_hash"),
        field_name="training.dataset_manifest_file_hash",
    )
    model_feature_registry_hash = _sha_text(
        training.get("feature_registry_hash"),
        field_name="training.feature_registry_hash",
    )
    model_source_hashes = _source_hash_pairs(
        training.get("source_manifest_hashes")
    )
    model_feature_packs = _feature_pack_mappings(
        training.get("feature_packs")
    )

    spool_directory = Path(
        tempfile.mkdtemp(prefix="baldr-post-freeze-shadow-spool-")
    )
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(spool_directory / "snapshot.sqlite")
        connection.row_factory = sqlite3.Row
        _initialize_spool(connection)
        base_definitions = _base_feature_definitions(raw_manifest)
        runtime_definitions = dict(base_definitions)
        source_digest = hashlib.sha256()
        raw_row_count, raw_feature_value_count = (
            PortfolioMLDatasetAssembler()._spool_raw_observations(
                connection=connection,
                dataset_manifest_path=raw_dataset_manifest.resolve(),
                manifest=raw_manifest,
                definitions=runtime_definitions,
                source_digest=source_digest,
                batch_size=batch_size,
            )
        )
        _finalize_long_format_definitions(
            runtime_definitions=runtime_definitions,
            base_definitions=base_definitions,
        )
        definitions = tuple(
            sorted(
                runtime_definitions.values(),
                key=lambda definition: definition.feature_id,
            )
        )
        if not definitions:
            raise ValueError("raw dataset contains no registered features")
        _validate_snapshot_temporal_boundary(
            connection,
            raw_cutoff=raw_cutoff,
            decision_at=requested_decision,
        )
        _validate_model_schema_custody(
            definitions=definitions,
            model_feature_packs=model_feature_packs,
            model_feature_registry_hash=model_feature_registry_hash,
            model_source_hashes=model_source_hashes,
        )
        rows, state, feature_counts = _assemble_shadow_rows(
            connection=connection,
            definitions=definitions,
            symbols=symbols,
            decision_at=requested_decision,
            expected_price_date=price_date,
            dataset_identity_hash=model_dataset_identity_hash,
            feature_registry_hash=model_feature_registry_hash,
            source_manifest_hashes=model_source_hashes,
            batch_size=batch_size,
            machine_operational_path=pit_machine_operational_publication,
            machine_now=(
                datetime.now(timezone.utc)
                if pit_machine_operational_publication is not None
                else None
            ),
        )
    finally:
        if connection is not None:
            connection.close()
        shutil.rmtree(spool_directory)

    input_payload = _inference_input_payload(rows)
    input_bytes = (_canonical_json(input_payload) + "\n").encode("utf-8")
    compressed_bytes = gzip.compress(
        input_bytes,
        compresslevel=compression_level,
        mtime=0,
    )
    input_hash = _sha256(input_bytes)
    compressed_hash = _sha256(compressed_bytes)
    row_payload_hashes = [
        {
            "row_id": row_payload["row_id"],
            "row_payload_hash": _sha256_json(row_payload),
        }
        for row_payload in input_payload["rows"]
    ]

    audit_without_hash: dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "mode": "post_freeze_shadow",
        "decision_at": requested_decision.isoformat(),
        "expected_price_date": price_date.isoformat(),
        "training_as_of": training_as_of.isoformat(),
        "benchmark_entity_id": BENCHMARK_ENTITY_ID,
        "raw_publication_manifest_hash": (
            expected_raw_publication_manifest_hash
        ),
        "raw_dataset_manifest_hash": raw_dataset_hash,
        "raw_publication_cutoff": raw_cutoff.isoformat(),
        "raw_row_count": raw_row_count,
        "raw_feature_value_count": raw_feature_value_count,
        "raw_content_digest": f"sha256:{source_digest.hexdigest()}",
        "training_manifest_file_hash": (
            expected_training_manifest_file_hash
        ),
        "model_artifact_hash": _sha_text(
            training.get("artifact_hash"),
            field_name="training.artifact_hash",
        ),
        "model_dataset_id": _text(
            training.get("dataset_id"),
            field_name="training.dataset_id",
        ),
        "model_dataset_identity_hash": model_dataset_identity_hash,
        "model_dataset_manifest_file_hash": (
            model_dataset_manifest_file_hash
        ),
        "model_feature_registry_hash": model_feature_registry_hash,
        "model_source_manifest_hashes": [
            list(item) for item in model_source_hashes
        ],
        "model_feature_packs": list(model_feature_packs),
        "schema_custody_policy": (
            "frozen_model_hashes_with_separate_new_raw_snapshot_hashes"
        ),
        "selected_symbols": list(symbols),
        "selected_symbol_count": len(symbols),
        "selected_row_count": len(rows),
        "strict_t_minus_one_tables": sorted(
            _STRICT_T_MINUS_ONE_TABLES
        ),
        "strict_t_minus_one_price_proof": {
            "stock_symbol_count": len(symbols),
            "benchmark_entity_id": BENCHMARK_ENTITY_ID,
            "event_date": price_date.isoformat(),
            "positive_ohlc_required": True,
        },
        "feature_counts": feature_counts,
        "pit_machine_operational_publication": (
            None
            if pit_machine_operational_publication is None
            else str(pit_machine_operational_publication.resolve())
        ),
        "row_payload_hashes": row_payload_hashes,
        "portfolio_state_hash": state.state_hash,
        "portfolio_state_policy": {
            "mode": "post_freeze_shadow_non_live_cash_only",
            "as_of_date": state.as_of_date,
            "cash_bp": state.weights.cash_bp,
            "positions_bp": [],
            "weekly_turnover_used_bp": 0,
            "reads_live_portfolio": False,
            "reads_same_day_advice": False,
        },
        "inference_input_schema_version": INPUT_SCHEMA_VERSION,
        "inference_input_uncompressed_hash": input_hash,
        "inference_input_compressed_hash": compressed_hash,
        "top_level_fields": ["rows", "schema_version"],
        "supervised_fields_removed": ["targets", "horizon_labels"],
        "supervised_field_occurrence_count": 0,
        "live_data": False,
        "current_live_portfolio_claimed": False,
        "formal_oos_allowed": False,
        "production_action_allowed": False,
        "production_blend_alpha_bp": 0,
        "broker_order_allowed": False,
        "not_performed": [
            "live_portfolio_read",
            "teacher_target_generation",
            "model_inference",
            "formal_oos_authorization",
            "rule_weight_blend",
            "portfolio_risk_projection",
            "advice_composition",
            "broker_order_routing",
        ],
    }
    audit_hash = _sha256_json(audit_without_hash)
    audit_payload = {
        **audit_without_hash,
        "audit_hash": audit_hash,
    }
    audit_bytes = (
        json.dumps(
            audit_payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    _atomic_commit_outputs(
        (
            (post_freeze_shadow_input_output, compressed_bytes),
            # audit 最後 replace，作為同一 shadow snapshot 的 commit marker。
            (audit_output, audit_bytes),
        )
    )
    return {
        "status": "post_freeze_shadow_input_built",
        "mode": "post_freeze_shadow",
        "decision_at": requested_decision.isoformat(),
        "expected_price_date": price_date.isoformat(),
        "selected_row_count": len(rows),
        "selected_symbol_count": len(symbols),
        "feature_counts": feature_counts,
        "inference_input_uncompressed_hash": input_hash,
        "inference_input_compressed_hash": compressed_hash,
        "audit_hash": audit_hash,
        "post_freeze_shadow_input_output": str(
            post_freeze_shadow_input_output
        ),
        "audit_output": str(audit_output),
        "live_data": False,
        "formal_oos_allowed": False,
        "production_action_allowed": False,
        "production_blend_alpha_bp": 0,
        "broker_order_allowed": False,
    }


def _load_raw_publication(
    path: Path,
    *,
    expected_manifest_hash: str,
    raw_dataset_manifest: Path,
    raw_dataset_manifest_hash: str,
) -> Mapping[str, Any]:
    publication = _load_json_object(
        path,
        field_name="raw publication manifest",
    )
    if publication.get("schema_version") != RAW_PUBLICATION_SCHEMA_VERSION:
        raise ValueError("unsupported raw publication manifest schema")
    if publication.get("stage") != "raw_pit_observations":
        raise ValueError("raw publication stage mismatch")
    declared_hash = _self_hash(
        publication,
        field_name="raw publication manifest",
    )
    if declared_hash != expected_manifest_hash:
        raise ValueError(
            "raw publication manifest external custody hash mismatch"
        )
    pit = _mapping(publication.get("pit"), field_name="raw publication.pit")
    if pit.get("strict_availability_required") is not True:
        raise ValueError("raw publication lacks strict PIT availability")
    if pit.get("future_rows_allowed") is not False:
        raise ValueError("raw publication allows future rows")
    if pit.get("first_seen_fallback_may_backdate") is not False:
        raise ValueError("raw publication allows first-seen backdating")
    execution = _mapping(
        publication.get("execution"),
        field_name="raw publication.execution",
    )
    if execution.get("production_action_allowed") is not False:
        raise ValueError("raw publication cannot authorize production action")

    datasets = _mapping(
        publication.get("datasets"),
        field_name="raw publication.datasets",
    )
    entry = _mapping(
        datasets.get(FORMAL_RAW_DATASET_ID),
        field_name="raw publication.datasets.all_field_enriched",
    )
    if entry.get("manifest_hash") != raw_dataset_manifest_hash:
        raise ValueError("raw publication dataset hash mismatch")
    relative = _text(
        entry.get("manifest_path"),
        field_name="raw publication dataset manifest_path",
    )
    resolved_entry = (path.resolve().parent / relative).resolve()
    if resolved_entry != raw_dataset_manifest.resolve():
        raise ValueError("raw publication dataset path custody mismatch")
    if not resolved_entry.is_relative_to(path.resolve().parent):
        raise ValueError("raw dataset manifest path escapes publication root")
    return publication


def _bounded_symbols(
    publication: Mapping[str, Any],
    *,
    expected_symbol_count: int,
) -> tuple[str, ...]:
    scope = _mapping(
        publication.get("scope"),
        field_name="raw publication.scope",
    )
    if scope.get("all_universe") is not False:
        raise ValueError(
            "post-freeze shadow requires an explicit bounded symbol universe"
        )
    raw_symbols = scope.get("symbols")
    if not isinstance(raw_symbols, list):
        raise TypeError("raw publication scope.symbols must be an array")
    symbols = tuple(
        _text(value, field_name="raw publication scope.symbols[]")
        for value in raw_symbols
    )
    if (
        len(symbols) != expected_symbol_count
        or len(symbols) != len(set(symbols))
        or symbols != tuple(sorted(symbols))
    ):
        raise ValueError(
            "raw publication bounded symbol universe count/order mismatch"
        )
    expected_hash = _sha256_json(
        {
            "all_universe": False,
            "symbols": list(symbols),
        }
    )
    if scope.get("symbols_hash") != expected_hash:
        raise ValueError("raw publication symbols_hash mismatch")
    return symbols


def _validate_eligibility_custody(
    *,
    publication_manifest_path: Path,
    publication: Mapping[str, Any],
    raw_dataset_manifest: Mapping[str, Any],
) -> None:
    source = _mapping(
        publication.get("source"),
        field_name="raw publication.source",
    )
    relative = _text(
        source.get("eligibility_file"),
        field_name="raw publication.source.eligibility_file",
    )
    publication_root = publication_manifest_path.resolve().parent
    eligibility_path = (publication_root / relative).resolve()
    if not eligibility_path.is_relative_to(publication_root):
        raise ValueError("eligibility manifest path escapes publication root")
    if not eligibility_path.is_file():
        raise FileNotFoundError(
            f"eligibility manifest is missing: {eligibility_path}"
        )
    expected_file_hash = _sha_text(
        source.get("eligibility_file_sha256"),
        field_name="eligibility_file_sha256",
    )
    raw_bytes = eligibility_path.read_bytes()
    if _sha256(raw_bytes) != expected_file_hash:
        raise ValueError("eligibility manifest file hash mismatch")
    try:
        decoded = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid eligibility manifest JSON") from exc
    eligibility = _mapping(
        decoded,
        field_name="eligibility manifest",
    )
    if (
        eligibility.get("schema_version")
        != "ml-feature-eligibility-matrix.v1"
    ):
        raise ValueError("unsupported eligibility manifest schema")
    declared_manifest_hash = _sha_text(
        eligibility.get("manifest_hash"),
        field_name="eligibility manifest_hash",
    )
    if declared_manifest_hash != source.get("eligibility_manifest_hash"):
        raise ValueError(
            "publication eligibility manifest hash custody mismatch"
        )
    if declared_manifest_hash != raw_dataset_manifest.get(
        "eligibility_manifest_hash"
    ):
        raise ValueError(
            "dataset eligibility manifest hash custody mismatch"
        )
    records = _mapping_sequence(
        eligibility.get("records"),
        field_name="eligibility.records",
    )
    feature_ids: list[str] = []
    record_hashes: list[str] = []
    for record in records:
        table_name = _text(
            record.get("table_name"),
            field_name="eligibility.table_name",
        )
        column_name = _text(
            record.get("column_name"),
            field_name="eligibility.column_name",
        )
        record_hash = _sha_text(
            record.get("record_hash"),
            field_name=f"{table_name}.{column_name}.record_hash",
        )
        body = dict(record)
        body.pop("record_hash", None)
        if _sha256_json(body) != record_hash:
            raise ValueError(
                "eligibility record self-hash mismatch: "
                f"{table_name}.{column_name}"
            )
        feature_ids.append(f"{table_name}.{column_name}")
        record_hashes.append(record_hash)
    if feature_ids != sorted(feature_ids) or len(feature_ids) != len(
        set(feature_ids)
    ):
        raise ValueError(
            "eligibility records must be canonically ordered and unique"
        )
    inspected_tables = _text_array(
        eligibility.get("inspected_tables"),
        field_name="eligibility.inspected_tables",
    )
    missing_tables = _text_array(
        eligibility.get("missing_tables"),
        field_name="eligibility.missing_tables",
    )
    if inspected_tables != tuple(sorted(inspected_tables)):
        raise ValueError("eligibility inspected_tables must be sorted")
    if missing_tables != tuple(sorted(missing_tables)):
        raise ValueError("eligibility missing_tables must be sorted")
    computed_manifest_hash = _sha256_json(
        {
            "records": record_hashes,
            "inspected_tables": list(inspected_tables),
            "missing_tables": list(missing_tables),
        }
    )
    if computed_manifest_hash != declared_manifest_hash:
        raise ValueError("eligibility manifest canonical hash mismatch")
    if raw_dataset_manifest.get("source_fingerprint") != source.get(
        "database_fingerprint"
    ):
        raise ValueError("raw database source fingerprint custody mismatch")


def _load_training_manifest(
    path: Path,
    *,
    expected_file_hash: str,
) -> Mapping[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"training manifest is missing: {resolved}")
    raw_bytes = resolved.read_bytes()
    if _sha256(raw_bytes) != expected_file_hash:
        raise ValueError("training manifest external file hash mismatch")
    try:
        decoded = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid UTF-8 training manifest JSON") from exc
    manifest = _mapping(decoded, field_name="training manifest")
    if manifest.get("schema_version") != TRAINING_MANIFEST_SCHEMA_VERSION:
        raise ValueError("unsupported training manifest schema")
    if manifest.get("status") != "training_completed":
        raise ValueError("training manifest is not completed")
    if manifest.get("formal_oos_allowed") is not False:
        raise ValueError("training manifest cannot authorize Formal OOS")
    if manifest.get("production_action_allowed") is not False:
        raise ValueError("training manifest cannot authorize production action")
    if manifest.get("production_alpha_bp") != 0:
        raise ValueError("training manifest cannot authorize non-zero alpha")
    _sha_text(
        manifest.get("artifact_hash"),
        field_name="training.artifact_hash",
    )
    return manifest


def _validate_snapshot_temporal_boundary(
    connection: sqlite3.Connection,
    *,
    raw_cutoff: datetime,
    decision_at: datetime,
) -> None:
    beyond_raw_cutoff = int(
        connection.execute(
            "SELECT COUNT(*) FROM observations WHERE available_at > ?",
            (raw_cutoff.isoformat(),),
        ).fetchone()[0]
    )
    if beyond_raw_cutoff:
        raise ValueError(
            "raw observation available_at exceeds publication cutoff"
        )
    poisoned_price = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM observations
            WHERE source_table IN (
                'daily_prices',
                'technical_indicators',
                'market_indices',
                'industry_indices'
            )
              AND available_at <= ?
              AND SUBSTR(event_at, 1, 10) >= ?
            """,
            (decision_at.isoformat(), decision_at.date().isoformat()),
        ).fetchone()[0]
    )
    if poisoned_price:
        raise ValueError(
            "price/technical future-prefix poison is available at decision"
        )
    future_realized = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM observations
            WHERE available_at <= ? AND event_at > ?
            """,
            (decision_at.isoformat(), decision_at.isoformat()),
        ).fetchone()[0]
    )
    if future_realized:
        raise ValueError(
            "future event observation cannot be represented as realized feature"
        )


def _validate_model_schema_custody(
    *,
    definitions: tuple[_FeatureDefinition, ...],
    model_feature_packs: tuple[Mapping[str, Any], ...],
    model_feature_registry_hash: str,
    model_source_hashes: tuple[tuple[str, str], ...],
) -> None:
    runtime_packs = _feature_pack_payloads(definitions)
    if runtime_packs != [dict(pack) for pack in model_feature_packs]:
        raise ValueError(
            "raw feature packs do not match frozen model schema custody"
        )
    registry_payload = {
        "features": [asdict(definition) for definition in definitions],
        "feature_packs": runtime_packs,
    }
    if _sha256_json(registry_payload) != model_feature_registry_hash:
        raise ValueError(
            "raw feature registry hash does not match frozen model"
        )
    runtime_source_ids = {
        definition.source_id for definition in definitions
    } | {"derived:feature_quality"}
    model_source_ids = {source_id for source_id, _ in model_source_hashes}
    if not runtime_source_ids.issubset(model_source_ids):
        raise ValueError(
            "raw source IDs are absent from frozen model source custody"
        )
    if (
        model_source_ids - runtime_source_ids
    ) - _ALLOWED_MODEL_ONLY_SOURCE_IDS:
        raise ValueError(
            "frozen model contains unsupported source schema identities"
        )


def _assemble_shadow_rows(
    *,
    connection: sqlite3.Connection,
    definitions: tuple[_FeatureDefinition, ...],
    symbols: tuple[str, ...],
    decision_at: datetime,
    expected_price_date: date,
    dataset_identity_hash: str,
    feature_registry_hash: str,
    source_manifest_hashes: tuple[tuple[str, str], ...],
    batch_size: int,
    machine_operational_path: Path | None = None,
    machine_now: datetime | None = None,
) -> tuple[
    tuple[PortfolioMLDatasetRow, ...],
    CausalPortfolioState,
    Mapping[str, Any],
]:
    machine_sector_manifest_hash: str | None = None
    machine_sector_count = 0
    if machine_operational_path is not None:
        machine_sector_manifest_hash, machine_sector_count = (
            _spool_sector_memberships(
                connection,
                None,
                training_as_of=decision_at,
                machine_operational_path=machine_operational_path,
                machine_now=machine_now,
            )
        )
    _advance_current_features(
        connection,
        previous_cutoff="0001-01-01T00:00:00+08:00",
        decision_at=decision_at.isoformat(),
        decision_date=decision_at.date().isoformat(),
        batch_size=batch_size,
    )
    _require_t_minus_one_ohlc(
        connection,
        scope="market",
        entity_key=BENCHMARK_ENTITY_ID,
        expected_price_date=expected_price_date,
        decision_at=decision_at,
    )
    for symbol in symbols:
        _require_t_minus_one_ohlc(
            connection,
            scope="stock",
            entity_key=symbol,
            expected_price_date=expected_price_date,
            decision_at=decision_at,
        )

    by_scope = {
        scope: tuple(
            definition
            for definition in definitions
            if definition.scope == scope
        )
        for scope in ("stock", "market", "industry")
    }
    feature_by_id = {
        definition.feature_id: definition for definition in definitions
    }
    expected_feature_families = {
        feature_id: pack["pack_id"]
        for pack in _feature_pack_payloads(definitions)
        for feature_id in pack["feature_ids"]
    }
    industry_feature_ids = frozenset(
        definition.feature_id
        for definition in definitions
        if definition.scope == "industry"
    )
    sectors: dict[str, str] = {}
    membership_provenance: dict[str, tuple[str | None, str]] = {}
    symbol_markets: dict[str, str | None] = {}
    symbol_market_sources: dict[str, str] = {}
    industry_current_by_sector: dict[str, dict[str, _CurrentValue]] = {}
    industry_entity_lineage: dict[str, str | None] = {}
    industry_index_kind: str | None = None
    industry_index_contract: tuple[str, str] | None = None
    industry_index_market_scope: str | None = None
    if machine_operational_path is not None:
        decision_date = decision_at.astimezone(_TAIPEI).date().isoformat()
        sectors = _sectors_for_decision(
            connection,
            decision_date=decision_date,
            decision_at=decision_at.isoformat(),
        )
        membership_provenance = _membership_provenance_for_decision(
            connection,
            decision_date=decision_date,
            decision_at=decision_at.isoformat(),
        )
        symbol_markets = {
            symbol: provenance[0]
            for symbol, provenance in membership_provenance.items()
        }
        symbol_market_sources = {
            symbol: provenance[1]
            for symbol, provenance in membership_provenance.items()
        }
        industry_index_kind = _industry_index_kind(
            definition.feature_id for definition in by_scope["industry"]
        )
        industry_index_contract = _industry_index_contract(
            by_scope["industry"]
        )
        if industry_index_contract is None:
            industry_index_kind = None
        industry_index_market_scope = (
            None
            if industry_index_contract is None
            else industry_index_contract[1]
        )
        for sector_id in sorted(set(sectors.values())):
            industry_current: dict[str, _CurrentValue] = {}
            selected_entity: str | None = None
            for entity_id in _industry_entity_candidates(
                sector_id,
                index_kind=industry_index_kind,
            ):
                candidate = _strict_t_minus_one_values(
                    _current_values(
                        connection,
                        scope="industry",
                        entity_key=entity_id,
                        decision_at=decision_at.isoformat(),
                    ),
                    feature_by_id=feature_by_id,
                    expected_price_date=expected_price_date,
                )
                if candidate:
                    industry_current = candidate
                    selected_entity = entity_id
                    break
            industry_current_by_sector[sector_id] = industry_current
            industry_entity_lineage[sector_id] = selected_entity
    market_current = _strict_t_minus_one_values(
        _current_values(
            connection,
            scope="market",
            entity_key=BENCHMARK_ENTITY_ID,
            decision_at=decision_at.isoformat(),
        ),
        feature_by_id=feature_by_id,
        expected_price_date=expected_price_date,
    )
    state = CausalPortfolioState.create(
        as_of_date=expected_price_date.isoformat(),
        weights=AllocationWeightContract(positions_bp=(), cash_bp=10_000),
        weekly_turnover_used_bp=0,
    )
    rows: list[PortfolioMLDatasetRow] = []
    observed_count = 0
    missing_count = 0
    industry_observed_count = 0
    industry_missing_count = 0
    industry_scope_mismatch_symbols: list[str] = []
    missing_by_family: dict[str, int] = {}
    decision_scope = (
        post_freeze_shadow_decision_scope()
        if machine_operational_path is not None
        else nullcontext()
    )
    with decision_scope:
        for symbol in symbols:
            stock_current = _strict_t_minus_one_values(
                _current_values(
                    connection,
                    scope="stock",
                    entity_key=symbol,
                    decision_at=decision_at.isoformat(),
                ),
                feature_by_id=feature_by_id,
                expected_price_date=expected_price_date,
            )
            features, missing_families = _build_feature_snapshot(
                decision_at=decision_at,
                definitions=definitions,
                feature_by_id=feature_by_id,
                by_scope=by_scope,
                stock_current=stock_current,
                market_current=market_current,
                industry_current=(
                    industry_current_by_sector.get(sectors.get(symbol, ""), {})
                    if machine_operational_path is not None
                    and symbol_markets.get(symbol) == "TWSE"
                    else {}
                ),
                industry_missing_reason=(
                    None
                    if machine_operational_path is None
                    or symbol_markets.get(symbol) == "TWSE"
                    else (
                        "industry_scope_mismatch:registry=TWSE:"
                        f"membership_market={symbol_markets.get(symbol) or 'unknown'}"
                    )
                ),
            )
            normalized_features = _normalize_missing_t_minus_one_events(
                features,
                feature_by_id=feature_by_id,
                expected_price_date=expected_price_date,
                decision_at=decision_at,
            )
            observed_feature_families = {
                feature.feature_id: feature.family_id
                for feature in normalized_features
            }
            if observed_feature_families != expected_feature_families:
                raise ValueError(
                    "assembled feature IDs/families differ from frozen schema"
                )
            exact_missing_families = tuple(
                sorted(
                    {
                        feature.family_id
                        for feature in normalized_features
                        if not feature.observed
                    }
                )
            )
            if missing_families != exact_missing_families:
                raise ValueError("derived missing-family mask mismatch")
            if (
                machine_operational_path is not None
                and symbol_markets.get(symbol) != "TWSE"
                and any(
                    feature.feature_id in industry_feature_ids
                    and not feature.observed
                    for feature in normalized_features
                )
            ):
                industry_scope_mismatch_symbols.append(symbol)
            row = PortfolioMLDatasetRow(
                row_id=(
                    "row:post-freeze-shadow:"
                    f"{decision_at.date().isoformat()}:{symbol}"
                ),
                decision_at=decision_at.isoformat(),
                symbol=symbol,
                features=normalized_features,
                missing_family_ids=exact_missing_families,
                portfolio_state=state,
                dataset_identity_hash=dataset_identity_hash,
                feature_registry_hash=feature_registry_hash,
                source_manifest_hashes=source_manifest_hashes,
                targets=None,
            )
            rows.append(row)
            observed_count += sum(
                int(feature.observed) for feature in normalized_features
            )
            missing_count += sum(
                int(not feature.observed) for feature in normalized_features
            )
            for feature in normalized_features:
                definition = feature_by_id.get(feature.feature_id)
                if definition is None or definition.scope != "industry":
                    continue
                industry_observed_count += int(feature.observed)
                industry_missing_count += int(not feature.observed)
            for family_id in exact_missing_families:
                missing_by_family[family_id] = (
                    missing_by_family.get(family_id, 0) + 1
                )
    return (
        tuple(rows),
        state,
        {
            "feature_count_per_row": len(rows[0].features),
            "observed_feature_value_count": observed_count,
            "missing_feature_value_count": missing_count,
            "rows_with_missing_family_count": sum(
                int(bool(row.missing_family_ids)) for row in rows
            ),
            "missing_family_row_counts": dict(
                sorted(missing_by_family.items())
            ),
            "industry_feature_observed_count": industry_observed_count,
            "industry_feature_missing_count": industry_missing_count,
            "machine_sector_manifest_hash": machine_sector_manifest_hash,
            "machine_sector_row_count": machine_sector_count,
            "machine_sector_mapped_symbol_count": len(sectors),
            "machine_symbol_markets": dict(
                sorted(
                    (symbol, symbol_markets.get(symbol))
                    for symbol in symbols
                )
            ),
            "machine_symbol_market_sources": dict(
                sorted(
                    (symbol, symbol_market_sources.get(symbol, ""))
                    for symbol in symbols
                )
            ),
            "industry_scope_mismatch_symbols": sorted(
                industry_scope_mismatch_symbols
            ),
            "industry_entity_lineage": dict(
                sorted(industry_entity_lineage.items())
            ),
            "industry_index_kind": industry_index_kind,
            "industry_index_market_scope": industry_index_market_scope,
            "industry_index_source_id": (
                "sqlite.industry_indices"
                if industry_index_contract is not None
                else None
            ),
        },
    )


def _industry_index_kind(feature_ids: Iterable[str]) -> str | None:
    """由凍結 feature registry 決定產業指數的明確語意。

    registry 沒有收盤／報酬指數語意時，不猜測資料庫中的 entity；這讓
    未知或日後變更的 feature schema 維持缺值並留下 blocker。
    """

    normalized = frozenset(feature_ids)
    if normalized and normalized.issubset(_INDUSTRY_PRICE_FEATURE_IDS):
        return "price_index"
    return None


def _industry_index_contract(
    definitions: Iterable[_FeatureDefinition],
) -> tuple[str, str] | None:
    """驗證 feature registry 的指數種類、來源與市場範圍契約。"""

    normalized = tuple(definitions)
    if not normalized or any(
        definition.table_name != "industry_indices"
        or definition.source_id != "sqlite.industry_indices"
        for definition in normalized
    ):
        return None
    kind = _industry_index_kind(
        definition.feature_id for definition in normalized
    )
    if kind is None:
        return None
    # 現有 producer（TWSE MI_INDEX）與 feature registry 只證明 TWSE
    # 產業收盤指數。industry_indices 沒有 exchange 欄位不能推導 TPEx；
    # 若日後需要 TPEx，必須新增帶有明確市場語意的 feature contract。
    return kind, "TWSE"


def _industry_entity_candidates(
    sector_id: str,
    *,
    index_kind: str | None,
) -> tuple[str, ...]:
    """把官方兩碼產業代碼映射到明確的 price-index entity identity。

    這是 current-day 的 deterministic code-to-index normalization；它只
    使用 feature registry 已定義的收盤指數語意，不會把報酬指數當成
    收盤指數，也不推導歷史成分或改寫 machine publication 原始代碼。
    """

    if index_kind != "price_index":
        return ()
    raw = sector_id.strip()
    values: list[str] = []

    def append(value: str) -> None:
        value = value.strip()
        if value and value not in values:
            values.append(value)

    category = INDUSTRY_CODE_TO_CATEGORY.get(raw)
    if category is None:
        return tuple(values)
    bases = [category]
    for suffix in ("工業", "產業", "業"):
        if category.endswith(suffix) and len(category) > len(suffix):
            bases.append(category[: -len(suffix)])
    for base in bases:
        append(f"{base}類指數")
    return tuple(values)


def _require_t_minus_one_ohlc(
    connection: sqlite3.Connection,
    *,
    scope: str,
    entity_key: str,
    expected_price_date: date,
    decision_at: datetime,
) -> None:
    latest_row = connection.execute(
        """
        SELECT MAX(event_date)
        FROM prices
        WHERE scope=? AND entity_key=? AND event_date < ?
          AND available_at <= ?
        """,
        (
            scope,
            entity_key,
            decision_at.date().isoformat(),
            decision_at.isoformat(),
        ),
    ).fetchone()
    latest_event_date = None if latest_row is None else latest_row[0]
    if latest_event_date != expected_price_date.isoformat():
        raise ValueError(
            "expected_price_date is not the latest provable T-1 OHLC date: "
            f"{scope}:{entity_key}:latest={latest_event_date}"
        )
    row = connection.execute(
        """
        SELECT available_at, open_int, open_scale, high_int, high_scale,
               low_int, low_scale, close_int, close_scale
        FROM prices
        WHERE scope=? AND entity_key=? AND event_date=?
          AND available_at <= ?
        """,
        (
            scope,
            entity_key,
            expected_price_date.isoformat(),
            decision_at.isoformat(),
        ),
    ).fetchone()
    if row is None:
        raise ValueError(
            "strict T-1 OHLC proof missing: "
            f"{scope}:{entity_key}:{expected_price_date.isoformat()}"
        )
    for field_name in ("open", "high", "low", "close"):
        value = row[f"{field_name}_int"]
        scale = row[f"{field_name}_scale"]
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            or isinstance(scale, bool)
            or not isinstance(scale, int)
            or scale <= 0
        ):
            raise ValueError(
                "strict T-1 OHLC proof contains invalid integer price: "
                f"{scope}:{entity_key}:{field_name}"
            )


def _strict_t_minus_one_values(
    values: Mapping[str, _CurrentValue],
    *,
    feature_by_id: Mapping[str, _FeatureDefinition],
    expected_price_date: date,
) -> dict[str, _CurrentValue]:
    expected = expected_price_date.isoformat()
    result: dict[str, _CurrentValue] = {}
    for feature_id, value in values.items():
        definition = feature_by_id.get(feature_id)
        if definition is None:
            raise ValueError(
                f"current feature is absent from registry: {feature_id}"
            )
        if (
            definition.table_name in _STRICT_T_MINUS_ONE_TABLES
            and value.event_at[:10] != expected
        ):
            continue
        result[feature_id] = value
    return result


def _normalize_missing_t_minus_one_events(
    features: tuple[PITFeatureValue, ...],
    *,
    feature_by_id: Mapping[str, _FeatureDefinition],
    expected_price_date: date,
    decision_at: datetime,
) -> tuple[PITFeatureValue, ...]:
    normalized: list[PITFeatureValue] = []
    for feature in features:
        definition = feature_by_id.get(feature.feature_id)
        if definition is None:
            # data_quality 是由 snapshot builder 衍生，不在 raw definitions。
            normalized.append(feature)
            continue
        if definition.table_name not in _STRICT_T_MINUS_ONE_TABLES:
            normalized.append(feature)
            continue
        if feature.observed:
            if feature.event_at[:10] != expected_price_date.isoformat():
                raise ValueError(
                    f"observed price feature is not strict T-1: {feature.feature_id}"
                )
            normalized.append(feature)
            continue
        preserved_reason = (
            feature.revision_id.removeprefix("missing:")
            if feature.revision_id.startswith("missing:")
            else ""
        )
        missing_reason = (
            preserved_reason
            if preserved_reason.startswith("industry_scope_mismatch:")
            else "strict_t_minus_one_not_observed"
        )
        normalized.append(
            replace(
                feature,
                event_at=expected_price_date.isoformat(),
                revision_id=f"missing:{missing_reason}",
                content_hash=_sha256_json(
                    {
                        "feature_id": feature.feature_id,
                        "decision_at": decision_at.isoformat(),
                        "expected_price_date": (
                            expected_price_date.isoformat()
                        ),
                        "reason": missing_reason,
                    }
                ),
            )
        )
    return tuple(sorted(normalized, key=lambda feature: feature.feature_id))


def _inference_input_payload(
    rows: tuple[PortfolioMLDatasetRow, ...],
) -> dict[str, Any]:
    if not rows:
        raise ValueError("post-freeze shadow input requires rows")
    row_payloads: list[dict[str, Any]] = []
    for row in rows:
        if row.targets is not None:
            raise ValueError("shadow inference row must not contain targets")
        row_payload = asdict(row)
        if row_payload.pop("targets", None) is not None:
            raise ValueError("targets could not be removed from inference row")
        if _contains_supervised_field(row_payload):
            raise ValueError("supervised field remains in inference row")
        row_payloads.append(row_payload)
    payload = {
        "schema_version": INPUT_SCHEMA_VERSION,
        "rows": row_payloads,
    }
    if set(payload) != {"schema_version", "rows"}:
        raise ValueError("inference input top-level contract drift")
    if _contains_supervised_field(payload):
        raise ValueError("supervised field remains in inference input")
    return payload


def _contains_supervised_field(value: object) -> bool:
    if isinstance(value, dict):
        if {"targets", "horizon_labels"} & set(value):
            return True
        return any(
            _contains_supervised_field(item) for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_supervised_field(item) for item in value)
    return False


def _validate_output_paths(
    *,
    raw_dataset_manifest: Path,
    training_manifest: Path,
    post_freeze_shadow_input_output: Path,
    audit_output: Path,
) -> None:
    input_name = post_freeze_shadow_input_output.name.lower()
    audit_name = audit_output.name.lower()
    if (
        "post_freeze_shadow" not in input_name
        or not input_name.endswith(".json.gz")
    ):
        raise ValueError(
            "shadow input name must contain post_freeze_shadow and end .json.gz"
        )
    if (
        "post_freeze_shadow" not in audit_name
        or not audit_name.endswith(".json")
    ):
        raise ValueError(
            "audit name must contain post_freeze_shadow and end .json"
        )
    outputs = {
        post_freeze_shadow_input_output.resolve(),
        audit_output.resolve(),
    }
    if len(outputs) != 2:
        raise ValueError("shadow input and audit outputs must be distinct")
    if outputs & {
        raw_dataset_manifest.resolve(),
        training_manifest.resolve(),
    }:
        raise ValueError("outputs must not overwrite custody manifests")


def _feature_pack_mappings(
    value: object,
) -> tuple[Mapping[str, Any], ...]:
    packs = _mapping_sequence(value, field_name="training.feature_packs")
    if not packs:
        raise ValueError("training feature_packs must not be empty")
    normalized: list[Mapping[str, Any]] = []
    seen_pack_ids: set[str] = set()
    seen_feature_ids: set[str] = set()
    for pack in packs:
        if set(pack) != {"pack_id", "feature_ids"}:
            raise ValueError("training feature pack fields are invalid")
        pack_id = _text(pack.get("pack_id"), field_name="pack_id")
        if pack_id in seen_pack_ids:
            raise ValueError("training feature pack IDs must be unique")
        seen_pack_ids.add(pack_id)
        raw_feature_ids = pack.get("feature_ids")
        if not isinstance(raw_feature_ids, list) or not raw_feature_ids:
            raise TypeError("training feature_ids must be a non-empty array")
        feature_ids = [
            _text(item, field_name=f"{pack_id}.feature_ids[]")
            for item in raw_feature_ids
        ]
        if (
            feature_ids != sorted(feature_ids)
            or len(feature_ids) != len(set(feature_ids))
            or seen_feature_ids.intersection(feature_ids)
        ):
            raise ValueError(
                "training feature IDs must be sorted and globally unique"
            )
        seen_feature_ids.update(feature_ids)
        normalized.append(
            {
                "pack_id": pack_id,
                "feature_ids": feature_ids,
            }
        )
    if [pack["pack_id"] for pack in normalized] != sorted(seen_pack_ids):
        raise ValueError("training feature packs must be sorted")
    return tuple(normalized)


def _source_hash_pairs(
    value: object,
) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list) or not value:
        raise TypeError(
            "training.source_manifest_hashes must be a non-empty array"
        )
    result: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise TypeError(
                "source_manifest_hashes entries must be two-item arrays"
            )
        source_id = _text(item[0], field_name="source_id")
        source_hash = _sha_text(item[1], field_name=f"{source_id}.hash")
        result.append((source_id, source_hash))
    source_ids = tuple(source_id for source_id, _ in result)
    if (
        len(source_ids) != len(set(source_ids))
        or source_ids != tuple(sorted(source_ids))
    ):
        raise ValueError(
            "training source manifest IDs must be unique and sorted"
        )
    return tuple(result)


def _load_json_object(
    path: Path,
    *,
    field_name: str,
) -> Mapping[str, Any]:
    resolved = path.resolve()
    if resolved.name != "manifest.json" or not resolved.is_file():
        raise ValueError(f"{field_name} must be an existing manifest.json")
    try:
        decoded = json.loads(resolved.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {field_name} JSON") from exc
    return _mapping(decoded, field_name=field_name)


def _self_hash(
    payload: Mapping[str, Any],
    *,
    field_name: str,
) -> str:
    declared = _sha_text(
        payload.get("manifest_hash"),
        field_name=f"{field_name}.manifest_hash",
    )
    body = dict(payload)
    body.pop("manifest_hash", None)
    if _sha256_json(body) != declared:
        raise ValueError(f"{field_name} self-hash mismatch")
    return declared


def _mapping_sequence(
    value: object,
    *,
    field_name: str,
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be an array")
    return tuple(
        _mapping(item, field_name=f"{field_name}[]") for item in value
    )


def _mapping(
    value: object,
    *,
    field_name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be an object")
    return value


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be a non-empty string")
    return value


def _text_array(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be an array")
    return tuple(
        _text(item, field_name=f"{field_name}[]") for item in value
    )


def _sha_text(value: object, *, field_name: str) -> str:
    text_value = _text(value, field_name=field_name)
    _require_sha256(text_value, field_name=field_name)
    return text_value


def _decision_datetime(value: str) -> datetime:
    parsed = _available_datetime(value, field_name="decision_at")
    if (
        parsed.timetz().replace(tzinfo=None) != _DECISION_TIME
        or parsed.tzinfo != _TAIPEI
    ):
        raise ValueError("decision_at must be 08:30 Asia/Taipei")
    return parsed


def _requested_decision_datetime(
    value: str,
    *,
    machine_operational_path: Path | None,
) -> datetime:
    """解析 shadow 決策時間，僅 machine 證據允許已發生的盤後時間。"""

    if machine_operational_path is None:
        return _decision_datetime(value)
    if len(value.strip()) == 10:
        raise ValueError(
            "machine post-freeze shadow decision_at requires a timestamp"
        )
    parsed = _available_datetime(value, field_name="decision_at")
    if parsed > datetime.now(timezone.utc).astimezone(_TAIPEI):
        raise ValueError(
            "machine post-freeze shadow decision_at cannot be future-dated"
        )
    return parsed


def _available_datetime(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return parsed.astimezone(_TAIPEI)


def _iso_date(value: str, *, field_name: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must be canonical YYYY-MM-DD")
    return parsed


def _validate_integer_option(
    value: object,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(
            f"{field_name} must be within {minimum}..{maximum}"
        )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_json(value: object) -> str:
    return _sha256(_canonical_json(value).encode("utf-8"))


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _require_sha256(value: str, *, field_name: str) -> None:
    digest = value[7:] if value.startswith("sha256:") else ""
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError(f"{field_name} must be a sha256: digest")


def _configure_standard_streams_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass


if __name__ == "__main__":
    raise SystemExit(main())
