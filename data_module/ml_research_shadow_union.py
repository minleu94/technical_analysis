"""建立全欄位、但永遠不得進入 Formal 的配置型 ML Research 資料集。

這個模組把兩條既有、已雜湊發布的資料鏈接在一起：

* ``all_field_enriched`` 的正式配置訓練 shards，提供已驗證的 T-1 特徵、
  causal portfolio state、teacher targets 與 horizon labels。
* ``research_shadow_all_fields`` 的 raw PIT observations，只以
  ``available_at <= decision_at`` 的 as-of join 追加至相同股票／決策時間。

輸出仍採 ``allocation-training-jsonl-v2``，所以可以交給既有配置型訓練核心；
publication manifest 則使用獨立 dataset identity，並永久宣告
``research_only=true``、``formal_oos_allowed=false``、
``production_alpha_bp=0``、``promotion_eligible=false``。任何 current snapshot
只能從可證明的 ``first_seen_at`` 往後出現；本模組不會將事件期末日當成歷史
可得日。

公開與持久化數值只有整數、布林與字串。sklearn 浮點邊界只存在後續訓練服務。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any, Iterable, Literal, Mapping, Sequence
from zoneinfo import ZoneInfo

from ml_module.allocation_contracts import (
    AllocationTargets,
    AllocationWeightContract,
    CausalPortfolioState,
    PITFeatureValue,
)


PUBLICATION_SCHEMA_VERSION = "portfolio-ml-training-shards.v2"
TRAINING_JSONL_SCHEMA_VERSION = "allocation-training-jsonl-v2"
RESEARCH_DATASET_ID = "research_shadow_challenger_all_fields"
RESEARCH_CAUSAL_DATASET_ID = (
    "research_shadow_causal_allocation_ledger"
)
RESEARCH_TRAINING_DATASET_IDS = frozenset(
    {RESEARCH_DATASET_ID, RESEARCH_CAUSAL_DATASET_ID}
)
RESEARCH_TRAINING_MANIFEST_SCHEMA_VERSION = (
    "allocation-research-training-manifest-v1"
)

_RAW_SCHEMA_VERSION = "ml-pit-year-shard-dataset.v1"
_RAW_ROW_SCHEMA_VERSION = "ml-pit-observation.v1"
_BASE_DATASET_SCHEMA_VERSION = "portfolio-ml-training-shards.v2"
_FORMAL_RAW_DATASET_ID = "all_field_enriched"
_SHADOW_RAW_DATASET_ID = "research_shadow_all_fields"
_TAIPEI = ZoneInfo("Asia/Taipei")
_LONG_FORMAT_TABLES = frozenset(
    {"fundamental_statement_items", "fundamental_valuation_metrics"}
)
_BROKER_TABLE = "broker_flows"
_ZERO_SHA256 = "sha256:" + ("0" * 64)
_RULE_PORTFOLIO_HEALTH_SOURCE_ID = "derived:causal_portfolio_state"
_CORPORATE_BLOCKED_SOURCE_ID = (
    "blocked:corporate_microstructure_official_timeline"
)
_CORPORATE_OFFICIAL_SOURCE_ID = "sidecar:official_halt_resume_timeline"
_OFFICIAL_EVENT_MANIFEST_SCHEMA_VERSION = (
    "official-market-event-publication.v1"
)
_OFFICIAL_EVENT_ROW_SCHEMA_VERSION = "official-market-event.v1"
_RULE_PORTFOLIO_HEALTH_FEATURE_IDS = (
    "rule_portfolio_health.cash_bp",
    "rule_portfolio_health.current_symbol_weight_bp",
    "rule_portfolio_health.invested_bp",
    "rule_portfolio_health.position_count",
    "rule_portfolio_health.state_complete_flag",
    "rule_portfolio_health.weekly_turnover_used_bp",
)
_CORPORATE_MICROSTRUCTURE_FEATURE_IDS = (
    "corporate_microstructure.corporate_action_flag",
    "corporate_microstructure.limit_lock_flag",
    "corporate_microstructure.suspension_flag",
    "corporate_microstructure.trading_restriction_flag",
)
_CORPORATE_HALT_RESUME_FEATURE_IDS = frozenset(
    {
        "corporate_microstructure.suspension_flag",
        "corporate_microstructure.trading_restriction_flag",
    }
)


@dataclass(frozen=True)
class ResearchShadowUnionRequest:
    """Research-only union 的顯式輸入與 bounded scope。"""

    formal_raw_manifest_path: Path
    shadow_raw_manifest_path: Path
    base_training_manifest_path: Path
    output_root: Path
    corporate_action_manifest_path: Path | None = None
    symbols: tuple[str, ...] | None = None
    years: tuple[int, ...] = ()
    batch_size: int = 2_048
    compression_level: int = 6

    def __post_init__(self) -> None:
        if self.symbols is not None:
            normalized = tuple(
                sorted(
                    {
                        str(symbol).strip()
                        for symbol in self.symbols
                        if str(symbol).strip()
                    }
                )
            )
            if not normalized:
                raise ValueError("symbols must be non-empty or None")
            object.__setattr__(self, "symbols", normalized)
        normalized_years = _normalized_years(self.years)
        object.__setattr__(self, "years", normalized_years)
        if isinstance(self.batch_size, bool) or not isinstance(
            self.batch_size, int
        ):
            raise TypeError("batch_size must be an integer")
        if self.batch_size < 1 or self.batch_size > 100_000:
            raise ValueError("batch_size must be between 1 and 100000")
        if isinstance(self.compression_level, bool) or not isinstance(
            self.compression_level, int
        ):
            raise TypeError("compression_level must be an integer")
        if not 0 <= self.compression_level <= 9:
            raise ValueError("compression_level must be within 0..9")


@dataclass(frozen=True)
class ResearchShadowUnionPublication:
    publication_id: str
    publication_directory: Path
    manifest_path: Path
    latest_manifest_path: Path
    manifest_hash: str
    dataset_identity_hash: str
    feature_registry_hash: str
    sample_count: int
    shard_paths: tuple[Path, ...]


@dataclass(frozen=True)
class _FeatureDefinition:
    feature_id: str
    base_feature_id: str
    family_id: str
    source_id: str
    source_table: str
    scale: int
    stale_after_days: int
    eligibility_status: str
    record_hash: str
    dimension_values: tuple[str, ...] = ()
    aggregation_policy: str = "latest_revision_as_of_decision"

    def registry_payload(self) -> dict[str, object]:
        return {
            "feature_id": self.feature_id,
            "base_feature_id": self.base_feature_id,
            "family_id": self.family_id,
            "source_id": self.source_id,
            "source_table": self.source_table,
            "scale": self.scale,
            "stale_after_days": self.stale_after_days,
            "eligibility_status": self.eligibility_status,
            "dimension_values": list(self.dimension_values),
            "aggregation_policy": self.aggregation_policy,
            "record_hash": self.record_hash,
        }


@dataclass(frozen=True)
class _CorporateEvent:
    symbol: str
    source_id: str
    event_type: Literal["trading_halt", "trading_resume"]
    event_at: str
    available_at: str
    revision_id: str
    event_id: str
    content_hash: str
    revision_availability_ambiguous: bool


@dataclass(frozen=True)
class _CorporateEventTimeline:
    manifest_path: Path
    manifest_hash: str
    manifest_file_hash: str
    canonical_file_hash: str
    events_by_symbol: Mapping[str, tuple[_CorporateEvent, ...]]
    complete_coverage_years: frozenset[int]
    decision_feature_event_count: int
    result_only_event_count: int


@dataclass(frozen=True)
class _CurrentValue:
    value_int: int | None
    scale: int
    event_at: str
    available_at: str
    revision_id: str
    quality: str
    content_hash: str
    stale_after_days: int
    missing_mask: bool
    quality_blocked_mask: bool
    component_count: int = 1


@dataclass(frozen=True)
class _ResearchTeacherCandidate:
    symbol: str
    horizon_end_date: str
    available_at: str
    benchmark_excess_return_bp: int
    tail_loss_bp: int
    max_drawdown_bp: int
    fill_feasible_observed: bool


class ResearchShadowUnionBuilder:
    """以 manifest-last、append-only publication 建立 Research 訓練 shards。"""

    def build(
        self, request: ResearchShadowUnionRequest
    ) -> ResearchShadowUnionPublication:
        formal_path = request.formal_raw_manifest_path.resolve()
        shadow_path = request.shadow_raw_manifest_path.resolve()
        base_path = request.base_training_manifest_path.resolve()
        corporate_path = (
            request.corporate_action_manifest_path.resolve()
            if request.corporate_action_manifest_path is not None
            else None
        )
        output_root = request.output_root.resolve()
        for path in (formal_path, shadow_path, base_path):
            if not path.is_file():
                raise FileNotFoundError(path)
        if corporate_path is not None and not corporate_path.is_file():
            raise FileNotFoundError(corporate_path)
        output_root.mkdir(parents=True, exist_ok=True)
        runs_root = output_root / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)

        formal = _load_and_validate_raw_manifest(
            formal_path,
            expected_dataset_id=_FORMAL_RAW_DATASET_ID,
            expected_formal_dataset=True,
        )
        shadow = _load_and_validate_raw_manifest(
            shadow_path,
            expected_dataset_id=_SHADOW_RAW_DATASET_ID,
            expected_formal_dataset=False,
        )
        base = _load_and_validate_base_manifest(base_path)
        corporate_timeline = (
            _load_official_corporate_event_timeline(corporate_path)
            if corporate_path is not None
            else None
        )
        _validate_custody_link(
            formal_manifest=formal,
            shadow_manifest=shadow,
            base_manifest=base,
        )

        staging = Path(
            tempfile.mkdtemp(prefix=".research-union-", dir=str(output_root))
        ).resolve()
        spool_directory = Path(
            tempfile.mkdtemp(
                prefix=".research-union-spool-", dir=str(output_root)
            )
        ).resolve()
        writers = _TrainingShardWriterRegistry(
            staging=staging,
            compression_level=request.compression_level,
        )
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(spool_directory / "shadow.sqlite")
            connection.row_factory = sqlite3.Row
            _initialize_spool(connection)
            base_definitions = _shadow_base_definitions(shadow)
            runtime_definitions, shadow_scan = _spool_shadow_observations(
                connection=connection,
                manifest_path=shadow_path,
                manifest=shadow,
                base_definitions=base_definitions,
                symbols=request.symbols,
                batch_size=request.batch_size,
            )
            definitions = _final_shadow_definitions(
                base_definitions=base_definitions,
                runtime_definitions=runtime_definitions,
            )
            feature_packs = _union_feature_packs(
                base_manifest=base,
                shadow_definitions=definitions,
            )
            feature_pack_dispositions = _feature_pack_dispositions(
                feature_packs,
                official_corporate_timeline=(
                    corporate_timeline is not None
                ),
            )
            source_manifest_hashes = _union_source_manifest_hashes(
                base_manifest=base,
                shadow_manifest=shadow,
                definitions=definitions,
                corporate_timeline=corporate_timeline,
            )
            feature_registry = _feature_registry_payload(
                base_manifest=base,
                shadow_definitions=definitions,
                feature_packs=feature_packs,
                corporate_timeline=corporate_timeline,
            )
            feature_registry_hash = _sha256_json(feature_registry)
            scope = {
                "symbols": (
                    None
                    if request.symbols is None
                    else list(request.symbols)
                ),
                "all_symbols": request.symbols is None,
                "years": list(request.years),
            }
            (
                research_teacher_targets,
                research_teacher_stats,
                research_teacher_hash,
            ) = _build_research_teacher_targets(
                base_manifest_path=base_path,
                base_manifest=base,
                symbols=request.symbols,
                years=request.years,
            )
            source_identity = {
                "formal_raw_manifest_hash": formal["manifest_hash"],
                "formal_raw_manifest_file_hash": _file_sha256(formal_path),
                "shadow_raw_manifest_hash": shadow["manifest_hash"],
                "shadow_raw_manifest_file_hash": _file_sha256(shadow_path),
                "base_training_manifest_hash": base["manifest_hash"],
                "base_training_manifest_file_hash": _file_sha256(base_path),
            }
            if corporate_timeline is not None:
                source_identity.update(
                    {
                        "official_corporate_event_manifest_hash": (
                            corporate_timeline.manifest_hash
                        ),
                        "official_corporate_event_manifest_file_hash": (
                            corporate_timeline.manifest_file_hash
                        ),
                        "official_corporate_event_canonical_file_hash": (
                            corporate_timeline.canonical_file_hash
                        ),
                    }
                )
            source_identity_hash = _sha256_json(source_identity)
            dataset_identity_hash = _sha256_json(
                {
                    "dataset_id": RESEARCH_DATASET_ID,
                    "source_identity_hash": source_identity_hash,
                    "feature_registry_hash": feature_registry_hash,
                    "research_teacher_hash": research_teacher_hash,
                    "feature_pack_dispositions": (
                        feature_pack_dispositions
                    ),
                    "scope": scope,
                    "join_policy": (
                        "symbol_decision_at_latest_available_revision"
                    ),
                    "snapshot_policy": (
                        "first_seen_at_only_no_historical_backfill"
                    ),
                    "research_only": True,
                }
            )
            blockers = tuple(
                sorted(
                    {
                        *(
                            str(value)
                            for value in base.get(
                                "assembly_blockers", ()
                            )
                        ),
                        "research_shadow_features_not_formal_source_accepted",
                        "research_shadow_dataset_permanently_ineligible_for_promotion",
                        "current_snapshot_values_first_seen_only",
                        "research_teacher_unknown_sector_unique_bucket_assumption",
                        "research_teacher_excluded_from_formal",
                        *(
                            (
                                "corporate_microstructure_halt_resume_only_result_events_excluded",
                            )
                            if corporate_timeline is not None
                            else (
                                "corporate_microstructure_pack_coverage_zero_official_timeline_missing",
                            )
                        ),
                        "rule_portfolio_health_pack_state_only_thesis_health_exit_history_missing",
                    }
                )
            )
            label_policy = dict(_base_label_policy(base_path, base))
            label_policy["research_teacher"] = (
                _research_teacher_policy_payload()
            )
            common_header = {
                "record_type": "header",
                "schema_version": TRAINING_JSONL_SCHEMA_VERSION,
                "direct_training_input": True,
                "dataset_id": RESEARCH_DATASET_ID,
                "dataset_identity_hash": dataset_identity_hash,
                "training_as_of": str(base["training_as_of"]),
                "horizons": list(base["horizons"]),
                "feature_packs": feature_packs,
                "folds": list(base["folds"]),
                "assembly_blockers": list(blockers),
                "feature_registry_hash": feature_registry_hash,
                "source_manifest_hashes": [
                    list(item) for item in source_manifest_hashes
                ],
                "portfolio_state_policy": base["portfolio_state_policy"],
                "label_policy": label_policy,
            }
            sample_count, union_stats = _stream_union_samples(
                connection=connection,
                base_manifest_path=base_path,
                base_manifest=base,
                definitions=definitions,
                source_manifest_hashes=source_manifest_hashes,
                dataset_identity_hash=dataset_identity_hash,
                feature_registry_hash=feature_registry_hash,
                common_header=common_header,
                research_teacher_targets=research_teacher_targets,
                corporate_timeline=corporate_timeline,
                writers=writers,
                symbols=request.symbols,
                years=request.years,
            )
            if sample_count == 0:
                raise ValueError("no research-shadow union samples were emitted")
            corporate_union_stats = _as_mapping(
                union_stats.get("corporate_microstructure"),
                "union_stats.corporate_microstructure",
            )
            writers.close_all()
            shards = writers.manifest_payloads(staging=staging)
            publication_identity = {
                "dataset_identity_hash": dataset_identity_hash,
                "source_identity_hash": source_identity_hash,
                "shards": [
                    {
                        "year": shard["year"],
                        "content_sha256": shard["content_sha256"],
                    }
                    for shard in shards
                ],
            }
            publication_id = (
                "research-union-"
                + _sha256_json(publication_identity)[7:31]
            )
            manifest: dict[str, Any] = {
                "schema_version": PUBLICATION_SCHEMA_VERSION,
                "publication_id": publication_id,
                "stage": "research_shadow_all_field_training_union",
                "direct_training_input": True,
                "target_cli": "scripts/train_ml_research_shadow_challenger.py",
                "target_schema_version": TRAINING_JSONL_SCHEMA_VERSION,
                "dataset_id": RESEARCH_DATASET_ID,
                "dataset_identity_hash": dataset_identity_hash,
                "feature_registry_hash": feature_registry_hash,
                "source_identity_hash": source_identity_hash,
                "source_identity": source_identity,
                "source_manifest_hashes": [
                    list(item) for item in source_manifest_hashes
                ],
                "training_as_of": str(base["training_as_of"]),
                "horizons": list(base["horizons"]),
                "feature_packs": feature_packs,
                "feature_pack_dispositions": feature_pack_dispositions,
                "feature_registry": feature_registry,
                "feature_count": _feature_pack_count(feature_packs),
                "folds": list(base["folds"]),
                "fold_count": len(base["folds"]),
                "sample_count": sample_count,
                "scope": scope,
                "raw_inputs": {
                    "formal_all_field_enriched": {
                        "path": str(formal_path),
                        "manifest_hash": formal["manifest_hash"],
                        "manifest_file_hash": source_identity[
                            "formal_raw_manifest_file_hash"
                        ],
                        "feature_count": formal["feature_count"],
                    },
                    "research_shadow_all_fields": {
                        "path": str(shadow_path),
                        "manifest_hash": shadow["manifest_hash"],
                        "manifest_file_hash": source_identity[
                            "shadow_raw_manifest_file_hash"
                        ],
                        "feature_count": shadow["feature_count"],
                    },
                    "base_portfolio_allocation_training": {
                        "path": str(base_path),
                        "manifest_hash": base["manifest_hash"],
                        "manifest_file_hash": source_identity[
                            "base_training_manifest_file_hash"
                        ],
                        "dataset_identity_hash": base[
                            "dataset_identity_hash"
                        ],
                    },
                },
                "shadow_scan": shadow_scan,
                "union_stats": union_stats,
                "research_teacher_policy": (
                    _research_teacher_policy_payload()
                ),
                "research_teacher_hash": research_teacher_hash,
                "research_teacher_stats": research_teacher_stats,
                "assembly_blockers": list(blockers),
                "research_only": True,
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
                "production_action_allowed": False,
                "promotion_eligible": False,
                "broker_order_allowed": False,
                "formal_consumer_compatible": False,
                "safety": {
                    "available_at_lte_decision_at": True,
                    "event_at_lte_decision_at": True,
                    "formal_features_reused_from_verified_causal_training": True,
                    "shadow_features_asof_joined": True,
                    "missing_masks_explicit": True,
                    "quality_blocked_values_used": False,
                    "stale_values_used": False,
                    "first_seen_fallback_may_backdate": False,
                    "current_snapshot_backfill_allowed": False,
                    "future_rows_allowed": False,
                    "future_outcomes_used_for_supervised_labels_only": True,
                    "research_teacher_targets_feed_next_state": False,
                    "research_teacher_excluded_from_formal": True,
                    "snapshot_backfill_research_assumption": False,
                    "unknown_sector_unique_bucket_research_assumption": True,
                    "rule_portfolio_health_from_T_minus_1_state": True,
                    "same_day_advice_read_allowed": False,
                    "corporate_microstructure_schema_registered": True,
                    "corporate_microstructure_coverage_bp": (
                        corporate_union_stats["coverage_bp"]
                    ),
                    "corporate_microstructure_zero_imputation_used": False,
                    "corporate_microstructure_known_no_event_zero_requires_complete_coverage": True,
                    "corporate_microstructure_result_only_event_feature_used": False,
                    "raw_float_persistence_allowed": False,
                    "formal_dataset": False,
                    "formal_orchestrator_load_allowed": False,
                    "promotion_consumer_load_allowed": False,
                    "atomic_manifest_last_publish": True,
                },
                "execution": {
                    "shadow_raw_streaming_gzip_jsonl": True,
                    "temporary_sqlite_asof_spool": True,
                    "base_training_streaming_gzip_jsonl": True,
                    "parquet_dependency_added": False,
                    "batch_size": request.batch_size,
                },
                "shards": shards,
            }
            if corporate_timeline is not None:
                raw_inputs_payload = _as_mapping(
                    manifest["raw_inputs"],
                    "manifest.raw_inputs",
                )
                manifest["raw_inputs"] = {
                    **raw_inputs_payload,
                    "official_corporate_events": {
                        "path": str(
                            corporate_timeline.manifest_path
                        ),
                        "manifest_hash": (
                            corporate_timeline.manifest_hash
                        ),
                        "manifest_file_hash": (
                            corporate_timeline.manifest_file_hash
                        ),
                        "canonical_file_hash": (
                            corporate_timeline.canonical_file_hash
                        ),
                        "decision_feature_event_count": (
                            corporate_timeline.decision_feature_event_count
                        ),
                        "result_only_event_count_excluded": (
                            corporate_timeline.result_only_event_count
                        ),
                        "complete_coverage_years": sorted(
                            corporate_timeline.complete_coverage_years
                        ),
                    },
                }
            manifest["manifest_hash"] = _sha256_json(manifest)
            _write_json(staging / "manifest.json", manifest)

            publication_directory = runs_root / publication_id
            if publication_directory.exists():
                existing = _read_json(publication_directory / "manifest.json")
                if existing.get("manifest_hash") != manifest["manifest_hash"]:
                    raise RuntimeError(
                        "research publication identity collision"
                    )
                _safe_remove_tree(staging, output_root)
            else:
                os.replace(staging, publication_directory)
            latest_manifest_path = output_root / "latest_manifest.json"
            _atomic_write_json(
                latest_manifest_path,
                {
                    "schema_version": (
                        "research-shadow-training-pointer.v1"
                    ),
                    "publication_id": publication_id,
                    "manifest_path": (
                        f"runs/{publication_id}/manifest.json"
                    ),
                    "manifest_hash": manifest["manifest_hash"],
                    "research_only": True,
                    "formal_oos_allowed": False,
                    "production_alpha_bp": 0,
                    "promotion_eligible": False,
                },
            )
            return ResearchShadowUnionPublication(
                publication_id=publication_id,
                publication_directory=publication_directory,
                manifest_path=publication_directory / "manifest.json",
                latest_manifest_path=latest_manifest_path,
                manifest_hash=str(manifest["manifest_hash"]),
                dataset_identity_hash=dataset_identity_hash,
                feature_registry_hash=feature_registry_hash,
                sample_count=sample_count,
                shard_paths=tuple(
                    publication_directory / str(shard["path"])
                    for shard in shards
                ),
            )
        except Exception:
            writers.close_all()
            if staging.exists():
                _safe_remove_tree(staging, output_root)
            raise
        finally:
            if connection is not None:
                connection.close()
            if spool_directory.exists():
                _safe_remove_tree(spool_directory, output_root)


def validate_research_training_publication(
    manifest_path: Path,
    input_paths: Sequence[Path],
) -> Mapping[str, Any]:
    """驗證專用 trainer 的輸入，並拒絕任何 Formal／可 promotion 宣告。"""

    resolved_manifest = manifest_path.resolve()
    manifest = _read_json(resolved_manifest)
    if manifest.get("schema_version") != PUBLICATION_SCHEMA_VERSION:
        raise ValueError("unsupported research union manifest schema")
    if manifest.get("dataset_id") not in RESEARCH_TRAINING_DATASET_IDS:
        raise ValueError("research trainer requires research dataset id")
    required_false = (
        "formal_oos_allowed",
        "production_action_allowed",
        "promotion_eligible",
        "broker_order_allowed",
        "formal_consumer_compatible",
    )
    if manifest.get("research_only") is not True:
        raise ValueError("research union must declare research_only=true")
    for field_name in required_false:
        if manifest.get(field_name) is not False:
            raise ValueError(f"{field_name} must remain false")
    if manifest.get("production_alpha_bp") != 0:
        raise ValueError("production_alpha_bp must remain zero")
    expected_hash = str(manifest.get("manifest_hash", ""))
    body = dict(manifest)
    body.pop("manifest_hash", None)
    if expected_hash != _sha256_json(body):
        raise ValueError("research union manifest hash mismatch")

    root = resolved_manifest.parent
    registered: dict[Path, Mapping[str, Any]] = {}
    for entry in _mapping_sequence(manifest.get("shards"), "shards"):
        path = (root / str(entry["path"])).resolve()
        if not path.is_relative_to(root):
            raise ValueError("research shard path escapes publication root")
        registered[path] = entry
    supplied = {Path(path).resolve() for path in input_paths}
    if supplied != set(registered):
        raise ValueError("all and only registered research shards are required")
    for path, entry in registered.items():
        if not path.is_file():
            raise FileNotFoundError(path)
        if _file_sha256(path) != entry.get("compressed_sha256"):
            raise ValueError("research shard compressed hash mismatch")
    return manifest


def lock_research_training_manifest(
    *,
    generic_manifest_path: Path,
    union_manifest_path: Path,
) -> Mapping[str, Any]:
    """把既有 trainer 的輸出轉成 Formal loader 不接受的 Research manifest。"""

    generic_path = generic_manifest_path.resolve()
    union_path = union_manifest_path.resolve()
    training = dict(_read_json(generic_path))
    union_payload = _read_json(union_path)
    union = validate_research_training_publication(
        union_path,
        tuple(
            union_path.parent / str(entry["path"])
            for entry in _mapping_sequence(
                union_payload.get("shards"), "shards"
            )
        ),
    )
    if training.get("dataset_id") != union.get("dataset_id"):
        raise ValueError("trained artifact dataset id is not research-only")
    if (
        training.get("production_alpha_bp") != 0
        or training.get("production_action_allowed") is not False
        or training.get("formal_oos_allowed") is not False
    ):
        raise ValueError("generic training output violated alpha=0 boundary")
    original_schema = str(training.get("schema_version", ""))
    training.update(
        {
            "schema_version": RESEARCH_TRAINING_MANIFEST_SCHEMA_VERSION,
            "base_training_schema_version": original_schema,
            "research_only": True,
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
            "production_action_allowed": False,
            "promotion_eligible": False,
            "broker_order_allowed": False,
            "formal_consumer_compatible": False,
            "source_union_manifest_hash": union["manifest_hash"],
            "source_union_manifest_file_hash": _file_sha256(union_path),
            "promotion_blockers": [
                "research_shadow_source_not_formal_accepted",
                "research_dataset_id_not_all_field_enriched",
                "research_manifest_schema_rejected_by_formal_loader",
            ],
        }
    )
    _atomic_write_json(generic_path, training)
    return training


def _load_and_validate_raw_manifest(
    path: Path,
    *,
    expected_dataset_id: str,
    expected_formal_dataset: bool,
) -> Mapping[str, Any]:
    manifest = _read_json(path)
    if manifest.get("schema_version") != _RAW_SCHEMA_VERSION:
        raise ValueError("unsupported raw PIT manifest schema")
    if manifest.get("stage") != "raw_pit_observations":
        raise ValueError("input is not raw PIT observations")
    if manifest.get("format") != "gzip_jsonl":
        raise ValueError("raw PIT dataset must use gzip_jsonl")
    if manifest.get("dataset_id") != expected_dataset_id:
        raise ValueError(f"unexpected raw dataset id: {expected_dataset_id}")
    expected_hash = str(manifest.get("manifest_hash", ""))
    body = dict(manifest)
    body.pop("manifest_hash", None)
    if expected_hash != _sha256_json(body):
        raise ValueError("raw PIT manifest hash mismatch")
    safety = _as_mapping(manifest.get("safety"), "safety")
    if safety.get("formal_dataset") is not expected_formal_dataset:
        raise ValueError("raw PIT formal_dataset boundary mismatch")
    if safety.get("unreviewed_included") is not False:
        raise ValueError("raw PIT manifest includes unreviewed fields")
    if safety.get("excluded_leakage_included") is not False:
        raise ValueError("raw PIT manifest includes leakage fields")
    if safety.get("raw_float_persistence_allowed") is not False:
        raise ValueError("raw PIT manifest permits float persistence")
    if safety.get("research_shadow_isolated") is not True:
        raise ValueError("raw PIT manifest does not isolate research shadow")
    statuses = tuple(str(value) for value in manifest.get("included_statuses", ()))
    if expected_formal_dataset:
        if not statuses or not set(statuses).issubset(
            {"formal_backfill", "first_seen_only"}
        ):
            raise ValueError("formal raw manifest contains non-formal status")
    elif statuses != ("research_shadow",):
        raise ValueError("shadow raw manifest status must be research_shadow")
    _mapping_sequence(manifest.get("features"), "features")
    _mapping_sequence(manifest.get("shards"), "shards")
    return manifest


def _load_and_validate_base_manifest(path: Path) -> Mapping[str, Any]:
    manifest = _read_json(path)
    if manifest.get("schema_version") != _BASE_DATASET_SCHEMA_VERSION:
        raise ValueError("unsupported base allocation dataset schema")
    if manifest.get("stage") != "portfolio_ml_dataset_row_assembly":
        raise ValueError("base input is not portfolio allocation training data")
    if manifest.get("direct_training_input") is not True:
        raise ValueError("base allocation data is not direct training input")
    expected_hash = str(manifest.get("manifest_hash", ""))
    body = dict(manifest)
    body.pop("manifest_hash", None)
    if expected_hash != _sha256_json(body):
        raise ValueError("base allocation manifest hash mismatch")
    if (
        manifest.get("formal_oos_allowed") is not False
        or manifest.get("production_alpha_bp") != 0
        or manifest.get("production_action_allowed") is not False
    ):
        raise ValueError("base allocation manifest violates pre-promotion safety")
    safety = _as_mapping(manifest.get("safety"), "base.safety")
    if safety.get("available_at_lte_decision_at") is not True:
        raise ValueError("base allocation data lacks PIT availability guarantee")
    if safety.get("price_and_technical_t_minus_1") is not True:
        raise ValueError("base allocation data lacks strict T-1 guarantee")
    if safety.get("current_company_snapshot_backfill_allowed") is not False:
        raise ValueError("base allocation data permits snapshot backfill")
    if safety.get("missing_values_zero_filled") is not False:
        raise ValueError("base allocation data zero-fills missing values")
    _mapping_sequence(manifest.get("shards"), "base.shards")
    _mapping_sequence(manifest.get("folds"), "base.folds")
    if int(manifest.get("fold_count", 0)) < 4:
        raise ValueError("base allocation data requires at least four folds")
    return manifest


def _load_official_corporate_event_timeline(
    path: Path,
) -> _CorporateEventTimeline:
    """驗證官方 event publication，僅載入 halt/resume 決策可用事件。"""

    manifest = _read_json(path)
    if (
        manifest.get("schema_version")
        != _OFFICIAL_EVENT_MANIFEST_SCHEMA_VERSION
    ):
        raise ValueError("unsupported official corporate event manifest schema")
    if manifest.get("status") != "formal_source_publication":
        raise ValueError("official corporate event publication is not formal")
    expected_manifest_hash = str(manifest.get("manifest_hash", ""))
    body = dict(manifest)
    body.pop("manifest_hash", None)
    if _sha256_json(body) != expected_manifest_hash:
        raise ValueError("official corporate event manifest hash mismatch")
    safety = _as_mapping(
        manifest.get("safety"),
        "official corporate event safety",
    )
    required_true = (
        "append_only_canonical_events",
        "available_at_effective_at_separated",
        "formal_source_publication",
        "result_tables_label_ledger_only",
    )
    if any(
        _json_bool(safety.get(field_name), f"official safety.{field_name}")
        is not True
        for field_name in required_true
    ):
        raise ValueError("official corporate event safety contract is incomplete")
    if _json_bool(
        safety.get("result_tables_decision_feature_allowed"),
        "official safety.result_tables_decision_feature_allowed",
    ):
        raise ValueError("result-only events cannot be decision features")

    registry = _as_mapping(
        manifest.get("source_registry"),
        "official source_registry",
    )
    registry_sources: dict[str, Mapping[str, Any]] = {}
    for source in _mapping_sequence(
        registry.get("sources"),
        "official source_registry.sources",
    ):
        source_id = str(source.get("source_id", "")).strip()
        if not source_id or source_id in registry_sources:
            raise ValueError("official source registry id is invalid or duplicated")
        registry_sources[source_id] = source
    decision_source_ids = {
        source_id
        for source_id, source in registry_sources.items()
        if not _json_bool(
            source.get("result_only"),
            f"official source {source_id}.result_only",
        )
    }
    if not decision_source_ids:
        raise ValueError("official event manifest has no halt/resume source")
    for source_id in sorted(decision_source_ids):
        allowed_uses_raw = registry_sources[source_id].get(
            "allowed_uses"
        )
        if not isinstance(allowed_uses_raw, (list, tuple)):
            raise TypeError("official source allowed_uses must be an array")
        allowed_uses = {str(item) for item in allowed_uses_raw}
        if "formal_trading_restriction_timeline" not in allowed_uses:
            raise ValueError(
                "official halt/resume source lacks trading restriction use"
            )

    coverage_by_source: dict[str, set[int]] = {
        source_id: set() for source_id in decision_source_ids
    }
    for coverage in _mapping_sequence(
        manifest.get("coverage"),
        "official coverage",
    ):
        source_id = str(coverage.get("source_id", "")).strip()
        if source_id not in decision_source_ids:
            continue
        if _json_bool(
            coverage.get("result_only"),
            f"official coverage {source_id}.result_only",
        ):
            raise ValueError("halt/resume coverage cannot be result-only")
        if not _json_bool(
            coverage.get("complete_year_coverage"),
            f"official coverage {source_id}.complete_year_coverage",
        ):
            continue
        start_year = _nonnegative_int(
            coverage.get("requested_start_year"),
            "official coverage requested_start_year",
        )
        end_year = _nonnegative_int(
            coverage.get("requested_end_year"),
            "official coverage requested_end_year",
        )
        if end_year < start_year:
            raise ValueError("official coverage year range is invalid")
        coverage_by_source[source_id].update(
            range(start_year, end_year + 1)
        )
    complete_years = set.intersection(
        *(coverage_by_source[source_id] for source_id in decision_source_ids)
    )
    if not complete_years:
        raise ValueError("official halt/resume complete coverage is empty")

    canonical = _as_mapping(
        manifest.get("canonical_events"),
        "official canonical_events",
    )
    if canonical.get("schema_version") != _OFFICIAL_EVENT_ROW_SCHEMA_VERSION:
        raise ValueError("unsupported official canonical event row schema")
    relative_path = Path(str(canonical.get("path", "")))
    events_path = (path.parent / relative_path).resolve()
    if not events_path.is_relative_to(path.parent.resolve()):
        raise ValueError("official canonical event path escapes publication")
    canonical_file_hash = str(canonical.get("file_hash", ""))
    if _file_sha256(events_path) != canonical_file_hash:
        raise ValueError("official canonical event file hash mismatch")

    events_by_symbol: dict[str, list[_CorporateEvent]] = {}
    result_only_event_count = 0
    row_count = 0
    with events_path.open("r", encoding="utf-8") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            if not raw_line.strip():
                continue
            row_count += 1
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid official event JSONL at line {line_number}"
                ) from exc
            event = _as_mapping(payload, "official event")
            if event.get("schema_version") != _OFFICIAL_EVENT_ROW_SCHEMA_VERSION:
                raise ValueError("unsupported official event row schema")
            source_id = str(event.get("source_id", "")).strip()
            result_only = _json_bool(
                event.get("result_only"),
                "official event.result_only",
            )
            if result_only:
                result_only_event_count += 1
                if _json_bool(
                    event.get("formal_decision_feature_allowed"),
                    "official result event.formal_decision_feature_allowed",
                ):
                    raise ValueError(
                        "result-only event incorrectly permits decision feature"
                    )
                continue
            if source_id not in decision_source_ids:
                raise ValueError("event references unknown halt/resume source")
            if not _json_bool(
                event.get("formal_trading_restriction_allowed"),
                "official event.formal_trading_restriction_allowed",
            ):
                raise ValueError(
                    "halt/resume event lacks trading restriction permission"
                )
            event_type = str(event.get("event_type", "")).strip()
            if event_type not in {"trading_halt", "trading_resume"}:
                raise ValueError("unsupported halt/resume event type")
            symbol = str(event.get("symbol", "")).strip()
            if not symbol:
                raise ValueError("official event symbol is required")
            event_at = _datetime_text(
                event.get("event_at"),
                "official event.event_at",
            )
            available_at = _datetime_text(
                event.get("available_at"),
                "official event.available_at",
            )
            revision_id = str(event.get("revision_id", "")).strip()
            event_id = str(event.get("event_id", "")).strip()
            content_hash = str(
                event.get("source_record_hash", "")
            ).strip()
            if not revision_id or not event_id or not content_hash:
                raise ValueError("official event custody hashes are required")
            events_by_symbol.setdefault(symbol, []).append(
                _CorporateEvent(
                    symbol=symbol,
                    source_id=source_id,
                    event_type=event_type,  # type: ignore[arg-type]
                    event_at=event_at,
                    available_at=available_at,
                    revision_id=revision_id,
                    event_id=event_id,
                    content_hash=content_hash,
                    revision_availability_ambiguous=_json_bool(
                        event.get("revision_availability_ambiguous"),
                        "official event.revision_availability_ambiguous",
                    ),
                )
            )
    expected_count = _nonnegative_int(
        canonical.get("event_count"),
        "official canonical event_count",
    )
    if row_count != expected_count:
        raise ValueError("official canonical event count mismatch")
    normalized_events = {
        symbol: tuple(
            sorted(
                events,
                key=lambda event: (
                    _parse_datetime(event.available_at),
                    _parse_datetime(event.event_at),
                    event.event_id,
                    event.revision_id,
                ),
            )
        )
        for symbol, events in sorted(events_by_symbol.items())
    }
    return _CorporateEventTimeline(
        manifest_path=path,
        manifest_hash=expected_manifest_hash,
        manifest_file_hash=_file_sha256(path),
        canonical_file_hash=canonical_file_hash,
        events_by_symbol=normalized_events,
        complete_coverage_years=frozenset(complete_years),
        decision_feature_event_count=sum(
            len(events) for events in normalized_events.values()
        ),
        result_only_event_count=result_only_event_count,
    )


def _validate_custody_link(
    *,
    formal_manifest: Mapping[str, Any],
    shadow_manifest: Mapping[str, Any],
    base_manifest: Mapping[str, Any],
) -> None:
    raw_link = _as_mapping(
        base_manifest.get("raw_dataset_manifest"),
        "base.raw_dataset_manifest",
    )
    if raw_link.get("dataset_id") != _FORMAL_RAW_DATASET_ID:
        raise ValueError("base allocation data is not linked to all_field_enriched")
    if raw_link.get("manifest_hash") != formal_manifest.get("manifest_hash"):
        raise ValueError("base allocation and formal raw manifest custody mismatch")
    if formal_manifest.get("decision_at") != shadow_manifest.get("decision_at"):
        raise ValueError("formal and shadow publications have different PIT freezes")
    if (
        formal_manifest.get("eligibility_manifest_hash")
        != shadow_manifest.get("eligibility_manifest_hash")
    ):
        raise ValueError("formal and shadow eligibility registries differ")


def _shadow_base_definitions(
    manifest: Mapping[str, Any],
) -> dict[str, _FeatureDefinition]:
    result: dict[str, _FeatureDefinition] = {}
    for payload in _mapping_sequence(manifest.get("features"), "features"):
        feature_id = str(payload["feature_id"])
        definition = _FeatureDefinition(
            feature_id=feature_id,
            base_feature_id=feature_id,
            family_id=str(payload["family"]),
            source_id=str(payload["source_id"]),
            source_table=str(payload["table_name"]),
            scale=_positive_int(payload["scale"], "feature.scale"),
            stale_after_days=_nonnegative_int(
                payload["staleness_days"], "feature.staleness_days"
            ),
            eligibility_status=str(payload["eligibility_status"]),
            record_hash=_sha256_text(
                payload["record_hash"], "feature.record_hash"
            ),
            aggregation_policy=(
                _broker_aggregation_policy(feature_id)
                if str(payload["table_name"]) == _BROKER_TABLE
                else "latest_revision_as_of_decision"
            ),
        )
        if definition.eligibility_status != "research_shadow":
            raise ValueError("shadow feature definition is not research_shadow")
        result[feature_id] = definition
    return result


def _initialize_spool(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA temp_store=FILE")
    connection.executescript(
        """
        CREATE TABLE observations (
            sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            feature_id TEXT NOT NULL,
            source_table TEXT NOT NULL,
            family_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            event_at TEXT NOT NULL,
            available_at TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            quality TEXT NOT NULL,
            source_row_hash TEXT NOT NULL,
            source_value_hash TEXT NOT NULL,
            value_int INTEGER,
            scale INTEGER NOT NULL,
            stale_after_days INTEGER NOT NULL,
            missing_mask INTEGER NOT NULL,
            quality_blocked_mask INTEGER NOT NULL
        );
        CREATE INDEX idx_research_observation_lookup
        ON observations(
            symbol, feature_id, event_at, available_at,
            revision_id, source_value_hash
        );
        """
    )


def _spool_shadow_observations(
    *,
    connection: sqlite3.Connection,
    manifest_path: Path,
    manifest: Mapping[str, Any],
    base_definitions: Mapping[str, _FeatureDefinition],
    symbols: tuple[str, ...] | None,
    batch_size: int,
) -> tuple[dict[str, _FeatureDefinition], dict[str, object]]:
    publication_root = manifest_path.parent.parent.resolve()
    symbol_filter = None if symbols is None else frozenset(symbols)
    runtime_definitions: dict[str, _FeatureDefinition] = {}
    rows_to_insert: list[tuple[object, ...]] = []
    scanned_rows = 0
    selected_rows = 0
    selected_values = 0
    quality_blocked_values = 0
    first_seen_rows = 0
    source_tables: set[str] = set()
    content_set_digest = hashlib.sha256()
    for shard in _mapping_sequence(manifest.get("shards"), "shards"):
        shard_path = (publication_root / str(shard["path"])).resolve()
        if not shard_path.is_relative_to(publication_root):
            raise ValueError("shadow shard path escapes publication")
        if _file_sha256(shard_path) != shard.get("compressed_sha256"):
            raise ValueError("shadow shard compressed hash mismatch")
        content_digest = hashlib.sha256()
        shard_rows = 0
        shard_values = 0
        with gzip.open(shard_path, "rb") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                if not raw_line.strip():
                    continue
                content_digest.update(raw_line)
                scanned_rows += 1
                shard_rows += 1
                try:
                    payload = json.loads(raw_line.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"invalid shadow JSONL at {shard_path}:{line_number}"
                    ) from exc
                row = _as_mapping(payload, "shadow observation")
                values = _mapping_sequence(row.get("values"), "values")
                shard_values += len(values)
                if row.get("schema_version") != _RAW_ROW_SCHEMA_VERSION:
                    raise ValueError("unsupported shadow observation schema")
                if row.get("dataset_id") != _SHADOW_RAW_DATASET_ID:
                    raise ValueError("shadow observation dataset id mismatch")
                if row.get("pit_status") != "eligible_as_of_decision":
                    raise ValueError("shadow observation is not PIT eligible")
                expected_row_hash = str(row.get("source_row_hash", ""))
                hash_body = dict(row)
                hash_body.pop("source_row_hash", None)
                if expected_row_hash != _sha256_json(hash_body):
                    raise ValueError("shadow observation row hash mismatch")
                symbol = str(row.get("entity_id", "")).split("|", 1)[0].strip()
                if not symbol:
                    raise ValueError("shadow stock observation requires symbol")
                if symbol_filter is not None and symbol not in symbol_filter:
                    continue
                event_at = _datetime_text(row.get("event_at"), "event_at")
                available_at = _datetime_text(
                    row.get("available_at"), "available_at"
                )
                if _parse_datetime(event_at) > _parse_datetime(available_at):
                    raise ValueError(
                        "realized shadow event_at exceeds available_at"
                    )
                first_seen_at_raw = row.get("first_seen_at")
                if first_seen_at_raw not in (None, ""):
                    first_seen_at = _datetime_text(
                        first_seen_at_raw, "first_seen_at"
                    )
                    first_seen_rows += 1
                    if _parse_datetime(available_at) < _parse_datetime(
                        first_seen_at
                    ):
                        raise ValueError(
                            "snapshot available_at precedes first_seen_at"
                        )
                source_table = str(row["source_table"])
                source_id = str(row["source_id"])
                family_id = str(row["family"])
                source_tables.add(source_table)
                revision_id = (
                    str(row["revision_id"])
                    if row.get("revision_id") not in (None, "")
                    else expected_row_hash
                )
                selected_rows += 1
                seen_feature_ids: set[str] = set()
                for value in values:
                    base_feature_id = str(value["feature_id"])
                    if base_feature_id in seen_feature_ids:
                        raise ValueError(
                            "shadow row contains duplicate feature id"
                        )
                    seen_feature_ids.add(base_feature_id)
                    base = base_definitions.get(base_feature_id)
                    if base is None:
                        raise ValueError(
                            f"shadow feature absent from manifest: {base_feature_id}"
                        )
                    if base.source_table != source_table:
                        raise ValueError("shadow feature source table mismatch")
                    if base.source_id != source_id:
                        raise ValueError("shadow feature source id mismatch")
                    if base.family_id != family_id:
                        raise ValueError("shadow feature family mismatch")
                    runtime = _runtime_definition(
                        base=base,
                        entity_id=str(row["entity_id"]),
                    )
                    runtime_definitions[runtime.feature_id] = runtime
                    value_int = value.get("value_int")
                    if value_int is not None and (
                        isinstance(value_int, bool)
                        or not isinstance(value_int, int)
                    ):
                        raise TypeError("shadow value_int must be integer or null")
                    scale = _positive_int(value.get("scale"), "value.scale")
                    if scale != base.scale:
                        raise ValueError("shadow feature scale mismatch")
                    eligibility = str(value.get("eligibility_status", ""))
                    if eligibility != "research_shadow":
                        raise ValueError(
                            "shadow observation contains non-shadow value"
                        )
                    if value.get("formal_training_eligible") is not False:
                        raise ValueError(
                            "shadow observation claims formal eligibility"
                        )
                    missing_mask = _json_bool(
                        value.get("missing_mask"), "missing_mask"
                    )
                    quality_blocked = _json_bool(
                        value.get("quality_blocked_mask"),
                        "quality_blocked_mask",
                    )
                    _json_bool(
                        value.get("staleness_mask"), "staleness_mask"
                    )
                    source_value_hash = _sha256_text(
                        value.get("source_value_hash"),
                        "source_value_hash",
                    )
                    rows_to_insert.append(
                        (
                            symbol,
                            runtime.feature_id,
                            source_table,
                            family_id,
                            source_id,
                            event_at,
                            available_at,
                            revision_id,
                            str(row.get("quality", "not_provided")),
                            expected_row_hash,
                            source_value_hash,
                            value_int,
                            scale,
                            _nonnegative_int(
                                value.get("stale_after_days"),
                                "stale_after_days",
                            ),
                            int(missing_mask),
                            int(quality_blocked),
                        )
                    )
                    selected_values += 1
                    quality_blocked_values += int(quality_blocked)
                    content_set_digest.update(
                        (
                            f"{expected_row_hash}|{source_value_hash}|"
                            f"{runtime.feature_id}\n"
                        ).encode("utf-8")
                    )
                    if len(rows_to_insert) >= batch_size:
                        _insert_shadow_rows(connection, rows_to_insert)
                        rows_to_insert.clear()
        if (
            f"sha256:{content_digest.hexdigest()}"
            != shard.get("content_sha256")
        ):
            raise ValueError("shadow shard content hash mismatch")
        if shard_rows != int(shard.get("row_count", -1)):
            raise ValueError("shadow shard row count mismatch")
        if shard_values != int(shard.get("feature_value_count", -1)):
            raise ValueError("shadow shard feature value count mismatch")
    if rows_to_insert:
        _insert_shadow_rows(connection, rows_to_insert)
    connection.commit()
    return runtime_definitions, {
        "scanned_row_count": scanned_rows,
        "selected_row_count": selected_rows,
        "selected_feature_value_count": selected_values,
        "quality_blocked_value_count": quality_blocked_values,
        "first_seen_row_count": first_seen_rows,
        "selected_source_tables": sorted(source_tables),
        "selected_content_set_hash": (
            f"sha256:{content_set_digest.hexdigest()}"
        ),
    }


def _runtime_definition(
    *, base: _FeatureDefinition, entity_id: str
) -> _FeatureDefinition:
    if base.source_table not in _LONG_FORMAT_TABLES:
        return base
    parts = tuple(str(entity_id).split("|"))
    dimension: tuple[str, ...]
    if base.source_table == "fundamental_statement_items":
        if len(parts) < 4:
            raise ValueError("statement item identity is incomplete")
        dimension = (parts[1], parts[3])
    else:
        if len(parts) < 2:
            raise ValueError("valuation metric identity is incomplete")
        dimension = (parts[1],)
    feature_id = (
        f"{base.base_feature_id}::"
        f"{_sha256_json({'dimension': dimension})[7:23]}"
    )
    return _FeatureDefinition(
        feature_id=feature_id,
        base_feature_id=base.base_feature_id,
        family_id=base.family_id,
        source_id=base.source_id,
        source_table=base.source_table,
        scale=base.scale,
        stale_after_days=base.stale_after_days,
        eligibility_status=base.eligibility_status,
        record_hash=_sha256_json(
            {
                "base_record_hash": base.record_hash,
                "dimension": dimension,
            }
        ),
        dimension_values=dimension,
        aggregation_policy=base.aggregation_policy,
    )


def _final_shadow_definitions(
    *,
    base_definitions: Mapping[str, _FeatureDefinition],
    runtime_definitions: Mapping[str, _FeatureDefinition],
) -> tuple[_FeatureDefinition, ...]:
    expanded_bases = {
        definition.base_feature_id
        for definition in runtime_definitions.values()
        if definition.feature_id != definition.base_feature_id
    }
    result = {
        feature_id: definition
        for feature_id, definition in base_definitions.items()
        if feature_id not in expanded_bases
    }
    result.update(runtime_definitions)
    return tuple(result[key] for key in sorted(result))


def _insert_shadow_rows(
    connection: sqlite3.Connection, rows: Sequence[tuple[object, ...]]
) -> None:
    connection.executemany(
        """
        INSERT INTO observations(
            symbol, feature_id, source_table, family_id, source_id,
            event_at, available_at, revision_id, quality,
            source_row_hash, source_value_hash, value_int, scale,
            stale_after_days, missing_mask, quality_blocked_mask
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _union_feature_packs(
    *,
    base_manifest: Mapping[str, Any],
    shadow_definitions: Sequence[_FeatureDefinition],
) -> list[dict[str, object]]:
    packs: dict[str, set[str]] = {}
    for pack in _mapping_sequence(
        base_manifest.get("feature_packs"), "base.feature_packs"
    ):
        pack_id = str(pack["pack_id"])
        packs.setdefault(pack_id, set()).update(
            str(value) for value in pack.get("feature_ids", ())
        )
    shadow_families: set[str] = set()
    for definition in shadow_definitions:
        packs.setdefault(definition.family_id, set()).add(
            definition.feature_id
        )
        shadow_families.add(definition.family_id)
    packs.setdefault("rule_portfolio_health", set()).update(
        _RULE_PORTFOLIO_HEALTH_FEATURE_IDS
    )
    packs.setdefault("corporate_microstructure", set()).update(
        _CORPORATE_MICROSTRUCTURE_FEATURE_IDS
    )
    quality_pack = packs.setdefault("data_quality", set())
    for family_id in sorted(shadow_families):
        for metric in (
            "coverage_bp",
            "max_available_lag_days",
            "missing_count",
            "quality_blocked_count",
            "stale_count",
        ):
            quality_pack.add(f"data_quality.{family_id}.{metric}")
    return [
        {
            "pack_id": pack_id,
            "feature_ids": sorted(feature_ids),
        }
        for pack_id, feature_ids in sorted(packs.items())
    ]


def _feature_pack_dispositions(
    feature_packs: Sequence[Mapping[str, object]],
    *,
    official_corporate_timeline: bool = False,
) -> list[dict[str, object]]:
    counts: dict[str, int] = {}
    for pack in feature_packs:
        feature_ids = pack.get("feature_ids")
        if not isinstance(feature_ids, (list, tuple)):
            raise TypeError("feature pack ids must be an array")
        counts[str(pack["pack_id"])] = len(feature_ids)
    definitions: tuple[tuple[str, str, str], ...] = (
        (
            "price_liquidity_technical",
            "present_causal",
            "verified_T_minus_1_formal_features_reused",
        ),
        (
            "market_sector_cross_section",
            "present_causal_with_masks",
            "sector_membership_absent_values_remain_explicit_missing",
        ),
        (
            "fundamental_growth_quality",
            "present_research_shadow_first_seen_only",
            "no_snapshot_historical_backfill",
        ),
        (
            "valuation",
            "present_research_shadow_first_seen_only",
            "no_snapshot_historical_backfill",
        ),
        (
            "flow_chip",
            "present_research_shadow_asof_join",
            "research_source_not_formal_accepted",
        ),
        (
            "corporate_microstructure",
            (
                "present_causal_halt_resume_partial_schema"
                if official_corporate_timeline
                else "schema_registered_blocked_zero_coverage"
            ),
            (
                "official_halt_resume_available_result_only_events_excluded"
                if official_corporate_timeline
                else "official_event_manifest_not_delivered"
            ),
        ),
        (
            "rule_portfolio_health",
            "present_causal_state_only",
            "T_minus_1_state_available_but_thesis_health_exit_history_unavailable",
        ),
        (
            "data_quality",
            "present_causal_derived",
            "missing_staleness_quality_and_coverage_masks",
        ),
    )
    dispositions: list[dict[str, object]] = []
    for pack_id, status, reason in definitions:
        feature_count = counts.get(pack_id, 0)
        if status.startswith("present") and feature_count == 0:
            raise ValueError(
                f"declared present feature pack is empty: {pack_id}"
            )
        if status == "schema_registered_blocked_zero_coverage" and (
            feature_count == 0
        ):
            raise ValueError(
                f"blocked feature pack lacks missing schema: {pack_id}"
            )
        dispositions.append(
            {
                "pack_id": pack_id,
                "status": status,
                "feature_count": feature_count,
                "reason": reason,
                "research_only": True,
                "formal_training_eligible": False,
                "contains_verified_formal_component": pack_id
                in {
                    "price_liquidity_technical",
                    "market_sector_cross_section",
                    "data_quality",
                },
                "declared_coverage_bp": (
                    (
                        5_000
                        if official_corporate_timeline
                        else 0
                    )
                    if pack_id == "corporate_microstructure"
                    else 10_000
                    if pack_id == "rule_portfolio_health"
                    else None
                ),
            }
        )
    unknown = sorted(set(counts) - {item[0] for item in definitions})
    if unknown:
        raise ValueError(
            f"feature packs lack explicit disposition: {unknown}"
        )
    return dispositions


def _feature_registry_payload(
    *,
    base_manifest: Mapping[str, Any],
    shadow_definitions: Sequence[_FeatureDefinition],
    feature_packs: Sequence[Mapping[str, object]],
    corporate_timeline: _CorporateEventTimeline | None,
) -> dict[str, object]:
    base_registry = _as_mapping(
        base_manifest.get("feature_registry"), "base.feature_registry"
    )
    base_features = list(
        _mapping_sequence(base_registry.get("features"), "base.features")
    )
    shadow_features = [
        definition.registry_payload() for definition in shadow_definitions
    ]
    shadow_families = sorted(
        {definition.family_id for definition in shadow_definitions}
    )
    quality_features = [
        {
            "feature_id": f"data_quality.{family_id}.{metric}",
            "base_feature_id": f"data_quality.{family_id}.{metric}",
            "family_id": "data_quality",
            "source_id": "derived:research_shadow_feature_quality",
            "source_table": "derived",
            "scale": 1,
            "stale_after_days": 0,
            "eligibility_status": "research_shadow",
            "dimension_values": [family_id],
            "aggregation_policy": "causal_missingness_summary",
            "record_hash": _sha256_json(
                {
                    "family_id": family_id,
                    "metric": metric,
                    "policy": "causal_missingness_summary",
                }
            ),
        }
        for family_id in shadow_families
        for metric in (
            "coverage_bp",
            "max_available_lag_days",
            "missing_count",
            "quality_blocked_count",
            "stale_count",
        )
    ]
    rule_state_features = [
        {
            "feature_id": feature_id,
            "base_feature_id": feature_id,
            "family_id": "rule_portfolio_health",
            "source_id": _RULE_PORTFOLIO_HEALTH_SOURCE_ID,
            "source_table": "causal_portfolio_state",
            "scale": 1,
            "stale_after_days": 0,
            "eligibility_status": "research_shadow",
            "dimension_values": [],
            "aggregation_policy": (
                "derive_from_T_minus_1_state_no_same_day_advice"
            ),
            "record_hash": _sha256_json(
                {
                    "feature_id": feature_id,
                    "policy": (
                        "derive_from_T_minus_1_state_no_same_day_advice"
                    ),
                }
            ),
        }
        for feature_id in _RULE_PORTFOLIO_HEALTH_FEATURE_IDS
    ]
    corporate_features: list[dict[str, object]] = [
        {
            "feature_id": feature_id,
            "base_feature_id": feature_id,
            "family_id": "corporate_microstructure",
            "source_id": (
                _CORPORATE_OFFICIAL_SOURCE_ID
                if corporate_timeline is not None
                and feature_id in _CORPORATE_HALT_RESUME_FEATURE_IDS
                else _CORPORATE_BLOCKED_SOURCE_ID
            ),
            "source_table": (
                "official_halt_resume_timeline"
                if corporate_timeline is not None
                and feature_id in _CORPORATE_HALT_RESUME_FEATURE_IDS
                else "unavailable_official_event_timeline"
            ),
            "scale": 1,
            "stale_after_days": 0,
            "eligibility_status": (
                "research_shadow"
                if corporate_timeline is not None
                and feature_id in _CORPORATE_HALT_RESUME_FEATURE_IDS
                else "blocked_no_provenance"
            ),
            "dimension_values": [],
            "aggregation_policy": (
                "latest_available_halt_resume_state_complete_coverage_only"
                if corporate_timeline is not None
                and feature_id in _CORPORATE_HALT_RESUME_FEATURE_IDS
                else "explicit_missing_fail_closed"
            ),
            "record_hash": _sha256_json(
                {
                    "feature_id": feature_id,
                    "policy": (
                        "latest_available_halt_resume_state_complete_coverage_only"
                        if corporate_timeline is not None
                        and feature_id
                        in _CORPORATE_HALT_RESUME_FEATURE_IDS
                        else "explicit_missing_fail_closed"
                    ),
                    "reason": (
                        None
                        if corporate_timeline is not None
                        and feature_id
                        in _CORPORATE_HALT_RESUME_FEATURE_IDS
                        else "official_source_not_applicable_or_not_delivered"
                    ),
                    "official_manifest_hash": (
                        corporate_timeline.manifest_hash
                        if corporate_timeline is not None
                        and feature_id
                        in _CORPORATE_HALT_RESUME_FEATURE_IDS
                        else None
                    ),
                    "result_only_events_allowed": False,
                }
            ),
        }
        for feature_id in _CORPORATE_MICROSTRUCTURE_FEATURE_IDS
    ]
    all_features = [
        *base_features,
        *shadow_features,
        *quality_features,
        *rule_state_features,
        *corporate_features,
    ]
    feature_ids = [str(feature["feature_id"]) for feature in all_features]
    if len(feature_ids) != len(set(feature_ids)):
        raise ValueError("union feature registry contains duplicate ids")
    return {
        "schema_version": "research-shadow-feature-registry.v1",
        "features": sorted(
            all_features, key=lambda feature: str(feature["feature_id"])
        ),
        "feature_packs": list(feature_packs),
        "research_only": True,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
    }


def _union_source_manifest_hashes(
    *,
    base_manifest: Mapping[str, Any],
    shadow_manifest: Mapping[str, Any],
    definitions: Sequence[_FeatureDefinition],
    corporate_timeline: _CorporateEventTimeline | None,
) -> tuple[tuple[str, str], ...]:
    result = {
        str(source_id): str(source_hash)
        for source_id, source_hash in base_manifest.get(
            "source_manifest_hashes", ()
        )
    }
    by_source: dict[str, list[str]] = {}
    for definition in definitions:
        by_source.setdefault(definition.source_id, []).append(
            definition.record_hash
        )
    for source_id, record_hashes in by_source.items():
        result[source_id] = _sha256_json(
            {
                "source_id": source_id,
                "shadow_manifest_hash": shadow_manifest["manifest_hash"],
                "feature_record_hashes": sorted(record_hashes),
                "research_only": True,
            }
        )
    result["derived:research_shadow_feature_quality"] = _sha256_json(
        {
            "shadow_manifest_hash": shadow_manifest["manifest_hash"],
            "policy": "causal_missingness_summary",
        }
    )
    result[_RULE_PORTFOLIO_HEALTH_SOURCE_ID] = _sha256_json(
        {
            "policy": "derive_from_T_minus_1_state_no_same_day_advice",
            "feature_ids": list(_RULE_PORTFOLIO_HEALTH_FEATURE_IDS),
            "targets_feed_next_state": False,
            "research_only": True,
        }
    )
    if corporate_timeline is None:
        result[_CORPORATE_BLOCKED_SOURCE_ID] = _sha256_json(
            {
                "policy": "explicit_missing_fail_closed",
                "reason": "official_event_manifest_not_delivered",
                "feature_ids": list(
                    _CORPORATE_MICROSTRUCTURE_FEATURE_IDS
                ),
                "coverage_bp": 0,
                "research_only": True,
            }
        )
    else:
        result[_CORPORATE_OFFICIAL_SOURCE_ID] = (
            corporate_timeline.manifest_hash
        )
        result[_CORPORATE_BLOCKED_SOURCE_ID] = _sha256_json(
            {
                "policy": "explicit_missing_non_halt_resume_features",
                "reason": "official_source_not_applicable_to_feature",
                "feature_ids": sorted(
                    set(_CORPORATE_MICROSTRUCTURE_FEATURE_IDS)
                    - _CORPORATE_HALT_RESUME_FEATURE_IDS
                ),
                "result_only_events_feature_allowed": False,
                "research_only": True,
            }
        )
    return tuple(sorted(result.items()))


def _research_teacher_policy_payload() -> dict[str, object]:
    return {
        "schema_version": "research-allocation-teacher.v1",
        "mode": "supervised_constrained_grid",
        "horizon_trading_days": 20,
        "future_outcomes_supervised_labels_only": True,
        "base_portfolio_state": (
            "per_decision_t_minus_1_cash_only_fallback"
        ),
        "causal_state_progression": (
            "independent_cash_only_fallback_targets_never_feed_next_state"
        ),
        "recursive_paper_ledger_available": False,
        "rule_portfolio_health_pack_used": False,
        "base_targets_preserved": False,
        "target_grid_bp": 100,
        "maximum_symbol_weight_bp": 1_500,
        "maximum_total_new_risky_bp": 2_000,
        "minimum_cash_bp": 8_000,
        "maximum_names": 2,
        "minimum_trade_bp": 200,
        "rebalance_band_bp": 300,
        "buy_cost_bp": 25,
        "sell_cost_bp": 55,
        "candidate_rule": (
            "positive_20d_benchmark_excess_and_feasible_fill"
        ),
        "ranking_tiebreak": [
            "benchmark_excess_return_bp_desc",
            "tail_loss_bp_asc",
            "max_drawdown_bp_asc",
            "symbol_asc",
        ],
        "unknown_sector_policy": (
            "unique_research_bucket_assumption"
        ),
        "snapshot_backfill_research_assumption": False,
        "unknown_sector_unique_bucket_research_assumption": True,
        "excluded_from_formal": True,
        "targets_feed_next_state": False,
        "turnover_or_cooldown_learning_claim_allowed": False,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "promotion_eligible": False,
    }


def _build_research_teacher_targets(
    *,
    base_manifest_path: Path,
    base_manifest: Mapping[str, Any],
    symbols: tuple[str, ...] | None,
    years: tuple[int, ...],
) -> tuple[dict[str, dict[str, object]], dict[str, object], str]:
    root = base_manifest_path.parent.resolve()
    symbol_filter = None if symbols is None else frozenset(symbols)
    year_filter = frozenset(years)
    training_as_of = _parse_datetime(
        _datetime_text(
            base_manifest.get("training_as_of"),
            "base.training_as_of",
        )
    )
    targets: dict[str, dict[str, object]] = {}
    current_decision_date: str | None = None
    current_candidates: list[_ResearchTeacherCandidate] = []
    current_symbols: set[str] = set()
    current_row_count = 0
    last_decision_date: str | None = None
    selected_row_count = 0
    eligible_candidate_count = 0
    nonzero_target_sample_row_count = 0
    nonzero_target_decision_count = 0
    allocated_position_count = 0
    risky_budget_distribution: dict[int, int] = {}

    def finalize_current() -> None:
        nonlocal current_decision_date
        nonlocal current_candidates
        nonlocal current_symbols
        nonlocal current_row_count
        nonlocal nonzero_target_sample_row_count
        nonlocal nonzero_target_decision_count
        nonlocal allocated_position_count
        if current_decision_date is None:
            return
        target = _research_target_for_decision(
            decision_date=current_decision_date,
            candidates=tuple(current_candidates),
        )
        if current_decision_date in targets:
            raise ValueError("duplicate research teacher decision date")
        targets[current_decision_date] = target
        risky_budget = _nonnegative_int(
            target["risky_budget_bp"],
            "research target risky_budget_bp",
        )
        risky_budget_distribution[risky_budget] = (
            risky_budget_distribution.get(risky_budget, 0) + 1
        )
        positions = _pair_sequence(
            _as_mapping(
                target["target_weights"],
                "research target weights",
            ).get("positions_bp"),
            "research target positions",
        )
        allocated_position_count += len(positions)
        if risky_budget > 0:
            nonzero_target_decision_count += 1
            nonzero_target_sample_row_count += current_row_count
        current_decision_date = None
        current_candidates = []
        current_symbols = set()
        current_row_count = 0

    for shard in _mapping_sequence(
        base_manifest.get("shards"), "base.shards"
    ):
        shard_year = _positive_int(shard.get("year"), "base.shard.year")
        if year_filter and shard_year not in year_filter:
            continue
        shard_path = (root / str(shard["path"])).resolve()
        if not shard_path.is_relative_to(root):
            raise ValueError("base training shard escapes publication")
        if _file_sha256(shard_path) != shard.get("compressed_sha256"):
            raise ValueError("base training shard compressed hash mismatch")
        content_digest = hashlib.sha256()
        base_sample_count = 0
        with gzip.open(shard_path, "rb") as stream:
            header_seen = False
            for line_number, raw_line in enumerate(stream, start=1):
                if not raw_line.strip():
                    continue
                content_digest.update(raw_line)
                try:
                    payload = json.loads(raw_line.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        "invalid base training JSONL at "
                        f"{shard_path}:{line_number}"
                    ) from exc
                record = _as_mapping(payload, "base training record")
                if record.get("record_type") == "header":
                    if header_seen or base_sample_count:
                        raise ValueError(
                            "base training header is not first"
                        )
                    header_seen = True
                    _validate_base_header(
                        record,
                        base_manifest,
                        shard_year,
                    )
                    continue
                if (
                    record.get("record_type") != "sample"
                    or not header_seen
                ):
                    raise ValueError("invalid base training record order")
                base_sample_count += 1
                sample = _as_mapping(record.get("sample"), "sample")
                row = _as_mapping(sample.get("row"), "sample.row")
                symbol = str(row.get("symbol", "")).strip()
                if symbol_filter is not None and symbol not in symbol_filter:
                    continue
                decision_at = _datetime_text(
                    row.get("decision_at"), "row.decision_at"
                )
                decision = _parse_datetime(decision_at)
                if decision.year != shard_year:
                    raise ValueError(
                        "base sample year does not match shard"
                    )
                _validate_base_row_pit(row, decision_at)
                decision_date = decision.date().isoformat()
                if (
                    last_decision_date is not None
                    and decision_date < last_decision_date
                ):
                    raise ValueError(
                        "base samples must be decision-date ordered"
                    )
                if (
                    current_decision_date is not None
                    and decision_date != current_decision_date
                ):
                    finalize_current()
                if current_decision_date is None:
                    current_decision_date = decision_date
                last_decision_date = decision_date
                if symbol in current_symbols:
                    raise ValueError(
                        "research teacher decision has duplicate symbol"
                    )
                current_symbols.add(symbol)
                _validate_research_teacher_cash_only_state(
                    row=row,
                    decision_date=decision_date,
                )
                candidate = _research_teacher_candidate(
                    symbol=symbol,
                    sample=sample,
                    decision_date=decision_date,
                    training_as_of=training_as_of,
                )
                current_candidates.append(candidate)
                current_row_count += 1
                selected_row_count += 1
                eligible_candidate_count += int(
                    candidate.fill_feasible_observed
                    and candidate.benchmark_excess_return_bp > 0
                )
        if not header_seen:
            raise ValueError("base training shard has no header")
        if (
            f"sha256:{content_digest.hexdigest()}"
            != shard.get("content_sha256")
        ):
            raise ValueError("base training shard content hash mismatch")
        if base_sample_count != int(shard.get("sample_count", -1)):
            raise ValueError("base training shard sample count mismatch")
    finalize_current()
    if not targets:
        raise ValueError("research teacher has no eligible decision rows")
    stats: dict[str, object] = {
        "decision_count": len(targets),
        "sample_row_count": selected_row_count,
        "eligible_candidate_count": eligible_candidate_count,
        "nonzero_target_decision_count": nonzero_target_decision_count,
        "nonzero_target_sample_row_count": (
            nonzero_target_sample_row_count
        ),
        "nonzero_delta_sample_row_count": (
            nonzero_target_sample_row_count
        ),
        "nonzero_risky_budget_decision_count": (
            nonzero_target_decision_count
        ),
        "allocated_position_count": allocated_position_count,
        "maximum_risky_budget_bp": max(risky_budget_distribution),
        "risky_budget_distribution": {
            str(key): risky_budget_distribution[key]
            for key in sorted(risky_budget_distribution)
        },
        "target_grid_bp": 100,
        "all_input_portfolio_states_cash_only": True,
        "targets_feed_next_state": False,
        "snapshot_backfill_research_assumption": False,
        "unknown_sector_unique_bucket_research_assumption": True,
        "excluded_from_formal": True,
    }
    teacher_hash = _sha256_json(
        {
            "policy": _research_teacher_policy_payload(),
            "targets": [
                [decision_date, targets[decision_date]]
                for decision_date in sorted(targets)
            ],
        }
    )
    return targets, stats, teacher_hash


def _research_teacher_candidate(
    *,
    symbol: str,
    sample: Mapping[str, Any],
    decision_date: str,
    training_as_of: datetime,
) -> _ResearchTeacherCandidate:
    labels = [
        label
        for label in _mapping_sequence(
            sample.get("horizon_labels"), "sample.horizon_labels"
        )
        if label.get("horizon_trading_days") == 20
    ]
    if len(labels) != 1:
        raise ValueError(
            "research teacher requires exactly one 20-day label"
        )
    label = labels[0]
    horizon_end_date = str(label.get("horizon_end_date", ""))
    horizon_end = date.fromisoformat(horizon_end_date)
    decision = date.fromisoformat(decision_date)
    if horizon_end <= decision:
        raise ValueError(
            "research teacher horizon must follow decision date"
        )
    available_at = _datetime_text(
        label.get("available_at"),
        "20-day label available_at",
    )
    available = _parse_datetime(available_at)
    if available.date() < horizon_end:
        raise ValueError(
            "research teacher label availability precedes horizon"
        )
    if available > training_as_of:
        raise ValueError(
            "research teacher label is not mature at training_as_of"
        )
    benchmark_excess = _integer(
        label.get("benchmark_excess_return_bp"),
        "20-day benchmark_excess_return_bp",
    )
    tail_loss = _nonnegative_int(
        label.get("tail_loss_bp"),
        "20-day tail_loss_bp",
    )
    max_drawdown = _nonnegative_int(
        label.get("max_drawdown_bp"),
        "20-day max_drawdown_bp",
    )
    fill_feasible = _json_bool(
        label.get("fill_feasible_observed"),
        "20-day fill_feasible_observed",
    )
    return _ResearchTeacherCandidate(
        symbol=symbol,
        horizon_end_date=horizon_end_date,
        available_at=available_at,
        benchmark_excess_return_bp=benchmark_excess,
        tail_loss_bp=tail_loss,
        max_drawdown_bp=max_drawdown,
        fill_feasible_observed=fill_feasible,
    )


def _validate_research_teacher_cash_only_state(
    *,
    row: Mapping[str, Any],
    decision_date: str,
) -> None:
    state = _as_mapping(
        row.get("portfolio_state"),
        "research teacher portfolio_state",
    )
    as_of_date = str(state.get("as_of_date", ""))
    if date.fromisoformat(as_of_date) >= date.fromisoformat(decision_date):
        raise ValueError(
            "research teacher portfolio state must be T-1 or earlier"
        )
    weights = _as_mapping(
        state.get("weights"),
        "research teacher portfolio_state.weights",
    )
    positions = _pair_sequence(
        weights.get("positions_bp"),
        "research teacher current positions",
    )
    if positions or weights.get("cash_bp") != 10_000:
        raise ValueError(
            "research teacher v1 requires a causal cash-only base state"
        )
    if state.get("weekly_turnover_used_bp") != 0:
        raise ValueError(
            "research teacher v1 requires zero prior weekly turnover"
        )
    _sha256_text(
        state.get("state_hash"),
        "research teacher portfolio state hash",
    )


def _research_target_for_decision(
    *,
    decision_date: str,
    candidates: tuple[_ResearchTeacherCandidate, ...],
) -> dict[str, object]:
    if not candidates:
        raise ValueError("research teacher decision has no candidates")
    symbols = tuple(candidate.symbol for candidate in candidates)
    if len(symbols) != len(set(symbols)):
        raise ValueError("research teacher candidate symbols must be unique")
    selected = sorted(
        (
            candidate
            for candidate in candidates
            if candidate.fill_feasible_observed
            and candidate.benchmark_excess_return_bp > 0
        ),
        key=lambda candidate: (
            -candidate.benchmark_excess_return_bp,
            candidate.tail_loss_bp,
            candidate.max_drawdown_bp,
            candidate.symbol,
        ),
    )[:2]
    requested = (1_500, 500)
    positions = tuple(
        sorted(
            (
                candidate.symbol,
                requested[index],
            )
            for index, candidate in enumerate(selected)
        )
    )
    risky_budget_bp = sum(weight for _, weight in positions)
    cash_bp = 10_000 - risky_budget_bp
    if risky_budget_bp > 2_000 or cash_bp < 8_000:
        raise ValueError("research teacher violated risk budget")
    if any(
        weight % 100 != 0 or weight > 1_500
        for _, weight in positions
    ):
        raise ValueError("research teacher violated weight grid")
    target_weights = AllocationWeightContract(
        positions_bp=positions,
        cash_bp=cash_bp,
    )
    available_at = max(
        candidates,
        key=lambda candidate: _parse_datetime(candidate.available_at),
    ).available_at
    horizon_end_date = max(
        candidate.horizon_end_date for candidate in candidates
    )
    targets = AllocationTargets(
        decision_date=decision_date,
        horizon_end_date=horizon_end_date,
        available_at=available_at,
        target_weights=target_weights,
        delta_weights_bp=positions,
        risk_contributions_bp=positions,
        risky_budget_bp=risky_budget_bp,
        cash_bp=cash_bp,
        rebalance_worthwhile=risky_budget_bp >= 300,
    )
    return {
        "decision_date": targets.decision_date,
        "horizon_end_date": targets.horizon_end_date,
        "available_at": targets.available_at,
        "target_weights": {
            "positions_bp": [
                [symbol, weight]
                for symbol, weight in targets.target_weights.positions_bp
            ],
            "cash_bp": targets.target_weights.cash_bp,
        },
        "delta_weights_bp": [
            [symbol, weight]
            for symbol, weight in targets.delta_weights_bp
        ],
        "risk_contributions_bp": [
            [symbol, weight]
            for symbol, weight in targets.risk_contributions_bp
        ],
        "risky_budget_bp": targets.risky_budget_bp,
        "cash_bp": targets.cash_bp,
        "rebalance_worthwhile": targets.rebalance_worthwhile,
    }


def _causal_portfolio_state_features(
    *,
    row: Mapping[str, Any],
    decision_at: str,
    symbol: str,
) -> list[dict[str, object]]:
    state_payload = _as_mapping(
        row.get("portfolio_state"),
        "portfolio_state",
    )
    weights_payload = _as_mapping(
        state_payload.get("weights"),
        "portfolio_state.weights",
    )
    positions = _pair_sequence(
        weights_payload.get("positions_bp"),
        "portfolio_state.weights.positions_bp",
    )
    cash_bp = _nonnegative_int(
        weights_payload.get("cash_bp"),
        "portfolio_state.weights.cash_bp",
    )
    weights = AllocationWeightContract(
        positions_bp=positions,
        cash_bp=cash_bp,
    )
    state = CausalPortfolioState(
        as_of_date=str(state_payload.get("as_of_date", "")),
        weights=weights,
        weekly_turnover_used_bp=_nonnegative_int(
            state_payload.get("weekly_turnover_used_bp"),
            "portfolio_state.weekly_turnover_used_bp",
        ),
        state_hash=_sha256_text(
            state_payload.get("state_hash"),
            "portfolio_state.state_hash",
        ),
    )
    decision = _parse_datetime(decision_at)
    if date.fromisoformat(state.as_of_date) >= decision.date():
        raise ValueError(
            "portfolio health features require T-1-or-earlier state"
        )
    current_weights = dict(state.weights.positions_bp)
    values = {
        "rule_portfolio_health.cash_bp": state.weights.cash_bp,
        "rule_portfolio_health.current_symbol_weight_bp": (
            current_weights.get(symbol, 0)
        ),
        "rule_portfolio_health.invested_bp": state.weights.invested_bp,
        "rule_portfolio_health.position_count": len(
            state.weights.positions_bp
        ),
        "rule_portfolio_health.state_complete_flag": 1,
        "rule_portfolio_health.weekly_turnover_used_bp": (
            state.weekly_turnover_used_bp
        ),
    }
    return [
        asdict(
            PITFeatureValue(
                feature_id=feature_id,
                family_id="rule_portfolio_health",
                source_id=_RULE_PORTFOLIO_HEALTH_SOURCE_ID,
                value_int=value_int,
                scale=1,
                event_at=state.as_of_date,
                available_at=decision.isoformat(),
                revision_id=state.state_hash,
                quality="observed",
                content_hash=_sha256_json(
                    {
                        "feature_id": feature_id,
                        "value_int": value_int,
                        "state_hash": state.state_hash,
                        "decision_at": decision.isoformat(),
                    }
                ),
                observed=True,
            )
        )
        for feature_id, value_int in sorted(values.items())
    ]


def _blocked_corporate_microstructure_features(
    *,
    decision_at: str,
) -> list[dict[str, object]]:
    decision = _parse_datetime(decision_at)
    event_at = (decision.date() - timedelta(days=1)).isoformat()
    reason = "official_event_manifest_not_delivered"
    return [
        asdict(
            PITFeatureValue(
                feature_id=feature_id,
                family_id="corporate_microstructure",
                source_id=_CORPORATE_BLOCKED_SOURCE_ID,
                value_int=None,
                scale=1,
                event_at=event_at,
                available_at=decision.isoformat(),
                revision_id=f"missing:{reason}",
                quality="missing",
                content_hash=_sha256_json(
                    {
                        "feature_id": feature_id,
                        "decision_at": decision.isoformat(),
                        "reason": reason,
                        "coverage_bp": 0,
                    }
                ),
                observed=False,
            )
        )
        for feature_id in _CORPORATE_MICROSTRUCTURE_FEATURE_IDS
    ]


def _official_corporate_microstructure_features(
    *,
    decision_at: str,
    symbol: str,
    timeline: _CorporateEventTimeline | None,
) -> list[dict[str, object]]:
    """產生 PIT halt/resume state；非適用或不可證明欄位維持 explicit missing。"""

    if timeline is None:
        return _blocked_corporate_microstructure_features(
            decision_at=decision_at
        )
    decision = _parse_datetime(decision_at)
    decision_year = decision.year
    inactive_feature_ids = tuple(
        sorted(
            set(_CORPORATE_MICROSTRUCTURE_FEATURE_IDS)
            - _CORPORATE_HALT_RESUME_FEATURE_IDS
        )
    )
    missing_features = [
        asdict(
            PITFeatureValue(
                feature_id=feature_id,
                family_id="corporate_microstructure",
                source_id=_CORPORATE_BLOCKED_SOURCE_ID,
                value_int=None,
                scale=1,
                event_at=(decision.date() - timedelta(days=1)).isoformat(),
                available_at=decision.isoformat(),
                revision_id="missing:official_source_not_applicable_to_feature",
                quality="missing",
                content_hash=_sha256_json(
                    {
                        "feature_id": feature_id,
                        "decision_at": decision.isoformat(),
                        "official_manifest_hash": timeline.manifest_hash,
                        "reason": (
                            "official_source_not_applicable_to_feature"
                        ),
                        "result_only_events_feature_allowed": False,
                    }
                ),
                observed=False,
            )
        )
        for feature_id in inactive_feature_ids
    ]
    if decision_year not in timeline.complete_coverage_years:
        missing_features.extend(
            asdict(
                PITFeatureValue(
                    feature_id=feature_id,
                    family_id="corporate_microstructure",
                    source_id=_CORPORATE_OFFICIAL_SOURCE_ID,
                    value_int=None,
                    scale=1,
                    event_at=(
                        decision.date() - timedelta(days=1)
                    ).isoformat(),
                    available_at=decision.isoformat(),
                    revision_id=(
                        "missing:official_halt_resume_year_coverage_incomplete"
                    ),
                    quality="missing",
                    content_hash=_sha256_json(
                        {
                            "feature_id": feature_id,
                            "decision_at": decision.isoformat(),
                            "official_manifest_hash": timeline.manifest_hash,
                            "reason": (
                                "official_halt_resume_year_coverage_incomplete"
                            ),
                        }
                    ),
                    observed=False,
                )
            )
            for feature_id in sorted(
                _CORPORATE_HALT_RESUME_FEATURE_IDS
            )
        )
        return sorted(
            missing_features,
            key=lambda feature: str(feature["feature_id"]),
        )

    causal_events = tuple(
        event
        for event in timeline.events_by_symbol.get(symbol, ())
        if _parse_datetime(event.available_at) <= decision
        and _parse_datetime(event.event_at) <= decision
    )
    ambiguous = tuple(
        event
        for event in causal_events
        if event.revision_availability_ambiguous
    )
    if ambiguous:
        missing_features.extend(
            asdict(
                PITFeatureValue(
                    feature_id=feature_id,
                    family_id="corporate_microstructure",
                    source_id=_CORPORATE_OFFICIAL_SOURCE_ID,
                    value_int=None,
                    scale=1,
                    event_at=ambiguous[-1].event_at,
                    available_at=ambiguous[-1].available_at,
                    revision_id=(
                        "missing:official_halt_resume_revision_ambiguous"
                    ),
                    quality="missing",
                    content_hash=_sha256_json(
                        {
                            "feature_id": feature_id,
                            "decision_at": decision.isoformat(),
                            "official_manifest_hash": timeline.manifest_hash,
                            "ambiguous_event_ids": [
                                event.event_id for event in ambiguous
                            ],
                        }
                    ),
                    observed=False,
                )
            )
            for feature_id in sorted(
                _CORPORATE_HALT_RESUME_FEATURE_IDS
            )
        )
        return sorted(
            missing_features,
            key=lambda feature: str(feature["feature_id"]),
        )

    active = 0
    for event in causal_events:
        active = 1 if event.event_type == "trading_halt" else 0
    if causal_events:
        latest = causal_events[-1]
        event_at = latest.event_at
        available_at = latest.available_at
        revision_id = latest.revision_id
    else:
        event_at = (decision.date() - timedelta(days=1)).isoformat()
        available_at = decision.isoformat()
        revision_id = (
            f"known-no-event:{timeline.manifest_hash}:{decision_year}"
        )
    state_payload = {
        "symbol": symbol,
        "decision_at": decision.isoformat(),
        "official_manifest_hash": timeline.manifest_hash,
        "complete_coverage_year": decision_year,
        "causal_events": [
            {
                "event_id": event.event_id,
                "revision_id": event.revision_id,
                "event_type": event.event_type,
                "event_at": event.event_at,
                "available_at": event.available_at,
                "content_hash": event.content_hash,
            }
            for event in causal_events
        ],
        "active_halt_state": active,
        "known_no_event": not causal_events,
        "result_only_events_feature_allowed": False,
    }
    observed_features = [
        asdict(
            PITFeatureValue(
                feature_id=feature_id,
                family_id="corporate_microstructure",
                source_id=_CORPORATE_OFFICIAL_SOURCE_ID,
                value_int=active,
                scale=1,
                event_at=event_at,
                available_at=available_at,
                revision_id=revision_id,
                quality="observed",
                content_hash=_sha256_json(
                    {
                        **state_payload,
                        "feature_id": feature_id,
                    }
                ),
                observed=True,
            )
        )
        for feature_id in sorted(_CORPORATE_HALT_RESUME_FEATURE_IDS)
    ]
    return sorted(
        [*missing_features, *observed_features],
        key=lambda feature: str(feature["feature_id"]),
    )


def _stream_union_samples(
    *,
    connection: sqlite3.Connection,
    base_manifest_path: Path,
    base_manifest: Mapping[str, Any],
    definitions: Sequence[_FeatureDefinition],
    source_manifest_hashes: tuple[tuple[str, str], ...],
    dataset_identity_hash: str,
    feature_registry_hash: str,
    common_header: Mapping[str, Any],
    research_teacher_targets: Mapping[str, Mapping[str, object]],
    corporate_timeline: _CorporateEventTimeline | None,
    writers: "_TrainingShardWriterRegistry",
    symbols: tuple[str, ...] | None,
    years: tuple[int, ...],
) -> tuple[int, dict[str, object]]:
    root = base_manifest_path.parent.resolve()
    symbol_filter = None if symbols is None else frozenset(symbols)
    year_filter = frozenset(years)
    sample_count = 0
    observed_shadow_values = 0
    missing_shadow_values = 0
    stale_shadow_values = 0
    quality_blocked_shadow_values = 0
    observed_by_family: dict[str, int] = {}
    missing_by_family: dict[str, int] = {}
    nonzero_target_sample_row_count = 0
    nonzero_delta_sample_row_count = 0
    nonzero_risky_budget_sample_row_count = 0
    observed_rule_portfolio_health_value_count = 0
    observed_corporate_microstructure_value_count = 0
    missing_corporate_microstructure_value_count = 0
    for shard in _mapping_sequence(base_manifest.get("shards"), "base.shards"):
        shard_year = int(shard["year"])
        if year_filter and shard_year not in year_filter:
            continue
        shard_path = (root / str(shard["path"])).resolve()
        if not shard_path.is_relative_to(root):
            raise ValueError("base training shard escapes publication")
        if _file_sha256(shard_path) != shard.get("compressed_sha256"):
            raise ValueError("base training shard compressed hash mismatch")
        content_digest = hashlib.sha256()
        base_sample_count = 0
        with gzip.open(shard_path, "rb") as stream:
            header_seen = False
            for line_number, raw_line in enumerate(stream, start=1):
                if not raw_line.strip():
                    continue
                content_digest.update(raw_line)
                try:
                    payload = json.loads(raw_line.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"invalid base training JSONL at "
                        f"{shard_path}:{line_number}"
                    ) from exc
                record = _as_mapping(payload, "base training record")
                if record.get("record_type") == "header":
                    if header_seen or base_sample_count:
                        raise ValueError("base training header is not first")
                    header_seen = True
                    _validate_base_header(record, base_manifest, shard_year)
                    continue
                if record.get("record_type") != "sample" or not header_seen:
                    raise ValueError("invalid base training record order")
                base_sample_count += 1
                sample = dict(_as_mapping(record.get("sample"), "sample"))
                row = dict(_as_mapping(sample.get("row"), "sample.row"))
                symbol = str(row.get("symbol", "")).strip()
                if symbol_filter is not None and symbol not in symbol_filter:
                    continue
                decision_at = _datetime_text(
                    row.get("decision_at"), "row.decision_at"
                )
                decision_year = _parse_datetime(decision_at).year
                if decision_year != shard_year:
                    raise ValueError("base sample year does not match shard")
                _validate_base_row_pit(row, decision_at)
                current = _current_shadow_values(
                    connection,
                    symbol=symbol,
                    decision_at=decision_at,
                    definitions=definitions,
                )
                shadow_features, missing_families, stats = (
                    _shadow_feature_snapshot(
                        decision_at=decision_at,
                        definitions=definitions,
                        current=current,
                    )
                )
                observed_shadow_values += stats["observed"]
                missing_shadow_values += stats["missing"]
                stale_shadow_values += stats["stale"]
                quality_blocked_shadow_values += stats["quality_blocked"]
                for family_id, value in stats["observed_by_family"].items():
                    observed_by_family[family_id] = (
                        observed_by_family.get(family_id, 0) + value
                    )
                for family_id, value in stats["missing_by_family"].items():
                    missing_by_family[family_id] = (
                        missing_by_family.get(family_id, 0) + value
                    )
                base_features = list(
                    _mapping_sequence(row.get("features"), "row.features")
                )
                feature_ids = {
                    str(feature["feature_id"]) for feature in base_features
                }
                for feature in shadow_features:
                    if feature["feature_id"] in feature_ids:
                        raise ValueError("shadow feature collides with formal feature")
                    feature_ids.add(str(feature["feature_id"]))
                    base_features.append(feature)
                rule_state_features = _causal_portfolio_state_features(
                    row=row,
                    decision_at=decision_at,
                    symbol=symbol,
                )
                corporate_features = (
                    _official_corporate_microstructure_features(
                        decision_at=decision_at,
                        symbol=symbol,
                        timeline=corporate_timeline,
                    )
                )
                for feature in (
                    *rule_state_features,
                    *corporate_features,
                ):
                    if feature["feature_id"] in feature_ids:
                        raise ValueError(
                            "fixed research feature collides with source feature"
                        )
                    feature_ids.add(str(feature["feature_id"]))
                    base_features.append(feature)
                observed_rule_portfolio_health_value_count += len(
                    rule_state_features
                )
                observed_corporate_microstructure_value_count += sum(
                    int(feature["observed"] is True)
                    for feature in corporate_features
                )
                missing_corporate_microstructure_value_count += sum(
                    int(feature["observed"] is False)
                    for feature in corporate_features
                )
                base_features.sort(key=lambda feature: str(feature["feature_id"]))
                row["row_id"] = f"research-shadow:{row['row_id']}"
                row["features"] = base_features
                row["missing_family_ids"] = sorted(
                    {
                        *(
                            str(value)
                            for value in row.get("missing_family_ids", ())
                        ),
                        *missing_families,
                        "corporate_microstructure",
                    }
                )
                row["dataset_identity_hash"] = dataset_identity_hash
                row["feature_registry_hash"] = feature_registry_hash
                row["source_manifest_hashes"] = [
                    list(item) for item in source_manifest_hashes
                ]
                decision_date = decision_at[:10]
                research_target = research_teacher_targets.get(
                    decision_date
                )
                if research_target is None:
                    raise ValueError(
                        "research teacher target missing for decision date"
                    )
                row["targets"] = dict(research_target)
                risky_budget = _nonnegative_int(
                    research_target.get("risky_budget_bp"),
                    "research target risky_budget_bp",
                )
                delta_weights = _pair_sequence(
                    research_target.get("delta_weights_bp"),
                    "research target delta_weights_bp",
                )
                target_weights = _as_mapping(
                    research_target.get("target_weights"),
                    "research target weights",
                )
                target_positions = _pair_sequence(
                    target_weights.get("positions_bp"),
                    "research target positions_bp",
                )
                nonzero_target_sample_row_count += int(
                    bool(target_positions)
                )
                nonzero_delta_sample_row_count += int(
                    bool(delta_weights)
                )
                nonzero_risky_budget_sample_row_count += int(
                    risky_budget > 0
                )
                sample["row"] = row
                _validate_union_sample_shape(
                    sample=sample,
                    decision_at=decision_at,
                    expected_feature_ids=feature_ids,
                )
                writers.get(
                    year=decision_year,
                    header={**common_header, "year": decision_year},
                ).write_sample(sample)
                sample_count += 1
        if not header_seen:
            raise ValueError("base training shard has no header")
        if (
            f"sha256:{content_digest.hexdigest()}"
            != shard.get("content_sha256")
        ):
            raise ValueError("base training shard content hash mismatch")
        if base_sample_count != int(shard.get("sample_count", -1)):
            raise ValueError("base training shard sample count mismatch")
    return sample_count, {
        "sample_count": sample_count,
        "observed_shadow_feature_value_count": observed_shadow_values,
        "missing_shadow_feature_value_count": missing_shadow_values,
        "stale_shadow_feature_value_count": stale_shadow_values,
        "quality_blocked_shadow_feature_value_count": (
            quality_blocked_shadow_values
        ),
        "nonzero_target_sample_row_count": (
            nonzero_target_sample_row_count
        ),
        "nonzero_delta_sample_row_count": (
            nonzero_delta_sample_row_count
        ),
        "nonzero_risky_budget_sample_row_count": (
            nonzero_risky_budget_sample_row_count
        ),
        "rule_portfolio_health": {
            "feature_value_count": (
                observed_rule_portfolio_health_value_count
            ),
            "observed_feature_value_count": (
                observed_rule_portfolio_health_value_count
            ),
            "missing_feature_value_count": 0,
            "coverage_bp": 10_000,
            "source": "T_minus_1_causal_portfolio_state",
            "same_day_advice_read": False,
        },
        "corporate_microstructure": {
            "feature_value_count": (
                observed_corporate_microstructure_value_count
                +
                missing_corporate_microstructure_value_count
            ),
            "observed_feature_value_count": (
                observed_corporate_microstructure_value_count
            ),
            "missing_feature_value_count": (
                missing_corporate_microstructure_value_count
            ),
            "coverage_bp": (
                (
                    observed_corporate_microstructure_value_count
                    * 10_000
                )
                // max(
                    1,
                    observed_corporate_microstructure_value_count
                    + missing_corporate_microstructure_value_count,
                )
            ),
            "blocked_reason": (
                None
                if corporate_timeline is not None
                else "official_event_manifest_not_delivered"
            ),
            "official_manifest_hash": (
                corporate_timeline.manifest_hash
                if corporate_timeline is not None
                else None
            ),
            "halt_resume_feature_ids": sorted(
                _CORPORATE_HALT_RESUME_FEATURE_IDS
            ),
            "result_only_event_feature_used": False,
            "known_no_event_zero_requires_complete_coverage": True,
            "zero_imputation_used": False,
        },
        "observed_by_family": {
            key: observed_by_family[key] for key in sorted(observed_by_family)
        },
        "missing_by_family": {
            key: missing_by_family[key] for key in sorted(missing_by_family)
        },
    }


