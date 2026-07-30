import json
from pathlib import Path

from scripts.build_ml_revalidation_runbook import main


def test_cli_writes_runbook_json(tmp_path: Path) -> None:
    output = tmp_path / "runbook.json"
    assert main(
        [
            "--run-id", "r1", "--trigger", "scheduled_review", "--dataset-id", "d1",
            "--current-model-id", "m1", "--training-as-of", "2026-09-30",
            "--owner", "reviewer", "--output", str(output),
        ]
    ) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["auto_retrain_allowed"] is False
    assert payload["auto_promotion_allowed"] is False
    assert payload["candidate_alpha_bp"] == [0, 2000, 3500, 5000]
    assert len(payload["steps"]) == 12


def test_cli_accepts_v4_production_promotion_command_without_legacy_optional_fields(
    tmp_path: Path,
) -> None:
    output = tmp_path / "runbook_prod.json"

    assert main(
        [
            "--run-id",
            "release-v4-prod",
            "--trigger",
            "production_promotion",
            "--dataset-id",
            "frozen-v4-dataset",
            "--owner",
            "release_owner",
            "--output",
            str(output),
        ]
    ) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["current_model_id"] == "rule-champion-v1"
    assert payload["auto_retrain_allowed"] is False
    assert payload["auto_promotion_allowed"] is True
    assert payload["production_scheduler_allowed"] is True
    assert payload["promotion_policy_id"] == "allocation-promotion-v4"
