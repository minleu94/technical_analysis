from __future__ import annotations

import json

from app_module.ml_readiness_contract import (
    ALLOWED_ML_ROLES,
    FORBIDDEN_ML_ACTIONS,
    MLReadinessContractService,
)
from scripts.inspect_ml_readiness_contract import main as inspect_ml_readiness_contract_main


def test_ml_contract_is_shadow_only_and_lists_allowed_roles() -> None:
    report = MLReadinessContractService().build_report()
    payload = report.to_dict()

    assert payload["shadow_only"] is True
    assert payload["allowed_ml_roles"] == list(ALLOWED_ML_ROLES)
    assert payload["forbidden_actions"] == list(FORBIDDEN_ML_ACTIONS)
    assert "weight_learning" in payload["allowed_ml_roles"]
    assert "probability_calibration" in payload["allowed_ml_roles"]
    assert "meta_labeling" in payload["allowed_ml_roles"]
    assert "ranking" in payload["allowed_ml_roles"]
    assert "production model training" in payload["forbidden_actions"]
    assert "replacing rule-generated signals" in payload["forbidden_actions"]
    assert "changing recommendation thresholds" in payload["forbidden_actions"]
    assert "auto lifecycle action" in payload["forbidden_actions"]
    assert "trading advice" in payload["forbidden_actions"]
    assert payload["access_boundary"]["production_model_training_allowed"] is False
    assert payload["access_boundary"]["recommendation_threshold_changes_allowed"] is False


def test_ml_contract_contains_feature_label_split_and_precondition_policy() -> None:
    payload = MLReadinessContractService().build_report().to_dict()

    assert "decision_time_features_only" in payload["feature_policy"]
    assert "future_5d_return_gt_0" in payload["label_policy"]["allowed_labels"]
    assert "future_20d_return_beats_taiex" in payload["label_policy"]["allowed_labels"]
    assert payload["split_policy"]["policy_id"] == "walk_forward_expanding_t_minus_1"
    assert payload["model_family_sequence"][0] == "logistic_regression_baseline"
    assert payload["required_preconditions"] == [
        "score_bucket_audit_reviewable",
        "threshold_robustness_matrix_reviewable",
        "component_ablation_readiness_reviewable",
    ]


def test_ml_readiness_contract_cli_outputs_json_and_markdown(tmp_path, capsys) -> None:
    json_path = tmp_path / "ml_contract.json"
    markdown_path = tmp_path / "ml_contract.md"

    assert inspect_ml_readiness_contract_main(["--format", "json", "--output", str(json_path)]) == 0
    assert inspect_ml_readiness_contract_main(["--format", "markdown", "--output", str(markdown_path)]) == 0

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert payload["shadow_only"] is True
    assert "shadow_only=true" in markdown
    assert "不訓練 production model" in markdown
    _ = capsys.readouterr()