def _validate_base_header(
    header: Mapping[str, Any],
    manifest: Mapping[str, Any],
    year: int,
) -> None:
    if header.get("schema_version") != TRAINING_JSONL_SCHEMA_VERSION:
        raise ValueError("unsupported base training JSONL schema")
    if header.get("direct_training_input") is not True:
        raise ValueError("base training shard is not direct input")
    if header.get("dataset_id") != manifest.get("dataset_id"):
        raise ValueError("base training header dataset id mismatch")
    if header.get("dataset_identity_hash") != manifest.get(
        "dataset_identity_hash"
    ):
        raise ValueError("base training header identity mismatch")
    if int(header.get("year", -1)) != year:
        raise ValueError("base training header year mismatch")


def _validate_base_row_pit(
    row: Mapping[str, Any], decision_at: str
) -> None:
    decision = _parse_datetime(decision_at)
    if not str(row.get("symbol", "")).strip():
        raise ValueError("base training row requires symbol")
    features = _mapping_sequence(row.get("features"), "row.features")
    if not features:
        raise ValueError("base training row has no features")
    ids: set[str] = set()
    for feature in features:
        feature_id = str(feature.get("feature_id", ""))
        if not feature_id or feature_id in ids:
            raise ValueError("base training row has duplicate feature id")
        ids.add(feature_id)
        available = _parse_datetime(
            _datetime_text(
                feature.get("available_at"),
                f"{feature_id}.available_at",
            )
        )
        event = _parse_temporal(
            str(feature.get("event_at", "")),
            f"{feature_id}.event_at",
        )
        if available > decision or event > decision:
            raise ValueError("base training row contains future feature")
        value_int = feature.get("value_int")
        if value_int is not None and (
            isinstance(value_int, bool) or not isinstance(value_int, int)
        ):
            raise TypeError("base feature value_int must be integer or null")
        _positive_int(feature.get("scale"), "base feature scale")


