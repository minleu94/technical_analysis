import json
from pathlib import Path
import subprocess
import sys


def test_cli_validates_manifest_without_writing_a_database(tmp_path: Path) -> None:
    manifest = tmp_path / "lineage.json"
    output = tmp_path / "report.json"
    manifest.write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "artifact_id": "daily",
                        "artifact_type": "daily_governed_data",
                        "run_id": "run-1",
                        "decision_date": "2026-07-12",
                        "as_of_date": "2026-07-11",
                        "available_date": "2026-07-12",
                        "source_id": "fixture.governed",
                        "source_version": "v1",
                        "data_quality": "observed",
                        "missing_state": "complete",
                        "strategy_version": "rule-v1",
                        "policy_version": "policy-v1",
                        "model_version": None,
                        "parent_artifact_ids": [],
                        "evidence_tier": "engineering_fixture",
                        "current_status": "current_engineering",
                        "content_hash": "a" * 64,
                        "rollback_reference": "commit:abc",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, "scripts/verify_artifact_lineage.py", "--manifest", str(manifest), "--output", str(output)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "complete"
    assert not tuple(tmp_path.glob("*.sqlite*"))
