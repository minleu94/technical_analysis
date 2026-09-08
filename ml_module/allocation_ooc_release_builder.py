"""由 minimal OOC 線性訓練產物建立可載入的 shadow inference release。

這個 builder 是 OOC artifact 與 daily ``AllocationReleaseAdapter`` 之間的
窄交付邊界。它只接受完整、正式來源的 ``minimal_linear_shadow`` run，將
``final_base_experts`` 與 ``final_meta`` 的 frozen joblib head 組成既有
``allocation-model-artifact-v3``，並以 outer-fold base OOF test rows 建立
真正可套用的整數 bp isotonic calibrator。

校準 fit 只讀取 OOF test rows，且每個來源 fold 只使用在下一個 outer fold
開始前已成熟的標籤；不讀 final model fit rows，也不讀 teacher target 作為
校準輸入。所有檔案都是 immutable write-once；promotion 權限仍固定關閉。
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Iterable, Mapping, Sequence, cast

import joblib
import numpy as np
from numpy.typing import NDArray

from ml_module.allocation_out_of_core_training_service import (
    AllocationOutOfCoreTrainingRequest,
    OOF_DTYPE,
    _NumericStore,
    _fit_meta_artifact,
    _read_and_validate_artifact,
    _quantize_head,
    _quantize_non_negative,
    _quantize_probability,
    _quantize_signed,
    _write_rank_column,
)
from ml_module.allocation_release_contract import (
    ARTIFACT_SCHEMA_VERSION,
    PREPROCESSOR_SCHEMA_VERSION,
    AllocationReleaseManifest,
    CalibrationBinding,
    IntegerProbabilityCalibrator,
    MissingPolicyBinding,
    PreprocessorBinding,
    bytes_hash,
    canonical_json,
    feature_order_hash,
    payload_hash,
)
from ml_module.allocation_training_service import (
    CLASSIFICATION_EXPERT_HEADS,
    EXPERT_HEAD_IDS,
    EXPERT_VECTOR_WIDTH,
    REGRESSION_EXPERT_HEADS,
)
from ml_module.allocation_rank_contract import (
    DEFAULT_RANK_CONTRACT,
    rank_values_bp,
    validate_rank_contract,
)
from ml_module.allocation_family_weight_contract import (
    FAMILY_WEIGHT_POLICY_COEFFICIENT_V1,
    FAMILY_WEIGHT_POLICY_LEGACY_UNKNOWN,
    FAMILY_WEIGHT_STATUS_LEGACY_UNKNOWN,
    validate_family_weight_binding,
    validate_family_weight_policy,
)
from ml_module.ooc_cross_fitted_calibration import (
    _fit_isotonic_mapping_bp,
)
from data_module.portfolio_ml_out_of_core_store import TARGET_FIELDS
from data_module.ml_storage_capacity import (
    BYTES_PER_GIB,
    MLStorageCapacityBudget,
    StorageCapacityError,
    StorageCapacityPreflight,
    acquire_heavy_chain_reservation,
    directory_size_bytes,
    heavy_chain_lock_path,
    preflight_capacity,
    release_heavy_chain_reservation,
    resolve_heavy_chain_lock_path,
)


_SHA256_PREFIX = "sha256:"
_TRAINING_SCHEMA_VERSION = "allocation-ooc-training.v5"
_PROFILE = "minimal_linear_shadow"
_MODEL_ARTIFACT_FILE = "model.joblib"
_PREPROCESSOR_FILE = "preprocessor.json"
_CALIBRATOR_FILE = "calibrator.json"
_EVIDENCE_FILE = "calibration_evidence.json"
_TRAINING_COMPAT_FILE = "training_manifest_v2.json"
_DERIVED_TRAINING_FILE = "derived_training_manifest.json"
_HELDOUT_EVALUATION_FILE = "heldout_evaluation.json"
_DERIVED_PROFILE = "derived_linear_shadow"
_MINIMAL_COMPLEXITY_POLICY = {
    "algorithm_count": 1,
    "horizon_count": 1,
    "formal_oos_allowed": False,
    "production_alpha_bp": 0,
}
_DERIVED_HOLDOUT_FOLD_COUNT = 4
_DERIVED_PERSISTENT_ESTIMATE = 256 * 1024 * 1024
_DERIVED_TEMPORARY_ESTIMATE = 256 * 1024 * 1024


@dataclass(frozen=True)
class AllocationOOCReleaseRequest:
    """建立一個獨立 release root 的請求。"""

    training_manifest_path: Path
    output_root: Path
    model_id: str = "baldr-ml-allocation-bounded-v4-operational"
    policy_id: str = "balanced-v4-operational"
    batch_size: int = 8_192

    def __post_init__(self) -> None:
        if not isinstance(self.model_id, str) or not self.model_id.strip():
            raise ValueError("model_id is required")
        if not isinstance(self.policy_id, str) or not self.policy_id.strip():
            raise ValueError("policy_id is required")
        if (
            isinstance(self.batch_size, bool)
            or not isinstance(self.batch_size, int)
            or self.batch_size <= 0
            or self.batch_size > 65_536
        ):
            raise ValueError("batch_size must be within 1..65536")


@dataclass(frozen=True)
class AllocationOOCReleasePublication:
    """已寫入的 release identity 與校準來源摘要。"""

    release_root: Path
    release_manifest_path: Path
    release_identity_hash: str
    model_artifact_path: Path
    model_artifact_hash: str
    calibration_id: str
    calibration_fit_fold_ids: tuple[str, ...]
    calibration_fit_row_count: int
    formal_oos_allowed: bool = False
    production_alpha_bp: int = 0
    production_action_allowed: bool = False
    broker_order_allowed: bool = False


@dataclass(frozen=True)
class AllocationDerivedOOCReleaseRequest:
    """以既有 Direct OOC parent 建立有界 derived shadow release。"""

    parent_training_manifest_path: Path
    output_root: Path
    model_id: str = "baldr-ml-allocation-derived-h5-v4"
    policy_id: str = "balanced-v4-operational"
    horizon: int = 5
    heldout_fold_count: int = _DERIVED_HOLDOUT_FOLD_COUNT
    batch_size: int = 8_192
    memory_budget_mb: int = 4_096
    persistent_new_bytes_budget: int = BYTES_PER_GIB
    temporary_peak_bytes_budget: int = BYTES_PER_GIB
    safety_reserve_bytes: int = 200 * BYTES_PER_GIB
    heavy_lock_path: Path | None = None
    acquire_heavy_lock: bool = False
    rank_contract: str = DEFAULT_RANK_CONTRACT
    family_weight_policy: str = FAMILY_WEIGHT_POLICY_COEFFICIENT_V1

    def __post_init__(self) -> None:
        for field_name in ("model_id", "policy_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} is required")
        for field_name in (
            "horizon",
            "heldout_fold_count",
            "batch_size",
            "memory_budget_mb",
            "persistent_new_bytes_budget",
            "temporary_peak_bytes_budget",
            "safety_reserve_bytes",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be integer")
            if value <= 0:
                raise ValueError(f"{field_name} must be positive")
        if self.horizon <= 0:
            raise ValueError("horizon must be positive")
        if self.heldout_fold_count != _DERIVED_HOLDOUT_FOLD_COUNT:
            raise ValueError("derived shadow requires exactly four folds")
        if self.batch_size > 65_536:
            raise ValueError("batch_size must be within 1..65536")
        if self.memory_budget_mb > 4_096:
            raise ValueError("derived shadow memory budget exceeds 4096 MB")
        if self.persistent_new_bytes_budget > BYTES_PER_GIB:
            raise ValueError("derived persistent budget exceeds 1 GiB")
        if self.temporary_peak_bytes_budget > BYTES_PER_GIB:
            raise ValueError("derived temporary budget exceeds 1 GiB")
        if not isinstance(self.acquire_heavy_lock, bool):
            raise TypeError("acquire_heavy_lock must be bool")
        if self.heavy_lock_path is not None and not isinstance(
            self.heavy_lock_path,
            Path,
        ):
            raise TypeError("heavy_lock_path must be a Path or None")
        validate_rank_contract(
            self.rank_contract,
            field_name="rank_contract",
        )
        validate_family_weight_policy(
            self.family_weight_policy,
            field_name="family_weight_policy",
        )


@dataclass(frozen=True)
class AllocationDerivedOOCReleasePublication:
    """derived release 與 withheld replay 的 immutable 產物摘要。"""

    release_root: Path
    release_manifest_path: Path
    derived_manifest_path: Path
    derived_manifest_hash: str
    release_identity_hash: str
    model_artifact_path: Path
    model_artifact_hash: str
    heldout_evaluation_path: Path
    heldout_evaluation_hash: str
    output_size_bytes: int
    heldout_fold_id: str
    selected_oof_artifact_count: int
    selected_oof_row_count: int
    meta_fit_row_count: int
    calibration_id: str
    calibration_fit_fold_ids: tuple[str, ...]
    calibration_fit_row_count: int
    capacity_preflight: Mapping[str, Any]
    formal_oos_allowed: bool = False
    production_alpha_bp: int = 0
    production_action_allowed: bool = False
    broker_order_allowed: bool = False


@dataclass(frozen=True)
class _DerivedContext:
    """derived run 內部只讀 selection context。"""

    request: AllocationDerivedOOCReleaseRequest
    parent_path: Path
    parent: Mapping[str, Any]
    parent_hash: str
    parent_run_root: Path
    store_path: Path
    store: _NumericStore
    packs: tuple[tuple[str, tuple[str, ...]], ...]
    horizon: int
    selected_folds: tuple[Mapping[str, Any], ...]
    selected_fold_ids: tuple[str, ...]
    heldout_fold_id: str
    oof_entries: Mapping[tuple[str, str], Mapping[str, Any]]
    final_entries: Mapping[str, Mapping[str, Any]]
    source_hashes: tuple[tuple[str, str], ...]
    selection_lineage: Mapping[str, Any]
    rank_contract: str
    family_weight_policy: str
    derived_identity_hash: str
    selected_oof_artifact_count: int
    selected_oof_row_count: int
    selected_oof_bytes: int


@dataclass(frozen=True)
class _DerivedMetaSelection:
    """單一 fold 的成熟 OOF row positions 與原始 row refs。"""

    fold_id: str
    selected_positions: NDArray[np.int64]
    selected_refs: NDArray[np.int64]
    full_row_count: int


@dataclass(frozen=True)
class _DerivedCapacityPreflight:
    """同時記錄 repo output 與 frozen store 所在 filesystem 的容量。"""

    output: StorageCapacityPreflight
    source: StorageCapacityPreflight

    def as_dict(self) -> dict[str, Any]:
        payload = self.output.as_dict()
        payload["source_drive_preflight"] = self.source.as_dict()
        payload["all_probe_within_budget"] = bool(
            self.output.within_budget and self.source.within_budget
        )
        return payload


def build_allocation_ooc_release(
    request: AllocationOOCReleaseRequest,
) -> AllocationOOCReleasePublication:
    """將一個已完成 minimal OOC run 發布成 daily 可載入的 shadow release。"""

    training_path = request.training_manifest_path.resolve()
    training = _read_json(training_path)
    _validate_training_manifest(training, training_path)
    training_hash = _required_sha(training.get("manifest_hash"), "manifest_hash")
    run_root = training_path.parent.resolve()
    store_path = _resolve_store_path(training, run_root)
    store = _NumericStore(store_path)
    _validate_training_store_binding(training, store)

    horizon = _validate_minimal_profile(training, store)
    packs = _normalise_store_packs(store.manifest.get("feature_packs"))
    feature_order = tuple(
        feature_id
        for _pack_id, feature_ids in packs
        for feature_id in feature_ids
    )
    order_hash = feature_order_hash(feature_order)
    source_hashes = _normalise_hash_pairs(
        store.manifest.get("source_manifest_hashes"),
        field_name="source_manifest_hashes",
    )

    final_entries = _validate_final_base_entries(
        training=training,
        run_root=run_root,
        store=store,
        packs=packs,
        horizon=horizon,
    )
    oof_entries = _validate_oof_entries(
        training=training,
        run_root=run_root,
        store=store,
        packs=packs,
        horizon=horizon,
    )
    final_meta = _validate_final_meta(
        training=training,
        run_root=run_root,
        store=store,
        expert_keys=tuple(
            f"{pack_id}|h{horizon}|ridge_logistic"
            for pack_id, _feature_ids in packs
        ),
    )
    strategies = {
        _required_text(item.get("preprocessing_strategy"), "preprocessing_strategy")
        for item in final_entries.values()
    }
    if len(strategies) != 1:
        raise ValueError("minimal OOC release requires one frozen preprocessor strategy")
    strategy = next(iter(strategies))

    mapping, calibrator_evidence = _fit_ooc_calibrator(
        training_hash=training_hash,
        store=store,
        oof_entries=oof_entries,
        pack_ids=tuple(pack_id for pack_id, _feature_ids in packs),
        horizon=horizon,
        batch_size=request.batch_size,
    )
    model_payload = _build_model_payload(
        training_hash=training_hash,
        store=store,
        packs=packs,
        horizon=horizon,
        final_entries=final_entries,
        final_meta=final_meta,
        rank_contract=validate_rank_contract(
            training.get("rank_contract", DEFAULT_RANK_CONTRACT),
            field_name="training.rank_contract",
        ),
        family_weight_policy=validate_family_weight_policy(
            training.get(
                "family_weight_policy",
                FAMILY_WEIGHT_POLICY_LEGACY_UNKNOWN,
            ),
            field_name="training.family_weight_policy",
        ),
    )
    model_bytes = _joblib_bytes(model_payload)
    model_hash = bytes_hash(model_bytes)

    release_identity_seed = {
        "training_manifest_hash": training_hash,
        "model_id": request.model_id,
        "store_manifest_hash": _required_sha(
            store.manifest.get("manifest_hash"),
            "store.manifest_hash",
        ),
        "feature_order_hash": order_hash,
        "calibration_id": str(calibrator_evidence["calibration_id"]),
    }
    release_id = "allocation-ooc-linear-" + payload_hash(
        release_identity_seed
    )[len(_SHA256_PREFIX) : len(_SHA256_PREFIX) + 16]

    preprocessor, preprocessor_bytes = _build_preprocessor_binding(
        model_id=request.model_id,
        strategy=strategy,
        order_hash=order_hash,
        training_hash=training_hash,
    )
    calibrator = IntegerProbabilityCalibrator.create(
        calibration_id=str(calibrator_evidence["calibration_id"]),
        model_id=request.model_id,
        feature_order_hash=order_hash,
        mapping_bp=mapping,
        fit_fold_ids=tuple(
            str(item) for item in calibrator_evidence["fit_fold_ids"]
        ),
    )
    calibrator_bytes = _json_bytes(calibrator.to_dict())
    calibration_binding = CalibrationBinding(
        calibration_id=calibrator.calibration_id,
        model_id=request.model_id,
        method="isotonic_integer_bp",
        application="external_integer_bp",
        feature_order_hash=order_hash,
        artifact_file=_CALIBRATOR_FILE,
        artifact_hash=bytes_hash(calibrator_bytes),
        fit_fold_ids=calibrator.fit_fold_ids,
    )
    missing_policy = MissingPolicyBinding.create(policy_id=request.policy_id)
    release = AllocationReleaseManifest.create(
        release_id=release_id,
        model_id=request.model_id,
        dataset_id=_required_text(
            store.manifest.get("dataset_id"),
            "store.dataset_id",
        ),
        training_manifest_hash=training_hash,
        artifact_file=_MODEL_ARTIFACT_FILE,
        artifact_hash=model_hash,
        dataset_identity_hash=_required_sha(
            store.manifest.get("dataset_identity_hash"),
            "store.dataset_identity_hash",
        ),
        feature_registry_hash=_required_sha(
            store.manifest.get("feature_registry_hash"),
            "store.feature_registry_hash",
        ),
        source_manifest_hashes=source_hashes,
        feature_order=feature_order,
        preprocessor=preprocessor,
        calibration=calibration_binding,
        missing_policy=missing_policy,
    )
    release_manifest_bytes = _json_bytes(release.to_dict())
    evidence_payload = dict(calibrator_evidence)
    evidence_payload.update(
        {
            "schema_version": "allocation-ml-calibration-evidence.v1",
            "model_id": request.model_id,
            "release_id": release.release_id,
            "release_identity_hash": release.release_identity_hash,
            "artifact_hash": model_hash,
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
            "production_action_allowed": False,
            "broker_order_allowed": False,
        }
    )
    evidence_bytes = _json_bytes(_with_hash(evidence_payload, "evidence_hash"))
    compatibility_manifest = _compatibility_manifest(
        release=release,
        store=store,
        training_hash=training_hash,
        horizon=horizon,
        calibration_evidence=evidence_payload,
    )

    release_root = request.output_root.resolve()
    release_root.mkdir(parents=True, exist_ok=True)
    _commit_immutable(release_root / _MODEL_ARTIFACT_FILE, model_bytes)
    _commit_immutable(release_root / _PREPROCESSOR_FILE, preprocessor_bytes)
    _commit_immutable(release_root / _CALIBRATOR_FILE, calibrator_bytes)
    _commit_immutable(release_root / _EVIDENCE_FILE, evidence_bytes)
    # release manifest 是 adapter 的 commit marker；daily legacy loader 會
    # 在進入 adapter 前先讀取相容 wrapper。
    _commit_immutable(
        release_root / "release_manifest.json",
        release_manifest_bytes,
    )
    _commit_immutable(
        release_root / _TRAINING_COMPAT_FILE,
        _json_bytes(compatibility_manifest),
    )
    return AllocationOOCReleasePublication(
        release_root=release_root,
        release_manifest_path=release_root / "release_manifest.json",
        release_identity_hash=release.release_identity_hash,
        model_artifact_path=release_root / _MODEL_ARTIFACT_FILE,
        model_artifact_hash=model_hash,
        calibration_id=calibrator.calibration_id,
        calibration_fit_fold_ids=calibrator.fit_fold_ids,
        calibration_fit_row_count=int(calibrator_evidence["fit_row_count"]),
    )


# 額外 alias 讓採用 OOC training service 名詞順序的 caller 也能找到 producer。
build_ooc_allocation_release = build_allocation_ooc_release


def preflight_allocation_derived_ooc_release(
    request: AllocationDerivedOOCReleaseRequest,
) -> Mapping[str, Any]:
    """只讀檢查 derived selection、來源 custody 與容量，不取得 heavy lock。"""

    context = _load_derived_context(request)
    capacity = _run_derived_capacity_preflight(
        context,
        stage="derived_ooc_preflight",
    )
    return {
        "status": "preflight_passed",
        "parent_training_manifest_hash": context.parent_hash,
        "parent_store_manifest_hash": context.store.manifest["manifest_hash"],
        "derived_identity_hash": context.derived_identity_hash,
        "parent_rank_contract": context.selection_lineage[
            "parent_rank_contract"
        ],
        "rank_contract": context.rank_contract,
        "family_weight_policy": context.family_weight_policy,
        "selected_horizon": context.horizon,
        "selected_fold_ids": list(context.selected_fold_ids),
        "heldout_fold_id": context.heldout_fold_id,
        "selected_oof_artifact_count": context.selected_oof_artifact_count,
        "selected_oof_row_count": context.selected_oof_row_count,
        "selected_oof_bytes": context.selected_oof_bytes,
        "memory_budget_mb": request.memory_budget_mb,
        "capacity_preflight": capacity.as_dict(),
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "production_action_allowed": False,
        "broker_order_allowed": False,
    }


def build_allocation_derived_ooc_release(
    request: AllocationDerivedOOCReleaseRequest,
) -> AllocationDerivedOOCReleasePublication:
    """從 immutable full parent 選取線性 heads，建立 derived shadow release。

    parent 的 base/OОF 檔案只讀重用；只有 derived meta、校準、release sidecar
    寫入 ``request.output_root``。heldout fold 的 base 與 meta replay 在 fit
    前已固定，final base/meta 不會被拿來冒充該 fold 的 OOS 輸出。
    """

    context = _load_derived_context(request)
    capacity = _run_derived_capacity_preflight(
        context,
        stage="derived_ooc_preflight",
    )
    reservation = None
    if request.acquire_heavy_lock:
        lock_path = resolve_heavy_chain_lock_path(
            context.parent_path,
            explicit_path=request.heavy_lock_path,
        )
        if lock_path is None:
            lock_path = _default_derived_lock_path(context.parent_path)
        reservation = acquire_heavy_chain_reservation(lock_path)
        if reservation is None:
            raise StorageCapacityError(
                "derived OOC heavy-chain reservation is unavailable",
                preflight={
                    "stage": "derived_ooc_lock",
                    "lock_path": str(lock_path.resolve()),
                    "blockers": ["heavy_chain_reservation_unavailable"],
                },
            )
        try:
            # 取得同一條 raw／Direct/OOC lock 後必須重新確認 free headroom。
            capacity = _run_derived_capacity_preflight(
                context,
                stage="derived_ooc_locked_recheck",
            )
            return _build_derived_release(context, capacity)
        finally:
            release_heavy_chain_reservation(reservation)
    return _build_derived_release(context, capacity)


def _load_derived_context(
    request: AllocationDerivedOOCReleaseRequest,
) -> _DerivedContext:
    parent_path = request.parent_training_manifest_path.resolve()
    parent = _read_json(parent_path)
    _validate_training_manifest(parent, parent_path)
    parent_hash = _required_sha(parent.get("manifest_hash"), "manifest_hash")
    parent_rank_contract = validate_rank_contract(
        parent.get("rank_contract", DEFAULT_RANK_CONTRACT),
        field_name="parent.rank_contract",
    )
    rank_contract = validate_rank_contract(
        request.rank_contract,
        field_name="request.rank_contract",
    )
    family_weight_policy = validate_family_weight_policy(
        request.family_weight_policy,
        field_name="request.family_weight_policy",
    )
    parent_run_root = parent_path.parent.resolve()
    store_path = _resolve_store_path(parent, parent_run_root)
    store = _NumericStore(store_path)
    _validate_training_store_binding(parent, store)
    _validate_derived_parent_selection(parent, store, request.horizon)
    _validate_derived_output_root(request.output_root, parent_run_root, store_path)

    packs = _normalise_store_packs(store.manifest.get("feature_packs"))
    if not packs:
        raise ValueError("derived release requires non-empty feature packs")
    if len(store.folds) < request.heldout_fold_count:
        raise ValueError("derived release lacks the required heldout fold")
    selected_folds = tuple(
        dict(fold) for fold in store.folds[: request.heldout_fold_count]
    )
    selected_fold_ids = tuple(
        _required_text(fold.get("fold_id"), "selected.fold_id")
        for fold in selected_folds
    )
    if len(selected_fold_ids) != len(set(selected_fold_ids)):
        raise ValueError("derived selected fold IDs must be unique")
    heldout_fold_id = selected_fold_ids[-1]

    oof_entries = _validate_derived_oof_entries(
        parent=parent,
        run_root=parent_run_root,
        store=store,
        packs=packs,
        horizon=request.horizon,
        selected_fold_ids=selected_fold_ids,
    )
    final_entries = _validate_derived_final_entries(
        parent=parent,
        run_root=parent_run_root,
        store=store,
        packs=packs,
        horizon=request.horizon,
    )
    source_hashes = _normalise_hash_pairs(
        store.manifest.get("source_manifest_hashes"),
        field_name="source_manifest_hashes",
    )
    expert_ids = tuple(
        f"{pack_id}|h{request.horizon}|ridge_logistic"
        for pack_id, _feature_ids in packs
    )
    oof_sources = [
        {
            "fold_id": fold_id,
            "expert_id": expert_id,
            "manifest_hash": _required_sha(
                oof_entries[(fold_id, expert_id)].get("manifest_hash"),
                "selected_oof.manifest_hash",
            ),
        }
        for fold_id in selected_fold_ids
        for expert_id in expert_ids
    ]
    final_sources = [
        {
            "expert_id": expert_id,
            "manifest_hash": _required_sha(
                final_entries[expert_id].get("manifest_hash"),
                "selected_final.manifest_hash",
            ),
        }
        for expert_id in expert_ids
    ]
    selected_oof_row_count = sum(
        _required_int(
            artifact.get("test_row_count"),
            "selected_oof.test_row_count",
        )
        for artifact in oof_entries.values()
    )
    selected_oof_bytes = sum(
        _required_int(item.get("byte_count"), "selected_oof.byte_count")
        for artifact in oof_entries.values()
        for item in _mapping_list(
            artifact.get("artifacts"),
            "selected_oof.artifacts",
        )
    )
    selection_lineage: dict[str, Any] = {
        "schema_version": "allocation-ooc-derived-selection.v1",
        "parent_training_manifest_hash": parent_hash,
        "parent_run_id": _required_text(parent.get("run_id"), "parent.run_id"),
        "parent_store_manifest_hash": _required_sha(
            store.manifest.get("manifest_hash"),
            "parent.store_manifest_hash",
        ),
        "parent_store_manifest_file_hash": store.manifest_file_hash,
        "selected_horizon": request.horizon,
        "selected_algorithm": "ridge_logistic",
        "selected_feature_pack_ids": [pack_id for pack_id, _ in packs],
        "selected_fold_ids": list(selected_fold_ids),
        "meta_fit_fold_ids": list(selected_fold_ids[:-1]),
        "calibration_fit_fold_ids": list(selected_fold_ids[:-1]),
        "heldout_fold_id": heldout_fold_id,
        "expert_vector_width": EXPERT_VECTOR_WIDTH,
        "parent_rank_contract": parent_rank_contract,
        "rank_contract": rank_contract,
        "family_weight_policy": family_weight_policy,
        "meta_probability_input": "raw_oof",
        "parent_final_meta_reused": False,
        "final_base_source": "parent_final_base_expert",
        "heldout_base_source": "parent_base_oof_expert",
        "selected_oof_artifacts": oof_sources,
        "selected_final_base_artifacts": final_sources,
        "complexity_policy": dict(_MINIMAL_COMPLEXITY_POLICY),
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
    }
    identity_seed = {
        "selection_lineage": selection_lineage,
        "source_manifest_hashes": [list(item) for item in source_hashes],
        "selected_oof_row_count": selected_oof_row_count,
        "selected_oof_bytes": selected_oof_bytes,
    }
    return _DerivedContext(
        request=request,
        parent_path=parent_path,
        parent=parent,
        parent_hash=parent_hash,
        parent_run_root=parent_run_root,
        store_path=store_path,
        store=store,
        packs=packs,
        horizon=request.horizon,
        selected_folds=selected_folds,
        selected_fold_ids=selected_fold_ids,
        heldout_fold_id=heldout_fold_id,
        oof_entries=oof_entries,
        final_entries=final_entries,
        source_hashes=source_hashes,
        selection_lineage=selection_lineage,
        rank_contract=rank_contract,
        family_weight_policy=family_weight_policy,
        derived_identity_hash=payload_hash(identity_seed),
        selected_oof_artifact_count=len(oof_entries),
        selected_oof_row_count=selected_oof_row_count,
        selected_oof_bytes=selected_oof_bytes,
    )


def _validate_derived_parent_selection(
    parent: Mapping[str, Any],
    store: _NumericStore,
    horizon: int,
) -> None:
    validate_rank_contract(
        parent.get("rank_contract", DEFAULT_RANK_CONTRACT),
        field_name="parent.rank_contract",
    )
    algorithms = parent.get("algorithms")
    if not isinstance(algorithms, list) or "ridge_logistic" not in algorithms:
        raise ValueError("derived release requires parent ridge_logistic heads")
    horizons = parent.get("horizons")
    if not isinstance(horizons, list) or horizon not in horizons:
        raise ValueError("derived release horizon is absent from parent")
    if horizon not in store.horizons:
        raise ValueError("derived release horizon is absent from frozen store")
    run_identity = parent.get("run_identity")
    if isinstance(run_identity, dict):
        identity_algorithms = run_identity.get("algorithms")
        identity_horizons = run_identity.get("horizons")
        if identity_algorithms != algorithms or identity_horizons != horizons:
            raise ValueError("parent run identity does not match selection")
    if parent.get("formal_oos_allowed") is not False:
        raise ValueError("derived parent cannot authorize formal OOS")
    if parent.get("production_alpha_bp") != 0:
        raise ValueError("derived parent production alpha must remain zero")


def _validate_derived_output_root(
    output_root: Path,
    parent_run_root: Path,
    store_path: Path,
) -> None:
    root = output_root.resolve()
    if root == parent_run_root or root.is_relative_to(parent_run_root):
        raise ValueError("derived output root must be outside parent run")
    if store_path.drive.upper() == "D:" and root.drive.upper() == "D:":
        raise ValueError("derived output must not write to the Direct D drive")
    if root.exists() and not root.is_dir():
        raise ValueError("derived output root must be a directory")


def _validate_derived_oof_entries(
    *,
    parent: Mapping[str, Any],
    run_root: Path,
    store: _NumericStore,
    packs: tuple[tuple[str, tuple[str, ...]], ...],
    horizon: int,
    selected_fold_ids: tuple[str, ...],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    summaries = _mapping_list(parent.get("base_experts"), "parent.base_experts")
    expected_ids = {
        (fold_id, f"{pack_id}|h{horizon}|ridge_logistic")
        for fold_id in selected_fold_ids
        for pack_id, _feature_ids in packs
    }
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    fold_by_id = {
        _required_text(fold.get("fold_id"), "store.fold_id"): fold
        for fold in store.folds
    }
    for summary in summaries:
        if (
            summary.get("fold_id") not in selected_fold_ids
            or summary.get("algorithm") != "ridge_logistic"
            or summary.get("horizon_trading_days") != horizon
        ):
            continue
        artifact = _load_training_artifact(summary, run_root)
        if artifact.get("artifact_kind") != "base_oof_expert":
            raise ValueError("derived selection requires base OOF artifacts")
        if artifact.get("algorithm") != "ridge_logistic":
            raise ValueError("derived OOF algorithm does not match selection")
        if artifact.get("horizon_trading_days") != horizon:
            raise ValueError("derived OOF horizon does not match selection")
        fold_id = _required_text(artifact.get("fold_id"), "derived_oof.fold_id")
        expert_id = _required_text(
            artifact.get("expert_id"),
            "derived_oof.expert_id",
        )
        key = (fold_id, expert_id)
        if key not in expected_ids or key in result:
            raise ValueError("derived OOF expert identity coverage is invalid")
        pack_id = _required_text(artifact.get("pack_id"), "derived_oof.pack_id")
        if expert_id != f"{pack_id}|h{horizon}|ridge_logistic":
            raise ValueError("derived OOF expert pack identity is invalid")
        if artifact.get("store_manifest_hash") != store.manifest.get("manifest_hash"):
            raise ValueError("derived OOF/store manifest hash mismatch")
        fold = fold_by_id[fold_id]
        expected_rows = _required_int(
            _as_mapping(fold.get("test"), "store.test").get("row_count"),
            "store.test.row_count",
        )
        if artifact.get("test_row_count") != expected_rows:
            raise ValueError("derived OOF test row count differs from fold refs")
        if artifact.get("oof_shape") != [expected_rows, EXPERT_VECTOR_WIDTH]:
            raise ValueError("derived OOF shape is invalid")
        if artifact.get("oof_dtype") != OOF_DTYPE.str:
            raise ValueError("derived OOF dtype is invalid")
        if artifact.get("label_maturity_filter_applied_before_feature_fit") is not True:
            raise ValueError("derived OOF maturity custody is missing")
        if artifact.get("full_train_rows_fit") is not True:
            raise ValueError("derived linear OOF must fit all mature train rows")
        _validate_head_records(artifact, require_oof=True)
        result[key] = artifact
    if set(result) != expected_ids:
        raise ValueError("derived OOF expert identity coverage is incomplete")
    return result


def _validate_derived_final_entries(
    *,
    parent: Mapping[str, Any],
    run_root: Path,
    store: _NumericStore,
    packs: tuple[tuple[str, tuple[str, ...]], ...],
    horizon: int,
) -> dict[str, Mapping[str, Any]]:
    summaries = _mapping_list(
        parent.get("final_base_experts"),
        "parent.final_base_experts",
    )
    expected_ids = {
        f"{pack_id}|h{horizon}|ridge_logistic"
        for pack_id, _feature_ids in packs
    }
    result: dict[str, Mapping[str, Any]] = {}
    for summary in summaries:
        if (
            summary.get("algorithm") != "ridge_logistic"
            or summary.get("horizon_trading_days") != horizon
        ):
            continue
        artifact = _load_training_artifact(summary, run_root)
        if artifact.get("artifact_kind") != "final_base_expert":
            raise ValueError("derived selection requires final base artifacts")
        if artifact.get("algorithm") != "ridge_logistic":
            raise ValueError("derived final algorithm does not match selection")
        if artifact.get("horizon_trading_days") != horizon:
            raise ValueError("derived final horizon does not match selection")
        if artifact.get("fold_id") != "final":
            raise ValueError("derived final base fold must be final")
        if artifact.get("store_manifest_hash") != store.manifest.get("manifest_hash"):
            raise ValueError("derived final base/store manifest hash mismatch")
        expert_id = _required_text(
            artifact.get("expert_id"),
            "derived_final.expert_id",
        )
        if expert_id not in expected_ids or expert_id in result:
            raise ValueError("derived final base identity coverage is invalid")
        if artifact.get("full_train_rows_fit") is not True:
            raise ValueError("derived final base must be a frozen linear fit")
        _validate_head_records(artifact, require_oof=False)
        result[expert_id] = artifact
    if set(result) != expected_ids:
        raise ValueError("derived final base identity coverage is incomplete")
    return result


def _run_derived_capacity_preflight(
    context: _DerivedContext,
    *,
    stage: str,
) -> _DerivedCapacityPreflight:
    request = context.request
    budget = MLStorageCapacityBudget(
        persistent_new_bytes_budget=request.persistent_new_bytes_budget,
        temporary_peak_bytes_budget=request.temporary_peak_bytes_budget,
        safety_reserve_bytes=request.safety_reserve_bytes,
    )
    output_root = request.output_root.resolve()
    current_output_bytes = directory_size_bytes(output_root)
    output_capacity = preflight_capacity(
        probe_path=request.output_root.resolve(),
        budget=budget,
        stage=stage,
        persistent_roots=(output_root,),
        # 以當前已寫入 bytes 更新估算，讓 meta streaming 每次 batch 都能
        # 在超過 1 GiB 前停止，而非只在最後 commit 才發現超額。
        persistent_new_bytes_estimate=max(
            _DERIVED_PERSISTENT_ESTIMATE,
            current_output_bytes,
        ),
        temporary_peak_bytes_observed=_DERIVED_TEMPORARY_ESTIMATE,
    )
    # source store 只讀，但它所在的 Direct filesystem 仍須獨立保留同一
    # safety/headroom；不能以 C: repo output 的 free bytes 代替 D: 查核。
    source_capacity = preflight_capacity(
        probe_path=context.store_path,
        budget=budget,
        stage=f"{stage}_source_drive",
        persistent_roots=(),
        persistent_new_bytes_estimate=0,
        temporary_peak_bytes_observed=0,
    )
    return _DerivedCapacityPreflight(
        output=output_capacity,
        source=source_capacity,
    )


def _default_derived_lock_path(parent_path: Path) -> Path:
    run_root = parent_path.parent.resolve()
    return heavy_chain_lock_path(run_root.parent.parent.parent)


def _prepare_derived_output_root(root: Path) -> None:
    if root.exists():
        if not root.is_dir():
            raise ValueError("derived output root must be a directory")
        if any(root.iterdir()):
            raise ValueError(
                "derived output root must be empty for immutable publication"
            )
    else:
        root.mkdir(parents=True, exist_ok=True)


def _derived_meta_fit_request(
    context: _DerivedContext,
) -> AllocationOutOfCoreTrainingRequest:
    identity = context.parent.get("run_identity")
    ridge_alpha_bp = 100
    logistic_iterations = 6
    if isinstance(identity, dict):
        raw_alpha = identity.get("ridge_alpha_bp", ridge_alpha_bp)
        raw_iterations = identity.get(
            "logistic_iterations",
            logistic_iterations,
        )
        if (
            isinstance(raw_alpha, bool)
            or not isinstance(raw_alpha, int)
            or raw_alpha <= 0
        ):
            raise ValueError("parent ridge alpha is invalid")
        if (
            isinstance(raw_iterations, bool)
            or not isinstance(raw_iterations, int)
            or raw_iterations <= 0
        ):
            raise ValueError("parent logistic iterations are invalid")
        ridge_alpha_bp = raw_alpha
        logistic_iterations = raw_iterations
    return AllocationOutOfCoreTrainingRequest(
        store_manifest_path=context.store_path,
        output_root=context.request.output_root.resolve(),
        algorithms=("ridge_logistic",),
        horizons=(context.horizon,),
        batch_size=context.request.batch_size,
        workers=1,
        memory_budget_mb=context.request.memory_budget_mb,
        ridge_alpha_bp=ridge_alpha_bp,
        logistic_iterations=logistic_iterations,
        resume=False,
        training_profile="minimal_linear_shadow",
        complexity_policy=dict(_MINIMAL_COMPLEXITY_POLICY),
        rank_contract=context.rank_contract,
        family_weight_policy=context.family_weight_policy,
    )


def _derived_meta_selections(
    context: _DerivedContext,
    *,
    folds: Sequence[Mapping[str, Any]],
    cutoff: str,
) -> tuple[_DerivedMetaSelection, ...]:
    result: list[_DerivedMetaSelection] = []
    for fold in folds:
        fold_id = _required_text(fold.get("fold_id"), "meta.fold_id")
        refs = context.store.open_fold_refs(fold, "test")
        try:
            positions = np.asarray(
                context.store.mature_positions(refs, cutoff=cutoff),
                dtype=np.int64,
            )
            selected_refs = np.asarray(refs[positions], dtype=np.int64)
            full_row_count = len(refs)
        finally:
            _close_memmap(refs)
        result.append(
            _DerivedMetaSelection(
                fold_id=fold_id,
                selected_positions=positions,
                selected_refs=selected_refs,
                full_row_count=full_row_count,
            )
        )
    total = sum(len(item.selected_positions) for item in result)
    if total < 10:
        raise ValueError("derived meta allocator lacks ten mature prior OOF rows")
    return tuple(result)


def _derived_meta_batch_factory(
    context: _DerivedContext,
    *,
    expert_ids: tuple[str, ...],
    folds: Sequence[Mapping[str, Any]],
    cutoff: str,
    batch_size: int,
    capacity_checkpoint: Callable[[], None] | None = None,
) -> tuple[
    Callable[[], Iterable[tuple[NDArray[Any], NDArray[np.int64]]]],
    int,
]:
    selections = _derived_meta_selections(
        context,
        folds=folds,
        cutoff=cutoff,
    )
    by_key = {
        (selection.fold_id, expert_id): context.oof_entries[
            (selection.fold_id, expert_id)
        ]
        for selection in selections
        for expert_id in expert_ids
    }

    def batches() -> Iterable[tuple[NDArray[Any], NDArray[np.int64]]]:
        for selection in selections:
            oof_mmaps: list[np.memmap] = []
            try:
                for expert_id in expert_ids:
                    artifact = by_key[(selection.fold_id, expert_id)]
                    directory = _artifact_directory(artifact)
                    row_count = _required_int(
                        artifact.get("test_row_count"),
                        "derived_meta.test_row_count",
                    )
                    if row_count != selection.full_row_count:
                        raise ValueError(
                            "derived meta OOF row count differs from fold refs"
                        )
                    oof_mmaps.append(
                        np.memmap(
                            directory / "oof.i32",
                            dtype=OOF_DTYPE,
                            mode="r",
                            shape=(row_count, EXPERT_VECTOR_WIDTH),
                        )
                    )
                selection_fold = next(
                    fold
                    for fold in context.selected_folds
                    if fold.get("fold_id") == selection.fold_id
                )
                selection_refs = context.store.open_fold_refs(
                    selection_fold,
                    "test",
                )
                try:
                    rank_columns = [
                        _rebuild_rank_column(
                            store=context.store,
                            test_refs=selection_refs,
                            oof=oof,
                            rank_contract=context.rank_contract,
                        )
                        for oof in oof_mmaps
                    ]
                finally:
                    _close_memmap(selection_refs)
                for start in range(
                    0,
                    len(selection.selected_positions),
                    batch_size,
                ):
                    stop = min(
                        len(selection.selected_positions),
                        start + batch_size,
                    )
                    positions = selection.selected_positions[start:stop]
                    if capacity_checkpoint is not None:
                        capacity_checkpoint()
                    matrix = np.empty(
                        (len(positions), len(expert_ids) * EXPERT_VECTOR_WIDTH),
                        dtype=np.float32,
                    )
                    for expert_index, oof in enumerate(oof_mmaps):
                        column_start = expert_index * EXPERT_VECTOR_WIDTH
                        column_stop = column_start + EXPERT_VECTOR_WIDTH
                        block = np.asarray(
                            oof[positions, :],
                            dtype=np.float32,
                        )
                        block[:, len(EXPERT_HEAD_IDS)] = rank_columns[
                            expert_index
                        ][positions]
                        matrix[:, column_start:column_stop] = block
                    yield (
                        matrix,
                        np.asarray(
                            selection.selected_refs[start:stop],
                            dtype=np.int64,
                        ),
                    )
            finally:
                for oof in oof_mmaps:
                    _close_memmap(oof)

    return batches, sum(len(item.selected_positions) for item in selections)


def _rebuild_rank_column(
    *,
    store: _NumericStore,
    test_refs: NDArray[np.integer[Any]],
    oof: NDArray[np.integer[Any]],
    rank_contract: str,
) -> NDArray[np.int32]:
    """從 frozen base OOF 依每個 decision date 重建 rank 欄位。

    derived meta 必須使用與 inference 相同的 rank contract；直接沿用
    parent ``oof.i32`` 會把 parent 舊版 rank policy 偷渡進新 derived fit。
    """

    if len(oof) != len(test_refs):
        raise ValueError("rank rebuild OOF/ref row count mismatch")
    rank_column = len(EXPERT_HEAD_IDS)
    grouped: dict[str, list[tuple[int, str, int]]] = {}
    for position, decision_date, row_id in store.iter_decision_dates(test_refs):
        tie_key = row_id.rsplit(":", 1)[-1]
        grouped.setdefault(decision_date, []).append(
            (int(oof[position, 0]), tie_key, position)
        )
    result = np.empty(len(test_refs), dtype=np.int32)
    covered = np.zeros(len(test_refs), dtype=np.bool_)
    for values in grouped.values():
        ranks = rank_values_bp(
            tuple(item[0] for item in values),
            tuple(item[1] for item in values),
            rank_contract=rank_contract,
        )
        for item, rank in zip(values, ranks):
            result[item[2]] = rank
            covered[item[2]] = True
    if len(result) and not bool(np.all(covered)):
        raise ValueError("rank rebuild did not cover every OOF row")
    # 觸發使用者可讀的欄位契約檢查，避免 unused local 導致 rank 欄位錯位。
    if rank_column >= oof.shape[1]:
        raise ValueError("rank column is outside expert vector")
    return result


def _read_selected_oof_matrix(
    context: _DerivedContext,
    *,
    expert_ids: tuple[str, ...],
    fold: Mapping[str, Any],
    batch_size: int,
) -> tuple[np.ndarray, np.ndarray]:
    fold_id = _required_text(fold.get("fold_id"), "selected_oof.fold_id")
    refs_map = _as_mapping(fold.get("test"), "selected_oof.test")
    row_count = _required_int(refs_map.get("row_count"), "selected_oof.row_count")
    refs = context.store.open_fold_refs(fold, "test")
    try:
        refs_array = np.asarray(refs, dtype=np.int64).copy()
    finally:
        _close_memmap(refs)
    if len(refs_array) != row_count:
        raise ValueError("selected OOF refs row count mismatch")
    matrix = np.empty(
        (row_count, len(expert_ids) * EXPERT_VECTOR_WIDTH),
        dtype=np.float32,
    )
    for expert_index, expert_id in enumerate(expert_ids):
        artifact = context.oof_entries[(fold_id, expert_id)]
        directory = _artifact_directory(artifact)
        oof = np.memmap(
            directory / "oof.i32",
            dtype=OOF_DTYPE,
            mode="r",
            shape=(row_count, EXPERT_VECTOR_WIDTH),
        )
        try:
            rank_column_values = _rebuild_rank_column(
                store=context.store,
                test_refs=refs_array,
                oof=oof,
                rank_contract=context.rank_contract,
            )
            column_start = expert_index * EXPERT_VECTOR_WIDTH
            column_stop = column_start + EXPERT_VECTOR_WIDTH
            for start in range(0, row_count, batch_size):
                stop = min(row_count, start + batch_size)
                block = np.asarray(
                    oof[start:stop, :],
                    dtype=np.float32,
                )
                block[:, len(EXPERT_HEAD_IDS)] = rank_column_values[
                    start:stop
                ]
                matrix[start:stop, column_start:column_stop] = block
        finally:
            _close_memmap(oof)
    return refs_array, matrix


def _build_heldout_evaluation(
    context: _DerivedContext,
    *,
    meta_artifact: Mapping[str, Any],
    batch_size: int,
) -> dict[str, Any]:
    """用 heldout fold 的 parent base 與 derived meta 做獨立 frozen replay。"""

    expert_ids = tuple(
        f"{pack_id}|h{context.horizon}|ridge_logistic"
        for pack_id, _feature_ids in context.packs
    )
    heldout_fold = context.selected_folds[-1]
    replayed_matrix, base_matches, base_sources = _replay_parent_oof(
        context,
        expert_ids=expert_ids,
        fold=heldout_fold,
        batch_size=batch_size,
    )
    meta_directory = _artifact_directory(meta_artifact)
    meta_records = {
        _required_text(record.get("head_id"), "heldout.meta.head_id"): record
        for record in _mapping_list(
            meta_artifact.get("head_models"),
            "heldout.meta.head_models",
        )
    }
    meta_oof_path = meta_directory / "oof.i32"
    row_count = len(replayed_matrix)
    if meta_artifact.get("test_row_count") != row_count:
        raise ValueError("heldout meta row count differs from fold refs")
    meta_oof = np.memmap(
        meta_oof_path,
        dtype=OOF_DTYPE,
        mode="r",
        shape=(row_count, len(TARGET_FIELDS)),
    )
    try:
        replayed_meta = np.empty(
            (row_count, len(TARGET_FIELDS)),
            dtype=np.int32,
        )
        for position, field_name in enumerate(TARGET_FIELDS):
            record = meta_records[field_name]
            model = _load_joblib(
                _contained_file(
                    meta_directory,
                    _required_text(record.get("path"), "heldout.meta.path"),
                )
            )
            raw_values = _predict_numeric(model, replayed_matrix)
            if field_name == "delta_weight_bp":
                quantized = _quantize_signed(raw_values)
            elif field_name == "rebalance_worthwhile":
                quantized = _quantize_probability(raw_values)
            else:
                quantized = _quantize_non_negative(raw_values)
            replayed_meta[:, position] = quantized
        meta_matches = bool(np.array_equal(replayed_meta, np.asarray(meta_oof)))
    finally:
        _close_memmap(meta_oof)
    meta_source_hash = _required_sha(
        meta_artifact.get("manifest_hash"),
        "heldout.meta.manifest_hash",
    )
    heldout_fold_id = _required_text(
        heldout_fold.get("fold_id"),
        "heldout.fold_id",
    )
    return {
        "schema_version": "allocation-ooc-derived-heldout-evaluation.v1",
        "derived_identity_hash": context.derived_identity_hash,
        "parent_training_manifest_hash": context.parent_hash,
        "heldout_fold_id": heldout_fold_id,
        "rank_contract": context.rank_contract,
        "base_oof_rank_rebuilt_from_parent_heads": True,
        "row_count": row_count,
        "selected_expert_ids": list(expert_ids),
        "base_source_artifact_manifest_hashes": base_sources,
        "base_oof_replay_matched": base_matches,
        "meta_source_artifact_manifest_hash": meta_source_hash,
        "meta_oof_replay_matched": meta_matches,
        "final_base_not_used": True,
        "final_meta_not_used": True,
        "target_fold_label_reads": 0,
        "target_fold_excluded_from_meta_fit": True,
        "target_fold_excluded_from_calibration": True,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "production_action_allowed": False,
        "broker_order_allowed": False,
    }


def _replay_parent_oof(
    context: _DerivedContext,
    *,
    expert_ids: tuple[str, ...],
    fold: Mapping[str, Any],
    batch_size: int,
) -> tuple[np.ndarray, bool, list[str]]:
    """以 parent fold-trained model 重建 OOF matrix，不讀 target labels。"""

    fold_id = _required_text(fold.get("fold_id"), "heldout.fold_id")
    refs = context.store.open_fold_refs(fold, "test")
    try:
        refs_array = np.asarray(refs, dtype=np.int64).copy()
    finally:
        _close_memmap(refs)
    replayed = np.empty(
        (len(refs_array), len(expert_ids) * EXPERT_VECTOR_WIDTH),
        dtype=np.float32,
    )
    all_matches = True
    source_hashes: list[str] = []
    for expert_index, expert_id in enumerate(expert_ids):
        artifact = context.oof_entries[(fold_id, expert_id)]
        directory = _artifact_directory(artifact)
        records = {
            _required_text(record.get("head_id"), "heldout.base.head_id"): record
            for record in _mapping_list(
                artifact.get("head_models"),
                "heldout.base.head_models",
            )
        }
        pack_id = _required_text(artifact.get("pack_id"), "heldout.base.pack_id")
        pack = next(
            item for item in context.packs if item[0] == pack_id
        )
        feature_positions = context.store.feature_positions_for_pack(
            {"feature_ids": list(pack[1])}
        )
        raw_matrix = np.asarray(
            context.store.read_feature_batch(refs_array, feature_positions),
            dtype=np.float32,
        )
        rebuilt = np.zeros(
            (len(refs_array), EXPERT_VECTOR_WIDTH),
            dtype=np.int32,
        )
        for column, head_id in enumerate(EXPERT_HEAD_IDS):
            record = records[head_id]
            if record.get("status") == "missing":
                rebuilt[:, len(EXPERT_HEAD_IDS) + 1 + column] = 1
                continue
            model = _load_joblib(
                _contained_file(
                    directory,
                    _required_text(record.get("path"), "heldout.base.path"),
                )
            )
            rebuilt[:, column] = _quantize_head(
                head_id=head_id,
                values=_predict_numeric(model, raw_matrix),
            )
        # 排名與 parent trainer 相同，按決策日分組並以 row_id 穩定排序。
        _write_rank_column(
            store=context.store,
            test_refs=refs_array,
            oof=cast(np.memmap, rebuilt),
            rank_contract=context.rank_contract,
        )
        column_start = expert_index * EXPERT_VECTOR_WIDTH
        column_stop = column_start + EXPERT_VECTOR_WIDTH
        rebuilt_float = np.asarray(rebuilt, dtype=np.float32)
        replayed[:, column_start:column_stop] = rebuilt_float
        persisted = np.memmap(
            directory / "oof.i32",
            dtype=OOF_DTYPE,
            mode="r",
            shape=(len(refs_array), EXPERT_VECTOR_WIDTH),
        )
        try:
            all_matches = all_matches and bool(
                np.array_equal(rebuilt, np.asarray(persisted))
            )
        finally:
            _close_memmap(persisted)
        source_hashes.append(
            _required_sha(
                artifact.get("manifest_hash"),
                "heldout.base.manifest_hash",
            )
        )
        del raw_matrix, rebuilt
    return replayed, all_matches, source_hashes


def _public_artifact_summary(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """移除內部 run path，留下可審查的 immutable artifact 摘要。"""

    fields = (
        "artifact_kind",
        "artifact_path",
        "manifest_hash",
        "fold_id",
        "pack_id",
        "horizon_trading_days",
        "algorithm",
        "expert_id",
        "train_row_count",
        "test_row_count",
        "oof_shape",
        "oof_dtype",
        "training_source_fold_ids",
        "label_maturity_cutoff_exclusive",
        "expert_ids",
        "expert_vector_width",
        "rank_contract",
        "target_summary",
        "feature_family_weights_status",
        "feature_family_weights_bp",
    )
    return {
        field_name: artifact[field_name]
        for field_name in fields
        if field_name in artifact
    }


def _build_derived_release(
    context: _DerivedContext,
    capacity: Any,
) -> AllocationDerivedOOCReleasePublication:
    request = context.request
    release_root = request.output_root.resolve()
    _prepare_derived_output_root(release_root)
    fit_request = _derived_meta_fit_request(context)

    def capacity_checkpoint() -> None:
        _run_derived_capacity_preflight(
            context,
            stage="derived_meta_batch",
        )

    expert_ids = tuple(
        f"{pack_id}|h{context.horizon}|ridge_logistic"
        for pack_id, _feature_ids in context.packs
    )
    meta_folds: dict[str, Mapping[str, Any]] = {}
    for target_index in range(1, len(context.selected_folds)):
        target_fold = context.selected_folds[target_index]
        target_fold_id = _required_text(
            target_fold.get("fold_id"),
            "derived.target_fold_id",
        )
        cutoff = _required_text(
            target_fold.get("test_start"),
            "derived.target_test_start",
        )[:10]
        train_folds = context.selected_folds[:target_index]
        train_factory, train_row_count = _derived_meta_batch_factory(
            context,
            expert_ids=expert_ids,
            folds=train_folds,
            cutoff=cutoff,
            batch_size=request.batch_size,
            capacity_checkpoint=capacity_checkpoint,
        )
        test_refs, test_matrix = _read_selected_oof_matrix(
            context,
            expert_ids=expert_ids,
            fold=target_fold,
            batch_size=request.batch_size,
        )
        try:
            artifact = _fit_meta_artifact(
                request=fit_request,
                store=context.store,
                run_directory=release_root,
                final_directory=(
                    release_root
                    / "artifacts"
                    / "meta"
                    / f"fold={target_fold_id}"
                ),
                fold_id=target_fold_id,
                train_refs=None,
                test_refs=test_refs,
                train_matrix=None,
                test_matrix=cast(np.memmap, test_matrix),
                expert_ids=expert_ids,
                training_source_fold_ids=tuple(
                    _required_text(item.get("fold_id"), "derived.train_fold_id")
                    for item in train_folds
                ),
                label_maturity_cutoff_exclusive=cutoff,
                batch_size=request.batch_size,
                batch_factory=train_factory,
                train_row_count=train_row_count,
            )
        finally:
            del test_matrix, test_refs
        meta_folds[target_fold_id] = artifact

    heldout_cutoff = _required_text(
        context.selected_folds[-1].get("test_start"),
        "derived.heldout_test_start",
    )[:10]
    final_factory, final_row_count = _derived_meta_batch_factory(
        context,
        expert_ids=expert_ids,
        folds=context.selected_folds[:-1],
        cutoff=heldout_cutoff,
        batch_size=request.batch_size,
        capacity_checkpoint=capacity_checkpoint,
    )
    final_meta = _fit_meta_artifact(
        request=fit_request,
        store=context.store,
        run_directory=release_root,
        final_directory=release_root / "artifacts" / "meta" / "final",
        fold_id="final",
        train_refs=None,
        test_refs=None,
        train_matrix=None,
        test_matrix=None,
        expert_ids=expert_ids,
        training_source_fold_ids=context.selected_fold_ids[:-1],
        label_maturity_cutoff_exclusive=heldout_cutoff,
        batch_size=request.batch_size,
        batch_factory=final_factory,
        train_row_count=final_row_count,
    )

    mapping, calibration_core = _fit_ooc_calibrator(
        training_hash=context.derived_identity_hash,
        store=context.store,
        oof_entries=context.oof_entries,
        pack_ids=tuple(pack_id for pack_id, _feature_ids in context.packs),
        horizon=context.horizon,
        batch_size=request.batch_size,
        fold_limit=request.heldout_fold_count,
    )
    calibration_core = dict(calibration_core)
    calibration_core.update(
        {
            "parent_training_manifest_hash": context.parent_hash,
            "derived_identity_hash": context.derived_identity_hash,
            "heldout_fold_id": context.heldout_fold_id,
            "final_meta_training_source_fold_ids": list(
                context.selected_fold_ids[:-1]
            ),
            "final_meta_label_maturity_cutoff_exclusive": heldout_cutoff,
            "final_base_not_used_for_heldout_evaluation": True,
        }
    )

    model_payload = _build_model_payload(
        training_hash=context.derived_identity_hash,
        store=context.store,
        packs=context.packs,
        horizon=context.horizon,
        final_entries=context.final_entries,
        final_meta=final_meta,
        training_profile=_DERIVED_PROFILE,
        complexity_policy=_MINIMAL_COMPLEXITY_POLICY,
        rank_contract=context.rank_contract,
        family_weight_policy=context.family_weight_policy,
    )
    model_bytes = _joblib_bytes(model_payload)
    model_hash = bytes_hash(model_bytes)

    strategies = {
        _required_text(
            item.get("preprocessing_strategy"),
            "derived.final.preprocessing_strategy",
        )
        for item in context.final_entries.values()
    }
    if len(strategies) != 1:
        raise ValueError("derived release requires one frozen preprocessor strategy")
    strategy = next(iter(strategies))
    preprocessor, preprocessor_bytes = _build_preprocessor_binding(
        model_id=request.model_id,
        strategy=strategy,
        order_hash=feature_order_hash(
            tuple(
                feature_id
                for _pack_id, feature_ids in context.packs
                for feature_id in feature_ids
            )
        ),
        training_hash=context.derived_identity_hash,
    )

    calibrator = IntegerProbabilityCalibrator.create(
        calibration_id=str(calibration_core["calibration_id"]),
        model_id=request.model_id,
        feature_order_hash=preprocessor.feature_order_hash,
        mapping_bp=mapping,
        fit_fold_ids=tuple(
            str(item) for item in calibration_core["fit_fold_ids"]
        ),
    )
    calibration_binding = CalibrationBinding(
        calibration_id=calibrator.calibration_id,
        model_id=request.model_id,
        method="isotonic_integer_bp",
        application="external_integer_bp",
        feature_order_hash=preprocessor.feature_order_hash,
        artifact_file=_CALIBRATOR_FILE,
        artifact_hash=bytes_hash(_json_bytes(calibrator.to_dict())),
        fit_fold_ids=calibrator.fit_fold_ids,
    )
    calibration_payload = dict(calibration_core)
    calibration_payload.update(
        {
            "schema_version": "allocation-ml-calibration-evidence.v1",
            "model_id": request.model_id,
            "feature_order_hash": preprocessor.feature_order_hash,
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
            "production_action_allowed": False,
            "broker_order_allowed": False,
        }
    )
    calibration_bytes = _json_bytes(
        _with_hash(calibration_payload, "evidence_hash")
    )
    calibration_evidence_hash = bytes_hash(calibration_bytes)

    heldout_evaluation = _build_heldout_evaluation(
        context,
        meta_artifact=meta_folds[context.heldout_fold_id],
        batch_size=request.batch_size,
    )
    heldout_bytes = _json_bytes(
        _with_hash(heldout_evaluation, "evaluation_hash")
    )
    heldout_hash = bytes_hash(heldout_bytes)
    capacity = _run_derived_capacity_preflight(
        context,
        stage="derived_ooc_post_fit",
    )

    meta_summary = {
        fold_id: _public_artifact_summary(artifact)
        for fold_id, artifact in meta_folds.items()
    }
    meta_summary["final"] = _public_artifact_summary(final_meta)
    bound_policy, family_weight_status = validate_family_weight_binding(
        final_meta.get("family_weight_policy", context.family_weight_policy),
        final_meta.get(
            "feature_family_weights_status",
            FAMILY_WEIGHT_STATUS_LEGACY_UNKNOWN,
        ),
        field_prefix="final_meta.feature_family_weights",
    )
    if bound_policy != context.family_weight_policy:
        raise ValueError("derived family weight policy differs from request")
    derived_body: dict[str, Any] = {
        "schema_version": "allocation-ooc-derived-training.v1",
        "status": "complete",
        "derived_run_id": (
            "allocation-derived-h5-f4-"
            + context.derived_identity_hash[len(_SHA256_PREFIX) : len(_SHA256_PREFIX) + 16]
        ),
        "derived_identity_hash": context.derived_identity_hash,
        "parent_training_manifest_hash": context.parent_hash,
        "parent_run_id": context.selection_lineage["parent_run_id"],
        "store_manifest_path": str(context.store_path),
        "store_manifest_hash": context.store.manifest["manifest_hash"],
        "store_manifest_file_hash": context.store.manifest_file_hash,
        "dataset_identity_hash": context.store.manifest["dataset_identity_hash"],
        "feature_registry_hash": context.store.manifest["feature_registry_hash"],
        "source_manifest_hashes": [list(item) for item in context.source_hashes],
        "training_profile": _DERIVED_PROFILE,
        "algorithms": ["ridge_logistic"],
        "horizons": [context.horizon],
        "rank_contract": context.rank_contract,
        "family_weight_policy": context.family_weight_policy,
        "feature_family_weights_status": family_weight_status,
        "target_summary": final_meta.get("target_summary"),
        "complexity_policy": dict(_MINIMAL_COMPLEXITY_POLICY),
        "selection_lineage": dict(context.selection_lineage),
        "selected_oof_artifact_count": context.selected_oof_artifact_count,
        "selected_oof_row_count": context.selected_oof_row_count,
        "selected_oof_bytes": context.selected_oof_bytes,
        "final_base_experts": [
            _public_artifact_summary(context.final_entries[expert_id])
            for expert_id in expert_ids
        ],
        "meta_artifacts": meta_summary,
        "final_meta_training_row_count": final_row_count,
        "calibration": {
            "calibration_id": calibration_core["calibration_id"],
            "fit_fold_ids": list(calibration_core["fit_fold_ids"]),
            "fit_row_count": calibration_core["fit_row_count"],
            "positive_row_count": calibration_core["positive_row_count"],
            "negative_row_count": calibration_core["negative_row_count"],
            "evidence_hash": calibration_evidence_hash,
        },
        "heldout_evaluation": {
            "path": _HELDOUT_EVALUATION_FILE,
            "file_hash": heldout_hash,
            "fold_id": context.heldout_fold_id,
            "base_oof_replay_matched": heldout_evaluation[
                "base_oof_replay_matched"
            ],
            "meta_oof_replay_matched": heldout_evaluation[
                "meta_oof_replay_matched"
            ],
            "final_base_not_used": heldout_evaluation["final_base_not_used"],
            "target_fold_label_reads": heldout_evaluation[
                "target_fold_label_reads"
            ],
        },
        "artifacts": {
            "model_file": _MODEL_ARTIFACT_FILE,
            "model_hash": model_hash,
            "preprocessor_file": _PREPROCESSOR_FILE,
            "preprocessor_hash": bytes_hash(preprocessor_bytes),
            "calibrator_file": _CALIBRATOR_FILE,
            "calibrator_hash": calibration_binding.artifact_hash,
            "calibration_evidence_file": _EVIDENCE_FILE,
            "calibration_evidence_hash": calibration_evidence_hash,
        },
        "capacity_preflight": capacity.as_dict(),
        "memory_budget_mb": request.memory_budget_mb,
        "persistent_new_bytes_budget": request.persistent_new_bytes_budget,
        "temporary_peak_bytes_budget": request.temporary_peak_bytes_budget,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "production_action_allowed": False,
        "broker_order_allowed": False,
    }
    derived_manifest_hash = _payload_sha(derived_body)
    derived_manifest = dict(derived_body)
    derived_manifest["manifest_hash"] = derived_manifest_hash

    release_identity_seed = {
        "derived_manifest_hash": derived_manifest_hash,
        "model_id": request.model_id,
        "store_manifest_hash": context.store.manifest["manifest_hash"],
        "feature_order_hash": preprocessor.feature_order_hash,
        "calibration_id": calibrator.calibration_id,
    }
    release_id = "allocation-derived-linear-" + payload_hash(
        release_identity_seed
    )[len(_SHA256_PREFIX) : len(_SHA256_PREFIX) + 16]
    missing_policy = MissingPolicyBinding.create(policy_id=request.policy_id)
    release = AllocationReleaseManifest.create(
        release_id=release_id,
        model_id=request.model_id,
        dataset_id=_required_text(
            context.store.manifest.get("dataset_id"),
            "derived.store.dataset_id",
        ),
        training_manifest_hash=derived_manifest_hash,
        artifact_file=_MODEL_ARTIFACT_FILE,
        artifact_hash=model_hash,
        dataset_identity_hash=_required_sha(
            context.store.manifest.get("dataset_identity_hash"),
            "derived.dataset_identity_hash",
        ),
        feature_registry_hash=_required_sha(
            context.store.manifest.get("feature_registry_hash"),
            "derived.feature_registry_hash",
        ),
        source_manifest_hashes=context.source_hashes,
        feature_order=tuple(
            feature_id
            for _pack_id, feature_ids in context.packs
            for feature_id in feature_ids
        ),
        preprocessor=preprocessor,
        calibration=calibration_binding,
        missing_policy=missing_policy,
    )
    release_manifest_bytes = _json_bytes(release.to_dict())
    compatibility_manifest = _compatibility_manifest(
        release=release,
        store=context.store,
        training_hash=derived_manifest_hash,
        horizon=context.horizon,
        calibration_evidence=calibration_payload,
        training_profile=_DERIVED_PROFILE,
        lineage=context.selection_lineage,
    )

    _commit_immutable(release_root / _MODEL_ARTIFACT_FILE, model_bytes)
    _commit_immutable(release_root / _PREPROCESSOR_FILE, preprocessor_bytes)
    _commit_immutable(
        release_root / _CALIBRATOR_FILE,
        _json_bytes(calibrator.to_dict()),
    )
    _commit_immutable(release_root / _EVIDENCE_FILE, calibration_bytes)
    _commit_immutable(release_root / _HELDOUT_EVALUATION_FILE, heldout_bytes)
    _commit_immutable(
        release_root / "release_manifest.json",
        release_manifest_bytes,
    )
    _commit_immutable(
        release_root / _TRAINING_COMPAT_FILE,
        _json_bytes(compatibility_manifest),
    )
    _commit_immutable(
        release_root / _DERIVED_TRAINING_FILE,
        _json_bytes(derived_manifest),
    )
    output_size = directory_size_bytes(release_root)
    if output_size > request.persistent_new_bytes_budget:
        raise StorageCapacityError(
            "derived release output exceeded persistent byte budget",
            preflight={
                "stage": "derived_ooc_post_write",
                "persistent_new_bytes": output_size,
                "persistent_new_bytes_budget": request.persistent_new_bytes_budget,
                "blockers": ["persistent_new_bytes_budget_exceeded"],
            },
        )
    return AllocationDerivedOOCReleasePublication(
        release_root=release_root,
        release_manifest_path=release_root / "release_manifest.json",
        derived_manifest_path=release_root / _DERIVED_TRAINING_FILE,
        derived_manifest_hash=derived_manifest_hash,
        release_identity_hash=release.release_identity_hash,
        model_artifact_path=release_root / _MODEL_ARTIFACT_FILE,
        model_artifact_hash=model_hash,
        heldout_evaluation_path=release_root / _HELDOUT_EVALUATION_FILE,
        heldout_evaluation_hash=heldout_hash,
        output_size_bytes=output_size,
        heldout_fold_id=context.heldout_fold_id,
        selected_oof_artifact_count=context.selected_oof_artifact_count,
        selected_oof_row_count=context.selected_oof_row_count,
        meta_fit_row_count=final_row_count,
        calibration_id=calibrator.calibration_id,
        calibration_fit_fold_ids=calibrator.fit_fold_ids,
        calibration_fit_row_count=int(calibration_core["fit_row_count"]),
        capacity_preflight=capacity.as_dict(),
    )


def _validate_training_manifest(
    training: Mapping[str, Any],
    path: Path,
) -> None:
    if training.get("schema_version") != _TRAINING_SCHEMA_VERSION:
        raise ValueError("unsupported OOC training schema")
    if training.get("status") != "complete":
        raise ValueError("OOC training must be complete")
    expected_hash = _required_sha(training.get("manifest_hash"), "manifest_hash")
    body = dict(training)
    body.pop("manifest_hash", None)
    if _payload_sha(body) != expected_hash:
        raise ValueError("OOC training manifest logical hash mismatch")
    if not path.is_file():
        raise FileNotFoundError(path)
    if training.get("formal_source_only") is not True:
        raise ValueError("OOC training is not a formal source-only run")
    if training.get("research_shadow_included") is not False:
        raise ValueError("OOC training is not a formal source-only run")
    for field_name in (
        "formal_oos_allowed",
        "broker_order_allowed",
    ):
        if training.get(field_name) is not False:
            raise ValueError(f"OOC training {field_name} must be false")
    if training.get("production_alpha_bp") != 0:
        raise ValueError("OOC training production alpha must remain zero")


def _validate_training_store_binding(
    training: Mapping[str, Any],
    store: _NumericStore,
) -> None:
    if training.get("store_manifest_hash") != store.manifest.get("manifest_hash"):
        raise ValueError("OOC training/store manifest hash mismatch")
    if training.get("store_manifest_file_hash") != store.manifest_file_hash:
        raise ValueError("OOC training/store manifest file hash mismatch")
    for field_name in (
        "dataset_identity_hash",
        "feature_registry_hash",
        "source_manifest_hashes",
    ):
        if _canonical_value(training.get(field_name)) != _canonical_value(
            store.manifest.get(field_name)
        ):
            raise ValueError(f"OOC training/store {field_name} mismatch")
    if _canonical_value(training.get("feature_packs")) != _canonical_value(
        store.manifest.get("feature_packs")
    ):
        raise ValueError("OOC training/store feature packs mismatch")


def _validate_minimal_profile(
    training: Mapping[str, Any],
    store: _NumericStore,
) -> int:
    if training.get("training_profile") != _PROFILE:
        raise ValueError("release builder requires minimal_linear_shadow profile")
    algorithms = training.get("algorithms")
    if algorithms != ["ridge_logistic"]:
        raise ValueError("minimal release requires ridge_logistic only")
    horizons = training.get("horizons")
    if not isinstance(horizons, list) or len(horizons) != 1:
        raise ValueError("minimal release requires exactly one horizon")
    horizon = _required_int(horizons[0], "training.horizon")
    if horizon not in store.horizons:
        raise ValueError("minimal release horizon is absent from frozen store")
    policy = training.get("complexity_policy")
    if not isinstance(policy, dict) or policy != _MINIMAL_COMPLEXITY_POLICY:
        raise ValueError("minimal release complexity policy is not bound")
    return horizon


def _validate_final_base_entries(
    *,
    training: Mapping[str, Any],
    run_root: Path,
    store: _NumericStore,
    packs: tuple[tuple[str, tuple[str, ...]], ...],
    horizon: int,
) -> dict[str, Mapping[str, Any]]:
    entries = _mapping_list(training.get("final_base_experts"), "final_base_experts")
    expected_ids = {
        f"{pack_id}|h{horizon}|ridge_logistic" for pack_id, _ in packs
    }
    if len(entries) != len(expected_ids):
        raise ValueError("final base expert coverage is incomplete")
    result: dict[str, Mapping[str, Any]] = {}
    for summary in entries:
        artifact = _load_training_artifact(summary, run_root)
        if artifact.get("artifact_kind") != "final_base_expert":
            raise ValueError("final base release requires final base artifacts")
        if artifact.get("fold_id") != "final":
            raise ValueError("final base artifact fold must be final")
        if artifact.get("algorithm") != "ridge_logistic":
            raise ValueError("final base release requires ridge_logistic")
        if artifact.get("horizon_trading_days") != horizon:
            raise ValueError("final base horizon mismatch")
        if artifact.get("store_manifest_hash") != store.manifest.get("manifest_hash"):
            raise ValueError("final base/store manifest hash mismatch")
        expert_id = _required_text(artifact.get("expert_id"), "final_base.expert_id")
        if expert_id in result or expert_id not in expected_ids:
            raise ValueError("final base expert identity coverage is invalid")
        _validate_head_records(artifact, require_oof=False)
        result[expert_id] = artifact
    if set(result) != expected_ids:
        raise ValueError("final base expert identity coverage is incomplete")
    return result


def _validate_oof_entries(
    *,
    training: Mapping[str, Any],
    run_root: Path,
    store: _NumericStore,
    packs: tuple[tuple[str, tuple[str, ...]], ...],
    horizon: int,
) -> dict[tuple[str, str], Mapping[str, Any]]:
    entries = _mapping_list(training.get("base_experts"), "base_experts")
    fold_ids = tuple(_required_text(fold.get("fold_id"), "fold_id") for fold in store.folds)
    expected_count = len(fold_ids) * len(packs)
    if len(entries) != expected_count:
        raise ValueError("base OOF expert coverage is incomplete")
    fold_by_id = {
        _required_text(fold.get("fold_id"), "fold_id"): fold
        for fold in store.folds
    }
    expected_keys = {
        (fold_id, f"{pack_id}|h{horizon}|ridge_logistic")
        for fold_id in fold_ids
        for pack_id, _ in packs
    }
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for summary in entries:
        artifact = _load_training_artifact(summary, run_root)
        if artifact.get("artifact_kind") != "base_oof_expert":
            raise ValueError("calibration requires base OOF artifacts")
        fold_id = _required_text(artifact.get("fold_id"), "base_oof.fold_id")
        expert_id = _required_text(artifact.get("expert_id"), "base_oof.expert_id")
        key = (fold_id, expert_id)
        if key not in expected_keys or key in result:
            raise ValueError("base OOF expert identity coverage is invalid")
        if artifact.get("algorithm") != "ridge_logistic":
            raise ValueError("calibration requires ridge_logistic OOF artifacts")
        if artifact.get("horizon_trading_days") != horizon:
            raise ValueError("base OOF horizon mismatch")
        if artifact.get("store_manifest_hash") != store.manifest.get("manifest_hash"):
            raise ValueError("base OOF/store manifest hash mismatch")
        fold = fold_by_id[fold_id]
        if artifact.get("label_maturity_cutoff_exclusive") != fold.get("test_start"):
            raise ValueError("base OOF maturity cutoff is not frozen to fold boundary")
        if artifact.get("label_maturity_filter_applied_before_feature_fit") is not True:
            raise ValueError("base OOF feature fit is not maturity-filtered")
        if artifact.get("full_train_rows_fit") is not True:
            raise ValueError("minimal linear OOF must fit all mature train rows")
        test_row_count = _required_int(artifact.get("test_row_count"), "base_oof.test_row_count")
        if artifact.get("oof_shape") != [test_row_count, EXPERT_VECTOR_WIDTH]:
            raise ValueError("base OOF shape is invalid")
        if artifact.get("oof_dtype") != OOF_DTYPE.str:
            raise ValueError("base OOF dtype is invalid")
        _validate_head_records(artifact, require_oof=True)
        result[key] = artifact
    if set(result) != expected_keys:
        raise ValueError("base OOF expert identity coverage is incomplete")
    return result


def _validate_final_meta(
    *,
    training: Mapping[str, Any],
    run_root: Path,
    store: _NumericStore,
    expert_keys: tuple[str, ...],
) -> Mapping[str, Any]:
    summary = training.get("final_meta")
    if not isinstance(summary, dict):
        raise TypeError("final_meta must be an object")
    artifact = _load_training_artifact(summary, run_root)
    if artifact.get("artifact_kind") != "final_meta_allocator":
        raise ValueError("release requires final meta allocator")
    if artifact.get("fold_id") != "final":
        raise ValueError("final meta fold must be final")
    if artifact.get("store_manifest_hash") != store.manifest.get("manifest_hash"):
        raise ValueError("final meta/store manifest hash mismatch")
    if _canonical_value(artifact.get("expert_ids")) != _canonical_value(list(expert_keys)):
        raise ValueError("final meta expert IDs do not match release experts")
    if _canonical_value(artifact.get("target_fields")) != _canonical_value(list(TARGET_FIELDS)):
        raise ValueError("final meta target fields do not match frozen schema")
    if artifact.get("causal_prior_fold_oof_only") is not True:
        raise ValueError("final meta causal OOF custody is missing")
    _validate_meta_head_records(artifact)
    return artifact


def _validate_head_records(
    artifact: Mapping[str, Any],
    *,
    require_oof: bool,
) -> None:
    records = _mapping_list(artifact.get("head_models"), "head_models")
    by_head = {
        _required_text(record.get("head_id"), "head_id"): record
        for record in records
    }
    if len(by_head) != len(records):
        raise ValueError("base head IDs must be unique")
    if set(by_head) != set(EXPERT_HEAD_IDS):
        raise ValueError("base head coverage is incomplete")
    for head_id, record in by_head.items():
        status = record.get("status")
        if status == "fit":
            _required_text(record.get("path"), f"{head_id}.path")
            if _required_int(record.get("fit_row_count"), f"{head_id}.fit_row_count") < 2:
                raise ValueError(f"{head_id} fit row count is too small")
        elif status == "missing":
            if head_id != "expected_sector_excess_return_bp":
                raise ValueError(f"unexpected missing base head: {head_id}")
            _required_text(record.get("missing_reason"), f"{head_id}.missing_reason")
        else:
            raise ValueError(f"unsupported base head status: {head_id}")
    if require_oof and artifact.get("test_row_count") in {None, 0}:
        raise ValueError("calibration requires non-empty OOF test rows")


def _validate_meta_head_records(artifact: Mapping[str, Any]) -> None:
    records = _mapping_list(artifact.get("head_models"), "meta.head_models")
    by_head = {
        _required_text(record.get("head_id"), "meta.head_id"): record
        for record in records
    }
    if len(by_head) != len(records):
        raise ValueError("final meta head IDs must be unique")
    if set(by_head) != set(TARGET_FIELDS):
        raise ValueError("final meta head coverage is incomplete")
    for field_name in TARGET_FIELDS:
        record = by_head[field_name]
        if record.get("status") != "fit":
            raise ValueError(f"final meta head is not fit: {field_name}")
        _required_text(record.get("path"), f"meta.{field_name}.path")
        if _required_int(record.get("fit_row_count"), f"meta.{field_name}.fit_row_count") < 2:
            raise ValueError(f"final meta fit row count is too small: {field_name}")


def _build_model_payload(
    *,
    training_hash: str,
    store: _NumericStore,
    packs: tuple[tuple[str, tuple[str, ...]], ...],
    horizon: int,
    final_entries: Mapping[str, Mapping[str, Any]],
    final_meta: Mapping[str, Any],
    training_profile: str = _PROFILE,
    complexity_policy: Mapping[str, object] = _MINIMAL_COMPLEXITY_POLICY,
    rank_contract: str = DEFAULT_RANK_CONTRACT,
    family_weight_policy: str = FAMILY_WEIGHT_POLICY_LEGACY_UNKNOWN,
) -> dict[str, Any]:
    rank_contract = validate_rank_contract(
        rank_contract,
        field_name="rank_contract",
    )
    family_weight_policy = validate_family_weight_policy(
        family_weight_policy,
        field_name="family_weight_policy",
    )
    expert_keys = tuple(
        f"{pack_id}|h{horizon}|ridge_logistic" for pack_id, _ in packs
    )
    base_models = {
        expert_id: _load_base_model_payload(
            training_hash=training_hash,
            artifact=final_entries[expert_id],
        )
        for expert_id in expert_keys
    }
    meta_models = _load_meta_model_payload(
        training_hash=training_hash,
        artifact=final_meta,
        expert_keys=expert_keys,
    )
    family_weights = _normalise_family_weights(
        final_meta.get("feature_family_weights_bp"),
        packs=packs,
    )
    bound_policy, family_weight_status = validate_family_weight_binding(
        final_meta.get(
            "family_weight_policy",
            family_weight_policy,
        ),
        final_meta.get(
            "feature_family_weights_status",
            FAMILY_WEIGHT_STATUS_LEGACY_UNKNOWN,
        ),
        field_prefix="final_meta.feature_family_weights",
    )
    if bound_policy != family_weight_policy:
        raise ValueError("final_meta family weight policy differs from request")
    target_summary = final_meta.get("target_summary")
    if target_summary is not None and not isinstance(target_summary, dict):
        raise TypeError("final_meta.target_summary must be an object")
    payload = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "dataset_id": _required_text(store.manifest.get("dataset_id"), "dataset_id"),
        "dataset_identity_hash": _required_sha(
            store.manifest.get("dataset_identity_hash"),
            "dataset_identity_hash",
        ),
        "dataset_manifest_file_hash": _required_sha(
            store.manifest.get("dataset_manifest_file_hash"),
            "dataset_manifest_file_hash",
        ),
        "feature_registry_hash": _required_sha(
            store.manifest.get("feature_registry_hash"),
            "feature_registry_hash",
        ),
        "source_manifest_hashes": [list(item) for item in _normalise_hash_pairs(
            store.manifest.get("source_manifest_hashes"),
            field_name="source_manifest_hashes",
        )],
        "training_as_of": _required_text(
            store.manifest.get("training_as_of"),
            "training_as_of",
        ),
        "feature_packs": [
            [pack_id, list(feature_ids)] for pack_id, feature_ids in packs
        ],
        "horizons": [horizon],
        "expert_keys": list(expert_keys),
        "expert_head_ids": list(EXPERT_HEAD_IDS),
        "expert_vector_width": EXPERT_VECTOR_WIDTH,
        "rank_contract": rank_contract,
        "family_weight_policy": family_weight_policy,
        # 明確綁定 OOC final meta 使用原始 OOF downside 機率；daily
        # calibrator 只改風險／audit 輸出，不改 meta 的輸入分布。
        "meta_probability_input": "raw_oof",
        "training_profile": training_profile,
        "complexity_policy": dict(complexity_policy),
        "base_models": base_models,
        "meta_models": meta_models,
        "feature_family_weights_status": family_weight_status,
        "feature_family_weights_bp": [list(item) for item in family_weights],
        "production_alpha_bp": 0,
        "production_action_allowed": False,
        "formal_oos_allowed": False,
        "broker_order_allowed": False,
    }
    if target_summary is not None:
        payload["target_summary"] = target_summary
    return payload


def _load_base_model_payload(
    *,
    training_hash: str,
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    directory = _artifact_directory(artifact)
    records = {
        _required_text(item.get("head_id"), "head_id"): item
        for item in _mapping_list(artifact.get("head_models"), "head_models")
    }
    regression: dict[str, object] = {}
    classification: dict[str, object] = {}
    fit_rows: dict[str, list[str]] = {}
    missing: dict[str, str] = {}
    expert_id = _required_text(artifact.get("expert_id"), "expert_id")
    manifest_hash = _required_sha(artifact.get("manifest_hash"), "artifact.manifest_hash")
    fit_row_count = {
        head_id: _required_int(record.get("fit_row_count"), f"{head_id}.fit_row_count")
        for head_id, record in records.items()
        if record.get("status") == "fit"
    }
    for head_id in EXPERT_HEAD_IDS:
        record = records[head_id]
        if record.get("status") == "missing":
            model = None
            fit_rows[head_id] = []
            missing[head_id] = _required_text(
                record.get("missing_reason"),
                f"{head_id}.missing_reason",
            )
        else:
            path = _contained_file(directory, _required_text(record.get("path"), f"{head_id}.path"))
            model = _load_joblib(path)
            if not callable(getattr(model, "predict_numeric", None)):
                raise ValueError(f"OOC linear head lacks predict_numeric: {expert_id}.{head_id}")
            if head_id in CLASSIFICATION_EXPERT_HEADS and getattr(model, "classifier", None) is not True:
                raise ValueError(f"classification head is not marked classifier: {expert_id}.{head_id}")
            if head_id in REGRESSION_EXPERT_HEADS and getattr(model, "classifier", False) is True:
                raise ValueError(f"regression head is marked classifier: {expert_id}.{head_id}")
            token = _fit_source_token(
                training_hash=training_hash,
                artifact_hash=manifest_hash,
                expert_id=expert_id,
                head_id=head_id,
                fit_row_count=fit_row_count[head_id],
                cutoff=_required_text(
                    artifact.get("label_maturity_cutoff_exclusive"),
                    "label_maturity_cutoff_exclusive",
                ),
            )
            fit_rows[head_id] = [token]
        if head_id in REGRESSION_EXPERT_HEADS:
            regression[head_id] = model
        else:
            classification[head_id] = model
    return {
        "regression_models": regression,
        "classification_models": classification,
        "preprocessing_strategy": _required_text(
            artifact.get("preprocessing_strategy"),
            "preprocessing_strategy",
        ),
        "head_fit_row_ids": fit_rows,
        "head_missing_reasons": missing,
        "fit_row_ids": sorted(
            {row_id for rows in fit_rows.values() for row_id in rows}
        ),
    }


def _load_meta_model_payload(
    *,
    training_hash: str,
    artifact: Mapping[str, Any],
    expert_keys: Sequence[str],
) -> dict[str, Any]:
    directory = _artifact_directory(artifact)
    records = {
        _required_text(item.get("head_id"), "meta.head_id"): item
        for item in _mapping_list(artifact.get("head_models"), "meta.head_models")
    }
    manifest_hash = _required_sha(artifact.get("manifest_hash"), "meta.manifest_hash")
    fit_count = _required_int(artifact.get("train_row_count"), "meta.train_row_count")
    source_fold_ids = _text_list(artifact.get("training_source_fold_ids"), "meta.training_source_fold_ids")
    source_key = "|".join(source_fold_ids)
    token = "|".join(
        (
            "ooc-fit",
            training_hash[len(_SHA256_PREFIX) :],
            manifest_hash[len(_SHA256_PREFIX) :],
            "fold=final",
            f"rows={fit_count}",
            f"sources={source_key}",
        )
    )
    numeric: dict[str, object] = {}
    for field_name in TARGET_FIELDS[:5]:
        model = _load_meta_head(directory, records[field_name], field_name)
        if getattr(model, "classifier", False) is True:
            raise ValueError(f"final meta numeric head is a classifier: {field_name}")
        numeric[field_name] = model
    rebalance = _load_meta_head(
        directory,
        records["rebalance_worthwhile"],
        "rebalance_worthwhile",
    )
    if getattr(rebalance, "classifier", None) is not True:
        raise ValueError("final meta rebalance head is not marked classifier")
    return {
        "numeric": numeric,
        "rebalance": rebalance,
        "fit_row_ids": [token],
    }


def _load_meta_head(
    directory: Path,
    record: Mapping[str, Any],
    field_name: str,
) -> object:
    if record.get("status") != "fit":
        raise ValueError(f"final meta head is not fit: {field_name}")
    path = _contained_file(directory, _required_text(record.get("path"), f"meta.{field_name}.path"))
    model = _load_joblib(path)
    if not callable(getattr(model, "predict_numeric", None)):
        raise ValueError(f"final meta head lacks predict_numeric: {field_name}")
    return model


def _fit_ooc_calibrator(
    *,
    training_hash: str,
    store: _NumericStore,
    oof_entries: Mapping[tuple[str, str], Mapping[str, Any]],
    pack_ids: Sequence[str],
    horizon: int,
    batch_size: int,
    fold_limit: int | None = None,
) -> tuple[tuple[int, ...], dict[str, Any]]:
    counts = np.zeros(10_001, dtype=np.int64)
    positive_counts = np.zeros(10_001, dtype=np.int64)
    fold_ids: list[str] = []
    source_hashes: list[str] = []
    fit_cutoffs: dict[str, str] = {}
    fit_row_count = 0
    probability_column = EXPERT_HEAD_IDS.index("downside_probability_bp")
    store_fold_ids = tuple(
        _required_text(fold.get("fold_id"), "fold_id") for fold in store.folds
    )
    normalized_pack_ids = tuple(pack_ids)
    if not normalized_pack_ids or len(normalized_pack_ids) != len(set(normalized_pack_ids)):
        raise ValueError("calibration feature pack coverage is invalid")
    observed_pack_ids = tuple(sorted({expert_id.split("|", 1)[0] for _, expert_id in oof_entries}))
    if set(observed_pack_ids) != set(normalized_pack_ids):
        raise ValueError("calibration OOF pack coverage is incomplete")
    effective_fold_limit = len(store.folds) if fold_limit is None else fold_limit
    if effective_fold_limit > len(store.folds):
        raise ValueError("calibration fold limit exceeds available folds")
    if fold_limit is None:
        if effective_fold_limit < 3:
            raise ValueError(
                "OOC calibration requires at least three folds for two fit folds"
            )
    elif effective_fold_limit < _DERIVED_HOLDOUT_FOLD_COUNT:
        raise ValueError("derived calibration requires at least four folds")
    for fold_index, fold in enumerate(store.folds[: effective_fold_limit - 1]):
        fold_id = store_fold_ids[fold_index]
        next_cutoff = _required_text(
            store.folds[fold_index + 1].get("test_start"),
            "next fold test_start",
        )[:10]
        refs = store.open_fold_refs(fold, "test")
        try:
            mature_positions = store.mature_positions(refs, cutoff=next_cutoff)
            ready = np.zeros(len(refs), dtype=np.bool_)
            ready[mature_positions] = True
            fold_fit_rows = 0
            for pack_id in normalized_pack_ids:
                expert_id = f"{pack_id}|h{horizon}|ridge_logistic"
                artifact = oof_entries[(fold_id, expert_id)]
                directory = _artifact_directory(artifact)
                row_count = len(refs)
                oof_path = directory / "oof.i32"
                oof = np.memmap(
                    oof_path,
                    dtype=OOF_DTYPE,
                    mode="r",
                    shape=(row_count, EXPERT_VECTOR_WIDTH),
                )
                try:
                    for start in range(0, row_count, batch_size):
                        stop = min(row_count, start + batch_size)
                        labels, masks = store.read_label_batch(
                            np.asarray(refs[start:stop], dtype=np.int64),
                            horizon,
                        )
                        probability = np.asarray(
                            oof[start:stop, probability_column],
                            dtype=np.int64,
                        )
                        valid = (
                            ready[start:stop]
                            & (masks[:, 2] == 0)
                            & ((labels[:, 2] == 0) | (labels[:, 2] == 1))
                        )
                        if np.any((probability < 0) | (probability > 10_000)):
                            raise ValueError("OOF probability is outside integer bp range")
                        selected_probability = probability[valid]
                        selected_observed = np.asarray(
                            labels[valid, 2],
                            dtype=np.int64,
                        )
                        if len(selected_probability):
                            np.add.at(counts, selected_probability, 1)
                            np.add.at(
                                positive_counts,
                                selected_probability,
                                selected_observed,
                            )
                            fold_fit_rows += len(selected_probability)
                finally:
                    _close_memmap(oof)
                source_hashes.append(
                    _required_sha(artifact.get("manifest_hash"), "base_oof.manifest_hash")
                )
            if fold_fit_rows:
                fold_ids.append(fold_id)
                fit_cutoffs[fold_id] = next_cutoff
                fit_row_count += fold_fit_rows
        finally:
            # ``refs`` 在正常與錯誤路徑都明確關閉，讓 Windows 可確定釋放
            # store handle。
            _close_memmap(refs)
    if len(fold_ids) < 2:
        raise ValueError(
            "OOC calibration cannot be attached: fewer than two mature OOF fit folds"
        )
    total_positive = int(np.sum(positive_counts))
    total_negative = int(np.sum(counts - positive_counts))
    if fit_row_count <= 0 or total_positive == 0 or total_negative == 0:
        raise ValueError(
            "OOC calibration cannot be attached: both label classes are required"
        )
    mapping = _fit_isotonic_mapping_bp(counts, positive_counts)
    evidence_seed = {
        "training_manifest_hash": training_hash,
        "store_manifest_hash": _required_sha(
            store.manifest.get("manifest_hash"),
            "store.manifest_hash",
        ),
        "horizon_trading_days": horizon,
        "fit_fold_ids": fold_ids,
        "source_artifact_manifest_hashes": sorted(set(source_hashes)),
        "fit_row_count": fit_row_count,
        "positive_row_count": total_positive,
        "negative_row_count": total_negative,
        "fit_cutoff_exclusive_by_fold": fit_cutoffs,
        "source": "base_oof_test_rows_only",
        "cross_fitted_oof_only": True,
        "target_fold_self_excluded": True,
        "label_maturity_before_next_fold": True,
        "shared_mapping_across_feature_packs": len(normalized_pack_ids) > 1,
        "feature_pack_ids": list(normalized_pack_ids),
    }
    if fold_limit is not None:
        evidence_seed.update(
            {
                "heldout_fold_id": store_fold_ids[effective_fold_limit - 1],
                "selected_fold_ids": list(
                    store_fold_ids[:effective_fold_limit]
                ),
            }
        )
    calibration_id = "ooc-isotonic-" + payload_hash(evidence_seed)[
        len(_SHA256_PREFIX) : len(_SHA256_PREFIX) + 16
    ]
    evidence_seed["calibration_id"] = calibration_id
    evidence_seed["fit_fold_ids"] = list(fold_ids)
    return tuple(int(value) for value in mapping), evidence_seed


def _build_preprocessor_binding(
    *,
    model_id: str,
    strategy: str,
    order_hash: str,
    training_hash: str,
) -> tuple[PreprocessorBinding, bytes]:
    preprocessor_id = "ooc-preprocessor-" + payload_hash(
        {
            "model_id": model_id,
            "strategy": strategy,
            "feature_order_hash": order_hash,
            "training_manifest_hash": training_hash,
        }
    )[len(_SHA256_PREFIX) : len(_SHA256_PREFIX) + 16]
    body = {
        "schema_version": PREPROCESSOR_SCHEMA_VERSION,
        "preprocessor_id": preprocessor_id,
        "strategy": strategy,
        "feature_order_hash": order_hash,
        "artifact_file": _PREPROCESSOR_FILE,
        "attached_to_model": True,
    }
    content = _json_bytes(body)
    return (
        PreprocessorBinding(
            preprocessor_id=preprocessor_id,
            strategy=strategy,
            feature_order_hash=order_hash,
            artifact_file=_PREPROCESSOR_FILE,
            artifact_hash=bytes_hash(content),
        ),
        content,
    )


def _compatibility_manifest(
    *,
    release: AllocationReleaseManifest,
    store: _NumericStore,
    training_hash: str,
    horizon: int,
    calibration_evidence: Mapping[str, Any],
    training_profile: str = _PROFILE,
    lineage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": "allocation-training-output-manifest-v2",
        "status": "training_completed",
        "model_id": release.model_id,
        "training_as_of": _required_text(store.manifest.get("training_as_of"), "training_as_of"),
        "dataset_id": release.dataset_id,
        "dataset_identity_hash": release.dataset_identity_hash,
        "dataset_manifest_file_hash": _required_sha(
            store.manifest.get("dataset_manifest_file_hash"),
            "dataset_manifest_file_hash",
        ),
        "feature_registry_hash": release.feature_registry_hash,
        "source_manifest_hashes": [list(item) for item in release.source_manifest_hashes],
        "feature_packs": store.manifest.get("feature_packs"),
        "horizons": [horizon],
        "artifact_file": release.artifact_file,
        "artifact_hash": release.artifact_hash,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "production_action_allowed": False,
        "broker_order_allowed": False,
        "promotion_eligible": False,
        "training_profile": training_profile,
        "ooc_training_manifest_hash": training_hash,
        "release_identity_hash": release.release_identity_hash,
        "calibration": dict(calibration_evidence),
    }
    if lineage is not None:
        body["derived_lineage"] = dict(lineage)
    body["manifest_hash"] = _payload_sha(body)
    return body


def _load_training_artifact(
    summary: Mapping[str, Any],
    run_root: Path,
) -> Mapping[str, Any]:
    relative = _required_text(summary.get("artifact_path"), "artifact_path")
    directory = (run_root / relative).resolve()
    if not directory.is_relative_to(run_root):
        raise ValueError("OOC artifact path escapes training run")
    artifact = _read_and_validate_artifact(directory)
    if summary.get("manifest_hash") != artifact.get("manifest_hash"):
        raise ValueError("OOC artifact summary hash mismatch")
    return artifact


def _artifact_directory(artifact: Mapping[str, Any]) -> Path:
    run_root = Path(_required_text(artifact.get("_run_directory"), "artifact.run_directory")).resolve()
    relative = _required_text(artifact.get("artifact_path"), "artifact_path")
    directory = (run_root / relative).resolve()
    if not directory.is_relative_to(run_root):
        raise ValueError("OOC artifact path escapes training run")
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    return directory


def _resolve_store_path(training: Mapping[str, Any], run_root: Path) -> Path:
    relative = _required_text(training.get("store_manifest_path"), "store_manifest_path")
    path = Path(relative)
    resolved = path.resolve() if path.is_absolute() else (run_root / path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"OOC store manifest is missing: {resolved}")
    return resolved


def _normalise_store_packs(value: object) -> tuple[tuple[str, tuple[str, ...]], ...]:
    items = _mapping_list(value, "feature_packs")
    result: list[tuple[str, tuple[str, ...]]] = []
    seen_features: set[str] = set()
    for item in items:
        pack_id = _required_text(item.get("pack_id"), "feature_pack.pack_id")
        raw_features = item.get("feature_ids")
        if not isinstance(raw_features, list) or not raw_features:
            raise TypeError("feature_pack.feature_ids must be a non-empty list")
        feature_ids = tuple(_required_text(feature, "feature_id") for feature in raw_features)
        if feature_ids != tuple(sorted(feature_ids)) or len(feature_ids) != len(set(feature_ids)):
            raise ValueError("feature pack feature order must be canonical")
        if seen_features.intersection(feature_ids):
            raise ValueError("feature ids must belong to one pack")
        seen_features.update(feature_ids)
        result.append((pack_id, feature_ids))
    if not result or tuple(pack_id for pack_id, _ in result) != tuple(sorted(pack_id for pack_id, _ in result)):
        raise ValueError("feature pack order must be canonical")
    return tuple(result)


def _normalise_family_weights(
    value: object,
    *,
    packs: Sequence[tuple[str, tuple[str, ...]]],
) -> tuple[tuple[str, int], ...]:
    items = _mapping_list(value, "feature_family_weights_bp")
    result: list[tuple[str, int]] = []
    for item in items:
        family_id = _required_text(item.get("family_id"), "family_id")
        weight = _required_int(item.get("weight_bp"), "weight_bp")
        if weight < 0 or weight > 10_000:
            raise ValueError("feature family weight must be bp")
        result.append((family_id, weight))
    expected = tuple(pack_id for pack_id, _ in packs)
    if tuple(item[0] for item in result) != expected or sum(item[1] for item in result) != 10_000:
        raise ValueError("feature family weights do not match frozen packs")
    return tuple(result)


def _fit_source_token(
    *,
    training_hash: str,
    artifact_hash: str,
    expert_id: str,
    head_id: str,
    fit_row_count: int,
    cutoff: str,
) -> str:
    return "|".join(
        (
            "ooc-fit",
            training_hash[len(_SHA256_PREFIX) :],
            artifact_hash[len(_SHA256_PREFIX) :],
            "fold=final",
            f"expert={expert_id}",
            f"head={head_id}",
            f"rows={fit_row_count}",
            f"cutoff={cutoff}",
        )
    )


def _contained_file(directory: Path, name: str) -> Path:
    path = (directory / name).resolve()
    if not path.is_relative_to(directory.resolve()) or not path.is_file():
        raise FileNotFoundError(path)
    return path


def _load_joblib(path: Path) -> object:
    try:
        return joblib.load(path)
    except Exception as exc:  # noqa: BLE001 - release boundary wraps deserialization
        raise ValueError(f"OOC model head deserialization failed: {path}") from exc


def _predict_numeric(model: object, matrix: np.ndarray) -> np.ndarray:
    """在 release 邊界確認 head 真正提供 numeric predictor。"""

    predictor = getattr(model, "predict_numeric", None)
    if not callable(predictor):
        raise ValueError("OOC model head lacks predict_numeric")
    return np.asarray(predictor(matrix), dtype=np.float64)


def _joblib_bytes(payload: object) -> bytes:
    buffer = BytesIO()
    joblib.dump(payload, buffer, compress=3)
    return buffer.getvalue()


def _json_bytes(payload: object) -> bytes:
    return (canonical_json(payload) + "\n").encode("utf-8")


def _with_hash(payload: Mapping[str, Any], field_name: str) -> dict[str, Any]:
    result = dict(payload)
    result[field_name] = _payload_sha(result)
    return result


def _commit_immutable(path: Path, content: bytes) -> None:
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError(f"refusing to overwrite immutable release file: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.read_bytes() != content:
            raise OSError(f"release staging verification failed: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _close_memmap(value: np.memmap) -> None:
    mmap_handle = getattr(value, "_mmap", None)
    if mmap_handle is not None:
        mmap_handle.close()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


def _payload_sha(value: object) -> str:
    return payload_hash(value)


def _canonical_value(value: object) -> str:
    return canonical_json(value)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be a non-empty string")
    return value.strip()


def _required_sha(value: object, field_name: str) -> str:
    result = _required_text(value, field_name)
    if len(result) != len(_SHA256_PREFIX) + 64 or not result.startswith(_SHA256_PREFIX):
        raise ValueError(f"{field_name} must be a sha256 digest")
    if any(char not in "0123456789abcdef" for char in result[len(_SHA256_PREFIX) :]):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")
    return result


def _required_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be integer")
    return value


def _text_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be a list")
    return [_required_text(item, field_name) for item in value]


def _mapping_list(value: object, field_name: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be a list")
    result: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise TypeError(f"{field_name} entries must be objects")
        result.append(item)
    return result


def _as_mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be an object")
    return value


def _normalise_hash_pairs(
    value: object,
    *,
    field_name: str,
) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list) or not value:
        raise TypeError(f"{field_name} must be a non-empty list")
    result: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise TypeError(f"{field_name} entries must be two-item lists")
        result.append(
            (
                _required_text(item[0], f"{field_name}.source_id"),
                _required_sha(item[1], f"{field_name}.source_hash"),
            )
        )
    if len(result) != len(set(source_id for source_id, _ in result)):
        raise ValueError(f"{field_name} source IDs must be unique")
    return tuple(result)


__all__ = [
    "AllocationDerivedOOCReleasePublication",
    "AllocationDerivedOOCReleaseRequest",
    "AllocationOOCReleasePublication",
    "AllocationOOCReleaseRequest",
    "build_allocation_derived_ooc_release",
    "build_allocation_ooc_release",
    "build_ooc_allocation_release",
    "preflight_allocation_derived_ooc_release",
]