def _current_shadow_values(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    decision_at: str,
    definitions: Sequence[_FeatureDefinition],
) -> dict[str, _CurrentValue]:
    definition_by_id = {
        definition.feature_id: definition for definition in definitions
    }
    rows = connection.execute(
        """
        SELECT * FROM observations
        WHERE symbol=? AND available_at<=? AND event_at<=?
        ORDER BY feature_id, event_at DESC, available_at DESC,
                 revision_id DESC, source_value_hash DESC, sequence_id DESC
        """,
        (symbol, decision_at, decision_at),
    )
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(str(row["feature_id"]), []).append(row)
    result: dict[str, _CurrentValue] = {}
    for feature_id, candidates in grouped.items():
        definition = definition_by_id.get(feature_id)
        if definition is None:
            raise ValueError("spooled shadow feature is absent from registry")
        latest_event = str(candidates[0]["event_at"])
        same_event = [
            row for row in candidates if str(row["event_at"]) == latest_event
        ]
        if definition.source_table == _BROKER_TABLE:
            result[feature_id] = _aggregate_broker_current(
                definition=definition,
                rows=same_event,
            )
        else:
            row = same_event[0]
            result[feature_id] = _row_current_value(row)
    return result


def _row_current_value(row: sqlite3.Row) -> _CurrentValue:
    return _CurrentValue(
        value_int=(
            None if row["value_int"] is None else int(row["value_int"])
        ),
        scale=int(row["scale"]),
        event_at=str(row["event_at"]),
        available_at=str(row["available_at"]),
        revision_id=str(row["revision_id"]),
        quality=str(row["quality"]),
        content_hash=str(row["source_value_hash"]),
        stale_after_days=int(row["stale_after_days"]),
        missing_mask=bool(row["missing_mask"]),
        quality_blocked_mask=bool(row["quality_blocked_mask"]),
    )


