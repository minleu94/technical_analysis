from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app_module.evidence_rehearsal_dtos import (
    CoverageMetric,
    EvidenceRehearsalReport,
    EvidenceRehearsalScenario,
    RehearsalArtifact,
)


def _scenario(**overrides: object) -> EvidenceRehearsalScenario:
    values: dict[str, object] = {
        "scenario_id": "replay-2026-07-12",
        "decision_date": "2026-07-12",
        "source_db_path": "C:/fixtures/evidence.sqlite",
        "working_copy_db_path": "C:/work/replay.sqlite",
        "tier": "historical_replay_candidate",
    }
    values.update(overrides)
    return EvidenceRehearsalScenario(**values)  # type: ignore[arg-type]


def test_rehearsal_contract_round_trip_is_frozen_and_fail_closed() -> None:
    scenario = _scenario()
    metric = CoverageMetric(
        source_id="daily_prices",
        total_count=10,
        observed_count=8,
        degraded_count=1,
        missing_count=1,
        future_blocked_count=0,
        immature_label_count=0,
        coverage_bp=8000,
    )
    artifact = RehearsalArtifact(
        artifact_id="coverage-summary",
        decision_date="2026-07-12",
        available_date="2026-07-12",
        tier="historical_replay_candidate",
    )
    report = EvidenceRehearsalReport(
        scenario=scenario,
        coverage_metrics=(metric,),
        artifacts=(artifact,),
    )

    assert report.to_dict() == {
        "scenario": scenario.to_dict(),
        "coverage_metrics": [metric.to_dict()],
        "artifacts": [artifact.to_dict()],
    }
    with pytest.raises(FrozenInstanceError):
        scenario.tier = "shadow_comparison"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("source_db_path", "C:/production/evidence.sqlite"),
        ("working_copy_db_path", "C:/prod/evidence.sqlite"),
        ("tier", "formal_evidence"),
        ("production_actions_allowed", True),
    ),
)
def test_scenario_rejects_production_like_inputs(
    field_name: str,
    invalid_value: object,
) -> None:
    with pytest.raises(ValueError, match=field_name):
        _scenario(**{field_name: invalid_value})


def test_artifact_rejects_future_available_date() -> None:
    with pytest.raises(ValueError, match="available_date"):
        RehearsalArtifact(
            artifact_id="late-data",
            decision_date="2026-07-12",
            available_date="2026-07-13",
            tier="shadow_comparison",
        )


@pytest.mark.parametrize("invalid_value", (-1, 10001, 1.5, True))
def test_coverage_metric_rejects_invalid_coverage_bp(invalid_value: object) -> None:
    with pytest.raises(ValueError, match="coverage_bp"):
        CoverageMetric(
            source_id="daily_prices",
            total_count=1,
            observed_count=1,
            degraded_count=0,
            missing_count=0,
            future_blocked_count=0,
            immature_label_count=0,
            coverage_bp=invalid_value,  # type: ignore[arg-type]
        )
