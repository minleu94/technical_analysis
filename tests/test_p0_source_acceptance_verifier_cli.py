import json
from pathlib import Path

from scripts.verify_p0_source_acceptance import main


def test_cli_emits_non_applying_review_package(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    output = tmp_path / "result.json"
    source.write_text(
        json.dumps(
            {
                "source_id": "institutional_flows",
                "decision_date": "2026-07-12",
                "coverage_bp": 9000,
                "license_evidence": "reviewed",
                "quality_evidence": "passed",
                "observations": [
                    {
                        "source_id": "institutional_flows",
                        "symbol": "2330",
                        "decision_date": "2026-07-12",
                        "available_date": "2026-07-10",
                        "source_version": "v1",
                        "status": "shadow_ready",
                        "diagnostics": [],
                        "raw_payload": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert main(["--input", str(source), "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "eligible_for_human_review"
    assert payload["formal_acceptance_applied"] is False
    assert payload["downstream_eligibility"] == "none"