def _aggregate_broker_current(
    *,
    definition: _FeatureDefinition,
    rows: Sequence[sqlite3.Row],
) -> _CurrentValue:
    usable = [
        row
        for row in rows
        if row["value_int"] is not None
        and not bool(row["missing_mask"])
        and not bool(row["quality_blocked_mask"])
    ]
    component_hashes = sorted(
        str(row["source_value_hash"]) for row in rows
    )
    content_hash = _sha256_json(
        {
            "feature_id": definition.feature_id,
            "event_at": str(rows[0]["event_at"]),
            "aggregation_policy": definition.aggregation_policy,
            "component_hashes": component_hashes,
        }
    )
    if not usable:
        value_int: int | None = None
    else:
        values = [int(row["value_int"]) for row in usable]
        if definition.aggregation_policy == "max_observed_flag":
            value_int = max(values)
        elif definition.aggregation_policy == "minimum_rank":
            value_int = min(values)
        else:
            value_int = sum(values)
    return _CurrentValue(
        value_int=value_int,
        scale=definition.scale,
        event_at=max(str(row["event_at"]) for row in rows),
        available_at=max(str(row["available_at"]) for row in rows),
        revision_id=f"research-aggregate:{content_hash[7:31]}",
        quality=(
            "degraded"
            if any(
                "degraded" in str(row["quality"]).casefold()
                for row in rows
            )
            else "estimated"
            if any(
                "estimated" in str(row["quality"]).casefold()
                for row in rows
            )
            else "observed"
        ),
        content_hash=content_hash,
        stale_after_days=definition.stale_after_days,
        missing_mask=not usable,
        quality_blocked_mask=not usable and any(
            bool(row["quality_blocked_mask"]) for row in rows
        ),
        component_count=len(rows),
    )


