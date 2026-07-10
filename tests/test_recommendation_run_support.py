from decimal import Decimal

import pytest

from app_module.recommendation_run_support import (
    build_negative_evidence_buffers,
    configured_volume_change_min_percent,
    format_decimal_for_payload,
    matrix_row,
    validate_ranking_config,
)


def test_matrix_row_keeps_screening_payload_schema_and_string_values() -> None:
    row = matrix_row(
        stock_code="2330",
        stock_name="",
        status="skipped",
        reason_codes=["liquidity_volume_ratio_below_min"],
        quality="degraded",
        stage="strategy_filter",
        observed_value=Decimal("-12.50"),
        required_value=Decimal("0"),
        total_score=Decimal("52.70"),
        score_bp=5270,
        warnings=["資料延遲"],
    )

    assert row == {
        "stock_code": "2330",
        "stock_name": "2330",
        "status": "skipped",
        "reason_codes": ["liquidity_volume_ratio_below_min"],
        "quality": "degraded",
        "stage": "strategy_filter",
        "threshold_name": "",
        "observed_value": "-12.50",
        "required_value": "0",
        "total_score": "52.70",
        "score_bp": 5270,
        "score_percentile_bp": None,
        "eligible_universe_size": None,
        "threshold_mode": "fixed",
        "warnings": ["資料延遲"],
        "industry": "",
    }


def test_decimal_and_volume_payload_helpers_preserve_decimal_boundary() -> None:
    assert format_decimal_for_payload(Decimal("1.2300")) == "1.23"
    assert configured_volume_change_min_percent({"filters": {"min_volume_ratio": "1.5"}}) == Decimal("50.0")
    assert configured_volume_change_min_percent({"filters": {"volume_ratio_min": "120"}}) == Decimal("120")
    assert configured_volume_change_min_percent({"filters": {"volume_ratio_min": "not-a-number"}}) is None


def test_validate_ranking_config_rejects_invalid_mode_and_preserves_quantile_mapping() -> None:
    with pytest.raises(ValueError, match="threshold_mode"):
        validate_ranking_config({"recommendation_ranking": {"threshold_mode": "adaptive"}})

    ranking_config = {
        "threshold_mode": "quantile",
        "recommendation_min_percentile_bp": 8000,
        "recommendation_min_universe_size": 20,
        "recommendation_ranking_method": "nearest_rank",
    }
    assert validate_ranking_config({"recommendation_ranking": ranking_config}) == (ranking_config, "quantile")


def test_negative_evidence_buffers_keep_negative_row_order_and_liquidity_filter() -> None:
    buffers = build_negative_evidence_buffers(
        [
            {"stock_code": "PASS", "status": "pass", "reason_codes": ["recommendation_selected"]},
            {
                "stock_code": "LIQ",
                "stock_name": "流動性",
                "status": "skipped",
                "reason_codes": ["liquidity_volume_ratio_below_min"],
                "quality": "degraded",
            },
            {"stock_code": "MISS", "status": "missing", "reason_codes": ["insufficient_history"]},
        ]
    )

    assert [row["stock_code"] for row in buffers.why_not_payload] == ["LIQ", "MISS"]
    assert buffers.excluded_candidates == [
        {
            "stock_code": "LIQ",
            "stock_name": "流動性",
            "status": "skipped",
            "reason_codes": ["liquidity_volume_ratio_below_min"],
            "quality": "degraded",
        },
        {
            "stock_code": "MISS",
            "stock_name": "",
            "status": "missing",
            "reason_codes": ["insufficient_history"],
            "quality": "degraded",
        },
    ]
    assert [row["stock_code"] for row in buffers.liquidity_gate_payload] == ["LIQ"]
    assert buffers.exclusion_quality == "observed"
    assert buffers.exclusion_warnings == ["screening_matrix_persisted_v1"]
