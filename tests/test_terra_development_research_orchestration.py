from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from development_module.research_orchestration import (
    FrozenDevelopmentResearchPolicy,
    TerraDevelopmentResearchOrchestrator,
)


def _write_dataset_v0(root: Path) -> tuple[Path, Path]:
    generation = root / "generations" / "terra-v0-research-test"
    generation.mkdir(parents=True)
    manifest = {
        "schema_version": "terra-development-dataset.v0",
        "generation_id": "terra-v0-research-test",
        "dataset_id": "terra-development-v0:terra-v0-research-test",
        "dataset_status": "research_only_degraded",
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "formal_rule_only_path_unchanged": True,
        "zero_formal_write": True,
        "feature_registry_hash": "sha256:" + "a" * 64,
        "label_registry_hash": "sha256:" + "b" * 64,
        "content_hash": "sha256:" + "c" * 64,
        "manifest_hash": "sha256:" + "d" * 64,
        "training_as_of": "2025-12-31",
        "evaluation_as_of": "2026-12-31",
        "new_holdout_start": "2026-07-15",
    }
    feature_names = ("rsi_normalized_bp", "adx_normalized_bp", "macd_normalized_bp")
    fit_rows = []
    for index in range(48):
        decision_date = date(2025, 1, 1) + timedelta(days=index)
        decision = decision_date.isoformat()
        label_available = (decision_date + timedelta(days=1)).isoformat()
        target = (index % 11 - 5) * 100
        fit_rows.append({
            "symbol": f"{1000 + index:04d}",
            "decision_date": decision,
            "feature_as_of_date": "2024-12-31",
            "available_date": decision,
            "features": [[feature_names[0], (index % 9 - 4) * 250], [feature_names[1], 2500 + index], [feature_names[2], (index % 5 - 2) * 100]],
            "labels": [
                {"label_id": "relative_return_20d_bp", "value": target, "horizon_end_date": label_available, "available_date": label_available, "maturity_status": "ready", "quality": "research_only"},
                {"label_id": "downside_20d_flag", "value": int(target <= -500), "horizon_end_date": label_available, "available_date": label_available, "maturity_status": "ready", "quality": "research_only"},
            ],
        })
    dataset = {"fit_rows": fit_rows, "evaluation_rows": []}
    manifest_path = generation / "manifest.json"
    dataset_path = generation / "dataset.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
    return manifest_path, dataset_path


def test_research_pipeline_is_development_only_and_excludes_2026_outcomes(tmp_path: Path) -> None:
    manifest_path, dataset_path = _write_dataset_v0(tmp_path)

    result = TerraDevelopmentResearchOrchestrator().run(
        manifest_path=manifest_path,
        dataset_path=dataset_path,
        policy=FrozenDevelopmentResearchPolicy.bounded_for_test(),
    )

    assert result.rule_baseline.baseline_kind == "historical_research_rule_replay"
    assert result.rule_baseline.formal_rule_champion is False
    assert "formal_attested_persisted_rule_snapshot_missing" in result.rule_baseline.blockers
    assert result.ml_challenger.model_families == ("linear_logistic", "hist_gradient_boosting")
    assert result.ml_challenger.max_selection_label_available_date <= "2025-12-31"
    assert result.comparison.data_scope == "historical_research_seen_development_data"
    assert result.comparison.formal_oos is False
    assert result.projection["status"]["formal_oos"] is False
    assert result.projection["status"]["alpha_bp"] == 0
    assert result.projection["status"]["apply_flags"] == {
        "apply_to_scoring": False,
        "apply_to_recommendation": False,
        "apply_to_portfolio": False,
        "apply_to_exit": False,
    }
    assert "2026-" not in result.lineage["max_label_available_date"]


def test_pipeline_records_but_excludes_evaluation_rows_and_rejects_apply_policy(tmp_path: Path) -> None:
    manifest_path, dataset_path = _write_dataset_v0(tmp_path)
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    evaluation_row = dict(dataset["fit_rows"][0])
    evaluation_row["decision_date"] = "2026-01-02"
    dataset["evaluation_rows"] = [evaluation_row]
    dataset_path.write_text(json.dumps(dataset), encoding="utf-8")

    result = TerraDevelopmentResearchOrchestrator().run(
        manifest_path=manifest_path,
        dataset_path=dataset_path,
        policy=FrozenDevelopmentResearchPolicy.bounded_for_test(),
    )

    assert result.ml_challenger.training_row_count == 48
    assert result.lineage["input_evaluation_row_count"] == 1
    assert result.lineage["max_label_available_date"] <= "2025-12-31"

    with pytest.raises(ValueError, match="production_apply_flags"):
        FrozenDevelopmentResearchPolicy.bounded_for_test(
            production_apply_flags=(("apply_to_scoring", True),),
        )