def _shadow_feature_snapshot(
    *,
    decision_at: str,
    definitions: Sequence[_FeatureDefinition],
    current: Mapping[str, _CurrentValue],
) -> tuple[list[dict[str, object]], set[str], dict[str, Any]]:
    decision = _parse_datetime(decision_at)
    features: list[dict[str, object]] = []
    missing_families: set[str] = set()
    family_stats: dict[str, dict[str, int]] = {}
    total_observed = 0
    total_missing = 0
    total_stale = 0
    total_quality_blocked = 0
    for definition in definitions:
        value = current.get(definition.feature_id)
        stale = False
        lag_days = 0
        observed = False
        missing_reason = "not_observed_as_of_decision"
        if value is not None:
            available = _parse_datetime(value.available_at)
            lag_days = max(0, (decision.date() - available.date()).days)
            stale = lag_days > value.stale_after_days
            if value.quality_blocked_mask:
                missing_reason = "quality_blocked"
            elif value.missing_mask or value.value_int is None:
                missing_reason = "source_missing"
            elif stale:
                missing_reason = "stale_at_decision"
            else:
                observed = available <= decision
        stats = family_stats.setdefault(
            definition.family_id,
            {
                "total": 0,
                "observed": 0,
                "missing": 0,
                "stale": 0,
                "quality_blocked": 0,
                "max_available_lag_days": 0,
            },
        )
        stats["total"] += 1
        stats["observed"] += int(observed)
        stats["missing"] += int(not observed)
        stats["stale"] += int(stale)
        stats["quality_blocked"] += int(
            value is not None and value.quality_blocked_mask
        )
        stats["max_available_lag_days"] = max(
            stats["max_available_lag_days"], lag_days
        )
        total_observed += int(observed)
        total_missing += int(not observed)
        total_stale += int(stale)
        total_quality_blocked += int(
            value is not None and value.quality_blocked_mask
        )
        if observed and value is not None and value.value_int is not None:
            quality = _feature_quality(value.quality)
            feature = PITFeatureValue(
                feature_id=definition.feature_id,
                family_id=definition.family_id,
                source_id=definition.source_id,
                value_int=value.value_int,
                scale=value.scale,
                event_at=value.event_at,
                available_at=value.available_at,
                revision_id=value.revision_id,
                quality=quality,
                content_hash=value.content_hash,
                observed=True,
            )
        else:
            missing_families.add(definition.family_id)
            feature = PITFeatureValue(
                feature_id=definition.feature_id,
                family_id=definition.family_id,
                source_id=definition.source_id,
                value_int=None,
                scale=definition.scale,
                event_at=(decision.date() - timedelta(days=1)).isoformat(),
                available_at=decision.isoformat(),
                revision_id=f"missing:{missing_reason}",
                quality="missing",
                content_hash=_sha256_json(
                    {
                        "feature_id": definition.feature_id,
                        "decision_at": decision.isoformat(),
                        "reason": missing_reason,
                        "research_only": True,
                    }
                ),
                observed=False,
            )
        features.append(asdict(feature))

    for family_id, stats in sorted(family_stats.items()):
        total = stats["total"]
        coverage_bp = (
            0
            if total == 0
            else (stats["observed"] * 10_000) // total
        )
        metrics = {
            "coverage_bp": coverage_bp,
            "max_available_lag_days": stats["max_available_lag_days"],
            "missing_count": stats["missing"],
            "quality_blocked_count": stats["quality_blocked"],
            "stale_count": stats["stale"],
        }
        for metric, metric_value in sorted(metrics.items()):
            feature_id = f"data_quality.{family_id}.{metric}"
            content_hash = _sha256_json(
                {
                    "feature_id": feature_id,
                    "decision_at": decision.isoformat(),
                    "value_int": metric_value,
                    "family_stats": stats,
                }
            )
            features.append(
                asdict(
                    PITFeatureValue(
                        feature_id=feature_id,
                        family_id="data_quality",
                        source_id=(
                            "derived:research_shadow_feature_quality"
                        ),
                        value_int=metric_value,
                        scale=1,
                        event_at=(
                            decision.date() - timedelta(days=1)
                        ).isoformat(),
                        available_at=decision.isoformat(),
                        revision_id=content_hash,
                        quality="observed",
                        content_hash=content_hash,
                        observed=True,
                    )
                )
            )
    features.sort(key=lambda feature: str(feature["feature_id"]))
    return features, missing_families, {
        "observed": total_observed,
        "missing": total_missing,
        "stale": total_stale,
        "quality_blocked": total_quality_blocked,
        "observed_by_family": {
            family_id: stats["observed"]
            for family_id, stats in sorted(family_stats.items())
        },
        "missing_by_family": {
            family_id: stats["missing"]
            for family_id, stats in sorted(family_stats.items())
        },
    }


