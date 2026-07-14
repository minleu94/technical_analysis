from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app_module.ml_shadow_projection_dtos import (
    MLShadowPredictionProjectionDTO,
    MLShadowProjectionDTO,
)


def test_projection_dto_is_neutral_and_keeps_production_alpha_zero() -> None:
    row = MLShadowPredictionProjectionDTO(
        prediction_id="prediction:1",
        symbol="2330",
        return_prediction_bp=125,
        ranking_score_bp=6500,
        downside_probability_bp=1800,
        uncertainty_bp=300,
    )
    projection = MLShadowProjectionDTO(
        decision_date="2025-01-03",
        model_id="model-1",
        dataset_id="dataset-1",
        status="shadow_available",
        predictions=(row,),
        blockers=(),
    )

    assert projection.production_blend_alpha_bp == 0
    assert projection.formal_rule_unchanged is True
    assert projection.production_action_allowed is False
    with pytest.raises(ValueError, match="production_blend_alpha_bp"):
        MLShadowProjectionDTO(
            decision_date="2025-01-03",
            model_id="model-1",
            dataset_id="dataset-1",
            status="shadow_available",
            predictions=(row,),
            blockers=(),
            production_blend_alpha_bp=1,
        )


def test_projection_module_does_not_import_ml_module() -> None:
    path = Path("app_module/ml_shadow_projection_dtos.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = tuple(
        name
        for node in ast.walk(tree)
        for name in (
            tuple(alias.name for alias in node.names)
            if isinstance(node, ast.Import)
            else ((node.module or ""),)
            if isinstance(node, ast.ImportFrom)
            else ()
        )
    )

    assert not any(name == "ml_module" or name.startswith("ml_module.") for name in imported)
