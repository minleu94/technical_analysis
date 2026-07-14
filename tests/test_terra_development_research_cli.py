from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path


def test_cli_writes_only_report_and_frozen_projection(tmp_path: Path) -> None:
    generation = tmp_path / "input" / "generations" / "cli-test"
    generation.mkdir(parents=True)
    manifest = {
        "schema_version": "terra-development-dataset.v0", "generation_id": "cli-test",
        "dataset_id": "terra-development-v0:cli-test", "dataset_status": "research_only_degraded",
        "formal_oos_allowed": False, "production_blend_alpha_bp": 0,
        "formal_rule_only_path_unchanged": True, "zero_formal_write": True,
        "feature_registry_hash": "sha256:" + "a" * 64, "label_registry_hash": "sha256:" + "b" * 64,
        "content_hash": "sha256:" + "c" * 64, "manifest_hash": "sha256:" + "d" * 64,
        "training_as_of": "2025-12-31", "new_holdout_start": "2026-07-15",
    }
    rows = []
    for index in range(48):
        decision_date = date(2025, 1, 1) + timedelta(days=index)
        decision = decision_date.isoformat()
        available = (decision_date + timedelta(days=1)).isoformat()
        target = (index % 11 - 5) * 100
        rows.append({"symbol": f"{2000 + index:04d}", "decision_date": decision, "feature_as_of_date": "2024-12-31", "available_date": decision, "features": [["rsi_normalized_bp", (index % 9 - 4) * 250], ["adx_normalized_bp", 2500 + index], ["macd_normalized_bp", (index % 5 - 2) * 100]], "labels": [{"label_id": "relative_return_20d_bp", "value": target, "horizon_end_date": available, "available_date": available, "maturity_status": "ready", "quality": "research_only"}, {"label_id": "downside_20d_flag", "value": int(target <= -500), "horizon_end_date": available, "available_date": available, "maturity_status": "ready", "quality": "research_only"}]})
    (generation / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (generation / "dataset.json").write_text(json.dumps({"fit_rows": rows, "evaluation_rows": []}), encoding="utf-8")
    output = tmp_path / "output"

    completed = subprocess.run(
        [sys.executable, "scripts/run_terra_development_research.py", "--manifest", str(generation / "manifest.json"), "--dataset", str(generation / "dataset.json"), "--output-root", str(output), "--bounded-smoke"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )

    projection = json.loads((output / "ResearchConsoleProjection.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert projection["status"]["formal_oos"] is False
    assert projection["status"]["alpha_bp"] == 0
    assert set(projection) == {"identity", "status", "frozen_metrics", "blockers", "lineage"}