def _validate_union_sample_shape(
    *,
    sample: Mapping[str, Any],
    decision_at: str,
    expected_feature_ids: set[str],
) -> None:
    row = _as_mapping(sample.get("row"), "union sample row")
    features = _mapping_sequence(row.get("features"), "union features")
    ids = [str(feature.get("feature_id", "")) for feature in features]
    if len(ids) != len(set(ids)) or set(ids) != expected_feature_ids:
        raise ValueError("union sample feature identity mismatch")
    decision = _parse_datetime(decision_at)
    for feature in features:
        value_int = feature.get("value_int")
        if value_int is not None and (
            isinstance(value_int, bool) or not isinstance(value_int, int)
        ):
            raise TypeError("union feature value_int must be integer or null")
        if _parse_datetime(
            _datetime_text(feature.get("available_at"), "available_at")
        ) > decision:
            raise ValueError("union feature uses future availability")
        if _parse_temporal(
            str(feature.get("event_at", "")), "event_at"
        ) > decision:
            raise ValueError("union feature uses future event")


def _base_label_policy(
    manifest_path: Path, manifest: Mapping[str, Any]
) -> Mapping[str, Any]:
    shards = _mapping_sequence(manifest.get("shards"), "base.shards")
    if not shards:
        raise ValueError("base training manifest has no shards")
    first_path = (manifest_path.parent / str(shards[0]["path"])).resolve()
    with gzip.open(first_path, "rt", encoding="utf-8") as stream:
        header = _as_mapping(json.loads(next(stream)), "base header")
    return _as_mapping(header.get("label_policy"), "base.label_policy")


