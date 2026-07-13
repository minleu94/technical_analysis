import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cli_builds_read_only_pruning_package(tmp_path: Path) -> None:
    source = tmp_path / "metrics.json"
    output = tmp_path / "pruning.json"
    source.write_text(
        json.dumps(
            {
                "manual_validation_status": "COMPLETED",
                "slices": [
                    {
                        "slice_id": "recommendation:included",
                        "sample_count": 60,
                        "hit_rate_bp": 6100,
                        "payoff_ratio_bp": 12000,
                        "score_monotonic": True,
                        "mae_mfe_ready": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_v3_pruning_package.py"),
            "--input",
            str(source),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["access_boundary"] == {
        "apply_action": False,
        "auto_trading": False,
        "review_required": True,
    }
    assert payload["proposals"][0]["action"] == "retain"
    assert payload["proposals"][0]["apply_action"] is False
