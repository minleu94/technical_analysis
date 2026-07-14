from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from ml_module.locked_oos import LockedOOSPreflight, LockedOOSPreflightRequest


def _request(**overrides: object) -> LockedOOSPreflightRequest:
    values: dict[str, object] = {
        "confirm_locked_oos": True,
        "dataset_content_hash": "sha256:" + "a" * 64,
        "model_artifact_hash": "sha256:" + "b" * 64,
        "max_train_decision_date": "2024-12-01",
        "max_train_label_available_date": "2024-12-31",
        "max_blend_selection_label_available_date": "2024-12-31",
        "training_as_of": "2024-12-31",
        "formal_oos_allowed": True,
        "production_alpha_bp": 0,
    }
    values.update(overrides)
    return LockedOOSPreflightRequest(**values)  # type: ignore[arg-type]


def test_preflight_blocks_before_loader_when_corporate_gate_is_not_clean() -> None:
    calls = []
    result = LockedOOSPreflight().execute(
        _request(formal_oos_allowed=False),
        oos_loader=lambda: calls.append("read-2025") or (),
    )

    assert result.executed is False
    assert result.blockers == ("dataset_not_formal_oos_eligible",)
    assert calls == []


def test_confirm_and_all_pre2025_cutoffs_are_mandatory_before_loader() -> None:
    calls = []
    result = LockedOOSPreflight().execute(
        _request(confirm_locked_oos=False,
                 max_blend_selection_label_available_date="2025-01-02"),
        oos_loader=lambda: calls.append("read-2025") or (),
    )

    assert result.executed is False
    assert result.blockers == (
        "confirm_locked_oos_required",
        "blend_selection_label_after_training_cutoff",
    )
    assert calls == []


def test_valid_preflight_calls_loader_exactly_once_and_keeps_production_alpha_zero() -> None:
    calls = []
    result = LockedOOSPreflight().execute(
        _request(), oos_loader=lambda: calls.append("read-2025") or ("payload",)
    )

    assert result.executed is True
    assert result.payload == ("payload",)
    assert result.production_alpha_bp == 0
    assert calls == ["read-2025"]


def test_cli_confirm_still_blocks_before_nonexistent_oos_payload(tmp_path: Path) -> None:
    summary = tmp_path / "freeze_summary.json"
    summary.write_text(json.dumps({
        "dataset_hash": "sha256:" + "a" * 64,
        "model_artifact_hash": "sha256:" + "b" * 64,
        "max_train_decision_date": "2024-10-02",
        "max_train_label_available_date": "2024-11-04",
        "max_blend_selection_label_available_date": "2024-08-29",
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
    }), encoding="utf-8")
    output = tmp_path / "preflight"
    missing_oos = tmp_path / "locked-2025-must-not-be-read.json"

    completed = subprocess.run([
        sys.executable, "scripts/evaluate_ml_2025_oos.py",
        "--freeze-summary", str(summary), "--oos-payload", str(missing_oos),
        "--output-root", str(output), "--confirm-locked-oos",
    ], capture_output=True, text=True, check=False)

    assert completed.returncode == 2
    assert not missing_oos.exists()
    report = json.loads((output / "locked_oos_preflight.json").read_text(encoding="utf-8"))
    assert report["executed"] is False
    assert report["blockers"] == ["dataset_not_formal_oos_eligible"]
    assert report["oos_payload_read"] is False