def _broker_aggregation_policy(feature_id: str) -> str:
    column = feature_id.rsplit(".", 1)[-1]
    if column in {"amount_observed", "lots_observed"}:
        return "max_observed_flag"
    if column in {"amount_rank", "lots_rank"}:
        return "minimum_rank"
    return "sum_same_symbol_event_components"


def _feature_quality(
    value: str,
) -> Literal["observed", "estimated", "degraded"]:
    normalized = value.casefold()
    if "estimated" in normalized:
        return "estimated"
    if "degraded" in normalized:
        return "degraded"
    return "observed"


def _feature_pack_count(
    packs: Sequence[Mapping[str, object]],
) -> int:
    count = 0
    for pack in packs:
        feature_ids = pack.get("feature_ids")
        if not isinstance(feature_ids, (list, tuple)):
            raise TypeError("feature pack ids must be an array")
        count += len(feature_ids)
    return count


class _TrainingShardWriter:
    def __init__(
        self,
        *,
        path: Path,
        year: int,
        header: Mapping[str, Any],
        compression_level: int,
    ) -> None:
        self.path = path
        self.year = year
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._raw = self.path.open("wb")
        self._gzip = gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=compression_level,
            fileobj=self._raw,
            mtime=0,
        )
        self._content_digest = hashlib.sha256()
        self._closed = False
        self.sample_count = 0
        self.min_decision_date: str | None = None
        self.max_decision_date: str | None = None
        self._write_record(header)

    def write_sample(self, sample: Mapping[str, Any]) -> None:
        self._write_record({"record_type": "sample", "sample": sample})
        row = _as_mapping(sample.get("row"), "sample.row")
        decision_date = str(row["decision_at"])[:10]
        self.sample_count += 1
        self.min_decision_date = (
            decision_date
            if self.min_decision_date is None
            else min(self.min_decision_date, decision_date)
        )
        self.max_decision_date = (
            decision_date
            if self.max_decision_date is None
            else max(self.max_decision_date, decision_date)
        )

    def _write_record(self, payload: Mapping[str, Any]) -> None:
        encoded = (_canonical_json(payload) + "\n").encode("utf-8")
        self._gzip.write(encoded)
        self._content_digest.update(encoded)

    def close(self) -> None:
        if self._closed:
            return
        self._gzip.close()
        self._raw.flush()
        os.fsync(self._raw.fileno())
        self._raw.close()
        self._closed = True

    def manifest_payload(self, *, staging: Path) -> dict[str, Any]:
        self.close()
        return {
            "year": self.year,
            "path": self.path.relative_to(staging).as_posix(),
            "format": "gzip_jsonl",
            "schema_version": TRAINING_JSONL_SCHEMA_VERSION,
            "compressed_sha256": _file_sha256(self.path),
            "content_sha256": f"sha256:{self._content_digest.hexdigest()}",
            "compressed_bytes": self.path.stat().st_size,
            "sample_count": self.sample_count,
            "min_decision_date": self.min_decision_date,
            "max_decision_date": self.max_decision_date,
            "direct_training_input": True,
            "research_only": True,
            "promotion_eligible": False,
        }


