from __future__ import annotations

import json
from pathlib import Path

from app_module.allocation_release_adapter import AllocationReleaseAdapter
from ml_module.allocation_release_contract import MissingPolicyBinding
from scripts.infer_ml_allocation_copilot import _load_rows
from scripts.validate_ml_release_parity import main
from tests.test_allocation_release_adapter import _write_release
from tests.test_infer_ml_allocation_copilot_cli import _write_input


def test_validate_release_parity_cli_is_read_only_and_fail_closed(
    tmp_path: Path,
    training_result,
    capsys,
) -> None:
    manifest = _write_release(tmp_path, training_result)
    input_path = tmp_path / "rows.json.gz"
    audit_path = tmp_path / "ooc-audit.json"
    _write_input(input_path)
    release = AllocationReleaseAdapter().load(tmp_path / "release")
    rows = _load_rows(input_path)
    result = release.infer(
        rows=rows,
        universe_id="pit-universe-test",
        policy_hash=MissingPolicyBinding.create(policy_id="balanced-v1").policy_hash,
    )
    audit_path.write_text(json.dumps(result.audit_payload()), encoding="utf-8")

    assert (
        main(
            [
                "--release-root",
                str(tmp_path / "release"),
                "--input",
                str(input_path),
                "--ooc-audit",
                str(audit_path),
                "--model-id",
                manifest.model_id,
                "--universe-id",
                "pit-universe-test",
                "--policy-id",
                manifest.missing_policy.policy_id,
                "--policy-hash",
                manifest.missing_policy.policy_hash,
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "matched"
    assert payload["mismatched_row_ids"] == []
    assert payload["production_alpha_bp"] == 0

    audit_path.write_text(
        json.dumps({"row_audits": [{"row_id": "poisoned", "prediction": 1}]}),
        encoding="utf-8",
    )
    assert main(
        [
            "--release-root",
            str(tmp_path / "release"),
            "--input",
            str(input_path),
            "--ooc-audit",
            str(audit_path),
            "--model-id",
            manifest.model_id,
            "--universe-id",
            "pit-universe-test",
            "--policy-id",
            manifest.missing_policy.policy_id,
            "--policy-hash",
            manifest.missing_policy.policy_hash,
        ]
    ) == 2
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["status"] == "blocked"
    assert blocked["production_action_allowed"] is False
