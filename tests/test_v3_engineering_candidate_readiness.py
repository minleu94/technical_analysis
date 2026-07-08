import json
import subprocess
import sys


def test_v3_readiness_reports_pending_manual_validation_without_failure() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/inspect_v3_engineering_candidate_readiness.py",
            "--sample",
            "--json-output",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    payload = json.loads(result.stdout)

    assert payload["active_milestone"] == "V3.0 engineering candidate"
    assert payload["manual_validation_status"] == "PENDING_MANUAL_VALIDATION"
    assert payload["production_scheduler_allowed"] is False
    assert payload["auto_trading"] is False
    assert payload["engineering_candidate_status"] in {
        "ready_for_manual_validation",
        "action_required",
    }


def test_v3_readiness_can_emit_markdown_report(tmp_path) -> None:
    report_path = tmp_path / "readiness.md"
    subprocess.run(
        [
            sys.executable,
            "scripts/inspect_v3_engineering_candidate_readiness.py",
            "--sample",
            "--markdown",
            "--report-output",
            str(report_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    text = report_path.read_text(encoding="utf-8")
    assert "production_scheduler_allowed: false" in text
    assert "No production DB write" in text
