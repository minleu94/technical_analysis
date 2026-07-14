from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_system_execution_blueprint import (
    BlueprintVerificationError,
    verify_system_execution_blueprint,
)


def _write_input(root: Path, name: str, payload: dict[str, object]) -> None:
    (root / f"{name}.json").write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _valid_inputs(root: Path) -> None:
    root.mkdir(parents=True)
    _write_input(
        root,
        "evidence_execution",
        {
            "status": "engineering_real_e2e_complete",
            "source_db_opened": True,
            "source_db_write_performed": False,
            "working_copy_created": True,
            "artifact_hashes": {"replay": "sha256:" + "a" * 64},
        },
    )
    _write_input(
        root,
        "ml_split_and_pit",
        {
            "training_end_date": "2024-12-31",
            "max_train_label_available_date": "2024-12-31",
            "max_blend_selection_label_available_date": "2024-12-31",
            "oos_start_date": "2025-01-01",
            "oos_end_date": "2025-12-31",
            "future_rows_excluded": True,
            "immature_labels_excluded": True,
        },
    )
    _write_input(
        root,
        "dataset_model_prediction_identity",
        {
            "dataset_id": "dataset-1",
            "dataset_hash": "sha256:" + "b" * 64,
            "model_id": "model-1",
            "model_hash": "sha256:" + "c" * 64,
            "prediction_ids": ["prediction-1"],
            "shadow_only": True,
        },
    )
    _write_input(
        root,
        "dashboard_visibility",
        {
            "fundamental_monthly_revenues": {"row_count": 0, "quality": "missing"},
            "institutional_flows": {"row_count": 0, "quality": "missing"},
            "credit_transactions": {"row_count": 0, "quality": "missing"},
            "tdcc_shareholding": {"row_count": 0, "quality": "missing"},
            "broker_flows": {"row_count": 1, "quality": "observed"},
        },
    )
    _write_input(
        root,
        "broker_latency",
        {
            "warm_samples_ms": [100 + index for index in range(20)],
            "warm_p95_ms": 119,
            "loading_state_ms": 20,
            "query_limit_pushed_down": True,
        },
    )
    _write_input(
        root,
        "formal_boundaries",
        {
            "production_blend_alpha_bp": 0,
            "formal_rule_unchanged": True,
            "formal_score_changed": False,
            "production_action_allowed": False,
            "formal_oos_allowed": False,
        },
    )
    _write_input(
        root,
        "external_pending",
        {
            "forward_evidence": "pending",
            "source_acceptance": "pending",
            "production_automation": "pending",
            "ml_promotion": "pending",
        },
    )


def test_pure_verifier_accepts_engineering_truth_and_keeps_external_gates_pending(
    tmp_path: Path,
) -> None:
    root = tmp_path / "inputs"
    _valid_inputs(root)

    result = verify_system_execution_blueprint(root)

    assert tuple(result) == (
        "evidence_execution",
        "ml_split_and_pit",
        "dataset_model_prediction_identity",
        "dashboard_visibility",
        "broker_latency",
        "formal_boundaries",
        "external_pending",
        "overall_engineering_status",
    )
    assert result["formal_boundaries"]["production_blend_alpha_bp"] == 0
    assert result["external_pending"]["source_acceptance"] == "pending"
    assert result["overall_engineering_status"] == (
        "engineering_integration_verified_external_gates_pending"
    )


@pytest.mark.parametrize(
    ("file_name", "field_name", "unsafe_value", "message"),
    (
        ("evidence_execution", "artifact_hashes", {}, "artifact hash"),
        ("ml_split_and_pit", "training_end_date", "2025-01-01", "2024-12-31"),
        (
            "ml_split_and_pit",
            "max_train_label_available_date",
            "2025-01-01",
            "2024-12-31",
        ),
        (
            "ml_split_and_pit",
            "max_blend_selection_label_available_date",
            "2025-01-01",
            "2024-12-31",
        ),
        ("dataset_model_prediction_identity", "shadow_only", False, "shadow"),
        ("broker_latency", "warm_samples_ms", [1, 2], "20"),
        ("broker_latency", "warm_p95_ms", "bad", "warm_p95_ms"),
        ("broker_latency", "loading_state_ms", "bad", "loading_state_ms"),
        ("formal_boundaries", "production_blend_alpha_bp", 1, "alpha"),
        ("formal_boundaries", "formal_score_changed", True, "formal score"),
        ("external_pending", "source_acceptance", "complete", "pending"),
    ),
)
def test_verifier_rejects_malformed_or_weakened_truth(
    tmp_path: Path,
    file_name: str,
    field_name: str,
    unsafe_value: object,
    message: str,
) -> None:
    root = tmp_path / "inputs"
    _valid_inputs(root)
    path = root / f"{file_name}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[field_name] = unsafe_value
    _write_input(root, file_name, payload)

    with pytest.raises(BlueprintVerificationError, match=message):
        verify_system_execution_blueprint(root)


def test_verifier_rejects_missing_artifact_file(tmp_path: Path) -> None:
    root = tmp_path / "inputs"
    _valid_inputs(root)
    (root / "dashboard_visibility.json").unlink()

    with pytest.raises(BlueprintVerificationError, match="missing input"):
        verify_system_execution_blueprint(root)


def test_zero_row_dashboard_source_cannot_be_ready(tmp_path: Path) -> None:
    root = tmp_path / "inputs"
    _valid_inputs(root)
    path = root / "dashboard_visibility.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["institutional_flows"] = {"row_count": 0, "quality": "ready"}
    _write_input(root, "dashboard_visibility", payload)

    with pytest.raises(BlueprintVerificationError, match="zero-row"):
        verify_system_execution_blueprint(root)


def test_verifier_accepts_utf8_bom_from_powershell_artifact_writer(
    tmp_path: Path,
) -> None:
    root = tmp_path / "inputs"
    _valid_inputs(root)
    path = root / "evidence_execution.json"
    payload = path.read_text(encoding="utf-8")
    path.write_text(payload, encoding="utf-8-sig")

    result = verify_system_execution_blueprint(root)

    assert result["evidence_execution"]["status"] == (
        "engineering_real_e2e_complete"
    )