class _TrainingShardWriterRegistry:
    def __init__(self, *, staging: Path, compression_level: int) -> None:
        self._staging = staging
        self._compression_level = compression_level
        self._writers: dict[int, _TrainingShardWriter] = {}

    def get(
        self, *, year: int, header: Mapping[str, Any]
    ) -> _TrainingShardWriter:
        writer = self._writers.get(year)
        if writer is None:
            writer = _TrainingShardWriter(
                path=self._staging / f"year={year:04d}.jsonl.gz",
                year=year,
                header=header,
                compression_level=self._compression_level,
            )
            self._writers[year] = writer
        return writer

    def close_all(self) -> None:
        for writer in self._writers.values():
            writer.close()

    def manifest_payloads(self, *, staging: Path) -> list[dict[str, Any]]:
        return [
            writer.manifest_payload(staging=staging)
            for _, writer in sorted(self._writers.items())
        ]


def _mapping_sequence(
    value: Any, field_name: str
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be an array")
    return tuple(_as_mapping(item, f"{field_name}[]") for item in value)


def _pair_sequence(
    value: Any, field_name: str
) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be an array")
    result: list[tuple[str, int]] = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise TypeError(f"{field_name} entries must be pairs")
        symbol = item[0]
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError(f"{field_name} symbols must be non-empty")
        result.append(
            (
                symbol,
                _integer(item[1], f"{field_name}[{symbol}]"),
            )
        )
    if len({symbol for symbol, _ in result}) != len(result):
        raise ValueError(f"{field_name} symbols must be unique")
    return tuple(result)


def _as_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be an object")
    return value


def _json_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be bool")
    return value


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TypeError(f"{field_name} must be a positive integer")
    return value


def _nonnegative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TypeError(f"{field_name} must be a non-negative integer")
    return value


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    return value


def _sha256_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise ValueError(f"{field_name} must use sha256")
    digest = value[7:]
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError(f"{field_name} must contain lowercase SHA-256")
    return value


def _datetime_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    parsed = _parse_datetime(value)
    return parsed.isoformat()


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("PIT timestamps must be timezone-aware")
    return parsed.astimezone(_TAIPEI)


def _parse_temporal(value: str, field_name: str) -> datetime:
    try:
        return _parse_datetime(value)
    except ValueError:
        try:
            return datetime.combine(
                date.fromisoformat(value),
                datetime.min.time(),
                tzinfo=_TAIPEI,
            )
        except ValueError as exc:
            raise ValueError(f"{field_name} must be ISO date/timestamp") from exc


def _normalized_years(values: Iterable[int]) -> tuple[int, ...]:
    normalized: set[int] = set()
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("years must contain integers")
        if not 1900 <= value <= 9999:
            raise ValueError("years must be within 1900..9999")
        normalized.add(value)
    return tuple(sorted(normalized))


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_json(payload: object) -> str:
    return (
        "sha256:"
        + hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON: {path}") from exc
    return _as_mapping(decoded, str(path))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    _write_json(temporary, payload)
    os.replace(temporary, path)


def _safe_remove_tree(path: Path, output_root: Path) -> None:
    resolved = path.resolve()
    root = output_root.resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError("refusing to remove path outside output root")
    if not resolved.name.startswith(
        (".research-union-", ".research-union-spool-")
    ):
        raise ValueError("refusing to remove non-staging research path")
    shutil.rmtree(resolved)
