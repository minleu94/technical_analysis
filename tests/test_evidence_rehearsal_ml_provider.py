from __future__ import annotations

import json
from pathlib import Path

from app_module.evidence_rehearsal_ml_comparison import MLRehearsalComparisonService
from app_module.evidence_rehearsal_ml_provider import JsonMLRehearsalEvidenceProvider


def _write_ml_input(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "rehearsal-ml-input.json"
    path.write_text(
        json.dumps(
            {
                "status": "shadow_ready",
                "manifest": {
                    "dataset_id": "dataset-v2",
                    "created_at": "2026-07-12",
                    "row_count": 1,
                    "frozen": True,
                    "shadow_only": True,
                    "production_eligible": False,
                },
                "accepted_rows": [],
                "rejected_rows": [
                    {
                        "row_id": "immature-row",
                        "diagnostics": ["label_not_mature"],
                    }
                ],
                "predictions": [],
                "training_as_of": "2026-07-12",
            }
        ),
        encoding="utf-8",
    )
    return path


def test_json_ml_provider_ignores_supplied_status_and_returns_boundary_inputs(
    tmp_path: Path,
) -> None:
    _write_ml_input(tmp_path)

    inputs = JsonMLRehearsalEvidenceProvider(tmp_path).load()
    result = MLRehearsalComparisonService().compare(
        inputs.manifest,
        inputs.boundary_report,
        inputs.predictions,
        diagnostics=inputs.diagnostics,
    )

    assert result.status == "insufficient_sample"
    assert result.immature_label_rows == 1
    assert result.production_action_allowed is False
