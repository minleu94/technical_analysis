from datetime import date
from decimal import Decimal

from decision_module.factors.factor_adapters import (
    broker_flow_quality_to_factor_quality,
    build_broker_flow_factor,
    build_technical_total_score_factor,
    build_volume_ratio_factor,
)
from decision_module.factors.factor_dtos import FactorQuality, MissingPolicy


def test_technical_score_adapter_quantizes_to_basis_points():
    record = build_technical_total_score_factor(
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 12),
        total_score=Decimal("82.35"),
    )

    assert record.factor_name == "technical.total_score"
    assert record.value == Decimal("82.35")
    assert record.score_bp == 8235
    assert record.quality == FactorQuality.OBSERVED
    assert record.missing_policy == MissingPolicy.FAIL_CLOSED


def test_technical_score_adapter_clamps_out_of_range_scores():
    high = build_technical_total_score_factor(
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 12),
        total_score=Decimal("120.00"),
    )
    low = build_technical_total_score_factor(
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 12),
        total_score=Decimal("-5.00"),
    )

    assert high.score_bp == 10000
    assert low.score_bp == 0


def test_volume_ratio_adapter_uses_neutral_policy_when_missing():
    record = build_volume_ratio_factor(
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 12),
        volume_ratio=None,
    )

    assert record.factor_name == "volume.volume_ratio"
    assert record.quality == FactorQuality.MISSING
    assert record.score_bp is None
    assert record.missing_policy == MissingPolicy.NEUTRAL


def test_volume_ratio_adapter_maps_normal_volume_to_neutral_score():
    record = build_volume_ratio_factor(
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 12),
        volume_ratio=Decimal("1.0"),
    )

    assert record.value == Decimal("1.0")
    assert record.score_bp == 5000
    assert record.quality == FactorQuality.OBSERVED


def test_volume_ratio_adapter_caps_high_volume_at_full_basis_points():
    record = build_volume_ratio_factor(
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 12),
        volume_ratio=Decimal("2.50"),
    )

    assert record.value == Decimal("2.50")
    assert record.score_bp == 10000
    assert record.quality == FactorQuality.OBSERVED


def test_broker_flow_quality_mapping_does_not_treat_unavailable_as_zero():
    assert broker_flow_quality_to_factor_quality("observed") == FactorQuality.OBSERVED
    assert broker_flow_quality_to_factor_quality("estimated") == FactorQuality.ESTIMATED
    assert broker_flow_quality_to_factor_quality("unavailable") == FactorQuality.MISSING
    assert broker_flow_quality_to_factor_quality("anything-else") == FactorQuality.MISSING


def test_broker_flow_adapter_preserves_rank_metadata():
    record = build_broker_flow_factor(
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 12),
        net_lots=120,
        quality="estimated",
        rank=7,
    )

    assert record.factor_name == "broker_flow.net_lots"
    assert record.value == 120
    assert record.score_bp is None
    assert record.quality == FactorQuality.ESTIMATED
    assert record.missing_policy == MissingPolicy.SKIP
    assert record.metadata["rank"] == 7
    assert record.metadata["source_quality"] == "estimated"


def test_broker_flow_adapter_keeps_unavailable_as_missing_not_zero():
    record = build_broker_flow_factor(
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 12),
        net_lots=0,
        quality="unavailable",
        rank=None,
    )

    assert record.value is None
    assert record.quality == FactorQuality.MISSING
