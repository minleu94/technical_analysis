import json
from pathlib import Path

from scripts.build_ml_promotion_review import main


def test_cli_emits_non_applying_review_package(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    output = tmp_path / "review.json"
    source.write_text(
        json.dumps(
            {
                "model_id": "m1",
                "dataset_id": "d1",
                "champion_model_id": "rule-v1",
                "shadow_observed_days": 30,
                "comparison_status": "challenger_directionally_better",
                "drift_statuses": ["stable"],
                "calibration_status": "passed",
                "rollback_artifact": "rollback.json",
                "verification_artifacts": ["walk-forward.json"],
            }
        ),
        encoding="utf-8",
    )

    assert main(["--input", str(source), "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["review_status"] == "eligible_for_human_review"
    assert payload["apply_promotion"] is False
    assert payload["auto_promotion_allowed"] is False
