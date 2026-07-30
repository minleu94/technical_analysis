"""建立配置型 ML 的 consumer-compatible promotion evidence。

本模組的權限刻意小於 Promotion Authority：

* 只讀正式 out-of-core model/dataset/OOF 與兩次獨立 portfolio replay。
* 只讀 Shadow sidecar 中「每個 decision date 的最新 revision」及其最新 outcome。
* 只讀 frozen promotion reference 與逐 horizon calibration/drift metrics。
* 完整時發布 :class:`~ml_module.allocation_validation.AllocationPromotionEvidence`
  可讀的 immutable artifact；不完整或 custody 不一致時只回傳 blockers。
* 不建立 HMAC、不選 production alpha、不寫 ``formal_oos_allowed``，也不具券商
  送單權限。

所有公開金融度量皆為整數 bp；本模組不以 ``float`` 表示報酬、風險、覆蓋率或
權重。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Mapping, Sequence, cast

from ml_module.allocation_validation import (
    ALPHA_LANES,
    AllocationFoldEvidence,
    AllocationPromotionEvidence,
    AlphaLaneEvidence,
)
from ml_module.allocation_promotion_reference import (
    OUTCOME_CONTRACT_HASH,
    OUTCOME_CONTRACT_VERSION,
    _validate_downside_outcome_source_custody,
)


BUILDER_RESULT_SCHEMA_VERSION = (
    "allocation-promotion-evidence-builder-result.v1"
)
POINTER_SCHEMA_VERSION = "allocation-promotion-evidence-pointer.v1"
PUBLICATION_SCHEMA_VERSION = "allocation-promotion-evidence-publication.v1"
EVIDENCE_SCHEMA_VERSION = "allocation-promotion-evidence.v1"
OOF_BUNDLE_SCHEMA_VERSION = "allocation-promotion-oof-custody.v1"
REPLAY_BUNDLE_SCHEMA_VERSION = "allocation-promotion-replay-custody.v1"
SHADOW_BUNDLE_SCHEMA_VERSION = "allocation-promotion-shadow-custody.v1"
FORMAL_REPLAY_SCHEMA_VERSION = "allocation-ooc-portfolio-replay.v1"
FORMAL_SEMANTIC_VERIFICATION_SCHEMA_VERSION = (
    "allocation-oos-semantic-verification.v1"
)
FORMAL_SEMANTIC_VERIFIER_ID = "allocation-oos-semantic-verifier-v1"
OOC_TRAINING_SCHEMA_VERSION = "allocation-ooc-training.v5"
OOC_EXPERT_SCHEMA_VERSION = "allocation-ooc-expert.v5"
OOC_META_SCHEMA_VERSION = "allocation-ooc-meta.v3"
OOC_STORE_SCHEMA_VERSION = "portfolio-ml-ooc-store.v3"
PROMOTION_POLICY_ID = "allocation-promotion-v4"
REQUIRED_HORIZONS = (5, 10, 20, 60)
MINIMUM_MATURED_DAYS = 20
MINIMUM_OUTER_FOLDS = 4
MINIMUM_META_OOF_FOLDS = 4
_SHA256_PREFIX = "sha256:"


@dataclass(frozen=True)
class AllocationPromotionEvidenceBuildRequest:
    """Builder 的全部輸入；所有 path 都是 read-only custody input。"""

    experiment_id: str
    decision_at: datetime
    as_of_date: date
    training_manifest_path: Path
    dataset_manifest_path: Path
    replay_primary_path: Path
    replay_verification_path: Path
    shadow_sidecar_database_path: Path
    promotion_reference_path: Path
    promotion_reference_metrics_path: Path
    output_root: Path
    expected_promotion_reference_file_hash: str | None = None
    minimum_matured_days: int = MINIMUM_MATURED_DAYS

    def __post_init__(self) -> None:
        _required_text(self.experiment_id, "experiment_id")
        if (
            not isinstance(self.decision_at, datetime)
            or self.decision_at.tzinfo is None
            or self.decision_at.utcoffset() is None
        ):
            raise ValueError("decision_at must be timezone-aware")
        if not isinstance(self.as_of_date, date):
            raise TypeError("as_of_date must be a date")
        if self.as_of_date > self.decision_at.date():
            raise ValueError("as_of_date must not be after decision_at")
        if (
            isinstance(self.minimum_matured_days, bool)
            or not isinstance(self.minimum_matured_days, int)
            or self.minimum_matured_days < MINIMUM_MATURED_DAYS
        ):
            raise ValueError("minimum_matured_days must be at least 20")
        if self.expected_promotion_reference_file_hash is not None:
            _required_sha256(
                self.expected_promotion_reference_file_hash,
                "expected_promotion_reference_file_hash",
            )


@dataclass(frozen=True)
class AllocationPromotionEvidenceBuildResult:
    """可直接序列化給 scheduler / Promotion Authority 的結果。"""

    status: str
    decision_at: str
    as_of_date: str
    blockers: tuple[str, ...]
    publication_id: str | None = None
    publication_hash: str | None = None
    publication_file_hash: str | None = None
    evidence_hash: str | None = None
    evidence_file_hash: str | None = None
    pointer_hash: str | None = None
    promotion_evidence_path: Path | None = None
    model_artifact_path: Path | None = None
    dataset_manifest_path: Path | None = None
    oof_bundle_path: Path | None = None
    shadow_evidence_path: Path | None = None
    replay_bundle_path: Path | None = None
    promotion_reference_path: Path | None = None
    promotion_reference_metrics_path: Path | None = None
    latest_pointer_path: Path | None = None
    idempotent: bool = False

    def __post_init__(self) -> None:
        if self.status not in {"published", "blocked"}:
            raise ValueError("status must be published or blocked")
        if self.status == "blocked":
            if not self.blockers:
                raise ValueError("blocked result requires blockers")
            if any(
                value is not None
                for value in (
                    self.publication_id,
                    self.publication_hash,
                    self.publication_file_hash,
                    self.evidence_hash,
                    self.evidence_file_hash,
                    self.pointer_hash,
                    self.promotion_evidence_path,
                    self.model_artifact_path,
                    self.dataset_manifest_path,
                    self.oof_bundle_path,
                    self.shadow_evidence_path,
                    self.replay_bundle_path,
                    self.promotion_reference_path,
                    self.promotion_reference_metrics_path,
                    self.latest_pointer_path,
                )
            ):
                raise ValueError("blocked result cannot expose compatible paths")
        elif self.blockers:
            raise ValueError("published result cannot contain blockers")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": BUILDER_RESULT_SCHEMA_VERSION,
            "status": self.status,
            "decision_at": self.decision_at,
            "as_of_date": self.as_of_date,
            "blockers": list(self.blockers),
            "publication_id": self.publication_id,
            "publication_hash": self.publication_hash,
            "publication_file_hash": self.publication_file_hash,
            "evidence_hash": self.evidence_hash,
            "evidence_file_hash": self.evidence_file_hash,
            "pointer_hash": self.pointer_hash,
            "promotion_evidence_path": _path_text(
                self.promotion_evidence_path
            ),
            "model_artifact_path": _path_text(self.model_artifact_path),
            "dataset_manifest_path": _path_text(
                self.dataset_manifest_path
            ),
            "oof_bundle_path": _path_text(self.oof_bundle_path),
            "shadow_evidence_path": _path_text(
                self.shadow_evidence_path
            ),
            "replay_bundle_path": _path_text(self.replay_bundle_path),
            "promotion_reference_path": _path_text(
                self.promotion_reference_path
            ),
            "promotion_reference_metrics_path": _path_text(
                self.promotion_reference_metrics_path
            ),
            "latest_pointer_path": _path_text(self.latest_pointer_path),
            "idempotent": self.idempotent,
            "authority_required": True,
            "authorization_artifact_created": False,
        }


class _BlockedEvidence(ValueError):
    def __init__(self, blocker: str) -> None:
        super().__init__(blocker)
        self.blocker = blocker


@dataclass(frozen=True)
class _FormalCustody:
    training: Mapping[str, object]
    dataset: Mapping[str, object]
    training_manifest_file_hash: str
    dataset_manifest_file_hash: str
    model_artifact_path: Path
    model_artifact_hash: str
    model_id: str
    dataset_id: str
    dataset_identity_hash: str
    outer_fold_ids: tuple[str, ...]
    oof_bundle: Mapping[str, object]
    oof_source_hash: str


@dataclass(frozen=True)
class _ReplayCustody:
    primary: Mapping[str, object]
    verification: Mapping[str, object]
    result_hash: str
    lanes: tuple[Mapping[str, object], ...]
    bundle: Mapping[str, object]


@dataclass(frozen=True)
class _ReferenceMetrics:
    reference: Mapping[str, object]
    metrics: Mapping[str, object]
    reference_hash: str
    reference_file_hash: str
    metrics_hash: str
    metrics_file_hash: str
    calibration_ece_bp: int
    calibrated_brier_bp: int
    uncalibrated_brier_bp: int
    psi_bp: int
    horizon_metrics: tuple[Mapping[str, object], ...]


@dataclass(frozen=True)
class _ShadowCustody:
    bundle: Mapping[str, object]
    matured_days: int


def build_compatible_allocation_promotion_evidence(
    request: AllocationPromotionEvidenceBuildRequest,
) -> AllocationPromotionEvidenceBuildResult:
    """驗證全部 custody 後發布 compatible evidence；不足時不寫 artifact。"""

    decision_at = request.decision_at.isoformat(timespec="seconds")
    as_of_text = request.as_of_date.isoformat()
    try:
        formal = _load_formal_custody(request)
        reference = _load_reference_metrics(request, formal=formal)
        shadow = _load_shadow_custody(
            request,
            formal=formal,
            reference=reference,
        )
        replay = _load_replay_custody(request, formal=formal)
        lanes = _build_alpha_lanes(
            replay=replay,
            reference=reference,
            matured_days=shadow.matured_days,
        )
        return _publish(
            request,
            formal=formal,
            replay=replay,
            reference=reference,
            shadow=shadow,
            lanes=lanes,
        )
    except _BlockedEvidence as exc:
        return AllocationPromotionEvidenceBuildResult(
            status="blocked",
            decision_at=decision_at,
            as_of_date=as_of_text,
            blockers=(exc.blocker,),
        )
    except (OSError, sqlite3.Error, UnicodeError, json.JSONDecodeError) as exc:
        return AllocationPromotionEvidenceBuildResult(
            status="blocked",
            decision_at=decision_at,
            as_of_date=as_of_text,
            blockers=(
                f"promotion_evidence_input_unreadable:{type(exc).__name__}",
            ),
        )
    except (TypeError, ValueError, KeyError) as exc:
        return AllocationPromotionEvidenceBuildResult(
            status="blocked",
            decision_at=decision_at,
            as_of_date=as_of_text,
            blockers=(
                "promotion_evidence_input_invalid:"
                f"{type(exc).__name__}:{_safe_reason(exc)}",
            ),
        )


def _load_formal_custody(
    request: AllocationPromotionEvidenceBuildRequest,
) -> _FormalCustody:
    training_path = request.training_manifest_path.resolve()
    dataset_path = request.dataset_manifest_path.resolve()
    _require_file(training_path, "training_manifest_missing")
    _require_file(dataset_path, "dataset_manifest_missing")
    training = _read_json_mapping(training_path, "training_manifest")
    dataset = _read_json_mapping(dataset_path, "dataset_manifest")

    if training.get("schema_version") != OOC_TRAINING_SCHEMA_VERSION:
        _blocked("training_manifest_not_formal_ooc_v5")
    if training.get("status") != "complete":
        _blocked("training_manifest_incomplete")
    _require_formal_lane(training, "training_manifest")
    _verify_logical_hash(
        training,
        hash_field="manifest_hash",
        blocker="training_manifest_logical_hash_mismatch",
    )
    training_file_hash = _file_hash(training_path)

    if dataset.get("schema_version") != OOC_STORE_SCHEMA_VERSION:
        _blocked("dataset_manifest_not_formal_ooc_v3")
    if dataset.get("status") != "complete":
        _blocked("dataset_manifest_incomplete")
    _require_formal_lane(dataset, "dataset_manifest")
    _verify_logical_hash(
        dataset,
        hash_field="manifest_hash",
        blocker="dataset_manifest_logical_hash_mismatch",
    )
    dataset_file_hash = _file_hash(dataset_path)
    if training.get("store_manifest_file_hash") != dataset_file_hash:
        _blocked("training_dataset_manifest_file_hash_mismatch")
    store_relative = _required_text(
        training.get("store_manifest_path"),
        "training_manifest.store_manifest_path",
    )
    # OOC training run 與 numeric store 通常位於不同 release_v4 子樹；
    # training manifest 的相對路徑可合法包含 ``..``。安全性由呼叫端明確提供、
    # 已 resolve 的 dataset manifest path 加上實體 hash/identity 比對負責。
    expected_store_path = (
        Path(store_relative).resolve()
        if Path(store_relative).is_absolute()
        else (training_path.parent / store_relative).resolve()
    )
    if expected_store_path != dataset_path:
        _blocked("training_dataset_manifest_path_mismatch")

    dataset_identity_hash = _required_sha256(
        dataset.get("dataset_identity_hash"),
        "dataset_identity_hash",
    )
    if training.get("dataset_identity_hash") != dataset_identity_hash:
        _blocked("training_dataset_identity_hash_mismatch")
    dataset_id = _required_text(dataset.get("dataset_id"), "dataset_id")

    readiness_value = dataset.get("readiness")
    if readiness_value is None:
        readiness_value = dataset.get("execution")
    readiness = _required_mapping(
        readiness_value,
        "dataset_manifest.readiness_or_execution",
    )
    if readiness.get("full_market_ready") is not True:
        _blocked("formal_ooc_dataset_full_market_not_ready")
    safety = _required_mapping(dataset.get("safety"), "dataset_manifest.safety")
    if safety.get("pit_contract_revalidated_per_row") is not True:
        _blocked("formal_ooc_dataset_pit_not_revalidated")
    if safety.get("t_minus_1_contract_revalidated_per_row") is not True:
        _blocked("formal_ooc_dataset_t_minus_one_not_revalidated")

    validation = _required_mapping(
        training.get("validation"),
        "training_manifest.validation",
    )
    for field_name in (
        "pit_violation_count",
        "future_prefix_violation_count",
        "constraint_violation_count",
    ):
        if _required_nonnegative_int(
            validation.get(field_name),
            f"training_manifest.validation.{field_name}",
        ) != 0:
            _blocked(f"formal_ooc_training_{field_name}_nonzero")
    if validation.get("deterministic_custody") is not True:
        _blocked("formal_ooc_training_deterministic_custody_missing")

    outer_folds = _mapping_sequence(dataset.get("folds"), "dataset.folds")
    outer_fold_ids = tuple(
        _required_text(item.get("fold_id"), "fold.fold_id")
        for item in outer_folds
    )
    if (
        len(outer_fold_ids) < MINIMUM_OUTER_FOLDS
        or len(outer_fold_ids) != len(set(outer_fold_ids))
    ):
        _blocked(
            "formal_ooc_outer_folds_incomplete:"
            f"{len(set(outer_fold_ids))}/{MINIMUM_OUTER_FOLDS}"
        )
    if _required_int(training.get("fold_count"), "training.fold_count") != len(
        outer_fold_ids
    ):
        _blocked("training_dataset_outer_fold_count_mismatch")

    final_meta = _required_mapping(
        training.get("final_meta"),
        "training_manifest.final_meta",
    )
    model_directory = _contained_path(
        training_path.parent,
        _required_text(
            final_meta.get("artifact_path"),
            "training_manifest.final_meta.artifact_path",
        ),
        blocker="final_model_artifact_path_escapes_run",
    )
    final_model_manifest_path = model_directory / "manifest.json"
    _require_file(final_model_manifest_path, "final_model_artifact_missing")
    model_manifest = _validate_model_artifact_directory(
        model_directory,
        expected_schema=OOC_META_SCHEMA_VERSION,
        blocker_prefix="final_model",
    )
    if model_manifest.get("artifact_kind") != "final_meta_allocator":
        _blocked("final_model_artifact_kind_mismatch")
    # OOC model 是一組 final base experts + final meta，而非單一 joblib。
    # training manifest 是這個 model suite 的正式實體 manifest，會遞迴綁定
    # 每個 artifact manifest/file hash；Promotion consumer 也應 rehash 此檔。
    model_artifact_path = training_path
    model_artifact_hash = training_file_hash
    model_id = _required_text(training.get("run_id"), "training.run_id")

    oof_entries: list[dict[str, object]] = []
    observed_base_folds: set[str] = set()
    base_experts = _mapping_sequence(
        training.get("base_experts"),
        "training_manifest.base_experts",
    )
    expected_base_count = _required_int(
        training.get("base_expert_count"),
        "training_manifest.base_expert_count",
    )
    if expected_base_count != len(base_experts) or not base_experts:
        _blocked("formal_ooc_base_expert_coverage_incomplete")
    for index, summary in enumerate(base_experts):
        fold_id = _required_text(summary.get("fold_id"), f"base[{index}].fold_id")
        observed_base_folds.add(fold_id)
        directory = _contained_path(
            training_path.parent,
            _required_text(
                summary.get("artifact_path"),
                f"base[{index}].artifact_path",
            ),
            blocker="base_oof_artifact_path_escapes_run",
        )
        manifest = _validate_model_artifact_directory(
            directory,
            expected_schema=OOC_EXPERT_SCHEMA_VERSION,
            blocker_prefix=f"base_oof:{fold_id}",
        )
        oof_entries.append(
            _oof_entry(
                directory=directory,
                manifest=manifest,
                kind="base",
            )
        )
    if observed_base_folds != set(outer_fold_ids):
        _blocked("formal_ooc_base_oof_fold_coverage_incomplete")

    meta_entries: list[dict[str, object]] = []
    observed_meta_folds: set[str] = set()
    for index, summary in enumerate(
        _mapping_sequence(
            training.get("meta_folds"),
            "training_manifest.meta_folds",
        )
    ):
        directory = _contained_path(
            training_path.parent,
            _required_text(
                summary.get("artifact_path"),
                f"meta[{index}].artifact_path",
            ),
            blocker="meta_oof_artifact_path_escapes_run",
        )
        manifest = _validate_model_artifact_directory(
            directory,
            expected_schema=OOC_META_SCHEMA_VERSION,
            blocker_prefix=f"meta_oof:{index}",
        )
        fold_id = _required_text(
            manifest.get("fold_id"),
            f"meta_oof[{index}].fold_id",
        )
        if fold_id in observed_meta_folds:
            _blocked("formal_ooc_meta_oof_fold_duplicate")
        observed_meta_folds.add(fold_id)
        meta_entries.append(
            _oof_entry(
                directory=directory,
                manifest=manifest,
                kind="meta",
            )
        )
    if (
        len(observed_meta_folds) < MINIMUM_META_OOF_FOLDS
        or not observed_meta_folds.issubset(set(outer_fold_ids))
    ):
        _blocked(
            "formal_ooc_meta_oof_fold_coverage_incomplete:"
            f"{len(observed_meta_folds)}/{MINIMUM_META_OOF_FOLDS}"
        )

    oof_body: dict[str, object] = {
        "schema_version": OOF_BUNDLE_SCHEMA_VERSION,
        "training_manifest_hash": _required_sha256(
            training.get("manifest_hash"),
            "training.manifest_hash",
        ),
        "training_manifest_file_hash": training_file_hash,
        "model_artifact_hash": model_artifact_hash,
        "dataset_id": dataset_id,
        "dataset_identity_hash": dataset_identity_hash,
        "dataset_manifest_file_hash": dataset_file_hash,
        "outer_fold_ids": list(outer_fold_ids),
        "base_oof_artifacts": sorted(
            oof_entries,
            key=lambda item: (
                str(item["fold_id"]),
                str(item.get("expert_id", "")),
            ),
        ),
        "meta_oof_artifacts": sorted(
            meta_entries,
            key=lambda item: str(item["fold_id"]),
        ),
        "formal_source_only": True,
        "research_shadow_included": False,
    }
    oof_source_hash = _payload_hash(oof_body)
    oof_bundle = {**oof_body, "oof_source_hash": oof_source_hash}
    return _FormalCustody(
        training=training,
        dataset=dataset,
        training_manifest_file_hash=training_file_hash,
        dataset_manifest_file_hash=dataset_file_hash,
        model_artifact_path=model_artifact_path,
        model_artifact_hash=model_artifact_hash,
        model_id=model_id,
        dataset_id=dataset_id,
        dataset_identity_hash=dataset_identity_hash,
        outer_fold_ids=outer_fold_ids,
        oof_bundle=oof_bundle,
        oof_source_hash=oof_source_hash,
    )


def _load_replay_custody(
    request: AllocationPromotionEvidenceBuildRequest,
    *,
    formal: _FormalCustody,
) -> _ReplayCustody:
    paths = (
        ("primary", request.replay_primary_path.resolve()),
        ("verification", request.replay_verification_path.resolve()),
    )
    loaded: list[tuple[str, Path, Mapping[str, object]]] = []
    expected_input = {
        "training_manifest_file_hash": formal.training_manifest_file_hash,
        "model_artifact_hash": formal.model_artifact_hash,
        "dataset_identity_hash": formal.dataset_identity_hash,
        "dataset_manifest_file_hash": formal.dataset_manifest_file_hash,
        "oof_source_hash": formal.oof_source_hash,
    }
    for label, path in paths:
        _require_file(path, f"formal_replay_{label}_missing")
        replay = _read_json_mapping(path, f"formal_replay_{label}")
        if replay.get("schema_version") != FORMAL_REPLAY_SCHEMA_VERSION:
            _blocked(f"formal_replay_{label}_schema_mismatch")
        if replay.get("status") != "complete":
            _blocked(f"formal_replay_{label}_incomplete")
        _require_formal_lane(replay, f"formal_replay_{label}")
        semantic_validation = _required_mapping(
            replay.get("formal_semantic_validation"),
            f"formal_replay_{label}.formal_semantic_validation",
        )
        if (
            semantic_validation.get("schema_version")
            != FORMAL_SEMANTIC_VERIFICATION_SCHEMA_VERSION
            or semantic_validation.get("verifier_id")
            != FORMAL_SEMANTIC_VERIFIER_ID
        ):
            _blocked(f"formal_replay_{label}_semantic_verifier_mismatch")
        semantic_blockers = _required_sequence(
            semantic_validation.get("blockers"),
            f"formal_replay_{label}.formal_semantic_validation.blockers",
        )
        if (
            semantic_validation.get("verified") is not True
            or replay.get("promotion_eligible_input") is not True
            or semantic_blockers
        ):
            _blocked(f"formal_replay_{label}_semantic_validation_incomplete")
        _verify_logical_hash(
            replay,
            hash_field="manifest_hash",
            blocker=f"formal_replay_{label}_logical_hash_mismatch",
        )
        custody = _required_mapping(
            replay.get("input_custody"),
            f"formal_replay_{label}.input_custody",
        )
        if dict(custody) != expected_input:
            _blocked(f"formal_replay_{label}_input_custody_mismatch")
        lanes = _normalize_replay_lanes(
            replay.get("lanes"),
            expected_fold_ids=formal.outer_fold_ids,
            label=label,
        )
        expected_result_hash = _payload_hash(
            {
                "input_custody": expected_input,
                "lanes": list(lanes),
            }
        )
        if replay.get("replay_result_hash") != expected_result_hash:
            _blocked(f"formal_replay_{label}_result_hash_mismatch")
        loaded.append((label, path, replay))

    primary = loaded[0][2]
    verification = loaded[1][2]
    primary_run_id = _required_text(
        primary.get("replay_run_id"),
        "primary.replay_run_id",
    )
    verification_run_id = _required_text(
        verification.get("replay_run_id"),
        "verification.replay_run_id",
    )
    if primary_run_id == verification_run_id:
        _blocked("formal_replay_independent_run_ids_required")
    primary_result_hash = _required_sha256(
        primary.get("replay_result_hash"),
        "primary.replay_result_hash",
    )
    verification_result_hash = _required_sha256(
        verification.get("replay_result_hash"),
        "verification.replay_result_hash",
    )
    if primary_result_hash != verification_result_hash:
        _blocked("deterministic_replay_hash_mismatch")
    primary_lanes = _normalize_replay_lanes(
        primary.get("lanes"),
        expected_fold_ids=formal.outer_fold_ids,
        label="primary",
    )
    verification_lanes = _normalize_replay_lanes(
        verification.get("lanes"),
        expected_fold_ids=formal.outer_fold_ids,
        label="verification",
    )
    if primary_lanes != verification_lanes:
        _blocked("deterministic_replay_payload_mismatch")
    bundle_body: dict[str, object] = {
        "schema_version": REPLAY_BUNDLE_SCHEMA_VERSION,
        "input_custody": expected_input,
        "primary": {
            "replay_run_id": primary_run_id,
            "manifest_hash": primary["manifest_hash"],
            "file_hash": _file_hash(loaded[0][1]),
        },
        "verification": {
            "replay_run_id": verification_run_id,
            "manifest_hash": verification["manifest_hash"],
            "file_hash": _file_hash(loaded[1][1]),
        },
        "replay_result_hash": primary_result_hash,
        "independent_replay_count": 2,
    }
    return _ReplayCustody(
        primary=primary,
        verification=verification,
        result_hash=primary_result_hash,
        lanes=primary_lanes,
        bundle={
            **bundle_body,
            "bundle_hash": _payload_hash(bundle_body),
        },
    )


def _load_reference_metrics(
    request: AllocationPromotionEvidenceBuildRequest,
    *,
    formal: _FormalCustody,
) -> _ReferenceMetrics:
    reference_path = request.promotion_reference_path.resolve()
    metrics_path = request.promotion_reference_metrics_path.resolve()
    _require_file(reference_path, "promotion_reference_missing")
    _require_file(metrics_path, "promotion_reference_metrics_missing")
    reference_file_hash = _file_hash(reference_path)
    if (
        request.expected_promotion_reference_file_hash is not None
        and reference_file_hash
        != request.expected_promotion_reference_file_hash
    ):
        _blocked("promotion_reference_file_hash_mismatch")
    reference = _read_json_mapping(reference_path, "promotion_reference")
    if not str(reference.get("schema_version", "")).startswith(
        "ml-allocation-promotion-reference-v"
    ):
        _blocked("promotion_reference_schema_mismatch")
    _verify_logical_hash(
        reference,
        hash_field="reference_hash",
        blocker="promotion_reference_logical_hash_mismatch",
    )
    reference_hash = _required_sha256(
        reference.get("reference_hash"),
        "reference.reference_hash",
    )
    custody = _required_mapping(
        reference.get("custody"),
        "promotion_reference.custody",
    )
    expected = {
        "model_artifact_hash": formal.model_artifact_hash,
        "training_manifest_file_hash": formal.training_manifest_file_hash,
        "dataset_identity_hash": formal.dataset_identity_hash,
        "dataset_manifest_file_hash": formal.dataset_manifest_file_hash,
    }
    for field_name, expected_value in expected.items():
        if custody.get(field_name) != expected_value:
            _blocked(f"promotion_reference_{field_name}_mismatch")
    safety = _required_mapping(
        reference.get("safety"),
        "promotion_reference.safety",
    )
    if safety.get("strict_pit_availability_verified") is not True:
        _blocked("promotion_reference_pit_not_verified")
    if safety.get("future_outcomes_used_in_reference") is not False:
        _blocked("promotion_reference_future_outcome_contamination")
    if safety.get("broker_order_allowed") is not False:
        _blocked("promotion_reference_broker_authority_forbidden")

    metrics = _read_json_mapping(metrics_path, "promotion_reference_metrics")
    if not str(metrics.get("schema_version", "")).startswith(
        "ml-allocation-promotion-reference-metrics"
    ):
        _blocked("promotion_reference_metrics_schema_mismatch")
    _verify_logical_hash(
        metrics,
        hash_field="metrics_hash",
        blocker="promotion_reference_metrics_logical_hash_mismatch",
    )
    metrics_hash = _required_sha256(
        metrics.get("metrics_hash"),
        "promotion_reference_metrics.metrics_hash",
    )
    if metrics.get("reference_hash") != reference_hash:
        _blocked("promotion_reference_metrics_reference_hash_mismatch")
    if metrics.get("reference_file_hash") != reference_file_hash:
        _blocked("promotion_reference_metrics_reference_file_hash_mismatch")
    if metrics.get("status") != "evaluated":
        _blocked("promotion_reference_horizon_metrics_incomplete")
    if _text_sequence(metrics.get("blockers"), "metrics.blockers"):
        _blocked("promotion_reference_horizon_metrics_incomplete")

    horizon_metrics = _normalize_horizon_metrics(
        metrics.get("horizon_metrics")
    )
    by_horizon = {
        _required_int(
            item.get("horizon_trading_days"),
            "horizon_metrics.horizon_trading_days",
        ): item
        for item in horizon_metrics
    }
    if set(by_horizon) != set(REQUIRED_HORIZONS):
        _blocked("promotion_reference_horizon_metrics_incomplete")
    for horizon in REQUIRED_HORIZONS:
        item = by_horizon[horizon]
        if item.get("status") != "evaluated":
            _blocked(
                f"promotion_reference_horizon_metrics_incomplete:{horizon}"
            )
        if item.get("blockers") is not None and _text_sequence(
            item.get("blockers"),
            f"horizon_metrics[{horizon}].blockers",
        ):
            _blocked(
                f"promotion_reference_horizon_metrics_incomplete:{horizon}"
            )
        matured = _required_nonnegative_int(
            item.get("matured_unique_decision_date_count"),
            f"horizon_metrics[{horizon}].matured_unique_decision_date_count",
        )
        if matured < request.minimum_matured_days:
            _blocked(
                "promotion_reference_horizon_metrics_incomplete:"
                f"{horizon}:{matured}/{request.minimum_matured_days}"
            )
        for field_name in (
            "calibration_ece_bp",
            "calibrated_brier_bp",
            "uncalibrated_brier_bp",
        ):
            _required_bp(item.get(field_name), f"horizon[{horizon}].{field_name}")

    worst_ece = max(
        _required_bp(item["calibration_ece_bp"], "calibration_ece_bp")
        for item in by_horizon.values()
    )
    # PSI 是同一批 frozen feature distribution 對 current distribution 的
    # 整體 drift，不應為了 outcome horizon 人為重複或拆分。
    worst_psi = _required_bp(metrics.get("psi_bp"), "metrics.psi_bp")
    brier_item = max(
        by_horizon.values(),
        key=lambda item: (
            _required_bp(item["calibrated_brier_bp"], "calibrated_brier_bp")
            - _required_bp(
                item["uncalibrated_brier_bp"],
                "uncalibrated_brier_bp",
            ),
            _required_int(
                item["horizon_trading_days"],
                "horizon_trading_days",
            ),
        ),
    )
    return _ReferenceMetrics(
        reference=reference,
        metrics=metrics,
        reference_hash=reference_hash,
        reference_file_hash=reference_file_hash,
        metrics_hash=metrics_hash,
        metrics_file_hash=_file_hash(metrics_path),
        calibration_ece_bp=worst_ece,
        calibrated_brier_bp=_required_bp(
            brier_item["calibrated_brier_bp"],
            "calibrated_brier_bp",
        ),
        uncalibrated_brier_bp=_required_bp(
            brier_item["uncalibrated_brier_bp"],
            "uncalibrated_brier_bp",
        ),
        psi_bp=worst_psi,
        horizon_metrics=tuple(
            by_horizon[horizon] for horizon in REQUIRED_HORIZONS
        ),
    )


def _load_shadow_custody(
    request: AllocationPromotionEvidenceBuildRequest,
    *,
    formal: _FormalCustody,
    reference: _ReferenceMetrics,
) -> _ShadowCustody:
    database_path = request.shadow_sidecar_database_path.resolve()
    _require_file(database_path, "shadow_sidecar_missing")
    before_hash = _file_hash(database_path)
    observations = _read_sidecar_records(database_path, "shadow_observations")
    outcomes = _read_sidecar_records(database_path, "shadow_outcomes")
    after_hash = _file_hash(database_path)
    if before_hash != after_hash:
        _blocked("shadow_sidecar_changed_during_snapshot")

    latest_observations = _latest_by_key(
        observations,
        key_field="decision_date",
        label="shadow_observation",
    )
    latest_observation_hashes = {
        _required_sha256(item.get("record_hash"), "observation.record_hash")
        for item in latest_observations
    }
    latest_outcomes = _latest_by_key(
        tuple(
            item
            for item in outcomes
            if item.get("observation_hash") in latest_observation_hashes
        ),
        key_field="observation_hash",
        label="shadow_outcome",
    )
    outcome_by_observation = {
        _required_sha256(item.get("observation_hash"), "outcome.observation_hash"):
        item
        for item in latest_outcomes
    }

    matured: list[tuple[Mapping[str, object], Mapping[str, object]]] = []
    for observation in latest_observations:
        _validate_shadow_observation(
            observation,
            formal=formal,
            reference=reference,
        )
        observation_hash = _required_sha256(
            observation.get("record_hash"),
            "observation.record_hash",
        )
        outcome = outcome_by_observation.get(observation_hash)
        if outcome is None:
            continue
        _validate_shadow_outcome(
            outcome,
            observation=observation,
            as_of_date=request.as_of_date,
        )
        matured.append((observation, outcome))
    unique_dates = {
        _required_text(item[0].get("decision_date"), "decision_date")
        for item in matured
    }
    if len(unique_dates) < request.minimum_matured_days:
        _blocked(
            "matured_shadow_days_insufficient:"
            f"{len(unique_dates)}/{request.minimum_matured_days}"
        )
    for horizon_metric in reference.horizon_metrics:
        reference_days = _required_nonnegative_int(
            horizon_metric.get("matured_unique_decision_date_count"),
            "horizon_metric.matured_unique_decision_date_count",
        )
        if reference_days != len(unique_dates):
            _blocked(
                "promotion_reference_shadow_maturity_count_mismatch:"
                f"{horizon_metric['horizon_trading_days']}"
            )

    bundle_body: dict[str, object] = {
        "schema_version": SHADOW_BUNDLE_SCHEMA_VERSION,
        "as_of_date": request.as_of_date.isoformat(),
        "sidecar_snapshot_file_hash": before_hash,
        "latest_observation_hashes": sorted(
            _required_sha256(item.get("record_hash"), "record_hash")
            for item, _ in matured
        ),
        "latest_outcome_hashes": sorted(
            _required_sha256(item.get("record_hash"), "record_hash")
            for _, item in matured
        ),
        "matured_unique_decision_dates": sorted(unique_dates),
        "matured_unique_decision_date_count": len(unique_dates),
        "promotion_reference_hash": reference.reference_hash,
        "promotion_reference_file_hash": reference.reference_file_hash,
        "promotion_reference_metrics_hash": reference.metrics_hash,
        "promotion_reference_metrics_file_hash": reference.metrics_file_hash,
        "promotion_reference_horizons": [
            {
                "horizon_trading_days": item["horizon_trading_days"],
                "matured_unique_decision_date_count": item[
                    "matured_unique_decision_date_count"
                ],
                "calibration_ece_bp": item["calibration_ece_bp"],
                "calibrated_brier_bp": item["calibrated_brier_bp"],
                "uncalibrated_brier_bp": item["uncalibrated_brier_bp"],
                "psi_bp": reference.psi_bp,
            }
            for item in reference.horizon_metrics
        ],
        "model_artifact_hash": formal.model_artifact_hash,
        "training_manifest_file_hash": formal.training_manifest_file_hash,
        "dataset_identity_hash": formal.dataset_identity_hash,
        "dataset_manifest_file_hash": formal.dataset_manifest_file_hash,
    }
    return _ShadowCustody(
        bundle={
            **bundle_body,
            "bundle_hash": _payload_hash(bundle_body),
        },
        matured_days=len(unique_dates),
    )


def _build_alpha_lanes(
    *,
    replay: _ReplayCustody,
    reference: _ReferenceMetrics,
    matured_days: int,
) -> tuple[AlphaLaneEvidence, ...]:
    result: list[AlphaLaneEvidence] = []
    for lane in replay.lanes:
        alpha_bp = _required_int(lane.get("alpha_bp"), "lane.alpha_bp")
        folds = tuple(
            AllocationFoldEvidence(
                fold_id=_required_text(item.get("fold_id"), "fold.fold_id"),
                after_cost_excess_vs_rule_bp=_required_int(
                    item.get("after_cost_excess_vs_rule_bp"),
                    "fold.after_cost_excess_vs_rule_bp",
                ),
            )
            for item in _mapping_sequence(lane.get("folds"), "lane.folds")
        )
        daily_excess = tuple(
            _required_int(value, "daily_after_cost_excess_vs_rule_bp")
            for fold in _mapping_sequence(lane.get("folds"), "lane.folds")
            for value in _integer_sequence(
                fold.get("daily_after_cost_excess_vs_rule_bp"),
                "fold.daily_after_cost_excess_vs_rule_bp",
            )
        )
        if len(daily_excess) < MINIMUM_MATURED_DAYS:
            _blocked(f"block_bootstrap_input_incomplete:{alpha_bp}")
        bootstrap = deterministic_block_bootstrap_lower_95_bp(daily_excess)
        result.append(
            AlphaLaneEvidence(
                alpha_bp=alpha_bp,
                pit_violation_count=_required_nonnegative_int(
                    lane.get("pit_violation_count"),
                    "lane.pit_violation_count",
                ),
                future_prefix_violation_count=_required_nonnegative_int(
                    lane.get("future_prefix_violation_count"),
                    "lane.future_prefix_violation_count",
                ),
                constraint_violation_count=_required_nonnegative_int(
                    lane.get("constraint_violation_count"),
                    "lane.constraint_violation_count",
                ),
                replay_hash_pairs=(
                    (replay.result_hash, replay.result_hash),
                ),
                folds=folds,
                bootstrap_lower_bound_bp=bootstrap,
                calibration_ece_bp=reference.calibration_ece_bp,
                calibrated_brier_bp=reference.calibrated_brier_bp,
                uncalibrated_brier_bp=reference.uncalibrated_brier_bp,
                psi_bp=reference.psi_bp,
                core_coverage_bp=_required_bp(
                    lane.get("core_coverage_bp"),
                    "lane.core_coverage_bp",
                ),
                enriched_coverage_bp=_required_bp(
                    lane.get("enriched_coverage_bp"),
                    "lane.enriched_coverage_bp",
                ),
                feasible_fill_coverage_bp=_required_bp(
                    lane.get("feasible_fill_coverage_bp"),
                    "lane.feasible_fill_coverage_bp",
                ),
                mdd_worsening_vs_rule_bp=_required_int(
                    lane.get("mdd_worsening_vs_rule_bp"),
                    "lane.mdd_worsening_vs_rule_bp",
                ),
                cvar_worsening_vs_rule_bp=_required_int(
                    lane.get("cvar_worsening_vs_rule_bp"),
                    "lane.cvar_worsening_vs_rule_bp",
                ),
                weekly_turnover_bp=_required_nonnegative_int(
                    lane.get("weekly_turnover_bp"),
                    "lane.weekly_turnover_bp",
                ),
                turnover_increment_vs_rule_bp=_required_nonnegative_int(
                    lane.get("turnover_increment_vs_rule_bp"),
                    "lane.turnover_increment_vs_rule_bp",
                ),
                shadow_observed_days=matured_days,
            )
        )
    return tuple(sorted(result, key=lambda item: item.alpha_bp))


def _publish(
    request: AllocationPromotionEvidenceBuildRequest,
    *,
    formal: _FormalCustody,
    replay: _ReplayCustody,
    reference: _ReferenceMetrics,
    shadow: _ShadowCustody,
    lanes: tuple[AlphaLaneEvidence, ...],
) -> AllocationPromotionEvidenceBuildResult:
    output_root = request.output_root.resolve()
    runs_root = output_root / "runs"
    staging_root = output_root / ".staging"
    runs_root.mkdir(parents=True, exist_ok=True)
    staging_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="promotion-", dir=staging_root))
    try:
        oof_path = temporary / "oof_bundle.json"
        replay_path = temporary / "replay_bundle.json"
        shadow_path = temporary / "shadow_evidence.json"
        _write_json(oof_path, formal.oof_bundle)
        _write_json(replay_path, replay.bundle)
        _write_json(shadow_path, shadow.bundle)
        oof_file_hash = _file_hash(oof_path)
        replay_file_hash = _file_hash(replay_path)
        shadow_file_hash = _file_hash(shadow_path)
        evidence = AllocationPromotionEvidence(
            experiment_id=request.experiment_id,
            model_id=formal.model_id,
            dataset_id=formal.dataset_id,
            model_artifact_hash=formal.model_artifact_hash,
            dataset_identity_hash=formal.dataset_identity_hash,
            dataset_manifest_file_hash=formal.dataset_manifest_file_hash,
            oof_bundle_hash=oof_file_hash,
            shadow_evidence_hash=shadow_file_hash,
            lanes=lanes,
        )
        evidence_payload: dict[str, object] = {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "promotion_policy_id": PROMOTION_POLICY_ID,
            "decision_at": request.decision_at.isoformat(timespec="seconds"),
            "as_of_date": request.as_of_date.isoformat(),
            "promotion_evidence": evidence.canonical_payload(),
            "evidence_hash": evidence.evidence_hash,
            "authority_required": True,
            "authorization_artifact_created": False,
            "broker_order_allowed": False,
        }
        evidence_path = temporary / "promotion_evidence.json"
        _write_json(evidence_path, evidence_payload)
        evidence_file_hash = _file_hash(evidence_path)
        publication_body: dict[str, object] = {
            "schema_version": PUBLICATION_SCHEMA_VERSION,
            "promotion_policy_id": PROMOTION_POLICY_ID,
            "decision_at": request.decision_at.isoformat(timespec="seconds"),
            "as_of_date": request.as_of_date.isoformat(),
            "evidence_hash": evidence.evidence_hash,
            "evidence_file_hash": evidence_file_hash,
            "model_artifact_hash": formal.model_artifact_hash,
            "training_manifest_file_hash": (
                formal.training_manifest_file_hash
            ),
            "dataset_identity_hash": formal.dataset_identity_hash,
            "dataset_manifest_file_hash": (
                formal.dataset_manifest_file_hash
            ),
            "oof_bundle_file_hash": oof_file_hash,
            "replay_bundle_file_hash": replay_file_hash,
            "shadow_evidence_file_hash": shadow_file_hash,
            "promotion_reference_hash": reference.reference_hash,
            "promotion_reference_file_hash": reference.reference_file_hash,
            "promotion_reference_metrics_hash": reference.metrics_hash,
            "promotion_reference_metrics_file_hash": (
                reference.metrics_file_hash
            ),
            "relative_paths": {
                "promotion_evidence_path": "promotion_evidence.json",
                "oof_bundle_path": "oof_bundle.json",
                "replay_bundle_path": "replay_bundle.json",
                "shadow_evidence_path": "shadow_evidence.json",
            },
            "authority_required": True,
            "authorization_artifact_created": False,
            "broker_order_allowed": False,
        }
        publication_hash = _payload_hash(publication_body)
        publication_payload = {
            **publication_body,
            "publication_hash": publication_hash,
        }
        publication_id = (
            f"promotion-evidence-{publication_hash[7:23]}"
        )
        publication_path = temporary / "publication.json"
        _write_json(publication_path, publication_payload)
        publication_file_hash = _file_hash(publication_path)
        final_directory = runs_root / publication_id
        idempotent = False
        if final_directory.exists():
            expected_files = {
                "oof_bundle.json": oof_file_hash,
                "replay_bundle.json": replay_file_hash,
                "shadow_evidence.json": shadow_file_hash,
                "promotion_evidence.json": evidence_file_hash,
                "publication.json": publication_file_hash,
            }
            if any(
                not (final_directory / name).is_file()
                or _file_hash(final_directory / name) != expected_hash
                for name, expected_hash in expected_files.items()
            ):
                _blocked("immutable_promotion_publication_collision")
            idempotent = True
            shutil.rmtree(temporary)
        else:
            os.replace(temporary, final_directory)

        final_evidence = final_directory / "promotion_evidence.json"
        final_oof = final_directory / "oof_bundle.json"
        final_replay = final_directory / "replay_bundle.json"
        final_shadow = final_directory / "shadow_evidence.json"
        final_publication = final_directory / "publication.json"
        generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        pointer_body: dict[str, object] = {
            "schema_version": POINTER_SCHEMA_VERSION,
            "publication_id": publication_id,
            "decision_at": request.decision_at.isoformat(timespec="seconds"),
            "as_of_date": request.as_of_date.isoformat(),
            "generated_at": generated_at,
            "publication_hash": publication_hash,
            "publication_file_hash": _file_hash(final_publication),
            "evidence_hash": evidence.evidence_hash,
            "evidence_file_hash": _file_hash(final_evidence),
            "promotion_evidence_path": str(final_evidence.resolve()),
            "model_artifact_path": str(
                formal.model_artifact_path.resolve()
            ),
            "dataset_manifest_path": str(
                request.dataset_manifest_path.resolve()
            ),
            "oof_bundle_path": str(final_oof.resolve()),
            "shadow_evidence_path": str(final_shadow.resolve()),
            "replay_bundle_path": str(final_replay.resolve()),
            "promotion_reference_path": str(
                request.promotion_reference_path.resolve()
            ),
            "promotion_reference_metrics_path": str(
                request.promotion_reference_metrics_path.resolve()
            ),
            "authority_required": True,
            "authorization_artifact_created": False,
            "broker_order_allowed": False,
        }
        pointer_hash = _payload_hash(pointer_body)
        pointer_payload = {**pointer_body, "pointer_hash": pointer_hash}
        latest_pointer = output_root / "latest_pointer.json"
        _atomic_write_json(latest_pointer, pointer_payload)
        return AllocationPromotionEvidenceBuildResult(
            status="published",
            decision_at=request.decision_at.isoformat(timespec="seconds"),
            as_of_date=request.as_of_date.isoformat(),
            blockers=(),
            publication_id=publication_id,
            publication_hash=publication_hash,
            publication_file_hash=publication_file_hash,
            evidence_hash=evidence.evidence_hash,
            evidence_file_hash=evidence_file_hash,
            pointer_hash=pointer_hash,
            promotion_evidence_path=final_evidence,
            model_artifact_path=formal.model_artifact_path,
            dataset_manifest_path=request.dataset_manifest_path.resolve(),
            oof_bundle_path=final_oof,
            shadow_evidence_path=final_shadow,
            replay_bundle_path=final_replay,
            promotion_reference_path=request.promotion_reference_path.resolve(),
            promotion_reference_metrics_path=(
                request.promotion_reference_metrics_path.resolve()
            ),
            latest_pointer_path=latest_pointer,
            idempotent=idempotent,
        )
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def deterministic_block_bootstrap_lower_95_bp(
    excess_returns_bp: Sequence[int],
    *,
    block_size: int = 5,
) -> int:
    """以固定 hash draws 執行 circular block-bootstrap 的 5% 下界。"""

    values = tuple(
        _required_int(item, "excess_return_bp")
        for item in excess_returns_bp
    )
    if len(values) < MINIMUM_MATURED_DAYS:
        raise ValueError("bootstrap requires at least 20 observations")
    if (
        isinstance(block_size, bool)
        or not isinstance(block_size, int)
        or block_size <= 0
    ):
        raise ValueError("block_size must be a positive integer")
    sample_count = 2_000
    seed = _canonical_json(
        {
            "values": list(values),
            "block_size": block_size,
            "sample_count": sample_count,
        }
    ).encode("utf-8")
    means: list[int] = []
    for sample_index in range(sample_count):
        sample: list[int] = []
        draw_index = 0
        while len(sample) < len(values):
            digest = hashlib.sha256(
                seed
                + sample_index.to_bytes(4, byteorder="big", signed=False)
                + draw_index.to_bytes(4, byteorder="big", signed=False)
            ).digest()
            cursor = int.from_bytes(
                digest[:8],
                byteorder="big",
                signed=False,
            ) % len(values)
            for offset in range(block_size):
                sample.append(values[(cursor + offset) % len(values)])
                if len(sample) == len(values):
                    break
            draw_index += 1
        means.append(sum(sample) // len(sample))
    ordered = sorted(means)
    return ordered[max(0, sample_count * 5 // 100 - 1)]


def _normalize_replay_lanes(
    value: object,
    *,
    expected_fold_ids: tuple[str, ...],
    label: str,
) -> tuple[Mapping[str, object], ...]:
    raw_lanes = _mapping_sequence(value, f"{label}.lanes")
    lanes: list[dict[str, object]] = []
    for index, raw in enumerate(raw_lanes):
        alpha = _required_int(raw.get("alpha_bp"), f"{label}.lane.alpha_bp")
        folds: list[dict[str, object]] = []
        for fold in _mapping_sequence(
            raw.get("folds"),
            f"{label}.lane[{index}].folds",
        ):
            fold_id = _required_text(fold.get("fold_id"), "fold.fold_id")
            daily = list(
                _integer_sequence(
                    fold.get("daily_after_cost_excess_vs_rule_bp"),
                    "fold.daily_after_cost_excess_vs_rule_bp",
                )
            )
            if not daily:
                _blocked(f"block_bootstrap_input_incomplete:{alpha}:{fold_id}")
            folds.append(
                {
                    "fold_id": fold_id,
                    "after_cost_excess_vs_rule_bp": _required_int(
                        fold.get("after_cost_excess_vs_rule_bp"),
                        "fold.after_cost_excess_vs_rule_bp",
                    ),
                    "daily_after_cost_excess_vs_rule_bp": daily,
                }
            )
        folds.sort(key=lambda item: str(item["fold_id"]))
        fold_ids = tuple(str(item["fold_id"]) for item in folds)
        if set(fold_ids) != set(expected_fold_ids) or len(fold_ids) != len(
            set(fold_ids)
        ):
            _blocked(
                f"formal_replay_outer_folds_incomplete:{alpha}:"
                f"{len(set(fold_ids))}/{len(expected_fold_ids)}"
            )
        winning = sum(
            cast(int, item["after_cost_excess_vs_rule_bp"]) > 0
            for item in folds
        )
        declared_winning = _required_nonnegative_int(
            raw.get("winning_fold_count"),
            "lane.winning_fold_count",
        )
        if declared_winning != winning:
            _blocked(f"formal_replay_winning_fold_count_mismatch:{alpha}")
        lane: dict[str, object] = {
            "alpha_bp": alpha,
            "folds": folds,
            "winning_fold_count": winning,
        }
        for field_name in (
            "mdd_worsening_vs_rule_bp",
            "cvar_worsening_vs_rule_bp",
        ):
            lane[field_name] = _required_int(
                raw.get(field_name),
                f"lane.{field_name}",
            )
        for field_name in (
            "weekly_turnover_bp",
            "turnover_increment_vs_rule_bp",
            "pit_violation_count",
            "future_prefix_violation_count",
            "constraint_violation_count",
        ):
            lane[field_name] = _required_nonnegative_int(
                raw.get(field_name),
                f"lane.{field_name}",
            )
        for field_name in (
            "core_coverage_bp",
            "enriched_coverage_bp",
            "feasible_fill_coverage_bp",
        ):
            lane[field_name] = _required_bp(
                raw.get(field_name),
                f"lane.{field_name}",
            )
        lanes.append(lane)
    lanes.sort(key=lambda item: cast(int, item["alpha_bp"]))
    if tuple(cast(int, item["alpha_bp"]) for item in lanes) != ALPHA_LANES:
        _blocked("formal_replay_alpha_lanes_incomplete")
    return tuple(lanes)


def _normalize_horizon_metrics(
    value: object,
) -> tuple[Mapping[str, object], ...]:
    if isinstance(value, dict):
        result = []
        for key, raw in value.items():
            item = dict(_required_mapping(raw, f"horizon_metrics[{key}]"))
            item.setdefault("horizon_trading_days", _parse_horizon_key(key))
            result.append(item)
        return tuple(result)
    return tuple(
        _required_mapping(item, "horizon_metric")
        for item in _required_sequence(value, "horizon_metrics")
    )


def _validate_shadow_observation(
    observation: Mapping[str, object],
    *,
    formal: _FormalCustody,
    reference: _ReferenceMetrics,
) -> None:
    _verify_record_hash(
        observation,
        hash_field="record_hash",
        blocker="shadow_observation_record_hash_mismatch",
    )
    if observation.get("research_only") is not True:
        _blocked("shadow_observation_lane_marker_invalid")
    if observation.get("formal_oos_allowed") is not False:
        _blocked("shadow_observation_claimed_formal_oos")
    if observation.get("broker_order_allowed") is not False:
        _blocked("shadow_observation_broker_authority_forbidden")
    custody = _required_mapping(
        observation.get("custody"),
        "shadow_observation.custody",
    )
    expected = {
        "model_hash": formal.model_artifact_hash,
        "release_training_manifest_file_hash": (
            formal.training_manifest_file_hash
        ),
        "dataset_identity_hash": formal.dataset_identity_hash,
        "dataset_manifest_file_hash": formal.dataset_manifest_file_hash,
        "promotion_reference_hash": reference.reference_hash,
        "promotion_reference_file_hash": reference.reference_file_hash,
    }
    for field_name, expected_value in expected.items():
        if custody.get(field_name) != expected_value:
            _blocked(f"shadow_observation_{field_name}_mismatch")
    for field_name in (
        "pit_violation_count",
        "future_prefix_violation_count",
        "constraint_violation_count",
    ):
        _required_nonnegative_int(
            observation.get(field_name),
            f"shadow_observation.{field_name}",
        )
    lanes = _mapping_sequence(observation.get("lanes"), "observation.lanes")
    if tuple(
        sorted(_required_int(item.get("alpha_bp"), "lane.alpha_bp") for item in lanes)
    ) != ALPHA_LANES:
        _blocked("shadow_observation_alpha_lanes_incomplete")


def _validate_shadow_outcome(
    outcome: Mapping[str, object],
    *,
    observation: Mapping[str, object],
    as_of_date: date,
) -> None:
    _verify_record_hash(
        outcome,
        hash_field="record_hash",
        blocker="shadow_outcome_record_hash_mismatch",
    )
    observation_hash = _required_sha256(
        observation.get("record_hash"),
        "observation.record_hash",
    )
    if outcome.get("observation_hash") != observation_hash:
        _blocked("shadow_outcome_observation_hash_mismatch")
    decision_text = _required_text(
        observation.get("decision_date"),
        "observation.decision_date",
    )
    if outcome.get("decision_date") != decision_text:
        _blocked("shadow_outcome_decision_date_mismatch")
    decision_date = _parse_date(decision_text, "decision_date")
    if outcome.get("completed_horizons_trading_sessions") is not None:
        _validate_contract_shadow_outcome(
            outcome,
            decision_date=decision_date,
            decision_text=decision_text,
            as_of_date=as_of_date,
        )
        horizons: dict[int, Mapping[str, object]] = {}
    else:
        horizons = _outcome_horizons(outcome)
    if not horizons:
        for field_name in (
            "pit_violation_count",
            "future_prefix_violation_count",
            "constraint_violation_count",
        ):
            _required_nonnegative_int(
                outcome.get(field_name),
                f"shadow_outcome.{field_name}",
            )
        return
    if set(horizons) != set(REQUIRED_HORIZONS):
        _blocked(
            f"shadow_outcome_horizons_incomplete:{decision_text}"
        )
    for horizon in REQUIRED_HORIZONS:
        item = horizons[horizon]
        end_date = _parse_date(
            _required_text(
                item.get("horizon_end_date"),
                f"outcome[{horizon}].horizon_end_date",
            ),
            "horizon_end_date",
        )
        if end_date > as_of_date:
            _blocked(
                f"shadow_outcome_future_horizon:{decision_text}:{horizon}"
            )
        if end_date <= decision_date:
            _blocked(
                f"shadow_outcome_noncausal_horizon:{decision_text}:{horizon}"
            )
        lane_metrics_value = item.get("lane_metrics")
        if lane_metrics_value is not None and {
            int(key)
            for key in _required_mapping(
                lane_metrics_value,
                f"outcome[{horizon}].lane_metrics",
            )
        } != set(ALPHA_LANES):
            _blocked(
                f"shadow_outcome_lane_metrics_incomplete:"
                f"{decision_text}:{horizon}"
            )
    for field_name in (
        "pit_violation_count",
        "future_prefix_violation_count",
        "constraint_violation_count",
    ):
        _required_nonnegative_int(
            outcome.get(field_name),
            f"shadow_outcome.{field_name}",
        )


def _validate_contract_shadow_outcome(
    outcome: Mapping[str, object],
    *,
    decision_date: date,
    decision_text: str,
    as_of_date: date,
) -> None:
    if outcome.get("status") != "matured_all_horizons":
        _blocked(f"shadow_outcome_horizons_incomplete:{decision_text}")
    completed = tuple(
        _required_int(item, "completed_horizon")
        for item in _required_sequence(
            outcome.get("completed_horizons_trading_sessions"),
            "completed_horizons_trading_sessions",
        )
    )
    if completed != REQUIRED_HORIZONS:
        _blocked(f"shadow_outcome_horizons_incomplete:{decision_text}")
    if outcome.get("blockers") is not None and _text_sequence(
        outcome.get("blockers"),
        "shadow_outcome.blockers",
    ):
        _blocked(f"shadow_outcome_horizons_incomplete:{decision_text}")
    contract_version = _required_text(
        outcome.get("outcome_contract_version"),
        "outcome_contract_version",
    )
    contract_hash = _required_sha256(
        outcome.get("outcome_contract_hash"),
        "outcome_contract_hash",
    )
    source_custody = _required_mapping(
        outcome.get("outcome_source_custody"),
        "outcome_source_custody",
    )
    if (
        source_custody.get("outcome_contract_version") != contract_version
        or source_custody.get("outcome_contract_hash") != contract_hash
    ):
        _blocked("shadow_outcome_contract_custody_mismatch")
    _verify_logical_hash(
        {
            **source_custody,
            "outcome_source_custody_hash": outcome.get(
                "outcome_source_custody_hash"
            ),
        },
        hash_field="outcome_source_custody_hash",
        blocker="shadow_outcome_source_custody_hash_mismatch",
    )
    rows = _mapping_sequence(
        outcome.get("downside_outcomes"),
        "shadow_outcome.downside_outcomes",
    )
    if not rows:
        _blocked(f"shadow_outcome_horizons_incomplete:{decision_text}")
    symbols: set[str] = set()
    keys: set[tuple[str, int]] = set()
    outcome_hashes: list[str] = []
    for row in rows:
        _verify_logical_hash(
            row,
            hash_field="outcome_hash",
            blocker="shadow_downside_outcome_hash_mismatch",
        )
        outcome_hashes.append(
            _required_sha256(row.get("outcome_hash"), "outcome.outcome_hash")
        )
        if (
            contract_version != OUTCOME_CONTRACT_VERSION
            or contract_hash != OUTCOME_CONTRACT_HASH
            or row.get("outcome_contract_version") != OUTCOME_CONTRACT_VERSION
            or row.get("outcome_contract_hash") != OUTCOME_CONTRACT_HASH
            or row.get("decision_date") != decision_text
        ):
            _blocked("shadow_downside_outcome_contract_mismatch")
        symbol = _required_text(row.get("symbol"), "outcome.symbol")
        horizon = _required_int(
            row.get("horizon_trading_sessions"),
            "outcome.horizon_trading_sessions",
        )
        if horizon not in REQUIRED_HORIZONS:
            _blocked("shadow_downside_outcome_horizon_unsupported")
        key = (symbol, horizon)
        if key in keys:
            _blocked("shadow_downside_outcome_duplicate")
        keys.add(key)
        symbols.add(symbol)
        entry_date = _parse_date(
            _required_text(row.get("entry_date"), "outcome.entry_date"),
            "entry_date",
        )
        end_date = _parse_date(
            _required_text(
                row.get("horizon_end_date"),
                "outcome.horizon_end_date",
            ),
            "horizon_end_date",
        )
        if entry_date < decision_date:
            _blocked(
                f"shadow_outcome_entry_predates_decision:{decision_text}:{horizon}"
            )
        if end_date > as_of_date:
            _blocked(
                f"shadow_outcome_future_horizon:{decision_text}:{horizon}"
            )
        if end_date <= decision_date or end_date < entry_date:
            _blocked(
                f"shadow_outcome_noncausal_horizon:{decision_text}:{horizon}"
            )
        available_at = _parse_aware_datetime(
            _required_text(row.get("available_at"), "outcome.available_at"),
            "available_at",
        )
        if available_at.date() < end_date:
            _blocked(
                "shadow_outcome_availability_predates_horizon:"
                f"{decision_text}:{horizon}"
            )
        if available_at.date() > as_of_date:
            _blocked(
                f"shadow_outcome_future_availability:{decision_text}:{horizon}"
            )
        for field_name in (
            "stock_source_rows_hash",
            "benchmark_source_rows_hash",
            "calendar_hash",
            "corporate_action_manifest_hash",
            "corporate_action_canonical_events_hash",
            "revision_id",
        ):
            _required_sha256(row.get(field_name), f"outcome.{field_name}")
        actual = _required_nonnegative_int(
            row.get("actual_downside"),
            "outcome.actual_downside",
        )
        stock_return = _required_int(
            row.get("stock_open_to_close_return_bp"),
            "outcome.stock_open_to_close_return_bp",
        )
        benchmark_return = _required_int(
            row.get("taiex_open_to_close_return_bp"),
            "outcome.taiex_open_to_close_return_bp",
        )
        buy_cost = _required_int(
            row.get("buy_cost_bp"),
            "outcome.buy_cost_bp",
        )
        sell_cost = _required_int(
            row.get("sell_cost_bp"),
            "outcome.sell_cost_bp",
        )
        if buy_cost != 25 or sell_cost != 55:
            _blocked("shadow_downside_outcome_transaction_cost_mismatch")
        excess = _required_int(
            row.get("benchmark_excess_return_bp"),
            "outcome.benchmark_excess_return_bp",
        )
        if excess != stock_return - benchmark_return - buy_cost - sell_cost:
            _blocked("shadow_downside_outcome_excess_return_formula_mismatch")
        if actual not in {0, 1} or actual != int(excess < 0):
            _blocked("shadow_downside_outcome_label_formula_mismatch")
        try:
            _validate_downside_outcome_source_custody(
                outcome=row,
                decision_date=decision_text,
                symbol=symbol,
                horizon=horizon,
                entry_date=entry_date,
                end_date=end_date,
                available_at=available_at,
                stock_return_bp=stock_return,
                benchmark_return_bp=benchmark_return,
            )
        except (TypeError, ValueError) as exc:
            _blocked(
                "shadow_downside_outcome_source_custody_invalid:"
                f"{_safe_reason(exc)}"
            )
    if not symbols or any(
        (symbol, horizon) not in keys
        for symbol in symbols
        for horizon in REQUIRED_HORIZONS
    ):
        _blocked(f"shadow_outcome_horizons_incomplete:{decision_text}")
    source_hashes = tuple(
        _required_sha256(item, "downside_outcome_hash")
        for item in _required_sequence(
            source_custody.get("downside_outcome_hashes"),
            "outcome_source_custody.downside_outcome_hashes",
        )
    )
    if source_hashes != tuple(outcome_hashes):
        _blocked("shadow_outcome_source_custody_rows_mismatch")


def _outcome_horizons(
    outcome: Mapping[str, object],
) -> dict[int, Mapping[str, object]]:
    raw = outcome.get("horizon_metrics")
    if isinstance(raw, dict):
        return {
            _parse_horizon_key(key): _required_mapping(
                item,
                f"horizon_metrics[{key}]",
            )
            for key, item in raw.items()
        }
    raw_rows = outcome.get("horizon_outcomes")
    if isinstance(raw_rows, list):
        result = {}
        for item in _mapping_sequence(raw_rows, "horizon_outcomes"):
            horizon = _required_int(
                item.get("horizon_trading_days"),
                "horizon_trading_days",
            )
            result[horizon] = item
        return result
    if "trading_day_count" in outcome:
        horizon = _required_int(
            outcome.get("trading_day_count"),
            "trading_day_count",
        )
        return {horizon: outcome}
    _blocked("shadow_outcome_horizon_metrics_missing")
    raise AssertionError("unreachable")


def _validate_model_artifact_directory(
    directory: Path,
    *,
    expected_schema: str,
    blocker_prefix: str,
) -> Mapping[str, object]:
    manifest_path = directory / "manifest.json"
    _require_file(manifest_path, f"{blocker_prefix}_manifest_missing")
    manifest = _read_json_mapping(manifest_path, f"{blocker_prefix}.manifest")
    if manifest.get("schema_version") != expected_schema:
        _blocked(f"{blocker_prefix}_schema_mismatch")
    _verify_logical_hash(
        manifest,
        hash_field="manifest_hash",
        blocker=f"{blocker_prefix}_manifest_hash_mismatch",
    )
    artifacts = _mapping_sequence(
        manifest.get("artifacts"),
        f"{blocker_prefix}.artifacts",
    )
    if not artifacts:
        _blocked(f"{blocker_prefix}_artifact_files_missing")
    for item in artifacts:
        path = _contained_path(
            directory,
            _required_text(item.get("path"), "artifact.path"),
            blocker=f"{blocker_prefix}_artifact_path_escapes_directory",
        )
        _require_file(path, f"{blocker_prefix}_artifact_file_missing")
        expected_hash = _required_sha256(
            item.get("file_sha256"),
            "artifact.file_sha256",
        )
        if _file_hash(path) != expected_hash:
            _blocked(f"{blocker_prefix}_artifact_file_hash_mismatch")
        expected_bytes = _required_nonnegative_int(
            item.get("byte_count"),
            "artifact.byte_count",
        )
        if path.stat().st_size != expected_bytes:
            _blocked(f"{blocker_prefix}_artifact_byte_count_mismatch")
    return manifest


def _oof_entry(
    *,
    directory: Path,
    manifest: Mapping[str, object],
    kind: str,
) -> dict[str, object]:
    artifacts = _mapping_sequence(manifest.get("artifacts"), "artifacts")
    oof = next(
        (
            item
            for item in artifacts
            if Path(_required_text(item.get("path"), "artifact.path")).name
            == "oof.i32"
        ),
        None,
    )
    if oof is None:
        _blocked(f"{kind}_oof_file_missing")
    assert oof is not None
    oof_path = _contained_path(
        directory,
        _required_text(oof.get("path"), "oof.path"),
        blocker=f"{kind}_oof_path_escapes_directory",
    )
    return {
        "kind": kind,
        "fold_id": _required_text(manifest.get("fold_id"), "fold_id"),
        "expert_id": manifest.get("expert_id"),
        "artifact_manifest_hash": _required_sha256(
            manifest.get("manifest_hash"),
            "artifact_manifest_hash",
        ),
        "artifact_manifest_file_hash": _file_hash(
            directory / "manifest.json"
        ),
        "oof_file_hash": _file_hash(oof_path),
        "oof_byte_count": oof_path.stat().st_size,
        "oof_shape": manifest.get("oof_shape"),
        "oof_dtype": manifest.get("oof_dtype"),
    }


def _read_sidecar_records(
    path: Path,
    table_name: str,
) -> tuple[Mapping[str, object], ...]:
    if table_name not in {"shadow_observations", "shadow_outcomes"}:
        raise ValueError("unsupported shadow sidecar table")
    uri = f"{path.as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(
            f"SELECT payload_json FROM {table_name} ORDER BY rowid"  # noqa: S608
        ).fetchall()
    return tuple(
        _required_mapping(
            json.loads(str(row[0])),
            f"{table_name}.payload",
        )
        for row in rows
    )


def _latest_by_key(
    records: Sequence[Mapping[str, object]],
    *,
    key_field: str,
    label: str,
) -> tuple[Mapping[str, object], ...]:
    latest: dict[str, Mapping[str, object]] = {}
    for record in records:
        _verify_record_hash(
            record,
            hash_field="record_hash",
            blocker=f"{label}_record_hash_mismatch",
        )
        key = _required_text(record.get(key_field), f"{label}.{key_field}")
        revision = _required_nonnegative_int(
            record.get("revision"),
            f"{label}.revision",
        )
        if revision < 1:
            _blocked(f"{label}_revision_invalid")
        existing = latest.get(key)
        if existing is None or revision > _required_int(
            existing.get("revision"),
            f"{label}.revision",
        ):
            latest[key] = record
    return tuple(latest[key] for key in sorted(latest))


def _require_formal_lane(
    payload: Mapping[str, object],
    label: str,
) -> None:
    if payload.get("formal_source_only") is not True:
        _blocked(f"{label}_formal_source_marker_missing")
    if payload.get("research_shadow_included") is not False:
        _blocked(f"{label}_research_lane_forbidden")
    if payload.get("research_only") not in {None, False}:
        _blocked(f"{label}_research_lane_forbidden")


def _verify_logical_hash(
    payload: Mapping[str, object],
    *,
    hash_field: str,
    blocker: str,
) -> None:
    expected = _required_sha256(payload.get(hash_field), hash_field)
    body = dict(payload)
    body.pop(hash_field, None)
    if _payload_hash(body) != expected:
        _blocked(blocker)


def _verify_record_hash(
    payload: Mapping[str, object],
    *,
    hash_field: str,
    blocker: str,
) -> None:
    _verify_logical_hash(
        payload,
        hash_field=hash_field,
        blocker=blocker,
    )


def _mapping_sequence(
    value: object,
    label: str,
) -> tuple[Mapping[str, object], ...]:
    return tuple(
        _required_mapping(item, f"{label}[{index}]")
        for index, item in enumerate(_required_sequence(value, label))
    )


def _text_sequence(value: object, label: str) -> tuple[str, ...]:
    return tuple(
        _required_text(item, f"{label}[{index}]")
        for index, item in enumerate(_required_sequence(value, label))
    )


def _integer_sequence(value: object, label: str) -> tuple[int, ...]:
    return tuple(
        _required_int(item, f"{label}[{index}]")
        for index, item in enumerate(_required_sequence(value, label))
    )


def _required_sequence(value: object, label: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, list):
        raise TypeError(f"{label} must be an array")
    return value


def _required_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return cast(Mapping[str, object], value)


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{label} must be a non-empty string")
    return value


def _required_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    return value


def _required_nonnegative_int(value: object, label: str) -> int:
    result = _required_int(value, label)
    if result < 0:
        raise ValueError(f"{label} must be non-negative")
    return result


def _required_bp(value: object, label: str) -> int:
    result = _required_int(value, label)
    if not 0 <= result <= 10_000:
        raise ValueError(f"{label} must be within 0..10000 bp")
    return result


def _required_sha256(value: object, label: str) -> str:
    text = _required_text(value, label)
    digest = text[7:] if text.startswith(_SHA256_PREFIX) else ""
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError(f"{label} must be a sha256 digest")
    return text


def _parse_horizon_key(value: object) -> int:
    if isinstance(value, bool):
        raise TypeError("horizon key must be an integer")
    try:
        result = int(str(value))
    except ValueError as exc:
        raise TypeError("horizon key must be an integer") from exc
    return result


def _parse_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date") from exc


def _parse_aware_datetime(value: str, label: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO datetime") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return result


def _contained_path(root: Path, relative: str, *, blocker: str) -> Path:
    if Path(relative).is_absolute():
        candidate = Path(relative).resolve()
    else:
        candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        _blocked(blocker)
    return candidate


def _require_file(path: Path, blocker: str) -> None:
    if not path.is_file():
        _blocked(blocker)


def _read_json_mapping(path: Path, label: str) -> Mapping[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _required_mapping(payload, label)


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_hash(payload: object) -> str:
    return (
        f"{_SHA256_PREFIX}"
        f"{hashlib.sha256(_canonical_json(payload).encode('utf-8')).hexdigest()}"
    )


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"{_SHA256_PREFIX}{digest.hexdigest()}"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        _write_json(temporary, payload)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _path_text(path: Path | None) -> str | None:
    return str(path.resolve()) if path is not None else None


def _safe_reason(exc: BaseException) -> str:
    return str(exc).replace("\r", " ").replace("\n", " ")[:240]


def _blocked(blocker: str) -> None:
    raise _BlockedEvidence(blocker)


__all__ = [
    "AllocationPromotionEvidenceBuildRequest",
    "AllocationPromotionEvidenceBuildResult",
    "BUILDER_RESULT_SCHEMA_VERSION",
    "EVIDENCE_SCHEMA_VERSION",
    "FORMAL_REPLAY_SCHEMA_VERSION",
    "MINIMUM_MATURED_DAYS",
    "OOC_STORE_SCHEMA_VERSION",
    "OOC_TRAINING_SCHEMA_VERSION",
    "POINTER_SCHEMA_VERSION",
    "PROMOTION_POLICY_ID",
    "PUBLICATION_SCHEMA_VERSION",
    "REQUIRED_HORIZONS",
    "build_compatible_allocation_promotion_evidence",
    "deterministic_block_bootstrap_lower_95_bp",
]
