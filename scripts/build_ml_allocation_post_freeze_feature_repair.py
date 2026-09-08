"""建立保留 frozen 輸入、但修復四個特徵語意的 bounded shadow 輸入。

此入口只讀取既有 ``allocation-inference-input-v2`` 與 immutable raw
publication。它從官方 ``market_indices`` TAIEX observation 的連續來源交易日
重算漲跌點數／百分比，並將 ``technical_indicators.涨跌`` 與
``technical_indicators.漲跌(+/-)`` 從新 contract 排除；這兩欄是分類／legacy
欄位，不能把 ``+``、``-`` 或 NULL 偽裝成 numeric feature。

輸出是 ``allocation-inference-input-v3`` candidate。舊 v2 artifact 與 frozen
model 的 registry hash 不會改寫；v3 明確要求新的 model release，仍固定
``formal_oos_allowed=false``、``production_blend_alpha_bp=0``，不寫正式 DB。
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
import gzip
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml_module.allocation_contracts import (  # noqa: E402
    PITFeatureValue,
    PortfolioMLDatasetRow,
    post_freeze_shadow_decision_scope,
)
from ml_module.allocation_feature_contract import (  # noqa: E402
    DERIVED_MARKET_SOURCE_ID,
    DERIVED_MARKET_FEATURE_IDS,
    MARKET_CHANGE_DERIVATION_METHOD,
    AllocationFeatureContract,
    build_market_repair_contract,
    derived_source_manifest_hash,
)
from data_module.official_trading_calendar import (  # noqa: E402
    OfficialTradingCalendar,
)
from scripts.build_ml_allocation_post_freeze_shadow_input import (  # noqa: E402
    RAW_DATASET_SCHEMA_VERSION,
    RAW_PUBLICATION_SCHEMA_VERSION,
    _available_datetime,
    _canonical_json,
    _load_json_object,
    _load_raw_publication,
    _mapping,
    _mapping_sequence,
    _require_sha256,
    _self_hash,
    _sha256,
    _sha256_json,
    _text,
    _validate_eligibility_custody,
    _validate_raw_dataset_manifest,
)
from scripts.infer_ml_allocation_copilot import (  # noqa: E402
    INPUT_SCHEMA_VERSION as LEGACY_INPUT_SCHEMA_VERSION,
    _load_rows as _load_legacy_rows,
    _parse_row as _parse_legacy_row,
)
from scripts.build_ml_allocation_matured_replay_input import (  # noqa: E402
    _atomic_commit_outputs,
)


INPUT_SCHEMA_VERSION = "allocation-inference-input-v3"
AUDIT_SCHEMA_VERSION = "allocation-inference-post-freeze-feature-repair-audit-v1"
_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "feature_contract",
        "feature_contract_hash",
        "parent_input_schema_version",
        "parent_input_compressed_hash",
        "rows",
    }
)
_MARKET_SOURCE_TABLE = "market_indices"
_MARKET_SOURCE_ID = "sqlite.market_indices"
_MARKET_FAMILY_ID = "market_sector_cross_section"
_TAIPEI_TZ = ZoneInfo("Asia/Taipei")
_EFFECTIVE_QUALITY_SOURCE_ID = (
    "derived:feature_quality.effective_contract.v1"
)
_EFFECTIVE_QUALITY_SCHEMA_VERSION = "allocation-effective-quality-projection.v1"
_QUALITY_METRICS = (
    "coverage_bp",
    "missing_count",
    "stale_count",
    "quality_blocked_count",
    "max_available_lag_days",
)


@dataclass(frozen=True)
class _OfficialClose:
    event_date: str
    event_at: str
    available_at: str
    value_int: int
    scale: int
    source_row_hash: str
    source_value_hash: str


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--parent-input",
        type=Path,
        required=True,
        help="既有 allocation-inference-input-v2 JSON.GZ；此檔只讀取",
    )
    parser.add_argument(
        "--expected-parent-input-compressed-hash",
        required=True,
        help="父 v2 artifact bytes 的 sha256:<64 hex>",
    )
    parser.add_argument(
        "--raw-dataset-manifest",
        type=Path,
        required=True,
        help="official raw all_field_enriched/manifest.json",
    )
    parser.add_argument(
        "--expected-raw-publication-manifest-hash",
        required=True,
        help="official raw publication canonical sha256:<64 hex>",
    )
    parser.add_argument(
        "--expected-raw-dataset-manifest-hash",
        required=True,
        help="official raw dataset canonical sha256:<64 hex>",
    )
    parser.add_argument(
        "--expected-decision-at",
        required=True,
        help="父輸入的實際 machine decision timestamp（含 timezone）",
    )
    parser.add_argument(
        "--expected-price-date",
        required=True,
        help="官方 T-1 market close date YYYY-MM-DD",
    )
    parser.add_argument(
        "--calendar-database",
        type=Path,
        required=True,
        help=(
            "只讀的官方 trading-calendar provider database；"
            "缺少日期證據時 fail closed"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="新 v3 JSON.GZ；應與父輸入、raw manifest 分離",
    )
    parser.add_argument(
        "--audit-output",
        type=Path,
        required=True,
        help="新 v3 audit JSON",
    )
    parser.add_argument("--compression-level", type=int, default=6)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_standard_streams_utf8()
    args = _parser().parse_args(argv)
    try:
        summary = _run(
            parent_input=args.parent_input,
            expected_parent_input_compressed_hash=(
                args.expected_parent_input_compressed_hash
            ),
            raw_dataset_manifest=args.raw_dataset_manifest,
            expected_raw_publication_manifest_hash=(
                args.expected_raw_publication_manifest_hash
            ),
            expected_raw_dataset_manifest_hash=(
                args.expected_raw_dataset_manifest_hash
            ),
            expected_decision_at=args.expected_decision_at,
            expected_price_date=args.expected_price_date,
            calendar_database=args.calendar_database,
            output=args.output,
            audit_output=args.audit_output,
            compression_level=args.compression_level,
        )
    except (OSError, TypeError, ValueError, KeyError) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "mode": "post_freeze_feature_repair",
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
    parent_input: Path,
    expected_parent_input_compressed_hash: str,
    raw_dataset_manifest: Path,
    expected_raw_publication_manifest_hash: str,
    expected_raw_dataset_manifest_hash: str,
    expected_decision_at: str,
    expected_price_date: str,
    calendar_database: Path,
    output: Path,
    audit_output: Path,
    compression_level: int,
) -> dict[str, Any]:
    _require_sha256(
        expected_parent_input_compressed_hash,
        field_name="expected_parent_input_compressed_hash",
    )
    _require_sha256(
        expected_raw_publication_manifest_hash,
        field_name="expected_raw_publication_manifest_hash",
    )
    _require_sha256(
        expected_raw_dataset_manifest_hash,
        field_name="expected_raw_dataset_manifest_hash",
    )
    if (
        isinstance(compression_level, bool)
        or not isinstance(compression_level, int)
        or not 0 <= compression_level <= 9
    ):
        raise ValueError("compression_level must be an integer within 0..9")
    expected_decision = _available_datetime(
        expected_decision_at,
        field_name="expected_decision_at",
    )
    if len(expected_price_date) != 10:
        raise ValueError("expected_price_date must be YYYY-MM-DD")
    try:
        datetime.strptime(expected_price_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("expected_price_date must be YYYY-MM-DD") from exc
    _validate_paths(
        parent_input=parent_input,
        raw_dataset_manifest=raw_dataset_manifest,
        calendar_database=calendar_database,
        output=output,
        audit_output=audit_output,
    )

    parent_bytes = parent_input.resolve().read_bytes()
    parent_hash = _sha256(parent_bytes)
    if parent_hash != expected_parent_input_compressed_hash:
        raise ValueError("parent input compressed hash mismatch")
    # v2 rows with a real post-freeze timestamp require the same explicit
    # target-free shadow scope used by the producer.  The old parser remains
    # the consumer for v2 and is intentionally not changed to accept v3.
    with post_freeze_shadow_decision_scope():
        parent_rows = _load_legacy_rows(parent_input.resolve())
    if not parent_rows:
        raise ValueError("parent input contains no rows")
    _validate_parent_rows(
        parent_rows,
        expected_decision=expected_decision,
        expected_price_date=expected_price_date,
    )
    parent_feature_ids = tuple(
        feature.feature_id for feature in parent_rows[0].features
    )
    if any(
        tuple(feature.feature_id for feature in row.features)
        != parent_feature_ids
        for row in parent_rows
    ):
        raise ValueError("parent rows do not share one frozen feature set")
    parent_registry_hash = parent_rows[0].feature_registry_hash
    contract = build_market_repair_contract(
        parent_feature_registry_hash=parent_registry_hash,
        feature_ids=parent_feature_ids,
    )
    market_source_manifest_hash = _source_manifest_hash(
        parent_rows=parent_rows,
        source_id=_MARKET_SOURCE_ID,
    )
    derived_manifest_hash = derived_source_manifest_hash(
        contract=contract,
        input_source_manifest_hash=market_source_manifest_hash,
    )
    quality_manifest_hash = _effective_quality_manifest_hash(
        contract=contract,
        parent_input_hash=parent_hash,
    )

    raw_manifest = _load_json_object(
        raw_dataset_manifest,
        field_name="raw dataset manifest",
    )
    if raw_manifest.get("schema_version") != RAW_DATASET_SCHEMA_VERSION:
        raise ValueError("unsupported raw dataset manifest schema")
    if raw_manifest.get("dataset_id") != "all_field_enriched":
        raise ValueError("feature repair requires all_field_enriched raw data")
    _validate_raw_dataset_manifest(raw_manifest)
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
    official_closes = _load_official_closes(
        raw_dataset_manifest=raw_dataset_manifest.resolve(),
        raw_manifest=raw_manifest,
        expected_price_date=expected_price_date,
        decision_at=expected_decision,
    )
    calendar_previous_date, calendar_evidence = _load_calendar_evidence(
        calendar_database=calendar_database.resolve(),
        expected_price_date=expected_price_date,
    )
    current_close, previous_close = _select_close_pair(
        official_closes,
        expected_price_date=expected_price_date,
        calendar_previous_date=calendar_previous_date,
    )
    derived_values = _derive_market_values(
        contract=contract,
        current=current_close,
        previous=previous_close,
        decision_at=expected_decision,
        expected_price_date=expected_price_date,
    )

    repaired_rows = _repair_rows(
        parent_rows=parent_rows,
        contract=contract,
        derived_manifest_hash=derived_manifest_hash,
        derived_values=derived_values,
        parent_dataset_hash=parent_rows[0].dataset_identity_hash,
        parent_input_hash=parent_hash,
        raw_dataset_hash=raw_dataset_hash,
        quality_manifest_hash=quality_manifest_hash,
    )
    input_payload = _input_payload(
        rows=repaired_rows,
        contract=contract,
        parent_input_hash=parent_hash,
    )
    input_bytes = (_canonical_json(input_payload) + "\n").encode("utf-8")
    compressed_bytes = gzip.compress(
        input_bytes,
        compresslevel=compression_level,
        mtime=0,
    )
    input_hash = _sha256(input_bytes)
    compressed_hash = _sha256(compressed_bytes)

    # Read back both contracts through their real consumers.  The legacy
    # consumer must accept the preserved v2 artifact; it must reject v3 until
    # a new model release explicitly supports the new contract.  Use a
    # temporary candidate file for the negative check so a failed build never
    # leaves a partially published output.
    with post_freeze_shadow_decision_scope():
        consumed_parent = _load_legacy_rows(parent_input.resolve())
        legacy_rejection = _legacy_rejection_for_bytes(compressed_bytes)
    if len(consumed_parent) != len(parent_rows):
        raise ValueError("parent consumer readback row count changed")

    row_payload_hashes = [
        {
            "row_id": row_payload["row_id"],
            "row_payload_hash": _sha256_json(row_payload),
        }
        for row_payload in input_payload["rows"]
    ]
    effective_quality_metrics = {
        row.symbol: _effective_quality_stats(
            features=row.features,
            decision_at=_available_datetime(
                row.decision_at,
                field_name="repaired row.decision_at",
            ),
        )
        for row in repaired_rows
    }
    audit_without_hash: dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "mode": "post_freeze_feature_repair_candidate",
        "decision_at": expected_decision.isoformat(),
        "expected_price_date": expected_price_date,
        "parent_input_schema_version": LEGACY_INPUT_SCHEMA_VERSION,
        "parent_input_compressed_hash": parent_hash,
        "raw_publication_manifest_hash": expected_raw_publication_manifest_hash,
        "raw_dataset_manifest_hash": raw_dataset_hash,
        "feature_contract": contract.payload(),
        "feature_contract_hash": contract.contract_hash,
        "derived_source_manifest_hash": derived_manifest_hash,
        "effective_quality_source_id": _EFFECTIVE_QUALITY_SOURCE_ID,
        "effective_quality_manifest_hash": quality_manifest_hash,
        "effective_quality_method": (
            "recompute_from_effective_pit_feature_set.v1"
        ),
        "effective_quality_metrics": effective_quality_metrics,
        "derived_market_source_id": DERIVED_MARKET_SOURCE_ID,
        "market_derivation_method": MARKET_CHANGE_DERIVATION_METHOD,
        "official_calendar_evidence": calendar_evidence,
        "market_change_derivations": _derivation_proofs(derived_values),
        "excluded_feature_ids": list(contract.excluded_feature_ids),
        "excluded_feature_policy": (
            "classification_or_legacy_untyped_fields_are_not_numeric; "
            "a future release must define an explicit categorical contract"
        ),
        "parent_feature_counts": _feature_counts(parent_rows),
        "repaired_feature_counts": _feature_counts(repaired_rows),
        "selected_row_count": len(repaired_rows),
        "selected_symbols": [row.symbol for row in repaired_rows],
        "inference_comparison": {
            "parent_v2_consumer_accepted": True,
            "parent_v2_row_count": len(consumed_parent),
            "repaired_v3_consumer": "legacy_v2_rejected_until_new_release",
            "legacy_rejection": legacy_rejection,
            "model_inference_performed": False,
            "new_release_required": True,
        },
        "input_uncompressed_hash": input_hash,
        "input_compressed_hash": compressed_hash,
        "row_payload_hashes": row_payload_hashes,
        "live_data": False,
        "formal_oos_allowed": False,
        "production_action_allowed": False,
        "production_blend_alpha_bp": 0,
        "broker_order_allowed": False,
        "not_performed": [
            "formal_model_inference",
            "new_model_release",
            "formal_oos_authorization",
            "formal_database_write",
            "teacher_target_generation",
            "broker_order_routing",
        ],
    }
    audit_hash = _sha256_json(audit_without_hash)
    audit_payload = {**audit_without_hash, "audit_hash": audit_hash}
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
            (output, compressed_bytes),
            (audit_output, audit_bytes),
        )
    )
    # The readback above intentionally happened before output publication for
    # the parent.  Read the newly committed v3 through its dedicated consumer
    # after the atomic commit, so the returned summary is evidence of the
    # actual bytes that were published.
    consumed_repaired = load_repaired_input(
        output,
        expected_contract_hash=contract.contract_hash,
    )
    if len(consumed_repaired) != len(repaired_rows):
        raise ValueError("repaired consumer readback row count changed")
    return {
        "status": "post_freeze_feature_repair_candidate_built",
        "mode": "post_freeze_feature_repair_candidate",
        "decision_at": expected_decision.isoformat(),
        "expected_price_date": expected_price_date,
        "selected_row_count": len(repaired_rows),
        "feature_contract_version": contract.contract_version,
        "feature_contract_hash": contract.contract_hash,
        "effective_quality_source_id": _EFFECTIVE_QUALITY_SOURCE_ID,
        "effective_quality_manifest_hash": quality_manifest_hash,
        "input_compressed_hash": compressed_hash,
        "audit_hash": audit_hash,
        "output": str(output),
        "audit_output": str(audit_output),
        "legacy_v2_consumer_accepted": True,
        "repaired_v3_consumer_readback": True,
        "new_release_required": True,
        "live_data": False,
        "formal_oos_allowed": False,
        "production_action_allowed": False,
        "production_blend_alpha_bp": 0,
        "broker_order_allowed": False,
    }


def _derivation_proofs(
    derived_values: Mapping[str, Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    proofs: list[Mapping[str, Any]] = []
    for feature_id in sorted(derived_values):
        proof = derived_values[feature_id].get("proof")
        if not isinstance(proof, Mapping):
            raise ValueError("derived market value is missing proof")
        proofs.append(proof)
    return proofs


def _validate_paths(
    *,
    parent_input: Path,
    raw_dataset_manifest: Path,
    calendar_database: Path,
    output: Path,
    audit_output: Path,
) -> None:
    output_resolved = output.resolve()
    audit_resolved = audit_output.resolve()
    calendar_resolved = calendar_database.resolve()
    if output_resolved == audit_resolved:
        raise ValueError("output and audit_output must be distinct")
    protected_paths = {
        parent_input.resolve(),
        raw_dataset_manifest.resolve(),
        calendar_resolved,
    }
    if output_resolved in protected_paths:
        raise ValueError("output must not overwrite parent or raw manifest")
    if audit_resolved in protected_paths:
        raise ValueError("audit_output must not overwrite parent or raw manifest")
    if not output_resolved.name.lower().endswith(".json.gz"):
        raise ValueError("output must end with .json.gz")
    if not audit_resolved.name.lower().endswith(".json"):
        raise ValueError("audit_output must end with .json")
    if not parent_input.resolve().is_file():
        raise ValueError("parent_input must be an existing file")
    if not raw_dataset_manifest.resolve().is_file():
        raise ValueError("raw_dataset_manifest must be an existing file")
    if not calendar_resolved.is_file():
        raise ValueError("calendar_database must be an existing file")


def _validate_parent_rows(
    rows: Sequence[PortfolioMLDatasetRow],
    *,
    expected_decision: datetime,
    expected_price_date: str,
) -> None:
    for row in rows:
        if row.decision_at != expected_decision.isoformat():
            raise ValueError("parent row decision_at differs from expected")
        if row.row_id.startswith("row:post-freeze-shadow:") is False:
            raise ValueError("parent row is not a post-freeze shadow row")
        if row.portfolio_state.as_of_date != expected_price_date:
            raise ValueError("parent state date differs from expected price date")
        if row.targets is not None:
            raise ValueError("parent feature repair cannot consume targets")


def _source_manifest_hash(
    *,
    parent_rows: Sequence[PortfolioMLDatasetRow],
    source_id: str,
) -> str:
    values = {
        dict(row.source_manifest_hashes).get(source_id)
        for row in parent_rows
    }
    if len(values) != 1:
        raise ValueError(f"parent source manifest is inconsistent: {source_id}")
    source_hash = next(iter(values))
    if source_hash is None:
        raise ValueError(f"parent source manifest is missing: {source_id}")
    _require_sha256(source_hash, field_name=f"parent source {source_id}")
    return source_hash


def _load_official_closes(
    *,
    raw_dataset_manifest: Path,
    raw_manifest: Mapping[str, Any],
    expected_price_date: str,
    decision_at: datetime,
) -> dict[str, _OfficialClose]:
    publication_root = raw_dataset_manifest.parent.parent.resolve()
    result: dict[str, _OfficialClose] = {}
    shards = _mapping_sequence(raw_manifest.get("shards"), field_name="shards")
    for shard in shards:
        relative = _text(shard.get("path"), field_name="raw shard path")
        shard_path = (publication_root / relative).resolve()
        if not shard_path.is_relative_to(publication_root):
            raise ValueError("raw shard path escapes publication root")
        expected_compressed_hash = _text(
            shard.get("compressed_sha256"),
            field_name="raw shard compressed_sha256",
        )
        _require_sha256(
            expected_compressed_hash,
            field_name="raw shard compressed_sha256",
        )
        if _sha256(shard_path.read_bytes()) != expected_compressed_hash:
            raise ValueError(f"raw shard compressed hash mismatch: {shard_path}")
        with gzip.open(shard_path, "rb") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                if not raw_line.strip():
                    continue
                try:
                    raw_payload = json.loads(raw_line.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"invalid raw JSONL at {shard_path}:{line_number}"
                    ) from exc
                row = _mapping(raw_payload, field_name="raw observation")
                if row.get("source_table") != _MARKET_SOURCE_TABLE:
                    continue
                if row.get("source_id") != _MARKET_SOURCE_ID:
                    continue
                if row.get("entity_id") != "TAIEX":
                    continue
                if row.get("schema_version") != "ml-pit-observation.v1":
                    raise ValueError("unsupported market raw observation schema")
                if row.get("pit_status") != "eligible_as_of_decision":
                    raise ValueError("market raw observation is not PIT eligible")
                source_row_hash = _text(
                    row.get("source_row_hash"),
                    field_name="market source_row_hash",
                )
                _require_sha256(source_row_hash, field_name="market source_row_hash")
                row_without_hash = dict(row)
                row_without_hash.pop("source_row_hash", None)
                if _sha256_json(row_without_hash) != source_row_hash:
                    raise ValueError("market source_row_hash mismatch")
                event_at = _available_datetime(
                    _text(row.get("event_at"), field_name="market event_at"),
                    field_name="market event_at",
                )
                available_at = _available_datetime(
                    _text(
                        row.get("available_at"),
                        field_name="market available_at",
                    ),
                    field_name="market available_at",
                )
                if available_at > decision_at or event_at > decision_at:
                    raise ValueError(
                        "market close evidence is after decision_at: "
                        f"{event_at.isoformat()}"
                    )
                event_date = event_at.astimezone(_TAIPEI_TZ).date().isoformat()
                values = _mapping_sequence(
                    row.get("values"),
                    field_name="market values",
                )
                close_values = [
                    value
                    for value in values
                    if value.get("feature_id") == "market_indices.收盤指數"
                ]
                if len(close_values) != 1:
                    raise ValueError(
                        "official TAIEX observation must contain one 收盤指數: "
                        + event_date
                    )
                close = close_values[0]
                value_int = close.get("value_int")
                scale = close.get("scale")
                if (
                    isinstance(value_int, bool)
                    or not isinstance(value_int, int)
                    or value_int <= 0
                    or isinstance(scale, bool)
                    or not isinstance(scale, int)
                    or scale <= 0
                    or scale != 10_000
                ):
                    raise ValueError(
                        "official TAIEX close must be positive integer scale=10000: "
                        + event_date
                    )
                for field_name in (
                    "formal_training_eligible",
                    "missing_mask",
                    "quality_blocked_mask",
                ):
                    if close.get(field_name) is not True and field_name == "formal_training_eligible":
                        raise ValueError(
                            f"official TAIEX close is not eligible: {event_date}"
                        )
                    if field_name != "formal_training_eligible" and close.get(field_name) is not False:
                        raise ValueError(
                            f"official TAIEX close has blocked quality: {event_date}"
                        )
                source_value_hash = _text(
                    close.get("source_value_hash"),
                    field_name="market close source_value_hash",
                )
                _require_sha256(
                    source_value_hash,
                    field_name="market close source_value_hash",
                )
                if event_date in result:
                    raise ValueError(
                        "duplicate official TAIEX trading date: " + event_date
                    )
                result[event_date] = _OfficialClose(
                    event_date=event_date,
                    event_at=event_at.isoformat(),
                    available_at=available_at.isoformat(),
                    value_int=value_int,
                    scale=scale,
                    source_row_hash=source_row_hash,
                    source_value_hash=source_value_hash,
                )
    if expected_price_date not in result:
        raise ValueError(
            "official TAIEX close missing for expected price date: "
            + expected_price_date
        )
    if len(result) < 2:
        raise ValueError("official TAIEX history lacks a prior trading date")
    return result


def _load_calendar_evidence(
    *,
    calendar_database: Path,
    expected_price_date: str,
) -> tuple[str, dict[str, Any]]:
    """Resolve T-1 from the existing official calendar provider.

    The local provider is deliberately used without an online probe.  A
    weekday without a local market-index observation is therefore unknown,
    rather than silently treated as open.  This keeps a missing calendar
    record fail-closed and lets the close-pair selector reject a missing
    middle trading day separately from a genuine weekend/holiday.
    """

    resolved_database = calendar_database.resolve()
    if not resolved_database.is_file():
        raise ValueError("calendar_database must be an existing file")
    try:
        target_date = date.fromisoformat(expected_price_date)
    except ValueError as exc:
        raise ValueError("expected_price_date must be YYYY-MM-DD") from exc

    # A bounded lookback is enough for the recent shadow source while keeping
    # this producer from scanning an unbounded historical database.
    range_start = target_date - timedelta(days=31)
    provider = OfficialTradingCalendar(db_path=resolved_database)
    raw_days = provider.get_trading_days_in_range(
        range_start,
        target_date,
        allow_online_probe=False,
    )
    days: list[dict[str, Any]] = []
    by_date: dict[date, bool | None] = {}
    for raw_day in raw_days:
        date_value = raw_day.get("date")
        date_string = raw_day.get("date_str")
        status = raw_day.get("is_trading_day")
        reason = raw_day.get("reason_code")
        if not isinstance(date_value, date):
            raise ValueError("official calendar returned an invalid date")
        if not isinstance(date_string, str) or date_string != date_value.isoformat():
            raise ValueError("official calendar returned an invalid date string")
        if status is not True and status is not False and status is not None:
            raise ValueError("official calendar returned an invalid status")
        if not isinstance(reason, str) or not reason:
            raise ValueError("official calendar returned an invalid reason")
        by_date[date_value] = status
        days.append(
            {
                "date": date_string,
                "is_trading_day": status,
                "reason_code": reason,
            }
        )

    expected_dates = [
        range_start + timedelta(days=offset)
        for offset in range((target_date - range_start).days + 1)
    ]
    if len(days) != len(expected_dates) or tuple(sorted(by_date)) != tuple(
        expected_dates
    ):
        raise ValueError("official calendar evidence has a date gap")
    if by_date.get(target_date) is not True:
        raise ValueError(
            "official calendar does not prove expected price date is trading: "
            + expected_price_date
        )
    candidates = sorted(
        calendar_date
        for calendar_date, is_trading_day in by_date.items()
        if calendar_date < target_date and is_trading_day is True
    )
    if not candidates:
        raise ValueError("official calendar has no prior trading date in bounded lookback")
    previous_date = candidates[-1]

    # Only the interval that decides the pair must be complete.  Older
    # unknown weekdays before the selected lookback candidate do not affect
    # the T-1 proof; an unknown weekday inside the interval does.
    cursor = previous_date + timedelta(days=1)
    while cursor < target_date:
        if cursor.weekday() < 5 and by_date.get(cursor) is None:
            raise ValueError(
                "official calendar evidence unavailable: " + cursor.isoformat()
            )
        cursor += timedelta(days=1)

    evidence_without_hash: dict[str, Any] = {
        "schema_version": "official-trading-calendar-evidence.v1",
        "provider": "data_module.official_trading_calendar.OfficialTradingCalendar",
        "source": "twstock_db_market_indices_evidence",
        "database_path": str(resolved_database),
        "allow_online_probe": False,
        "range_start": range_start.isoformat(),
        "range_end": target_date.isoformat(),
        "selected_previous_trading_date": previous_date.isoformat(),
        "days": days,
    }
    evidence = {
        **evidence_without_hash,
        "evidence_hash": _sha256_json(evidence_without_hash),
    }
    return previous_date.isoformat(), evidence


def _select_close_pair(
    closes: Mapping[str, _OfficialClose],
    *,
    expected_price_date: str,
    calendar_previous_date: str,
) -> tuple[_OfficialClose, _OfficialClose]:
    try:
        expected_date = date.fromisoformat(expected_price_date)
        previous_date = date.fromisoformat(calendar_previous_date)
    except ValueError as exc:
        raise ValueError("official calendar dates must be YYYY-MM-DD") from exc
    if (
        expected_date.isoformat() != expected_price_date
        or previous_date.isoformat() != calendar_previous_date
    ):
        raise ValueError("official calendar dates must be canonical YYYY-MM-DD")
    current = closes.get(expected_price_date)
    if current is None:
        raise ValueError("official close missing for expected price date")
    if previous_date >= expected_date:
        raise ValueError("official calendar prior date is not before expected date")
    previous = closes.get(calendar_previous_date)
    if previous is None:
        raise ValueError(
            "official prior trading date close missing: " + calendar_previous_date
        )
    if previous.event_date != calendar_previous_date:
        raise ValueError("official prior close event date does not match calendar")
    return current, previous


def _derive_market_values(
    *,
    contract: AllocationFeatureContract,
    current: _OfficialClose,
    previous: _OfficialClose,
    decision_at: datetime,
    expected_price_date: str,
) -> dict[str, dict[str, Any]]:
    if current.event_date != expected_price_date:
        raise ValueError("current official close date does not match expected date")
    current_available = _available_datetime(
        current.available_at,
        field_name="official current available_at",
    )
    previous_available = _available_datetime(
        previous.available_at,
        field_name="official previous available_at",
    )
    current_event = _available_datetime(
        current.event_at,
        field_name="official current event_at",
    )
    previous_event = _available_datetime(
        previous.event_at,
        field_name="official previous event_at",
    )
    if (
        current_available > decision_at
        or previous_available > decision_at
        or current_event > decision_at
        or previous_event > decision_at
    ):
        raise ValueError("official close evidence is after decision_at")
    current_decimal = Decimal(current.value_int) / Decimal(current.scale)
    previous_decimal = Decimal(previous.value_int) / Decimal(previous.scale)
    if (
        not current_decimal.is_finite()
        or not previous_decimal.is_finite()
        or current_decimal <= 0
        or previous_decimal <= 0
    ):
        raise ValueError("official close decimals must be finite and positive")
    point_delta = current_decimal - previous_decimal
    percent_delta = point_delta / previous_decimal * Decimal(100)
    outputs = {
        "market_indices.漲跌點數": (
            point_delta,
            "index_1e4",
            10_000,
        ),
        "market_indices.漲跌百分比": (
            percent_delta,
            "percent_1e4",
            10_000,
        ),
    }
    if set(outputs) != set(contract.derived_feature_ids):
        raise ValueError("market repair derived feature contract drift")
    result: dict[str, dict[str, Any]] = {}
    for feature_id, (decimal_value, unit, output_scale) in outputs.items():
        scaled = int(
            (decimal_value * Decimal(output_scale)).to_integral_value(
                rounding=ROUND_HALF_EVEN
            )
        )
        proof = {
            "schema_version": "market-index-change-derivation.v1",
            "feature_id": feature_id,
            "method": contract.derivation_method,
            "unit": unit,
            "output_scale": output_scale,
            "expected_price_date": expected_price_date,
            "decision_at": decision_at.isoformat(),
            "current_event_date": current.event_date,
            "current_event_at": current.event_at,
            "current_available_at": current.available_at,
            "current_close_decimal": str(current_decimal),
            "current_close_int": current.value_int,
            "current_close_scale": current.scale,
            "current_source_row_hash": current.source_row_hash,
            "current_source_value_hash": current.source_value_hash,
            "previous_event_date": previous.event_date,
            "previous_event_at": previous.event_at,
            "previous_available_at": previous.available_at,
            "previous_close_decimal": str(previous_decimal),
            "previous_close_int": previous.value_int,
            "previous_close_scale": previous.scale,
            "previous_source_row_hash": previous.source_row_hash,
            "previous_source_value_hash": previous.source_value_hash,
            "derived_decimal": str(decimal_value),
            "value_int": scaled,
            "source_id": contract.derived_source_id,
            "source_table": _MARKET_SOURCE_TABLE,
        }
        derivation_hash = _sha256_json(proof)
        proof["derivation_hash"] = derivation_hash
        result[feature_id] = {
            "value_int": scaled,
            "scale": output_scale,
            "event_at": current.event_at,
            "available_at": max(current_available, previous_available).isoformat(),
            "revision_id": (
                "derived:market-index-change.v1:"
                + derivation_hash[7:]
            ),
            "content_hash": derivation_hash,
            "proof": proof,
        }
    return result


def _effective_quality_manifest_hash(
    *,
    contract: AllocationFeatureContract,
    parent_input_hash: str,
) -> str:
    _require_sha256(parent_input_hash, field_name="parent_input_hash")
    return _sha256_json(
        {
            "schema_version": _EFFECTIVE_QUALITY_SCHEMA_VERSION,
            "source_id": _EFFECTIVE_QUALITY_SOURCE_ID,
            "parent_input_compressed_hash": parent_input_hash,
            "feature_contract_hash": contract.contract_hash,
            "included_feature_ids": list(contract.included_feature_ids),
            "excluded_feature_ids": list(contract.excluded_feature_ids),
            "method": "recompute_from_effective_pit_feature_set.v1",
        }
    )


def _effective_quality_stats(
    *,
    features: Sequence[PITFeatureValue],
    decision_at: datetime,
) -> dict[str, dict[str, int]]:
    """從有效列重建 DQ；無法區分的 stale／blocked 狀態一律阻擋。"""

    stats: dict[str, dict[str, int]] = {}
    base_features = [
        feature for feature in features if feature.family_id != "data_quality"
    ]
    if not base_features:
        raise ValueError("effective quality projection has no base features")
    for feature in base_features:
        available = _available_datetime(
            feature.available_at,
            field_name=f"{feature.feature_id}.available_at",
        )
        if available > decision_at:
            raise ValueError(
                "effective feature available_at is after decision_at: "
                + feature.feature_id
            )
        lag_days = max(0, (decision_at.date() - available.date()).days)
        family_stats = stats.setdefault(
            feature.family_id,
            {
                "total": 0,
                "observed": 0,
                "missing": 0,
                "stale": 0,
                "quality_blocked": 0,
                "max_available_lag_days": 0,
            },
        )
        family_stats["total"] += 1
        family_stats["observed"] += int(feature.observed)
        family_stats["missing"] += int(not feature.observed)
        family_stats["max_available_lag_days"] = max(
            family_stats["max_available_lag_days"],
            lag_days,
        )
        if feature.observed:
            if feature.revision_id.startswith("missing:"):
                raise ValueError(
                    "observed effective feature has missing revision: "
                    + feature.feature_id
                )
            continue
        revision = feature.revision_id.casefold()
        stale = "stale" in revision
        quality_blocked = "quality_blocked" in revision
        if not stale and not quality_blocked:
            raise ValueError(
                "effective quality cannot classify unobserved feature: "
                + feature.feature_id
            )
        family_stats["stale"] += int(stale)
        family_stats["quality_blocked"] += int(quality_blocked)
    return stats


def _recompute_data_quality_features(
    *,
    features: Sequence[PITFeatureValue],
    decision_at: datetime,
    quality_manifest_hash: str,
) -> tuple[tuple[PITFeatureValue, ...], dict[str, dict[str, int]]]:
    """以 effective feature set 產生新的 DQ lineage 與完整 metrics。"""

    _require_sha256(
        quality_manifest_hash,
        field_name="quality_manifest_hash",
    )
    quality_features = [
        feature for feature in features if feature.family_id == "data_quality"
    ]
    if not quality_features:
        return tuple(sorted(features, key=lambda item: item.feature_id)), {}
    stats = _effective_quality_stats(features=features, decision_at=decision_at)
    for feature in quality_features:
        if not feature.feature_id.startswith("data_quality."):
            raise ValueError("data quality feature id is invalid")
        parts = feature.feature_id.split(".", 2)
        if len(parts) != 3 or parts[2] not in _QUALITY_METRICS:
            raise ValueError("data quality feature metric is unsupported")
        if feature.scale != 1:
            raise ValueError("data quality feature scale must remain 1")

    base_features = [
        feature for feature in features if feature.family_id != "data_quality"
    ]
    base_feature_hashes = {
        feature.feature_id: feature.content_hash
        for feature in base_features
    }
    rebuilt_quality: list[PITFeatureValue] = []
    for feature in sorted(quality_features, key=lambda item: item.feature_id):
        _, family_id, metric_name = feature.feature_id.split(".", 2)
        family_stats = stats.get(family_id)
        if family_stats is None:
            raise ValueError(
                "data quality feature has no effective base family: "
                + feature.feature_id
            )
        total = family_stats["total"]
        metric_values = {
            "coverage_bp": (
                0 if total == 0 else family_stats["observed"] * 10_000 // total
            ),
            "missing_count": family_stats["missing"],
            "stale_count": family_stats["stale"],
            "quality_blocked_count": family_stats["quality_blocked"],
            "max_available_lag_days": family_stats[
                "max_available_lag_days"
            ],
        }
        value_int = metric_values[metric_name]
        content_payload = {
            "schema_version": _EFFECTIVE_QUALITY_SCHEMA_VERSION,
            "source_id": _EFFECTIVE_QUALITY_SOURCE_ID,
            "quality_manifest_hash": quality_manifest_hash,
            "feature_id": feature.feature_id,
            "family_id": family_id,
            "metric": metric_name,
            "decision_at": decision_at.isoformat(),
            "base_feature_ids": sorted(base_feature_hashes),
            "base_feature_content_hashes": {
                key: base_feature_hashes[key]
                for key in sorted(base_feature_hashes)
            },
            "stats": dict(family_stats),
            "value_int": value_int,
        }
        content_hash = _sha256_json(content_payload)
        rebuilt_quality.append(
            PITFeatureValue(
                feature_id=feature.feature_id,
                family_id="data_quality",
                source_id=_EFFECTIVE_QUALITY_SOURCE_ID,
                value_int=value_int,
                scale=1,
                event_at=decision_at.isoformat(),
                available_at=decision_at.isoformat(),
                revision_id="derived:data-quality-effective-v1:" + content_hash[7:],
                quality="observed",
                content_hash=content_hash,
                observed=True,
            )
        )
    rebuilt = tuple(
        sorted(
            [*base_features, *rebuilt_quality],
            key=lambda item: item.feature_id,
        )
    )
    return rebuilt, stats


def _repair_rows(
    *,
    parent_rows: Sequence[PortfolioMLDatasetRow],
    contract: AllocationFeatureContract,
    derived_manifest_hash: str,
    derived_values: Mapping[str, Mapping[str, Any]],
    parent_dataset_hash: str,
    parent_input_hash: str,
    raw_dataset_hash: str,
    quality_manifest_hash: str | None = None,
) -> tuple[PortfolioMLDatasetRow, ...]:
    del raw_dataset_hash
    quality_manifest_hash = quality_manifest_hash or _effective_quality_manifest_hash(
        contract=contract,
        parent_input_hash=parent_input_hash,
    )
    _require_sha256(quality_manifest_hash, field_name="quality_manifest_hash")
    source_pairs = dict(parent_rows[0].source_manifest_hashes)
    source_pairs[contract.derived_source_id] = derived_manifest_hash
    source_pairs[_EFFECTIVE_QUALITY_SOURCE_ID] = quality_manifest_hash
    source_manifest_hashes = tuple(sorted(source_pairs.items()))
    repaired_dataset_hash = _sha256_json(
        {
            "schema_version": INPUT_SCHEMA_VERSION,
            "parent_dataset_identity_hash": parent_dataset_hash,
            "parent_input_compressed_hash": parent_input_hash,
            "feature_contract_hash": contract.contract_hash,
        }
    )
    repaired: list[PortfolioMLDatasetRow] = []
    for parent in parent_rows:
        features: list[PITFeatureValue] = []
        for feature in parent.features:
            if feature.feature_id in contract.excluded_feature_ids:
                continue
            derived = derived_values.get(feature.feature_id)
            if derived is None:
                features.append(feature)
                continue
            features.append(
                replace(
                    feature,
                    source_id=contract.derived_source_id,
                    value_int=int(derived["value_int"]),
                    scale=int(derived["scale"]),
                    event_at=str(derived["event_at"]),
                    available_at=str(derived["available_at"]),
                    revision_id=str(derived["revision_id"]),
                    quality="observed",
                    content_hash=str(derived["content_hash"]),
                    observed=True,
                )
            )
        normalized_features, _quality_stats = _recompute_data_quality_features(
            features=features,
            decision_at=_available_datetime(
                parent.decision_at,
                field_name="parent.decision_at",
            ),
            quality_manifest_hash=quality_manifest_hash,
        )
        missing_families = tuple(
            sorted(
                {
                    feature.family_id
                    for feature in normalized_features
                    if not feature.observed
                }
            )
        )
        with post_freeze_shadow_decision_scope():
            repaired.append(
                replace(
                    parent,
                    features=normalized_features,
                    missing_family_ids=missing_families,
                    dataset_identity_hash=repaired_dataset_hash,
                    feature_registry_hash=contract.contract_hash,
                    source_manifest_hashes=source_manifest_hashes,
                )
            )
    return tuple(repaired)


def _input_payload(
    *,
    rows: Sequence[PortfolioMLDatasetRow],
    contract: AllocationFeatureContract,
    parent_input_hash: str,
) -> dict[str, Any]:
    row_payloads = []
    for row in rows:
        payload = asdict(row)
        if payload.get("targets") is not None:
            raise ValueError("repaired input cannot contain targets")
        payload.pop("targets", None)
        row_payloads.append(payload)
    result = {
        "schema_version": INPUT_SCHEMA_VERSION,
        "feature_contract": contract.payload(),
        "feature_contract_hash": contract.contract_hash,
        "parent_input_schema_version": LEGACY_INPUT_SCHEMA_VERSION,
        "parent_input_compressed_hash": parent_input_hash,
        "rows": row_payloads,
    }
    if set(result) != _TOP_LEVEL_FIELDS:
        raise ValueError("repaired input top-level contract drift")
    return result


def load_repaired_input(
    path: Path,
    *,
    expected_contract_hash: str,
) -> tuple[PortfolioMLDatasetRow, ...]:
    """v3 dedicated consumer；舊 v2 inference parser 不會讀取此 schema。"""

    _require_sha256(expected_contract_hash, field_name="expected_contract_hash")
    raw_bytes = path.resolve().read_bytes()
    if not path.name.lower().endswith(".gz"):
        raise ValueError("repaired input must be gzip compressed")
    try:
        payload = json.loads(gzip.decompress(raw_bytes).decode("utf-8"))
    except (OSError, EOFError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid repaired input") from exc
    mapping = _mapping(payload, field_name="repaired input")
    if set(mapping) != _TOP_LEVEL_FIELDS:
        raise ValueError("repaired input top-level fields are invalid")
    if mapping.get("schema_version") != INPUT_SCHEMA_VERSION:
        raise ValueError("repaired input schema_version mismatch")
    if mapping.get("parent_input_schema_version") != LEGACY_INPUT_SCHEMA_VERSION:
        raise ValueError("repaired input parent schema mismatch")
    parent_hash = _text(
        mapping.get("parent_input_compressed_hash"),
        field_name="parent_input_compressed_hash",
    )
    _require_sha256(parent_hash, field_name="parent_input_compressed_hash")
    contract_payload = _mapping(
        mapping.get("feature_contract"),
        field_name="feature_contract",
    )
    parent_registry_hash = _text(
        contract_payload.get("parent_feature_registry_hash"),
        field_name="feature_contract.parent_feature_registry_hash",
    )
    feature_ids = contract_payload.get("included_feature_ids")
    if not isinstance(feature_ids, list):
        raise TypeError("feature_contract.included_feature_ids must be an array")
    contract = build_market_repair_contract(
        parent_feature_registry_hash=parent_registry_hash,
        feature_ids=tuple(str(value) for value in feature_ids)
        + tuple(
            str(value)
            for value in contract_payload.get("excluded_feature_ids", [])
        ),
    )
    if contract_payload != contract.payload():
        raise ValueError("feature contract payload mismatch")
    declared_hash = _text(
        mapping.get("feature_contract_hash"),
        field_name="feature_contract_hash",
    )
    _require_sha256(declared_hash, field_name="feature_contract_hash")
    if declared_hash != contract.contract_hash or declared_hash != expected_contract_hash:
        raise ValueError("feature contract hash mismatch")
    row_payloads = _mapping_sequence(mapping.get("rows"), field_name="rows")
    if not row_payloads:
        raise ValueError("repaired input rows must not be empty")
    with post_freeze_shadow_decision_scope():
        rows = tuple(_parse_legacy_row(row) for row in row_payloads)
    expected_ids = set(contract.included_feature_ids)
    for row in rows:
        if row.feature_registry_hash != declared_hash:
            raise ValueError("repaired row feature registry hash mismatch")
        ids = {feature.feature_id for feature in row.features}
        if ids != expected_ids:
            raise ValueError("repaired row feature set differs from contract")
        if any(
            feature.feature_id in contract.excluded_feature_ids
            for feature in row.features
        ):
            raise ValueError("excluded classification feature remains in row")
        derived = {
            feature.feature_id: feature
            for feature in row.features
            if feature.feature_id in contract.derived_feature_ids
        }
        if set(derived) != set(contract.derived_feature_ids) or any(
            feature.source_id != contract.derived_source_id
            or not feature.observed
            for feature in derived.values()
        ):
            raise ValueError("derived market features are not observed/custodied")
        quality_source_hash = dict(row.source_manifest_hashes).get(
            _EFFECTIVE_QUALITY_SOURCE_ID
        )
        if quality_source_hash is not None:
            expected_quality_hash = _effective_quality_manifest_hash(
                contract=contract,
                parent_input_hash=parent_hash,
            )
            if quality_source_hash != expected_quality_hash:
                raise ValueError("effective quality manifest hash mismatch")
            expected_features, _ = _recompute_data_quality_features(
                features=row.features,
                decision_at=_available_datetime(
                    row.decision_at,
                    field_name="row.decision_at",
                ),
                quality_manifest_hash=expected_quality_hash,
            )
            expected_quality = {
                feature.feature_id: feature
                for feature in expected_features
                if feature.family_id == "data_quality"
            }
            actual_quality = {
                feature.feature_id: feature
                for feature in row.features
                if feature.family_id == "data_quality"
            }
            if expected_quality != actual_quality:
                raise ValueError("effective data quality feature mismatch")
        elif any(
            feature.source_id == _EFFECTIVE_QUALITY_SOURCE_ID
            for feature in row.features
            if feature.family_id == "data_quality"
        ):
            raise ValueError("effective quality source manifest is missing")
    return rows


def _feature_counts(
    rows: Sequence[PortfolioMLDatasetRow],
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for row in rows:
        for feature in row.features:
            stats = result.setdefault(
                feature.feature_id,
                {"observed": 0, "missing": 0},
            )
            stats["observed" if feature.observed else "missing"] += 1
    return {key: result[key] for key in sorted(result)}


def _configure_standard_streams_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")


def _legacy_rejection_for_bytes(compressed_bytes: bytes) -> str:
    """以舊 v2 parser 實讀候選 bytes，確認需要新 release。"""

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="baldr-feature-repair-",
            suffix=".json.gz",
            delete=False,
        ) as stream:
            stream.write(compressed_bytes)
            temporary_path = Path(stream.name)
        try:
            _load_legacy_rows(temporary_path)
        except (OSError, TypeError, ValueError, KeyError) as exc:
            return f"{type(exc).__name__}: {exc}"
        raise ValueError("legacy v2 consumer unexpectedly accepted v3")
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
