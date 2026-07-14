from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app_module.research_console_dtos import (
    ResearchConsoleBoundaryDTO,
    ResearchConsoleDTO,
    ResearchPipelineRowDTO,
)


def test_boundary_is_immutable_and_permanently_fail_closed() -> None:
    boundary = ResearchConsoleBoundaryDTO()

    assert boundary.formal_oos_allowed is False
    assert boundary.production_blend_alpha_bp == 0
    assert boundary.production_ml_enabled is False
    assert boundary.formal_rule_unchanged is True
    assert boundary.recommendation_path == "rule_only"
    assert boundary.portfolio_path == "rule_only"
    assert boundary.trading_allowed is False
    with pytest.raises(FrozenInstanceError):
        boundary.formal_oos_allowed = True  # type: ignore[misc]


def test_console_defensively_copies_frozen_metrics() -> None:
    metrics = {
        "sample_count": 48,
        "coverage_bp": 10000,
        "rule": {"status": "research_baseline", "samples": [1, 2]},
    }
    console = ResearchConsoleDTO(
        overall_status="degraded",
        source_reference="fixture",
        boundary=ResearchConsoleBoundaryDTO(),
        pipeline=(
            ResearchPipelineRowDTO(
                component_id="dataset",
                label="Development Dataset V0",
                identity="dataset:g-1",
                status="degraded",
            ),
        ),
        frozen_metrics=metrics,
        blockers=("research_only_degraded",),
    )

    metrics["sample_count"] = 999
    metrics["rule"]["status"] = "mutated"  # type: ignore[index]
    assert console.frozen_metrics["sample_count"] == 48
    rule = console.frozen_metrics["rule"]
    assert rule["status"] == "research_baseline"  # type: ignore[index]
    assert rule["samples"] == (1, 2)  # type: ignore[index]
    with pytest.raises(TypeError):
        console.frozen_metrics["sample_count"] = 1  # type: ignore[index]
    with pytest.raises(TypeError):
        rule["status"] = "mutated"  # type: ignore[index]


def test_pipeline_counts_use_none_for_unknown_instead_of_zero() -> None:
    row = ResearchPipelineRowDTO(
        component_id="dataset",
        label="Development Dataset V0",
        identity="Missing",
        status="missing",
    )

    assert row.row_count is None
    assert row.eligible_count is None
    assert row.feature_count is None
    assert row.generated_at is None
