import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_position_health_sample_cli_reports_non_executable_exit_candidate() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/inspect_position_health.py", "--sample", "--format", "json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert payload["research_only"] is True
    assert payload["state"] == "EXIT_CANDIDATE"
    assert payload["auto_action_allowed"] is False

