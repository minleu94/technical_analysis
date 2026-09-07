"""受控的 allocation ML release loader 與 frozen-row parity validator。

``MLAllocationInferenceService`` 原本接受既有 direct artifact；本 adapter
則提供一個 opt-in 的 release 邊界，把模型 artifact、前處理、校準、feature
order 與 missing policy 在載入前先做 hash/identity 驗證。這讓 daily inference
可以拒絕不完整的 OOC diagnostic manifest，而不必重寫既有 trainer 或每日
orchestration script。

此模組只產生唯讀 inference service。所有 production authority 維持
``alpha=0``、``formal_oos_allowed=False``、``production_action_allowed=False``
與 ``broker_order_allowed=False``。
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib

from app_module.ml_allocation_inference_service import (
    MLAllocationInferenceResult,
    MLAllocationInferenceService,
)
from ml_module.allocation_release_contract import (
    ARTIFACT_SCHEMA_VERSION,
    AllocationReleaseManifest,
    CalibrationBinding,
    IntegerProbabilityCalibrator,
    PreprocessorBinding,
    bytes_hash,
    payload_hash,
)
from ml_module.allocation_contracts import PortfolioMLDatasetRow


@dataclass(frozen=True)
class ReleaseParityResult:
    """同一批 frozen rows 的 release/OOC output 比對結果。"""

    status: str
    row_count: int
    release_output_hash: str
    ooc_output_hash: str
    mismatched_row_ids: tuple[str, ...] = ()
    formal_oos_allowed: bool = False
    production_alpha_bp: int = 0
    production_action_allowed: bool = False
    broker_order_allowed: bool = False

    def __post_init__(self) -> None:
        if self.status not in {"matched", "mismatch"}:
            raise ValueError("release parity status is invalid")
        if (
            isinstance(self.row_count, bool)
            or not isinstance(self.row_count, int)
        ):
            raise TypeError("release parity row_count must be an integer")
        if self.row_count < 0:
            raise ValueError("release parity row_count must be non-negative")
        for field_name, value in {
            "release_output_hash": self.release_output_hash,
            "ooc_output_hash": self.ooc_output_hash,
        }.items():
            _require_sha256(value, field_name=field_name)
        if len(self.mismatched_row_ids) != len(set(self.mismatched_row_ids)):
            raise ValueError("release parity row ids must be unique")
        if any(
            not isinstance(row_id, str) or not row_id
            for row_id in self.mismatched_row_ids
        ):
            raise TypeError("release parity row ids must be non-empty strings")
        if self.status == "matched" and self.mismatched_row_ids:
            raise ValueError("matched release parity cannot contain mismatches")
        if self.formal_oos_allowed is not False:
            raise ValueError("release parity cannot authorize formal OOS")
        if (
            isinstance(self.production_alpha_bp, bool)
            or not isinstance(self.production_alpha_bp, int)
            or self.production_alpha_bp != 0
        ):
            raise ValueError("release parity production alpha must remain zero")
        if self.production_action_allowed is not False:
            raise ValueError("release parity cannot authorize production action")
        if self.broker_order_allowed is not False:
            raise ValueError("release parity cannot authorize broker orders")

    @property
    def matched(self) -> bool:
        return self.status == "matched"

    def assert_matched(self) -> "ReleaseParityResult":
        if not self.matched:
            detail = ",".join(self.mismatched_row_ids[:5]) or "unknown"
            raise ValueError(f"frozen row output parity mismatch: {detail}")
        return self


@dataclass(frozen=True)
class LoadedAllocationRelease:
    """已通過 release contract 的唯讀推論入口。"""

    release_root: Path
    manifest_path: Path
    manifest: AllocationReleaseManifest
    service: MLAllocationInferenceService
    release_manifest_file_hash: str

    @property
    def release_id(self) -> str:
        return self.manifest.release_id

    @property
    def model_id(self) -> str:
        return self.manifest.model_id

    @property
    def dataset_id(self) -> str:
        return self.manifest.dataset_id

    @property
    def artifact_hash(self) -> str:
        return self.manifest.artifact_hash

    def infer(
        self,
        *,
        rows: Sequence[PortfolioMLDatasetRow],
        model_id: str | None = None,
        universe_id: str,
        policy_id: str | None = None,
        policy_hash: str,
        expected_universe_hash: str | None = None,
    ) -> MLAllocationInferenceResult:
        """用 release 綁定的 model/policy identity 執行既有 inference。"""

        effective_model_id = self.manifest.model_id if model_id is None else model_id
        effective_policy_id = (
            self.manifest.missing_policy.policy_id
            if policy_id is None
            else policy_id
        )
        if effective_model_id != self.manifest.model_id:
            raise ValueError("inference model id does not match release")
        if effective_policy_id != self.manifest.missing_policy.policy_id:
            raise ValueError("inference missing policy id does not match release")
        if policy_hash != self.manifest.missing_policy.policy_hash:
            raise ValueError("inference missing policy hash does not match release")
        return self.service.infer(
            rows=rows,
            model_id=effective_model_id,
            universe_id=universe_id,
            policy_id=effective_policy_id,
            policy_hash=policy_hash,
            expected_universe_hash=expected_universe_hash,
        )

    def compare_frozen_rows(
        self,
        *,
        rows: Sequence[PortfolioMLDatasetRow],
        ooc_outputs: object,
        universe_id: str,
        policy_hash: str,
        model_id: str | None = None,
        policy_id: str | None = None,
        expected_universe_hash: str | None = None,
    ) -> ReleaseParityResult:
        """比較相同 frozen rows 的 release audit 與 OOC row outputs。

        OOC output 可以是 row-audit array、含 ``row_audits`` 的 audit object，
        或另一個具有 ``audit_payload()`` 的 inference result。比較只取模型
        output（base expert、downside probability、meta output），排除
        proposal hash 與 consumer-specific metadata。
        """

        release_result = self.infer(
            rows=rows,
            model_id=model_id,
            universe_id=universe_id,
            policy_id=policy_id,
            policy_hash=policy_hash,
            expected_universe_hash=expected_universe_hash,
        )
        release_rows = _extract_row_outputs(release_result.audit_payload())
        ooc_rows = _extract_row_outputs(ooc_outputs)
        release_hash = payload_hash(release_rows)
        ooc_hash = payload_hash(ooc_rows)
        row_ids = sorted(set(release_rows) | set(ooc_rows))
        mismatches = tuple(
            row_id
            for row_id in row_ids
            if release_rows.get(row_id) != ooc_rows.get(row_id)
        )
        return ReleaseParityResult(
            status="matched" if not mismatches else "mismatch",
            row_count=len(release_rows),
            release_output_hash=release_hash,
            ooc_output_hash=ooc_hash,
            mismatched_row_ids=mismatches,
        )

    def validate_frozen_rows(
        self,
        *,
        rows: Sequence[PortfolioMLDatasetRow],
        ooc_outputs: object,
        universe_id: str,
        policy_hash: str,
        model_id: str | None = None,
        policy_id: str | None = None,
        expected_universe_hash: str | None = None,
    ) -> ReleaseParityResult:
        """執行 parity check，任何 output mismatch 都 fail closed。"""

        return self.compare_frozen_rows(
            rows=rows,
            ooc_outputs=ooc_outputs,
            universe_id=universe_id,
            policy_hash=policy_hash,
            model_id=model_id,
            policy_id=policy_id,
            expected_universe_hash=expected_universe_hash,
        ).assert_matched()


class AllocationReleaseAdapter:
    """載入並驗證一個 immutable allocation inference release。"""

    def __init__(self, *, manifest_name: str = "release_manifest.json") -> None:
        _require_basename(manifest_name, field_name="manifest_name")
        self._manifest_name = manifest_name

    def load(
        self,
        release_root: str | Path,
        *,
        expected_release_identity_hash: str | None = None,
    ) -> LoadedAllocationRelease:
        root = Path(release_root).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"release root is missing: {root}")
        manifest_path = _controlled_path(root, self._manifest_name, "release manifest")
        if not manifest_path.is_file():
            raise FileNotFoundError(f"release manifest is missing: {manifest_path}")
        manifest_bytes = manifest_path.read_bytes()
        manifest_payload = _read_json_object(
            manifest_bytes,
            field_name="release manifest",
        )
        manifest = AllocationReleaseManifest.from_dict(manifest_payload)
        if expected_release_identity_hash is not None:
            _require_sha256(
                expected_release_identity_hash,
                field_name="expected_release_identity_hash",
            )
            if manifest.release_identity_hash != expected_release_identity_hash:
                raise ValueError("release identity hash mismatch")

        artifact_path = _controlled_path(
            root,
            manifest.artifact_file,
            "model artifact",
        )
        artifact_bytes = _read_hashed_file(
            artifact_path,
            expected_hash=manifest.artifact_hash,
            field_name="model artifact",
        )
        raw_artifact = _load_joblib_object(artifact_bytes, field_name="model artifact")
        _validate_artifact_lineage(raw_artifact, manifest)
        _validate_feature_order(raw_artifact, manifest)
        _validate_preprocessor(root, raw_artifact, manifest.preprocessor, manifest)
        calibrator = _validate_calibration(
            root,
            raw_artifact,
            manifest.calibration,
            manifest,
        )

        service = MLAllocationInferenceService(
            artifact_bytes=artifact_bytes,
            expected_artifact_hash=manifest.artifact_hash,
            expected_dataset_id=manifest.dataset_id,
            probability_calibrator=(
                calibrator.calibrate_bp if calibrator is not None else None
            ),
        )
        return LoadedAllocationRelease(
            release_root=root,
            manifest_path=manifest_path,
            manifest=manifest,
            service=service,
            release_manifest_file_hash=bytes_hash(manifest_bytes),
        )


def load_allocation_release(
    release_root: str | Path,
    *,
    expected_release_identity_hash: str | None = None,
    manifest_name: str = "release_manifest.json",
) -> LoadedAllocationRelease:
    """函式型 convenience API，供 daily caller 使用。"""

    return AllocationReleaseAdapter(manifest_name=manifest_name).load(
        release_root,
        expected_release_identity_hash=expected_release_identity_hash,
    )


def _validate_artifact_lineage(
    raw_artifact: object,
    manifest: AllocationReleaseManifest,
) -> None:
    if not isinstance(raw_artifact, dict):
        raise TypeError("release artifact payload must be an object")
    if raw_artifact.get("artifact_schema_version") != ARTIFACT_SCHEMA_VERSION:
        raise ValueError("release artifact schema version mismatch")
    for field_name in (
        "dataset_identity_hash",
        "feature_registry_hash",
        "source_manifest_hashes",
    ):
        actual = raw_artifact.get(field_name)
        expected: object
        if field_name == "source_manifest_hashes":
            expected = tuple(manifest.source_manifest_hashes)
            actual = _normalise_hash_pairs(actual, field_name=field_name)
        else:
            expected = getattr(manifest, field_name)
        if actual != expected:
            raise ValueError(f"release {field_name} mismatch")
    if raw_artifact.get("dataset_id") != manifest.dataset_id:
        raise ValueError("release dataset id mismatch")


def _validate_feature_order(
    raw_artifact: object,
    manifest: AllocationReleaseManifest,
) -> None:
    if not isinstance(raw_artifact, dict):
        raise TypeError("release artifact payload must be an object")
    packs = raw_artifact.get("feature_packs")
    if not isinstance(packs, (list, tuple)):
        raise TypeError("release artifact feature_packs must be an array")
    actual_order: list[str] = []
    for pack in packs:
        if isinstance(pack, dict):
            feature_ids = pack.get("feature_ids")
        elif isinstance(pack, (list, tuple)) and len(pack) == 2:
            feature_ids = pack[1]
        else:
            raise TypeError("release artifact feature pack must be an object")
        if not isinstance(feature_ids, (list, tuple)):
            raise TypeError("release artifact feature_ids must be an array")
        actual_order.extend(
            _require_text(feature_id, "artifact feature_id")
            for feature_id in feature_ids
        )
    if tuple(actual_order) != manifest.feature_order:
        raise ValueError("release feature order mismatch")


def _validate_preprocessor(
    root: Path,
    raw_artifact: object,
    binding: PreprocessorBinding,
    manifest: AllocationReleaseManifest,
) -> None:
    path = _controlled_path(root, binding.artifact_file, "preprocessor artifact")
    content = _read_hashed_file(
        path,
        expected_hash=binding.artifact_hash,
        field_name="preprocessor artifact",
    )
    if binding.artifact_file == manifest.artifact_file:
        if binding.artifact_hash != manifest.artifact_hash:
            raise ValueError("embedded preprocessor hash is not model-bound")
    else:
        payload = _read_json_object(content, field_name="preprocessor binding")
        if payload != _sidecar_binding_payload(binding.to_dict(), hash_key="artifact_hash"):
            raise ValueError("preprocessor binding payload mismatch")

    if not isinstance(raw_artifact, dict):
        raise TypeError("release artifact payload must be an object")
    base_models = raw_artifact.get("base_models")
    if not isinstance(base_models, dict):
        raise TypeError("release artifact base_models must be an object")
    strategies = {
        model_payload.get("preprocessing_strategy")
        for model_payload in base_models.values()
        if isinstance(model_payload, dict)
    }
    if binding.strategy not in strategies and binding.strategy not in {
        "artifact_embedded",
        "direct_artifact_embedded",
    }:
        raise ValueError("preprocessor strategy is not attached to model")


def _validate_calibration(
    root: Path,
    raw_artifact: object,
    binding: CalibrationBinding,
    manifest: AllocationReleaseManifest,
) -> IntegerProbabilityCalibrator | None:
    path = _controlled_path(root, binding.artifact_file, "calibration artifact")
    content = _read_hashed_file(
        path,
        expected_hash=binding.artifact_hash,
        field_name="calibration artifact",
    )
    if binding.application == "external_integer_bp":
        if binding.artifact_file == manifest.artifact_file:
            raise ValueError("external calibration must have an attached calibrator artifact")
        payload = _read_json_object(content, field_name="calibrator artifact")
        calibrator = IntegerProbabilityCalibrator.from_dict(payload)
        if calibrator.calibration_id != binding.calibration_id:
            raise ValueError("calibrator id mismatch")
        if calibrator.model_id != manifest.model_id:
            raise ValueError("calibrator model identity mismatch")
        if calibrator.feature_order_hash != manifest.feature_order_hash:
            raise ValueError("calibrator feature order identity mismatch")
        if calibrator.method != binding.method:
            raise ValueError("calibrator method mismatch")
        if calibrator.fit_fold_ids != binding.fit_fold_ids:
            raise ValueError("calibrator fit folds mismatch")
        return calibrator

    # Embedded sklearn calibration is carried by the direct model object.  A
    # small sidecar is still accepted and checked when supplied; this gives a
    # release reviewer a stable calibration identity without duplicating the
    # serialized estimator.
    if binding.artifact_file != manifest.artifact_file:
        payload = _read_json_object(content, field_name="calibration binding")
        if payload != _sidecar_binding_payload(binding.to_dict(), hash_key="artifact_hash"):
            raise ValueError("calibration binding payload mismatch")
    if not isinstance(raw_artifact, dict):
        raise TypeError("release artifact payload must be an object")
    base_models = raw_artifact.get("base_models")
    if not isinstance(base_models, dict):
        raise TypeError("release artifact base_models must be an object")
    for expert_key, model_payload in base_models.items():
        if not isinstance(model_payload, dict):
            raise TypeError(f"release base model is invalid: {expert_key}")
        classifiers = model_payload.get("classification_models")
        if not isinstance(classifiers, dict):
            raise TypeError(f"release classification models are invalid: {expert_key}")
        for head_id, model in classifiers.items():
            if model is None:
                continue
            folds = getattr(model, "calibrated_classifiers_", None)
            if not isinstance(folds, list) or not folds:
                raise ValueError(
                    "embedded calibration is not attached to model: "
                    f"{expert_key}.{head_id}"
                )
    return None


def _extract_row_outputs(value: object) -> dict[str, dict[str, object]]:
    if isinstance(value, MLAllocationInferenceResult):
        value = value.audit_payload()
    if isinstance(value, Mapping) and "row_audits" in value:
        value = value["row_audits"]
    if isinstance(value, Mapping):
        # Permit a map keyed by row_id while retaining a strict row contract.
        if not value:
            return {}
        if all(isinstance(key, str) for key in value):
            entries = []
            for row_id, row_output in value.items():
                if isinstance(row_output, Mapping) and "row_id" not in row_output:
                    entries.append({"row_id": row_id, **row_output})
                else:
                    entries.append(row_output)
        else:
            raise TypeError("frozen row outputs must use string row ids")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        entries = list(value)
    else:
        raise TypeError("frozen row outputs must be an array or object")

    result: dict[str, dict[str, object]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise TypeError("frozen row output entry must be an object")
        row_id = entry.get("row_id")
        if not isinstance(row_id, str) or not row_id:
            raise TypeError("frozen row output row_id must be a non-empty string")
        if row_id in result:
            raise ValueError("frozen row output row ids must be unique")
        result[row_id] = _output_projection(entry)
    return {row_id: result[row_id] for row_id in sorted(result)}


def _output_projection(value: Mapping[str, object]) -> dict[str, object]:
    nested = value.get("output")
    source: Mapping[str, object] = nested if isinstance(nested, Mapping) else value
    keys = (
        "base_expert_outputs",
        "downside_probability_by_horizon_bp",
        "meta_output",
    )
    projection = {key: source[key] for key in keys if key in source}
    if not projection:
        # Keep a useful strict comparison for future OOC adapters whose row
        # shape uses one explicit ``prediction`` field.
        for key in ("prediction", "predictions", "head_outputs"):
            if key in source:
                projection[key] = source[key]
        if not projection:
            raise ValueError("frozen row output has no model output fields")
    return projection


def _read_json_object(content: bytes, *, field_name: str) -> dict[str, object]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field_name} must be valid JSON") from exc
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be a JSON object")
    return value


def _load_joblib_object(content: bytes, *, field_name: str) -> object:
    try:
        return joblib.load(BytesIO(content))
    except Exception as exc:
        raise ValueError(f"{field_name} deserialization failed") from exc


def _read_hashed_file(path: Path, *, expected_hash: str, field_name: str) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(f"{field_name} is missing: {path}")
    content = path.read_bytes()
    if bytes_hash(content) != expected_hash:
        raise ValueError(f"{field_name} hash mismatch")
    return content


def _controlled_path(root: Path, filename: str, field_name: str) -> Path:
    _require_basename(filename, field_name=field_name)
    path = (root / filename).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field_name} escapes release root") from exc
    return path


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be a non-empty string")
    return value.strip()


def _require_basename(value: object, *, field_name: str) -> str:
    text = _require_text(value, field_name)
    if text in {".", ".."} or "/" in text or "\\" in text:
        raise ValueError(f"{field_name} must be a controlled basename")
    if Path(text).name != text:
        raise ValueError(f"{field_name} must be a controlled basename")
    return text


def _require_sha256(value: object, *, field_name: str) -> str:
    text = _require_text(value, field_name)
    if not text.startswith("sha256:") or len(text) != len("sha256:") + 64:
        raise ValueError(f"{field_name} must be a sha256 digest")
    if any(char not in "0123456789abcdef" for char in text[len("sha256:") :]):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")
    return text


def _normalise_hash_pairs(value: object, *, field_name: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be an array")
    pairs: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise TypeError(f"{field_name} entries must be two-item arrays")
        source_id = _require_text(item[0], f"{field_name}.source_id")
        source_hash = _require_sha256(item[1], field_name=f"{field_name}.source_hash")
        pairs.append((source_id, source_hash))
    return tuple(pairs)


def _sidecar_binding_payload(
    payload: Mapping[str, object],
    *,
    hash_key: str,
) -> dict[str, object]:
    """回傳不含 sidecar 自身 hash 的 metadata body。

    component hash 位於 release manifest；若把同一個 hash 再寫進被 hash
    的 JSON 會形成不可能的循環。因此 sidecar 只攜帶 identity metadata，
    artifact_hash 由外層 binding 驗證。
    """

    return {key: value for key, value in payload.items() if key != hash_key}
