from __future__ import annotations

from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path

import joblib
import pytest
from typing import Any, cast

from app_module.allocation_release_adapter import AllocationReleaseAdapter
from ml_module.allocation_release_contract import (
    AllocationReleaseManifest,
    CalibrationBinding,
    IntegerProbabilityCalibrator,
    MissingPolicyBinding,
    PreprocessorBinding,
    bytes_hash,
    canonical_json,
    feature_order_hash,
)
from tests.test_ml_allocation_inference_service import (
    _inference_rows,
    _research_rows,
)


pytest_plugins = ("tests.test_ml_allocation_training_service",)


_MODEL_ID = "allocator-v4-release-test"
_UNIVERSE_ID = "pit-universe-test"
_POLICY_ID = "balanced-v1"
_POLICY_HASH = MissingPolicyBinding.create(policy_id=_POLICY_ID).policy_hash


def _write_json(path: Path, payload: object) -> bytes:
    content = canonical_json(payload).encode("utf-8")
    path.write_bytes(content)
    return content


def _write_release(
    tmp_path: Path,
    training_result,
    *,
    external_calibration: bool = False,
) -> AllocationReleaseManifest:
    root = tmp_path / "release"
    root.mkdir()
    artifact_path = root / "model.joblib"
    artifact_path.write_bytes(training_result.artifact_bytes)
    feature_order = tuple(
        feature_id
        for _, feature_ids in joblib.load(BytesIO(training_result.artifact_bytes))["feature_packs"]
        for feature_id in feature_ids
    )
    order_hash = feature_order_hash(feature_order)

    preprocessor = PreprocessorBinding(
        preprocessor_id="prep-embedded-v1",
        strategy="artifact_embedded",
        feature_order_hash=order_hash,
        artifact_file="preprocessor.json",
        artifact_hash="sha256:" + ("0" * 64),
    )
    preprocessor_body = {
        key: value
        for key, value in preprocessor.to_dict().items()
        if key != "artifact_hash"
    }
    preprocessor = replace(
        preprocessor,
        artifact_hash=bytes_hash(_write_json(root / preprocessor.artifact_file, preprocessor_body)),
    )

    if external_calibration:
        calibrator = IntegerProbabilityCalibrator.create(
            calibration_id="cal-external-v1",
            model_id=_MODEL_ID,
            feature_order_hash=order_hash,
            mapping_bp=(1_234,) * 10_001,
            fit_fold_ids=tuple(training_result.outer_fold_ids),
        )
        calibration_file = "calibrator.json"
        calibration_content = _write_json(
            root / calibration_file,
            calibrator.to_dict(),
        )
        calibration = CalibrationBinding(
            calibration_id=calibrator.calibration_id,
            model_id=_MODEL_ID,
            method="isotonic_integer_bp",
            application="external_integer_bp",
            feature_order_hash=order_hash,
            artifact_file=calibration_file,
            artifact_hash=bytes_hash(calibration_content),
            fit_fold_ids=tuple(training_result.outer_fold_ids),
        )
    else:
        calibration = CalibrationBinding(
            calibration_id="cal-embedded-v1",
            model_id=_MODEL_ID,
            method="sigmoid_embedded",
            application="embedded_model",
            feature_order_hash=order_hash,
            artifact_file="calibration.json",
            artifact_hash="sha256:" + ("0" * 64),
            fit_fold_ids=tuple(training_result.outer_fold_ids),
        )
        calibration_body = {
            key: value
            for key, value in calibration.to_dict().items()
            if key != "artifact_hash"
        }
        calibration = replace(
            calibration,
            artifact_hash=bytes_hash(
                _write_json(root / calibration.artifact_file, calibration_body)
            ),
        )

    missing_policy = MissingPolicyBinding.create(policy_id=_POLICY_ID)
    manifest = AllocationReleaseManifest.create(
        release_id="release-v1",
        model_id=_MODEL_ID,
        dataset_id=training_result.dataset_id,
        training_manifest_hash=training_result.dataset_manifest_file_hash,
        artifact_file=artifact_path.name,
        artifact_hash=training_result.artifact_hash,
        dataset_identity_hash=training_result.dataset_identity_hash,
        feature_registry_hash=training_result.feature_registry_hash,
        source_manifest_hashes=training_result.source_manifest_hashes,
        feature_order=feature_order,
        preprocessor=preprocessor,
        calibration=calibration,
        missing_policy=missing_policy,
    )
    _write_json(root / "release_manifest.json", manifest.to_dict())
    return manifest


