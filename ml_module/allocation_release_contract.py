"""配置型 ML release 的可稽核契約。

這個模組是 OOC 訓練產物與每日推論之間的窄邊界。Release manifest 會把
模型、前處理、校準器、特徵順序、缺值政策及資料 lineage 綁在同一個
immutable identity；consumer 遇到任何不一致時必須停止 ML path。

所有跨模組及持久化的決策數值均使用整數 bp/count。校準 mapping 也是
``0..10_000`` 的整數 bp，因此不需要在 release validator 增加金融用
``float`` 計算。
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence


RELEASE_SCHEMA_VERSION = "allocation-ml-inference-release.v1"
PREPROCESSOR_SCHEMA_VERSION = "allocation-ml-preprocessor.v1"
CALIBRATION_SCHEMA_VERSION = "allocation-ml-calibration.v1"
MISSING_POLICY_SCHEMA_VERSION = "allocation-ml-missing-policy.v1"
ARTIFACT_SCHEMA_VERSION = "allocation-model-artifact-v3"
PROBABILITY_MAX_BP = 10_000
SHA256_PREFIX = "sha256:"

_CALIBRATION_METHODS = frozenset(
    {"isotonic_integer_bp", "sigmoid_embedded"}
)
_CALIBRATION_APPLICATIONS = frozenset(
    {"external_integer_bp", "embedded_model"}
)
_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "release_id",
        "model_id",
        "dataset_id",
        "training_manifest_hash",
        "artifact_schema_version",
        "artifact_file",
        "artifact_hash",
        "dataset_identity_hash",
        "feature_registry_hash",
        "source_manifest_hashes",
        "feature_order",
        "feature_order_hash",
        "preprocessor",
        "calibration",
        "missing_policy",
        "release_identity_hash",
        "formal_oos_allowed",
        "production_alpha_bp",
        "production_action_allowed",
        "broker_order_allowed",
        "promotion_eligible",
    }
)


def canonical_json(payload: object) -> str:
    """回傳 release identity 使用的 deterministic JSON。"""

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def payload_hash(payload: object) -> str:
    return SHA256_PREFIX + hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()


def bytes_hash(payload: bytes) -> str:
    return SHA256_PREFIX + hashlib.sha256(payload).hexdigest()


def feature_order_hash(feature_order: Sequence[str]) -> str:
    return payload_hash({"feature_order": list(feature_order)})


@dataclass(frozen=True)
class PreprocessorBinding:
    """模型前處理的 identity 與 frozen feature order。"""

    preprocessor_id: str
    strategy: str
    feature_order_hash: str
    artifact_file: str
    artifact_hash: str
    attached_to_model: bool = True
    schema_version: str = PREPROCESSOR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_text(
            preprocessor_id=self.preprocessor_id,
            strategy=self.strategy,
            artifact_file=self.artifact_file,
        )
        if self.schema_version != PREPROCESSOR_SCHEMA_VERSION:
            raise ValueError("unsupported preprocessor schema version")
        _require_sha256(
            self.feature_order_hash,
            field_name="preprocessor.feature_order_hash",
        )
        _require_sha256(
            self.artifact_hash,
            field_name="preprocessor.artifact_hash",
        )
        _require_basename(self.artifact_file, field_name="preprocessor.artifact_file")
        if self.attached_to_model is not True:
            raise ValueError("preprocessor must be attached to the release model")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "preprocessor_id": self.preprocessor_id,
            "strategy": self.strategy,
            "feature_order_hash": self.feature_order_hash,
            "artifact_file": self.artifact_file,
            "artifact_hash": self.artifact_hash,
            "attached_to_model": self.attached_to_model,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PreprocessorBinding":
        _require_keys(
            payload,
            {
                "schema_version",
                "preprocessor_id",
                "strategy",
                "feature_order_hash",
                "artifact_file",
                "artifact_hash",
                "attached_to_model",
            },
            field_name="preprocessor",
        )
        _reject_unknown(
            payload,
            {
                "schema_version",
                "preprocessor_id",
                "strategy",
                "feature_order_hash",
                "artifact_file",
                "artifact_hash",
                "attached_to_model",
            },
            field_name="preprocessor",
        )
        return cls(
            preprocessor_id=_text(
                payload.get("preprocessor_id"),
                "preprocessor.preprocessor_id",
            ),
            strategy=_text(payload.get("strategy"), "preprocessor.strategy"),
            feature_order_hash=_sha(
                payload.get("feature_order_hash"),
                "preprocessor.feature_order_hash",
            ),
            artifact_file=_text(
                payload.get("artifact_file"),
                "preprocessor.artifact_file",
            ),
            artifact_hash=_sha(
                payload.get("artifact_hash"),
                "preprocessor.artifact_hash",
            ),
            attached_to_model=payload.get("attached_to_model") is True,
            schema_version=_text(
                payload.get("schema_version"),
                "preprocessor.schema_version",
            ),
        )


@dataclass(frozen=True)
class CalibrationBinding:
    """校準器 attachment contract。

    ``diagnostic_only`` 與 ``oof_diagnostic_only`` 明確區分 OOC 的評估報告
    和可供 inference 使用的校準器。兩者任一為 true 都會被拒絕。
    """

    calibration_id: str
    model_id: str
    method: str
    application: str
    feature_order_hash: str
    artifact_file: str
    artifact_hash: str
    fit_fold_ids: tuple[str, ...]
    attached_to_model: bool = True
    diagnostic_only: bool = False
    oof_diagnostic_only: bool = False
    schema_version: str = CALIBRATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_text(
            calibration_id=self.calibration_id,
            model_id=self.model_id,
            method=self.method,
            application=self.application,
            artifact_file=self.artifact_file,
        )
        if self.schema_version != CALIBRATION_SCHEMA_VERSION:
            raise ValueError("unsupported calibration schema version")
        if self.method not in _CALIBRATION_METHODS:
            raise ValueError("unsupported calibration method")
        if self.application not in _CALIBRATION_APPLICATIONS:
            raise ValueError("unsupported calibration application")
        _require_sha256(
            self.feature_order_hash,
            field_name="calibration.feature_order_hash",
        )
        _require_sha256(
            self.artifact_hash,
            field_name="calibration.artifact_hash",
        )
        _require_basename(self.artifact_file, field_name="calibration.artifact_file")
        if not self.fit_fold_ids or len(self.fit_fold_ids) < 2:
            raise ValueError("calibration requires at least two fit folds")
        if len(self.fit_fold_ids) != len(set(self.fit_fold_ids)):
            raise ValueError("calibration fit fold ids must be unique")
        for fold_id in self.fit_fold_ids:
            _require_text(fit_fold_id=fold_id)
        if self.attached_to_model is not True:
            raise ValueError("calibration must be attached to the release model")
        if self.diagnostic_only or self.oof_diagnostic_only:
            raise ValueError("calibration is diagnostic-only and cannot be released")
        if not isinstance(self.attached_to_model, bool):
            raise TypeError("calibration.attached_to_model must be bool")
        if not isinstance(self.diagnostic_only, bool) or not isinstance(
            self.oof_diagnostic_only, bool
        ):
            raise TypeError("calibration diagnostic flags must be bool")
        if self.application == "external_integer_bp" and self.method != "isotonic_integer_bp":
            raise ValueError("external calibration must use integer isotonic mapping")
        if self.application == "embedded_model" and self.method != "sigmoid_embedded":
            raise ValueError("embedded calibration must use embedded sigmoid model")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "calibration_id": self.calibration_id,
            "model_id": self.model_id,
            "method": self.method,
            "application": self.application,
            "feature_order_hash": self.feature_order_hash,
            "artifact_file": self.artifact_file,
            "artifact_hash": self.artifact_hash,
            "fit_fold_ids": list(self.fit_fold_ids),
            "attached_to_model": self.attached_to_model,
            "diagnostic_only": self.diagnostic_only,
            "oof_diagnostic_only": self.oof_diagnostic_only,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CalibrationBinding":
        _require_keys(
            payload,
            {
                "schema_version",
                "calibration_id",
                "model_id",
                "method",
                "application",
                "feature_order_hash",
                "artifact_file",
                "artifact_hash",
                "fit_fold_ids",
                "attached_to_model",
                "diagnostic_only",
                "oof_diagnostic_only",
            },
            field_name="calibration",
        )
        _reject_unknown(
            payload,
            {
                "schema_version",
                "calibration_id",
                "model_id",
                "method",
                "application",
                "feature_order_hash",
                "artifact_file",
                "artifact_hash",
                "fit_fold_ids",
                "attached_to_model",
                "diagnostic_only",
                "oof_diagnostic_only",
            },
            field_name="calibration",
        )
        fit_fold_ids = _text_tuple(
            payload.get("fit_fold_ids"),
            field_name="calibration.fit_fold_ids",
        )
        return cls(
            calibration_id=_text(
                payload.get("calibration_id"),
                "calibration.calibration_id",
            ),
            model_id=_text(payload.get("model_id"), "calibration.model_id"),
            method=_text(payload.get("method"), "calibration.method"),
            application=_text(
                payload.get("application"),
                "calibration.application",
            ),
            feature_order_hash=_sha(
                payload.get("feature_order_hash"),
                "calibration.feature_order_hash",
            ),
            artifact_file=_text(
                payload.get("artifact_file"),
                "calibration.artifact_file",
            ),
            artifact_hash=_sha(
                payload.get("artifact_hash"),
                "calibration.artifact_hash",
            ),
            fit_fold_ids=fit_fold_ids,
            attached_to_model=payload.get("attached_to_model") is True,
            diagnostic_only=payload.get("diagnostic_only") is True,
            oof_diagnostic_only=payload.get("oof_diagnostic_only") is True,
            schema_version=_text(
                payload.get("schema_version"),
                "calibration.schema_version",
            ),
        )


@dataclass(frozen=True)
class MissingPolicyBinding:
    """缺值行為的 identity；避免 consumer 靜默改用 zero imputation。"""

    policy_id: str
    mode: str
    unknown_feature_action: str
    missing_value_action: str
    partial_family_action: str
    all_missing_action: str
    policy_hash: str
    schema_version: str = MISSING_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_text(
            policy_id=self.policy_id,
            mode=self.mode,
            unknown_feature_action=self.unknown_feature_action,
            missing_value_action=self.missing_value_action,
            partial_family_action=self.partial_family_action,
            all_missing_action=self.all_missing_action,
        )
        if self.schema_version != MISSING_POLICY_SCHEMA_VERSION:
            raise ValueError("unsupported missing policy schema version")
        if self.mode != "explicit_mask_neutral_fallback":
            raise ValueError("unsupported missing policy mode")
        if self.unknown_feature_action != "reject":
            raise ValueError("unknown feature policy must reject")
        if self.missing_value_action != "missing_is_not_zero":
            raise ValueError("missing feature policy must preserve missingness")
        if self.partial_family_action != "neutral_fallback_with_diagnostic":
            raise ValueError("partial family policy is unsupported")
        if self.all_missing_action != "cash_only":
            raise ValueError("all-missing policy must be cash_only")
        _require_sha256(self.policy_hash, field_name="missing_policy.policy_hash")
        expected = payload_hash(self._body())
        if self.policy_hash != expected:
            raise ValueError("missing policy hash mismatch")

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "mode": self.mode,
            "unknown_feature_action": self.unknown_feature_action,
            "missing_value_action": self.missing_value_action,
            "partial_family_action": self.partial_family_action,
            "all_missing_action": self.all_missing_action,
        }

    @classmethod
    def create(
        cls,
        *,
        policy_id: str,
        mode: str = "explicit_mask_neutral_fallback",
        unknown_feature_action: str = "reject",
        missing_value_action: str = "missing_is_not_zero",
        partial_family_action: str = "neutral_fallback_with_diagnostic",
        all_missing_action: str = "cash_only",
    ) -> "MissingPolicyBinding":
        body = {
            "schema_version": MISSING_POLICY_SCHEMA_VERSION,
            "policy_id": policy_id,
            "mode": mode,
            "unknown_feature_action": unknown_feature_action,
            "missing_value_action": missing_value_action,
            "partial_family_action": partial_family_action,
            "all_missing_action": all_missing_action,
        }
        return cls(policy_hash=payload_hash(body), **body)

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "policy_hash": self.policy_hash}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MissingPolicyBinding":
        _require_keys(
            payload,
            {
                "schema_version",
                "policy_id",
                "mode",
                "unknown_feature_action",
                "missing_value_action",
                "partial_family_action",
                "all_missing_action",
                "policy_hash",
            },
            field_name="missing_policy",
        )
        _reject_unknown(
            payload,
            {
                "schema_version",
                "policy_id",
                "mode",
                "unknown_feature_action",
                "missing_value_action",
                "partial_family_action",
                "all_missing_action",
                "policy_hash",
            },
            field_name="missing_policy",
        )
        return cls(
            schema_version=_text(
                payload.get("schema_version"),
                "missing_policy.schema_version",
            ),
            policy_id=_text(
                payload.get("policy_id"),
                "missing_policy.policy_id",
            ),
            mode=_text(payload.get("mode"), "missing_policy.mode"),
            unknown_feature_action=_text(
                payload.get("unknown_feature_action"),
                "missing_policy.unknown_feature_action",
            ),
            missing_value_action=_text(
                payload.get("missing_value_action"),
                "missing_policy.missing_value_action",
            ),
            partial_family_action=_text(
                payload.get("partial_family_action"),
                "missing_policy.partial_family_action",
            ),
            all_missing_action=_text(
                payload.get("all_missing_action"),
                "missing_policy.all_missing_action",
            ),
            policy_hash=_sha(
                payload.get("policy_hash"),
                "missing_policy.policy_hash",
            ),
        )


@dataclass(frozen=True)
class IntegerProbabilityCalibrator:
    """可由 release adapter 套用的 isotonic 整數 bp mapping。"""

    calibration_id: str
    model_id: str
    feature_order_hash: str
    mapping_bp: tuple[int, ...]
    fit_fold_ids: tuple[str, ...]
    contract_hash: str
    method: str = "isotonic_integer_bp"
    schema_version: str = CALIBRATION_SCHEMA_VERSION
    attached_to_model: bool = True
    diagnostic_only: bool = False
    oof_diagnostic_only: bool = False

    def __post_init__(self) -> None:
        _require_text(calibration_id=self.calibration_id, model_id=self.model_id)
        if self.schema_version != CALIBRATION_SCHEMA_VERSION:
            raise ValueError("unsupported calibration schema version")
        if self.method != "isotonic_integer_bp":
            raise ValueError("integer calibrator must use isotonic_integer_bp")
        _require_sha256(
            self.feature_order_hash,
            field_name="calibrator.feature_order_hash",
        )
        _require_sha256(
            self.contract_hash,
            field_name="calibrator.contract_hash",
        )
        if len(self.mapping_bp) != PROBABILITY_MAX_BP + 1:
            raise ValueError("integer calibrator mapping must cover 0..10000 bp")
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= PROBABILITY_MAX_BP
            for value in self.mapping_bp
        ):
            raise ValueError("integer calibrator mapping must contain bp integers")
        if any(
            self.mapping_bp[index] > self.mapping_bp[index + 1]
            for index in range(PROBABILITY_MAX_BP)
        ):
            raise ValueError("integer calibrator mapping must be monotonic")
        if not self.fit_fold_ids or len(self.fit_fold_ids) < 2:
            raise ValueError("calibrator requires at least two fit folds")
        if len(self.fit_fold_ids) != len(set(self.fit_fold_ids)):
            raise ValueError("calibrator fit fold ids must be unique")
        for fold_id in self.fit_fold_ids:
            _text(fold_id, "calibrator.fit_fold_id")
        if not isinstance(self.attached_to_model, bool):
            raise TypeError("calibrator.attached_to_model must be bool")
        if not isinstance(self.diagnostic_only, bool) or not isinstance(
            self.oof_diagnostic_only, bool
        ):
            raise TypeError("calibrator diagnostic flags must be bool")
        if self.attached_to_model is not True:
            raise ValueError("calibrator must be attached to the model")
        if self.diagnostic_only or self.oof_diagnostic_only:
            raise ValueError("calibrator is diagnostic-only and cannot be released")
        if self.contract_hash != payload_hash(self._body()):
            raise ValueError("calibrator contract hash mismatch")

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "calibration_id": self.calibration_id,
            "model_id": self.model_id,
            "method": self.method,
            "feature_order_hash": self.feature_order_hash,
            "mapping_bp": list(self.mapping_bp),
            "fit_fold_ids": list(self.fit_fold_ids),
            "attached_to_model": self.attached_to_model,
            "diagnostic_only": self.diagnostic_only,
            "oof_diagnostic_only": self.oof_diagnostic_only,
        }

    @classmethod
    def create(
        cls,
        *,
        calibration_id: str,
        model_id: str,
        feature_order_hash: str,
        mapping_bp: Sequence[int],
        fit_fold_ids: Sequence[str],
    ) -> "IntegerProbabilityCalibrator":
        body = {
            "schema_version": CALIBRATION_SCHEMA_VERSION,
            "calibration_id": calibration_id,
            "model_id": model_id,
            "method": "isotonic_integer_bp",
            "feature_order_hash": feature_order_hash,
            "mapping_bp": list(mapping_bp),
            "fit_fold_ids": list(fit_fold_ids),
            "attached_to_model": True,
            "diagnostic_only": False,
            "oof_diagnostic_only": False,
        }
        return cls(
            calibration_id=calibration_id,
            model_id=model_id,
            feature_order_hash=feature_order_hash,
            mapping_bp=tuple(mapping_bp),
            fit_fold_ids=tuple(fit_fold_ids),
            contract_hash=payload_hash(body),
        )

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "contract_hash": self.contract_hash}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "IntegerProbabilityCalibrator":
        _require_keys(
            payload,
            {
                "schema_version",
                "calibration_id",
                "model_id",
                "method",
                "feature_order_hash",
                "mapping_bp",
                "fit_fold_ids",
                "attached_to_model",
                "diagnostic_only",
                "oof_diagnostic_only",
                "contract_hash",
            },
            field_name="calibrator",
        )
        _reject_unknown(
            payload,
            {
                "schema_version",
                "calibration_id",
                "model_id",
                "method",
                "feature_order_hash",
                "mapping_bp",
                "fit_fold_ids",
                "attached_to_model",
                "diagnostic_only",
                "oof_diagnostic_only",
                "contract_hash",
            },
            field_name="calibrator",
        )
        mapping = payload.get("mapping_bp")
        if not isinstance(mapping, list):
            raise TypeError("calibrator.mapping_bp must be an array")
        return cls(
            schema_version=_text(
                payload.get("schema_version"),
                "calibrator.schema_version",
            ),
            calibration_id=_text(
                payload.get("calibration_id"),
                "calibrator.calibration_id",
            ),
            model_id=_text(payload.get("model_id"), "calibrator.model_id"),
            feature_order_hash=_sha(
                payload.get("feature_order_hash"),
                "calibrator.feature_order_hash",
            ),
            mapping_bp=tuple(mapping),
            fit_fold_ids=_text_tuple(
                payload.get("fit_fold_ids"),
                field_name="calibrator.fit_fold_ids",
            ),
            contract_hash=_sha(
                payload.get("contract_hash"),
                "calibrator.contract_hash",
            ),
            method=_text(payload.get("method"), "calibrator.method"),
            attached_to_model=payload.get("attached_to_model") is True,
            diagnostic_only=payload.get("diagnostic_only") is True,
            oof_diagnostic_only=payload.get("oof_diagnostic_only") is True,
        )

    def calibrate_bp(self, raw_probability_bp: int) -> int:
        if (
            isinstance(raw_probability_bp, bool)
            or not isinstance(raw_probability_bp, int)
            or not 0 <= raw_probability_bp <= PROBABILITY_MAX_BP
        ):
            raise ValueError("raw probability must be an integer bp within 0..10000")
        return self.mapping_bp[raw_probability_bp]


@dataclass(frozen=True)
class AllocationReleaseManifest:
    """模型到 daily inference 的完整 hash-bound release identity。"""

    release_id: str
    model_id: str
    dataset_id: str
    training_manifest_hash: str
    artifact_file: str
    artifact_hash: str
    dataset_identity_hash: str
    feature_registry_hash: str
    source_manifest_hashes: tuple[tuple[str, str], ...]
    feature_order: tuple[str, ...]
    feature_order_hash: str
    preprocessor: PreprocessorBinding
    calibration: CalibrationBinding
    missing_policy: MissingPolicyBinding
    release_identity_hash: str
    artifact_schema_version: str = ARTIFACT_SCHEMA_VERSION
    schema_version: str = RELEASE_SCHEMA_VERSION
    formal_oos_allowed: bool = False
    production_alpha_bp: int = 0
    production_action_allowed: bool = False
    broker_order_allowed: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        _require_text(
            release_id=self.release_id,
            model_id=self.model_id,
            dataset_id=self.dataset_id,
            artifact_file=self.artifact_file,
        )
        if self.schema_version != RELEASE_SCHEMA_VERSION:
            raise ValueError("unsupported allocation release schema version")
        if self.artifact_schema_version != ARTIFACT_SCHEMA_VERSION:
            raise ValueError("artifact schema version mismatch")
        for field_name, value in {
            "training_manifest_hash": self.training_manifest_hash,
            "artifact_hash": self.artifact_hash,
            "dataset_identity_hash": self.dataset_identity_hash,
            "feature_registry_hash": self.feature_registry_hash,
        }.items():
            _require_sha256(value, field_name=field_name)
        _require_basename(self.artifact_file, field_name="artifact_file")
        _validate_source_hashes(self.source_manifest_hashes)
        if not self.feature_order or len(self.feature_order) != len(set(self.feature_order)):
            raise ValueError("feature_order must be non-empty and unique")
        for feature_id in self.feature_order:
            _require_text(feature_id=feature_id)
        _require_sha256(self.feature_order_hash, field_name="feature_order_hash")
        if self.feature_order_hash != feature_order_hash(self.feature_order):
            raise ValueError("feature_order_hash mismatch")
        if self.calibration.model_id != self.model_id:
            raise ValueError("calibration model identity mismatch")
        if self.preprocessor.feature_order_hash != self.feature_order_hash:
            raise ValueError("preprocessor feature order identity mismatch")
        if self.calibration.feature_order_hash != self.feature_order_hash:
            raise ValueError("calibration feature order identity mismatch")
        if self.production_alpha_bp != 0:
            raise ValueError("production_alpha_bp must remain zero")
        if isinstance(self.production_alpha_bp, bool) or not isinstance(
            self.production_alpha_bp, int
        ):
            raise TypeError("production_alpha_bp must be an integer bp")
        for field_name in (
            "formal_oos_allowed",
            "production_action_allowed",
            "broker_order_allowed",
            "promotion_eligible",
        ):
            if getattr(self, field_name) is not False:
                raise ValueError(f"release {field_name} must be false")
        if self.release_identity_hash != self.compute_identity_hash():
            raise ValueError("release identity hash mismatch")

    def _identity_body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "release_id": self.release_id,
            "model_id": self.model_id,
            "dataset_id": self.dataset_id,
            "training_manifest_hash": self.training_manifest_hash,
            "artifact_schema_version": self.artifact_schema_version,
            "artifact_file": self.artifact_file,
            "artifact_hash": self.artifact_hash,
            "dataset_identity_hash": self.dataset_identity_hash,
            "feature_registry_hash": self.feature_registry_hash,
            "source_manifest_hashes": [
                [source_id, source_hash]
                for source_id, source_hash in self.source_manifest_hashes
            ],
            "feature_order": list(self.feature_order),
            "feature_order_hash": self.feature_order_hash,
            "preprocessor": self.preprocessor.to_dict(),
            "calibration": self.calibration.to_dict(),
            "missing_policy": self.missing_policy.to_dict(),
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
            "production_action_allowed": False,
            "broker_order_allowed": False,
            "promotion_eligible": False,
        }

    def compute_identity_hash(self) -> str:
        return payload_hash(self._identity_body())

    @classmethod
    def create(
        cls,
        *,
        release_id: str,
        model_id: str,
        dataset_id: str,
        training_manifest_hash: str,
        artifact_file: str,
        artifact_hash: str,
        dataset_identity_hash: str,
        feature_registry_hash: str,
        source_manifest_hashes: Sequence[tuple[str, str]],
        feature_order: Sequence[str],
        preprocessor: PreprocessorBinding,
        calibration: CalibrationBinding,
        missing_policy: MissingPolicyBinding,
    ) -> "AllocationReleaseManifest":
        body = {
            "schema_version": RELEASE_SCHEMA_VERSION,
            "release_id": release_id,
            "model_id": model_id,
            "dataset_id": dataset_id,
            "training_manifest_hash": training_manifest_hash,
            "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
            "artifact_file": artifact_file,
            "artifact_hash": artifact_hash,
            "dataset_identity_hash": dataset_identity_hash,
            "feature_registry_hash": feature_registry_hash,
            "source_manifest_hashes": [
                [source_id, source_hash]
                for source_id, source_hash in source_manifest_hashes
            ],
            "feature_order": list(feature_order),
            "feature_order_hash": feature_order_hash(feature_order),
            "preprocessor": preprocessor.to_dict(),
            "calibration": calibration.to_dict(),
            "missing_policy": missing_policy.to_dict(),
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
            "production_action_allowed": False,
            "broker_order_allowed": False,
            "promotion_eligible": False,
        }
        return cls(
            release_id=release_id,
            model_id=model_id,
            dataset_id=dataset_id,
            training_manifest_hash=training_manifest_hash,
            artifact_file=artifact_file,
            artifact_hash=artifact_hash,
            dataset_identity_hash=dataset_identity_hash,
            feature_registry_hash=feature_registry_hash,
            source_manifest_hashes=tuple(source_manifest_hashes),
            feature_order=tuple(feature_order),
            feature_order_hash=feature_order_hash(feature_order),
            preprocessor=preprocessor,
            calibration=calibration,
            missing_policy=missing_policy,
            release_identity_hash=payload_hash(body),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            **self._identity_body(),
            "release_identity_hash": self.release_identity_hash,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AllocationReleaseManifest":
        _require_keys(payload, _TOP_LEVEL_FIELDS, field_name="release manifest")
        _reject_unknown(payload, _TOP_LEVEL_FIELDS, field_name="release manifest")
        source_hashes = _pair_hashes(
            payload.get("source_manifest_hashes"),
            field_name="source_manifest_hashes",
        )
        feature_values = payload.get("feature_order")
        feature_order = _text_tuple(feature_values, field_name="feature_order")
        preprocessor_payload = _mapping(payload.get("preprocessor"), "preprocessor")
        calibration_payload = _mapping(payload.get("calibration"), "calibration")
        missing_payload = _mapping(payload.get("missing_policy"), "missing_policy")
        return cls(
            schema_version=_text(payload.get("schema_version"), "schema_version"),
            release_id=_text(payload.get("release_id"), "release_id"),
            model_id=_text(payload.get("model_id"), "model_id"),
            dataset_id=_text(payload.get("dataset_id"), "dataset_id"),
            training_manifest_hash=_sha(
                payload.get("training_manifest_hash"),
                "training_manifest_hash",
            ),
            artifact_schema_version=_text(
                payload.get("artifact_schema_version"),
                "artifact_schema_version",
            ),
            artifact_file=_text(payload.get("artifact_file"), "artifact_file"),
            artifact_hash=_sha(payload.get("artifact_hash"), "artifact_hash"),
            dataset_identity_hash=_sha(
                payload.get("dataset_identity_hash"),
                "dataset_identity_hash",
            ),
            feature_registry_hash=_sha(
                payload.get("feature_registry_hash"),
                "feature_registry_hash",
            ),
            source_manifest_hashes=source_hashes,
            feature_order=feature_order,
            feature_order_hash=_sha(
                payload.get("feature_order_hash"),
                "feature_order_hash",
            ),
            preprocessor=PreprocessorBinding.from_dict(preprocessor_payload),
            calibration=CalibrationBinding.from_dict(calibration_payload),
            missing_policy=MissingPolicyBinding.from_dict(missing_payload),
            release_identity_hash=_sha(
                payload.get("release_identity_hash"),
                "release_identity_hash",
            ),
            formal_oos_allowed=payload.get("formal_oos_allowed") is True,
            production_alpha_bp=_integer_zero(
                payload.get("production_alpha_bp"),
                field_name="production_alpha_bp",
            ),
            production_action_allowed=payload.get("production_action_allowed") is True,
            broker_order_allowed=payload.get("broker_order_allowed") is True,
            promotion_eligible=payload.get("promotion_eligible") is True,
        )


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be an object")
    return value


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be a non-empty string")
    return value.strip()


def _require_text(**values: str) -> None:
    for field_name, value in values.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")


def _sha(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    _require_sha256(result, field_name=field_name)
    return result


def _require_sha256(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or not value.startswith(SHA256_PREFIX):
        raise ValueError(f"{field_name} must be a sha256 digest")
    digest = value[len(SHA256_PREFIX) :]
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")


def _integer_zero(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer bp")
    return value


def _require_basename(value: str, *, field_name: str) -> None:
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"{field_name} must be a controlled basename")


def _text_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise TypeError(f"{field_name} must be a non-empty array")
    result = tuple(_text(item, field_name=field_name) for item in value)
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} values must be unique")
    return result


def _pair_hashes(value: object, *, field_name: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise TypeError(f"{field_name} must be a non-empty array")
    result: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise TypeError(f"{field_name} entries must be two-item arrays")
        result.append(
            (
                _text(item[0], field_name=f"{field_name}.source_id"),
                _sha(item[1], f"{field_name}.source_hash"),
            )
        )
    return tuple(result)


def _validate_source_hashes(value: Sequence[tuple[str, str]]) -> None:
    pairs = _pair_hashes(value, field_name="source_manifest_hashes")
    if len(pairs) != len(set(source_id for source_id, _ in pairs)):
        raise ValueError("source manifest ids must be unique")


def _reject_unknown(
    payload: Mapping[str, Any],
    allowed: set[str] | frozenset[str],
    *,
    field_name: str,
) -> None:
    unknown = set(payload) - set(allowed)
    if unknown:
        raise ValueError(f"unsupported {field_name} field: {sorted(unknown)[0]}")


def _require_keys(
    payload: Mapping[str, Any],
    required: set[str] | frozenset[str],
    *,
    field_name: str,
) -> None:
    missing = set(required) - set(payload)
    if missing:
        raise ValueError(f"{field_name} field is missing: {sorted(missing)[0]}")
