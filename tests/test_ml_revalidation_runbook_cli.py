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
    assert len(payload["steps"]) == 10