def test_release_adapter_binds_artifact_components_and_replays_rows(
    tmp_path: Path,
    training_result,
) -> None:
    manifest = _write_release(tmp_path, training_result)
    loaded = AllocationReleaseAdapter().load(
        tmp_path / "release",
        expected_release_identity_hash=manifest.release_identity_hash,
    )

    result = loaded.infer(
        rows=_inference_rows(),
        universe_id=_UNIVERSE_ID,
        policy_hash=_POLICY_HASH,
    )
    parity = loaded.validate_frozen_rows(
        rows=_inference_rows(),
        ooc_outputs=result,
        universe_id=_UNIVERSE_ID,
        policy_hash=_POLICY_HASH,
    )

    assert loaded.manifest.release_identity_hash == manifest.release_identity_hash
    assert result.proposal.formal_oos_allowed is False
    assert result.proposal.production_blend_alpha_bp == 0
    assert parity.matched
    assert parity.row_count == 2


def test_release_adapter_research_shadow_entrypoint_preserves_safety_flags(
    tmp_path: Path,
    training_result,
) -> None:
    manifest = _write_release(tmp_path, training_result)
    loaded = AllocationReleaseAdapter().load(
        tmp_path / "release",
        expected_release_identity_hash=manifest.release_identity_hash,
    )
    rows = _research_rows()

    with pytest.raises(ValueError, match="08:30"):
        loaded.infer(
            rows=rows,
            universe_id=_UNIVERSE_ID,
            policy_hash=_POLICY_HASH,
        )

    result = loaded.infer_research_shadow(
        rows=rows,
        universe_id=_UNIVERSE_ID,
        policy_hash=_POLICY_HASH,
    )
    audit = result.audit_payload()
    assert audit["decision_at"] == "2027-01-04T18:00:00+08:00"
    assert audit["inference_readback_mode"] == "post_freeze_research_shadow"
    assert result.formal_oos_allowed is False
    assert result.production_action_allowed is False
    assert result.production_blend_alpha_bp == 0


def test_release_adapter_applies_attached_integer_calibrator(
    tmp_path: Path,
    training_result,
) -> None:
    _write_release(tmp_path, training_result, external_calibration=True)
    loaded = AllocationReleaseAdapter().load(tmp_path / "release")
    result = loaded.infer(
        rows=_inference_rows(),
        universe_id=_UNIVERSE_ID,
        policy_hash=_POLICY_HASH,
    )

    for row_audit in result.audit_payload()["row_audits"]:
        assert all(
            values["calibrated_downside_probability_bp"] == 1_234
            for values in row_audit["downside_probability_by_horizon_bp"].values()
        )


def test_release_adapter_rejects_diagnostic_calibration(
    tmp_path: Path,
    training_result,
) -> None:
    manifest = _write_release(tmp_path, training_result)
    payload = manifest.to_dict()
    calibration = dict(cast(dict[str, Any], payload["calibration"]))
    calibration["oof_diagnostic_only"] = True
    payload["calibration"] = calibration
    # The constructor is the fail-closed boundary, before identity can be
    # recomputed by an untrusted manifest consumer.
    with pytest.raises(ValueError, match="diagnostic-only"):
        AllocationReleaseManifest.from_dict(payload)


def test_release_adapter_rejects_artifact_hash_mismatch(
    tmp_path: Path,
    training_result,
) -> None:
    manifest = _write_release(tmp_path, training_result)
    artifact_path = tmp_path / "release" / manifest.artifact_file
    artifact_path.write_bytes(artifact_path.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="model artifact hash mismatch"):
        AllocationReleaseAdapter().load(tmp_path / "release")


def test_release_adapter_rejects_frozen_row_output_mismatch(
    tmp_path: Path,
    training_result,
) -> None:
    _write_release(tmp_path, training_result)
    loaded = AllocationReleaseAdapter().load(tmp_path / "release")
    result = loaded.infer(
        rows=_inference_rows(),
        universe_id=_UNIVERSE_ID,
        policy_hash=_POLICY_HASH,
    )
    poisoned = json.loads(result.audit_json)
    poisoned["row_audits"][0]["meta_output"]["cash_bp"] += 1

    with pytest.raises(ValueError, match="frozen row output parity mismatch"):
        loaded.validate_frozen_rows(
            rows=_inference_rows(),
            ooc_outputs=poisoned,
            universe_id=_UNIVERSE_ID,
            policy_hash=_POLICY_HASH,
        )


def test_integer_calibrator_is_monotonic_and_fail_closed() -> None:
    mapping = tuple(range(10_001))
    calibrator = IntegerProbabilityCalibrator.create(
        calibration_id="cal-integer-v1",
        model_id=_MODEL_ID,
        feature_order_hash="sha256:" + ("e" * 64),
        mapping_bp=mapping,
        fit_fold_ids=("fold-1", "fold-2"),
    )
    restored = IntegerProbabilityCalibrator.from_dict(calibrator.to_dict())

    assert restored.calibrate_bp(3_210) == 3_210
    with pytest.raises(ValueError, match="raw probability"):
        restored.calibrate_bp(10_001)
